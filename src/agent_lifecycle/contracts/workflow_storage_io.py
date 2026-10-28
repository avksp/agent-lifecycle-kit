"""Contained bounded storage I/O and checked create-only publication."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts.authority_io import (
    authority_location,
    create_authority_bytes,
    hold_authority_directory,
    read_authority_bytes,
)
from agent_lifecycle.contracts.canonical import (
    MAX_JSON_INPUT_BYTES,
    canonical_bytes,
    canonical_digest,
)
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.workflow_storage_context import (
    CheckedStorageWrites,
    StorageOperation,
    choose_operation,
    require_finite_deadline,
    write_set_digest,
)
from agent_lifecycle.contracts.workflow_storage_schemas import (
    MAX_RETAINED_BYTES,
    capacity_error,
    storage_error,
    validate_storage_metadata,
)


@dataclass(frozen=True)
class StorageFrontier:
    byte_count: int
    digest: str


def check_deadline(deadline: float) -> None:
    require_finite_deadline(deadline)
    if time.monotonic() >= deadline:
        raise LifecycleError(
            "workflow-storage-deadline-exceeded",
            "Storage cooperative I/O deadline exceeded",
        )


def storage_path(root: Path, metadata: dict[str, Any]) -> Path:
    validate_storage_metadata(metadata)
    return root.absolute() / metadata["root"]


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        getattr(info, "st_file_attributes", 0),
    )


def _regular(info: os.stat_result) -> None:
    if not stat.S_ISREG(info.st_mode) or (
        getattr(
            info,
            "st_file_attributes",
            0,
        )
        & 0x400
    ):
        raise storage_error("Storage contains a nonregular object")


def observe_object(
    root: Path,
    metadata: dict[str, Any],
    name: str,
    deadline: float,
) -> tuple[int, ...] | None:
    check_deadline(deadline)
    if (
        not isinstance(name, str)
        or re.fullmatch(
            r"objects/[0-9a-f]{64}\.json",
            name,
        )
        is None
    ):
        raise storage_error("Object path must be a contained digest name")
    path = storage_path(root, metadata) / name
    try:
        with hold_authority_directory(path.parent) as held:
            try:
                info = held.stat_child(path.name)
            except FileNotFoundError:
                return None
            _regular(info)
            result = _identity(info)
    except FileNotFoundError:
        return None
    check_deadline(deadline)
    return result


def read_object(
    root: Path,
    metadata: dict[str, Any],
    path: str,
    deadline: float,
    *,
    operation: StorageOperation | None = None,
) -> bytes:
    operation, owned = choose_operation(root, operation, deadline=deadline)
    try:
        return _read_object(root, metadata, path, operation)
    finally:
        if owned:
            operation.close()


def _read_object(
    root: Path,
    metadata: dict[str, Any],
    name: str,
    operation: StorageOperation,
) -> bytes:
    operation.check()
    anchor = authority_location(root / ".storage-anchor", root=root)[0]
    if operation.root != anchor:
        raise storage_error("Storage operation authority root mismatch")
    before = observe_object(root, metadata, name, operation.deadline)
    if before is None:
        raise LifecycleError(
            "workflow-storage-object-missing",
            "Immutable object is missing",
        )
    cached = operation._get(metadata, name)
    if cached is not None and cached.observed is not None:
        if cached.observed != before:
            raise LifecycleError(
                "workflow-storage-changed",
                "Cached object identity changed",
            )
        return cached.data
    data = read_authority_bytes(
        storage_path(root, metadata) / name,
        root=root,
        max_bytes=MAX_JSON_INPUT_BYTES,
    )
    operation._read_observed(len(data))
    after = observe_object(root, metadata, name, operation.deadline)
    if before != after:
        raise LifecycleError(
            "workflow-storage-changed",
            "Object changed during acquisition",
        )
    if cached is not None and cached.data != data:
        raise LifecycleError(
            "workflow-storage-object-conflict",
            "Existing immutable object has different bytes",
        )
    cached = operation._admit(metadata, name, data)
    cached.observed = after
    operation.check()
    return data


def _scan_directory(
    path: Path,
    deadline: float,
    *,
    objects: bool = False,
) -> tuple[int, int, int]:
    total, accumulator, count = 0, 0, 0
    with hold_authority_directory(path) as held:
        target = held.fd if held.fd is not None else path
        with os.scandir(target) as entries:
            for entry in entries:
                check_deadline(deadline)
                info = entry.stat(follow_symlinks=False)
                record: list[Any] = [entry.name, list(_identity(info))]
                if (
                    not objects
                    and entry.name == "objects"
                    and (
                        stat.S_ISDIR(
                            info.st_mode,
                        )
                    )
                ):
                    if getattr(info, "st_file_attributes", 0) & 0x400:
                        raise storage_error("Storage directory is a reparse")
                    size, digest, children = _scan_directory(
                        path / "objects",
                        deadline,
                        objects=True,
                    )
                    record.extend([digest, children])
                    total += size
                else:
                    _regular(info)
                    total += info.st_size
                digest_bytes = hashlib.sha256(canonical_bytes(record)).digest()
                accumulator = (
                    accumulator
                    + int.from_bytes(
                        digest_bytes,
                        "big",
                    )
                ) % (1 << 256)
                count += 1
                if total > MAX_RETAINED_BYTES:
                    raise capacity_error(
                        "retainedBytes",
                        total,
                        total,
                        MAX_RETAINED_BYTES,
                    )
    return total, accumulator, count


def storage_frontier(
    root: Path,
    metadata: dict[str, Any],
    deadline: float,
) -> StorageFrontier:
    """A bounded-memory identity of all retained entries, including orphans."""
    check_deadline(deadline)
    path = storage_path(root, metadata)
    opened = False
    try:
        with hold_authority_directory(path) as held:
            opened = True
            # A second held scan preserves the existing F02 entry-stat boundary.
            info = path.stat(follow_symlinks=False)
            identity = [info.st_dev, info.st_ino, info.st_mode]
            total, accumulator, count = _scan_directory(path, deadline)
            del held
    except FileNotFoundError:
        if opened:
            raise LifecycleError(
                "workflow-storage-changed",
                "Retained storage changed during its bounded scan",
            ) from None
        return StorageFrontier(0, canonical_digest({"absent": True}))
    check_deadline(deadline)
    digest = canonical_digest([identity, total, accumulator, count])
    return StorageFrontier(total, digest)


def retained_bytes(
    root: Path,
    metadata: dict[str, Any],
    deadline: float,
) -> int:
    return storage_frontier(root, metadata, deadline).byte_count


def preflight_objects(
    root: Path,
    metadata: dict[str, Any],
    objects: dict[str, bytes],
    operation: StorageOperation,
) -> tuple[StorageFrontier, tuple[str, ...]]:
    operation.check()
    before = storage_frontier(root, metadata, operation.deadline)
    missing: list[str] = []
    for name, data in objects.items():
        observed = observe_object(root, metadata, name, operation.deadline)
        if observed is None:
            cached = operation._get(metadata, name)
            if cached is not None and cached.observed is not None:
                raise LifecycleError(
                    "workflow-storage-changed",
                    "Observed object disappeared",
                )
            missing.append(name)
        elif (
            read_object(
                root,
                metadata,
                name,
                operation.deadline,
                operation=operation,
            )
            != data
        ):
            raise LifecycleError(
                "workflow-storage-object-conflict",
                "Existing immutable object has different bytes",
            )
    required = before.byte_count + sum(len(objects[name]) for name in missing)
    if required > MAX_RETAINED_BYTES:
        raise capacity_error(
            "retainedBytes",
            before.byte_count,
            required,
            MAX_RETAINED_BYTES,
        )
    after = storage_frontier(root, metadata, operation.deadline)
    if after != before:
        raise LifecycleError(
            "workflow-storage-changed",
            "Storage frontier changed in preflight",
        )
    operation.check()
    return after, tuple(missing)


def persist_objects(
    root: Path,
    metadata: dict[str, Any],
    objects: dict[str, bytes],
    *,
    operation: StorageOperation,
    checked: CheckedStorageWrites,
) -> None:
    operation.check()
    anchor = authority_location(root / ".storage-anchor", root=root)[0]
    if (
        operation is not checked.operation
        or anchor != checked.root
        or checked.storage_root != metadata["root"]
        or checked.write_digest != write_set_digest(objects)
    ):
        raise storage_error("Checked storage context/root/write-set changed")
    frontier = storage_frontier(root, metadata, operation.deadline)
    if frontier.digest != checked.frontier:
        raise LifecycleError(
            "workflow-storage-changed",
            "Checked storage frontier is stale",
        )
    operation._consume(checked)
    for name in checked.missing:
        operation.check()
        data = objects[name]
        path = storage_path(root, metadata) / name
        try:
            create_authority_bytes(path, data, root=root, private=True)
        except FileExistsError:
            if (
                read_object(
                    root,
                    metadata,
                    name,
                    operation.deadline,
                    operation=operation,
                )
                != data
            ):
                raise LifecycleError(
                    "workflow-storage-object-conflict",
                    "Concurrent immutable object has different bytes",
                ) from None
        else:
            # Record the factual completed write before checking time again.
            operation._published(path, data, "created")
            operation.check()
            entry = operation._admit(metadata, name, data)
            entry.observed = observe_object(
                root,
                metadata,
                name,
                operation.deadline,
            )
        operation.check()
    storage_frontier(root, metadata, operation.deadline)
    operation.check()

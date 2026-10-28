"""One bounded lifetime for lower workflow storage reads and publication."""

from __future__ import annotations

import math
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts.authority_io import authority_location
from agent_lifecycle.contracts.canonical import canonical_digest, sha256_hex
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.workflow_storage_schemas import (
    IO_DEADLINE_SECONDS,
    MAX_REACHABLE_BYTES,
    MAX_REACHABLE_OBJECTS,
    capacity_error,
    storage_error,
    validate_storage_metadata,
)

_ACTIVE_OPERATION: ContextVar[StorageOperation | None] = ContextVar(
    "workflow_storage_operation",
    default=None,
)


def require_finite_deadline(deadline: object) -> None:
    valid = False
    if isinstance(deadline, (int, float)) and not isinstance(deadline, bool):
        try:
            valid = math.isfinite(deadline)
        except OverflowError:
            valid = False
    if not valid:
        raise LifecycleError(
            "workflow-storage-deadline-invalid",
            "Storage deadline must be a supported finite number",
        )


@dataclass
class _CachedObject:
    data: bytes
    kind: str | None = None
    observed: tuple[int, ...] | None = None
    verified: dict[str, Any] | None = None


@dataclass(frozen=True)
class CheckedStorageWrites:
    """Opaque capability consumed only by its issuing operation."""

    root: Path
    state_digest: str
    write_digest: str
    storage_root: str
    frontier: str
    missing: tuple[str, ...]
    binding_digest: str
    operation: StorageOperation
    standalone: bool
    _token: object


class StorageOperation:
    """Bound exact raw bytes and trust to one root/run/state path and deadline.

    Native callers supply state_path and run_id. Standalone component callers
    may bind those later. Cache entries never outlive this operation and never
    become fields in the compact authority document.
    """

    def __init__(
        self,
        root: Path,
        *,
        state_path: Path | None = None,
        run_id: str | None = None,
        deadline: float | None = None,
    ) -> None:
        if deadline is not None:
            require_finite_deadline(deadline)
        self._input_root = root.absolute()
        self._root = authority_location(root / ".storage-anchor", root=root)[0]
        self._started = time.monotonic()
        maximum = self._started + IO_DEADLINE_SECONDS
        self._deadline = maximum if deadline is None else min(maximum, deadline)
        self._state_path: Path | None = None
        self._run_id = run_id
        self._package_id: str | None = None
        self._storage_root: str | None = None
        self._cache: dict[tuple[str, str], _CachedObject] = {}
        self._bytes = 0
        self._count = 0
        self._reads = 0
        self._read_bytes = 0
        self._closed = False
        self._graphs: set[str] = set()
        self._capabilities: dict[object, CheckedStorageWrites] = {}
        self._publications: list[dict[str, Any]] = []
        self._tokens: list[Token[StorageOperation | None]] = []
        if state_path is not None:
            self.bind_path(state_path)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def started(self) -> float:
        return self._started

    @property
    def deadline(self) -> float:
        return self._deadline

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._started

    @property
    def object_count(self) -> int:
        return self._count

    @property
    def object_bytes(self) -> int:
        return self._bytes

    @property
    def physical_reads(self) -> int:
        return self._reads

    @property
    def physical_read_bytes(self) -> int:
        return self._read_bytes

    @property
    def checked_graphs(self) -> frozenset[str]:
        return frozenset(self._graphs)

    @property
    def binding_digest(self) -> str:
        return canonical_digest(
            {
                "root": str(self.root),
                "statePath": str(self._state_path),
                "runId": self._run_id,
                "packageId": self._package_id,
                "storageRoot": self._storage_root,
            }
        )

    @property
    def publications(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self._publications)

    def __enter__(self) -> StorageOperation:
        self.check()
        active = _ACTIVE_OPERATION.get()
        if active is not None and active is not self:
            raise storage_error("An enclosing storage context already exists")
        self._tokens.append(_ACTIVE_OPERATION.set(self))
        return self

    def __exit__(self, *_args: Any) -> None:
        _ACTIVE_OPERATION.reset(self._tokens.pop())
        if not self._tokens:
            self.close()

    @staticmethod
    def current() -> StorageOperation | None:
        return _ACTIVE_OPERATION.get()

    def close(self) -> None:
        self._closed = True
        self._cache.clear()
        self._capabilities.clear()
        self._graphs.clear()

    def check(self) -> None:
        if self._closed:
            raise storage_error("Storage operation is closed")
        if time.monotonic() >= self._deadline:
            raise LifecycleError(
                "workflow-storage-deadline-exceeded",
                "Storage cooperative I/O deadline exceeded",
                {
                    "elapsedSeconds": self.elapsed_seconds,
                    "publications": list(
                        self.publications,
                    ),
                },
            )

    def bind_path(self, path: Path) -> None:
        self.check()
        root = self._root
        if path.absolute().is_relative_to(self._input_root):
            root = self._input_root
        anchor, name = authority_location(path, root=root)
        selected = anchor / name
        if self._state_path is not None and self._state_path != selected:
            raise storage_error("Storage operation state path cannot change")
        self._state_path = selected

    def bind(self, root: Path, state: dict[str, Any]) -> None:
        self.check()
        selected = authority_location(root / ".storage-anchor", root=root)[0]
        if selected != self._root:
            raise storage_error("Storage operation authority root mismatch")
        for name, field in (("_run_id", "runId"), ("_package_id", "packageId")):
            expected = getattr(self, name)
            actual = state.get(field)
            if not isinstance(actual, str) or not actual:
                raise storage_error("Storage operation run/package is invalid")
            if expected is not None and expected != actual:
                raise storage_error("Storage operation run/package changed")
            setattr(self, name, actual)
        if "storage" in state:
            metadata = validate_storage_metadata(state["storage"])
            if self._storage_root not in (None, metadata["root"]):
                raise storage_error("Storage operation storage root changed")
            self._storage_root = metadata["root"]

    def _get(self, metadata: dict[str, Any], name: str) -> _CachedObject | None:
        self.check()
        return self._cache.get((metadata["root"], name))

    def _admit(
        self,
        metadata: dict[str, Any],
        name: str,
        data: bytes,
        *,
        kind: str | None = None,
    ) -> _CachedObject:
        self.check()
        validate_storage_metadata(metadata)
        if self._storage_root not in (None, metadata["root"]):
            raise storage_error("Storage operation storage root changed")
        self._storage_root = metadata["root"]
        key = (metadata["root"], name)
        existing = self._cache.get(key)
        if existing is not None:
            known_kind = existing.kind
            changed_kind = kind is not None and known_kind not in (None, kind)
            if existing.data != data or changed_kind:
                raise storage_error("Cached immutable identity mismatch")
            if kind is not None:
                existing.kind = kind
            return existing
        count, size = len(self._cache) + 1, self._bytes + len(data)
        for category, current, required, limit in (
            (
                "operationObjects",
                len(
                    self._cache,
                ),
                count,
                MAX_REACHABLE_OBJECTS,
            ),
            ("operationBytes", self._bytes, size, MAX_REACHABLE_BYTES),
        ):
            if required > limit:
                raise capacity_error(category, current, required, limit)
        result = _CachedObject(data, kind)
        self._cache[key] = result
        self._bytes = size
        self._count = count
        return result

    def _read_observed(self, size: int) -> None:
        self._reads += 1
        self._read_bytes += size

    def _graph_checked(self, state: dict[str, Any]) -> None:
        self.check()
        self._graphs.add(canonical_digest(state))

    def _issue(
        self,
        *,
        state_digest: str,
        write_digest: str,
        storage_root: str,
        frontier: str,
        missing: tuple[str, ...],
        standalone: bool,
    ) -> CheckedStorageWrites:
        self.check()
        token = object()
        result = CheckedStorageWrites(
            self.root,
            state_digest,
            write_digest,
            storage_root,
            frontier,
            missing,
            self.binding_digest,
            self,
            standalone,
            token,
        )
        self._capabilities[token] = result
        return result

    def _consume(self, checked: CheckedStorageWrites) -> None:
        self.check()
        if checked.binding_digest != self.binding_digest:
            raise storage_error("Checked storage context binding changed")
        if self._capabilities.pop(checked._token, None) is not checked:
            raise storage_error(
                "Checked writes belong to another/stale context",
            )

    def _published(self, path: Path, data: bytes, outcome: str) -> None:
        self._publications.append(
            {
                "path": str(path),
                "bytes": len(data),
                "outcome": outcome,
                "sha256": sha256_hex(data),
                "observedAtMonotonic": time.monotonic(),
            }
        )


@contextmanager
def storage_operation(
    root: Path,
    state: dict[str, Any],
    operation: StorageOperation | None,
    *,
    deadline: float | None = None,
) -> Iterator[StorageOperation]:
    """Use the supplied lifetime; only standalone calls own a new context."""
    selected, owned = choose_operation(root, operation, deadline=deadline)
    try:
        selected.bind(root, state)
        yield selected
    finally:
        if owned:
            selected.close()


def choose_operation(
    root: Path,
    operation: StorageOperation | None = None,
    *,
    deadline: float | None = None,
) -> tuple[StorageOperation, bool]:
    if deadline is not None:
        require_finite_deadline(deadline)
    active = StorageOperation.current()
    if operation is not None and active is not None and operation is not active:
        raise storage_error("An enclosing storage context cannot be replaced")
    selected = operation or active
    owned = selected is None
    if selected is None:
        selected = StorageOperation(root, deadline=deadline)
    elif deadline is not None:
        if deadline > selected.deadline:
            raise storage_error("Nested storage deadline cannot be extended")
        selected._deadline = min(deadline, selected.deadline)
    selected.check()
    return selected, owned


def write_set_digest(objects: dict[str, bytes]) -> str:
    if any(not isinstance(data, bytes) for data in objects.values()):
        raise storage_error("Prepared writes require exact immutable bytes")
    identities = {}
    for name, data in objects.items():
        identities[name] = {"sha256": sha256_hex(data), "bytes": len(data)}
    return canonical_digest(identities)

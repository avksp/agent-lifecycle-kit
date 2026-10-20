"""Read-only, contracts-only observations for an actual local execution target."""

from __future__ import annotations

import hashlib
import os
import stat
import unicodedata
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts.authority_io import hold_authority_directory
from agent_lifecycle.contracts.canonical import canonical_digest
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.ownership_paths import repository_authority_name
from agent_lifecycle.contracts.paths import normalize_repo_path, read_stable_repository_file

TARGET_BINDING_SCHEMA = "agent-execution-target-binding.v1"
MAX_TARGET_PATHS = 10_000
MAX_TARGET_FILE_BYTES = 64 * 1024 * 1024
MAX_TARGET_TOTAL_BYTES = 512 * 1024 * 1024


def inspect_execution_target(
    repository_root: Path,
    *,
    source_identity: dict[str, Any],
    plan_identity: dict[str, Any],
    source_paths: list[str],
    outputs: list[dict[str, Any]],
    state_path: str,
    event_log: str,
    stage: str,
) -> dict[str, Any]:
    """Inspect every destination; this observation grants no write authority."""
    root = repository_root.resolve(strict=True)
    if not root.is_dir() or stage not in {"PLANNING", "FROZEN"}:
        raise LifecycleError("execution-target-invalid", "A real checkout and known preparation stage are required")
    if len(source_paths) > MAX_TARGET_PATHS or not 1 <= len(outputs) <= MAX_TARGET_PATHS:
        raise LifecycleError("execution-target-limit", "Execution target inventory exceeds its path limit")
    inventory = _source_inventory(root, source_paths)
    observed = [_inspect_destination(root, item) for item in outputs]
    names = [item["path"] for item in observed]
    if len({unicodedata.normalize("NFC", name).casefold() for name in names}) != len(names):
        raise LifecycleError("execution-target-alias", "Projected output paths must be unique and unaliased")
    conflicts = [item for item in observed if item["disposition"] in {"INCOMPATIBLE", "UNAVAILABLE"}]
    if conflicts:
        raise LifecycleError(
            "execution-target-output-conflict",
            "One or more actual target destinations are incompatible or unavailable",
            {"destinations": observed},
        )
    info = root.stat(follow_symlinks=False)
    target_id = canonical_digest({"root": os.path.normcase(str(root)), "device": info.st_dev, "inode": info.st_ino})
    body = {
        "schemaVersion": TARGET_BINDING_SCHEMA,
        "status": "PASS",
        "stage": stage,
        "targetId": target_id,
        "sourceIdentity": source_identity,
        "planIdentity": plan_identity,
        "sourceInventory": inventory,
        "statePath": normalize_repo_path(state_path, label="target state"),
        "eventLog": normalize_repo_path(event_log, label="target event log"),
        "outputs": sorted(observed, key=lambda item: item["path"]),
        "authorityClaimed": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "bindingDigest": canonical_digest(body)}


def require_execution_target_digest(expected_digest: str, current: dict[str, Any]) -> None:
    """Reject a stale observation; recomputation is owned by the real caller."""
    if not isinstance(expected_digest, str) or expected_digest != current.get("bindingDigest"):
        raise LifecycleError("execution-target-changed", "The actual execution target no longer matches preparation")
    body = {key: value for key, value in current.items() if key != "bindingDigest"}
    if canonical_digest(body) != expected_digest:
        raise LifecycleError("execution-target-changed", "Execution target binding integrity failed")


def _source_inventory(root: Path, paths: list[str]) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    total = 0
    for raw in sorted(set(paths)):
        name = repository_authority_name(root / normalize_repo_path(raw), root)
        path = root / name
        try:
            before = path.lstat()
        except FileNotFoundError:
            inventory.append({"path": name, "kind": "missing", "sha256": None, "fileIdentity": None})
            continue
        if not stat.S_ISREG(before.st_mode):
            raise LifecycleError("execution-target-source-unavailable", "Source inventory requires regular files")
        data = read_stable_repository_file(root, name, max_bytes=MAX_TARGET_FILE_BYTES, label="target source")
        total += len(data)
        if total > MAX_TARGET_TOTAL_BYTES:
            raise LifecycleError("execution-target-limit", "Execution target source bytes exceed their limit")
        after = path.lstat()
        if _file_identity(before) != _file_identity(after):
            raise LifecycleError("execution-target-changed", "Source identity changed during target inspection")
        inventory.append(
            {
                "path": name,
                "kind": "file",
                "sha256": hashlib.sha256(data).hexdigest(),
                "fileIdentity": canonical_digest(list(_file_identity(after))),
            }
        )
    return inventory


def _inspect_destination(root: Path, item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        raise LifecycleError("execution-target-invalid", "Each projected output needs a relative path")
    name = repository_authority_name(root / normalize_repo_path(item["path"]), root)
    expected = item.get("expectedSha256")
    limit = item.get("expectedBytes")
    if expected is not None and (
        not isinstance(expected, str)
        or len(expected) != 64
        or any(c not in "0123456789abcdef" for c in expected)
        or type(limit) is not int
        or not 0 <= limit <= MAX_TARGET_FILE_BYTES
    ):
        raise LifecycleError("execution-target-invalid", "Expected output identity is invalid")
    result = {
        "path": name,
        "role": item.get("role"),
        "expectedSha256": expected,
        "expectedBytes": limit,
        "allowExisting": item.get("allowExisting") is True,
    }
    try:
        path = root / name
        # Guard every existing parent even if the final output is absent.
        parent = path.parent
        while parent != root:
            if parent.is_symlink():
                raise LifecycleError("execution-target-alias", "Output parent is an unsafe alias")
            parent = parent.parent
        try:
            info = path.lstat()
        except FileNotFoundError:
            return {**result, "disposition": "ABSENT", "observedSha256": None}
        if not stat.S_ISREG(info.st_mode):
            raise LifecycleError("execution-target-alias", "Output must not be a symlink or non-regular entry")
        if expected is None or not result["allowExisting"]:
            return {**result, "disposition": "INCOMPATIBLE", "observedSha256": None}
        if type(limit) is not int:
            raise LifecycleError("execution-target-invalid", "Expected output byte limit is required")
        data = read_stable_repository_file(root, name, max_bytes=max(1, limit), label="target output")
        actual = hashlib.sha256(data).hexdigest()
        disposition = "EXACT_MATCH" if len(data) == limit and actual == expected else "INCOMPATIBLE"
        return {**result, "disposition": disposition, "observedSha256": actual}
    except (OSError, LifecycleError) as exc:
        code = exc.code if isinstance(exc, LifecycleError) else "output-unavailable"
        return {**result, "disposition": "UNAVAILABLE", "observedSha256": None, "code": code}


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def discard_created_output(
    repository_root: Path,
    name: str,
    expected_versions: list[bytes],
    *,
    expected_identity: tuple[int, ...] | None = None,
    allow_partial: bool = False,
) -> bool:
    """Undo an exclusively created output under the caller's shared writer lock.

    Mismatched bytes or identities belong to a competing writer and are retained.
    This is ordinary cooperating-writer rollback, not host-attested isolation.
    """
    root = repository_root.resolve(strict=True)
    relative = repository_authority_name(root / normalize_repo_path(name), root)
    path = root / relative
    if not expected_versions or max(map(len, expected_versions)) > MAX_TARGET_FILE_BYTES:
        raise LifecycleError("execution-target-invalid", "Rollback requires bounded prepared bytes")
    try:
        with hold_authority_directory(path.parent, writable=True) as directory:
            before = directory.stat_child(path.name)
            if not stat.S_ISREG(before.st_mode):
                return False
            identity = _file_identity(before)
            if expected_identity is not None and identity != expected_identity:
                return False
            identity_fields = 5 if os.name == "nt" else 6
            # Reuse the held parent; reopening it conflicts with Windows write sharing.
            with os.fdopen(directory.open_child(path.name), "rb", buffering=0) as stream:
                if _file_identity(os.fstat(stream.fileno()))[:identity_fields] != identity[:identity_fields]:
                    return False
                data = stream.read(max(map(len, expected_versions)) + 1)
                if _file_identity(os.fstat(stream.fileno()))[:identity_fields] != identity[:identity_fields]:
                    return False
            if not any(data == value or (allow_partial and value.startswith(data)) for value in expected_versions):
                return False
            if _file_identity(directory.stat_child(path.name)) != identity:
                return False
            directory.unlink_child(path.name)
            directory.sync()
        return True
    except FileNotFoundError:
        return True

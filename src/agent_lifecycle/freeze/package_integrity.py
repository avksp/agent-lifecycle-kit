"""Filesystem-backed integrity authority for frozen plan packages."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, sha256_hex
from agent_lifecycle.contracts.paths import read_stable_repository_file
from agent_lifecycle.contracts.paths import normalize_repo_path

PLAN_FILE_INVENTORY_SCHEMA = "agent-plan-file-inventory.v1"
PLAN_LOCK_V1_SCHEMA = "agent-plan-lock.v1"
PLAN_LOCK_V2_SCHEMA = "agent-plan-lock.v2"
PACKAGE_INTEGRITY_VERIFICATION_SCHEMA = "agent-plan-package-integrity-verification.v1"
MAX_PLAN_FILE_BYTES = 8 * 1024 * 1024


def plan_integrity_required(manifest: dict[str, Any]) -> bool:
    """Return whether a manifest opts into whole-package v2 verification."""

    integrity = manifest.get("packageIntegrity")
    return isinstance(integrity, dict) and integrity.get("required") is True


def verify_plan_lock_envelope(manifest: dict[str, Any], lock: dict[str, Any]) -> dict[str, Any]:
    """Verify lock metadata without claiming that filesystem bytes were checked."""

    if not isinstance(lock, dict):
        raise LifecycleError("invalid-plan-lock", "plan lock must be an object")
    schema = lock.get("schemaVersion")
    if schema == PLAN_LOCK_V1_SCHEMA:
        digest = canonical_digest(manifest)
        if lock.get("manifestHash") != digest:
            raise LifecycleError("plan-lock-mismatch", "plan lock manifestHash mismatch")
        if lock.get("planRevision") != manifest.get("planRevision"):
            raise LifecycleError("plan-lock-mismatch", "plan lock revision mismatch")
        if plan_integrity_required(manifest):
            raise LifecycleError("plan-lock-v2-required", "manifest requires an agent-plan-lock.v2 inventory binding")
        return {
            "schemaVersion": "agent-plan-lock-verification.v1",
            "packageId": lock.get("packageId") or manifest.get("package", {}).get("id"),
            "planRevision": lock.get("planRevision"),
            "manifestHash": digest,
            "filesystemVerified": False,
            "lockSchemaVersion": PLAN_LOCK_V1_SCHEMA,
        }
    if schema != PLAN_LOCK_V2_SCHEMA:
        raise LifecycleError("invalid-plan-lock", "plan lock schemaVersion is unsupported")
    digest = canonical_digest(manifest)
    package = manifest.get("package") if isinstance(manifest.get("package"), dict) else {}
    if lock.get("manifestHash") != digest:
        raise LifecycleError("plan-lock-mismatch", "plan lock manifestHash mismatch")
    if lock.get("planRevision") != manifest.get("planRevision"):
        raise LifecycleError("plan-lock-mismatch", "plan lock revision mismatch")
    if lock.get("packageId") != package.get("id"):
        raise LifecycleError("plan-lock-package-mismatch", "plan lock packageId mismatch")
    entries = _validate_entries(lock.get("entries"))
    expected_inventory_digest = canonical_digest({"schemaVersion": PLAN_FILE_INVENTORY_SCHEMA, "entries": entries})
    if lock.get("planFilesHash") != expected_inventory_digest:
        raise LifecycleError("plan-lock-inventory-mismatch", "plan lock planFilesHash mismatch")
    return {
        "schemaVersion": "agent-plan-lock-verification.v1",
        "packageId": package.get("id"),
        "planRevision": lock.get("planRevision"),
        "manifestHash": digest,
        "planFilesHash": expected_inventory_digest,
        "entries": entries,
        "filesystemVerified": False,
        "lockSchemaVersion": PLAN_LOCK_V2_SCHEMA,
    }


def build_plan_lock_v2(manifest: dict[str, Any], *, repository_root: Path) -> dict[str, Any]:
    """Build a v2 lock from the exact bytes of a declared plan package."""

    if not plan_integrity_required(manifest):
        raise LifecycleError("plan-lock-v2-not-required", "manifest must require v2 package integrity")
    entries = _inventory_entries(manifest, repository_root)
    package = manifest.get("package") if isinstance(manifest.get("package"), dict) else {}
    body = {
        "schemaVersion": PLAN_LOCK_V2_SCHEMA,
        "packageId": package.get("id"),
        "planRevision": manifest.get("planRevision"),
        "manifestHash": canonical_digest(manifest),
        "planFilesHash": canonical_digest({"schemaVersion": PLAN_FILE_INVENTORY_SCHEMA, "entries": entries}),
        "entries": entries,
    }
    verify_plan_lock_envelope(manifest, body)
    return body


def verify_plan_package_integrity(
    manifest: dict[str, Any],
    lock: dict[str, Any],
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Verify a lock and, when required, every declared package file."""

    envelope = verify_plan_lock_envelope(manifest, lock)
    if envelope["lockSchemaVersion"] == PLAN_LOCK_V1_SCHEMA:
        body = {
            "schemaVersion": PACKAGE_INTEGRITY_VERIFICATION_SCHEMA,
            "status": "PASS",
            "required": False,
            "lockSchemaVersion": PLAN_LOCK_V1_SCHEMA,
            "filesystemVerified": False,
            "manifestHash": envelope["manifestHash"],
            "planFilesHash": None,
            "entries": [],
            "blockers": [],
        }
        return {**body, "verificationDigest": canonical_digest(body)}

    expected_entries = _inventory_entries(manifest, repository_root)
    actual_entries = envelope["entries"]
    if actual_entries != expected_entries:
        raise LifecycleError(
            "plan-package-files-mismatch",
            "plan lock entries do not match the current declared package files",
            {"expected": expected_entries, "actual": actual_entries},
        )
    package = manifest.get("package") if isinstance(manifest.get("package"), dict) else {}
    package_root = _package_root(repository_root, package.get("planArtifactRoot"))
    _reject_undeclared_top_level_files(manifest, package_root, expected_entries, repository_root=repository_root)
    body = {
        "schemaVersion": PACKAGE_INTEGRITY_VERIFICATION_SCHEMA,
        "status": "PASS",
        "required": plan_integrity_required(manifest),
        "lockSchemaVersion": PLAN_LOCK_V2_SCHEMA,
        "filesystemVerified": True,
        "manifestHash": envelope["manifestHash"],
        "planFilesHash": envelope["planFilesHash"],
        "entries": expected_entries,
        "blockers": [],
    }
    return {**body, "verificationDigest": canonical_digest(body)}


def _inventory_entries(manifest: dict[str, Any], repository_root: Path) -> list[dict[str, Any]]:
    plan_files = manifest.get("planFiles")
    if not isinstance(plan_files, list) or not plan_files:
        raise LifecycleError("plan-files-missing", "v2 plan package must declare a non-empty planFiles inventory")
    package = manifest.get("package") if isinstance(manifest.get("package"), dict) else {}
    package_root = _package_root(repository_root, package.get("planArtifactRoot"))
    normalized: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(plan_files):
        if not isinstance(raw, str):
            raise LifecycleError("plan-file-path-invalid", "planFiles entries must be strings", {"index": index})
        path = normalize_repo_path(raw, label="planFiles entry")
        if path in seen:
            raise LifecycleError("plan-file-duplicate", "planFiles contains a duplicate path", {"path": path})
        seen.add(path)
        candidate = _resolve_declared_path(repository_root, package_root, path)
        # Reading through the shared stable repository boundary rejects missing,
        # symlinked, changing and over-sized authoritative files.
        data = read_stable_repository_file(
            repository_root,
            path,
            max_bytes=MAX_PLAN_FILE_BYTES,
            label="declared plan file",
        )
        if candidate.is_symlink():
            raise LifecycleError("plan-file-symlink", "declared plan files must not be symlinks", {"path": path})
        normalized.append(path)
        # Keep bytes in a side table only through the local list below.
        del data
    if normalized != sorted(normalized):
        raise LifecycleError("plan-files-unsorted", "planFiles must be sorted lexicographically")
    manifest_path = _manifest_path(package_root, repository_root)
    if manifest_path not in seen:
        raise LifecycleError("plan-manifest-unbound", "plan.manifest.json must be part of the v2 inventory")
    entries: list[dict[str, Any]] = []
    for path in normalized:
        data = read_stable_repository_file(
            repository_root,
            path,
            max_bytes=MAX_PLAN_FILE_BYTES,
            label="declared plan file",
        )
        entries.append({"path": path, "bytes": len(data), "sha256": sha256_hex(data)})
    return entries


def _validate_entries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise LifecycleError("plan-lock-inventory-invalid", "v2 lock entries must be a non-empty list")
    result: list[dict[str, Any]] = []
    previous: str | None = None
    for index, entry in enumerate(value):
        if not isinstance(entry, dict) or set(entry) != {"path", "bytes", "sha256"}:
            raise LifecycleError("plan-lock-inventory-invalid", "v2 lock entry shape is invalid", {"index": index})
        path = normalize_repo_path(entry.get("path"), label="plan lock entry")
        size = entry.get("bytes")
        digest = entry.get("sha256")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise LifecycleError("plan-lock-inventory-invalid", "v2 lock entry byte count is invalid", {"path": path})
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise LifecycleError("plan-lock-inventory-invalid", "v2 lock entry digest is invalid", {"path": path})
        if previous is not None and path <= previous:
            raise LifecycleError("plan-lock-inventory-order", "v2 lock entries must be unique and sorted", {"path": path})
        previous = path
        result.append({"path": path, "bytes": size, "sha256": digest})
    return result


def _package_root(repository_root: Path, raw: Any) -> Path:
    if not isinstance(raw, str) or not raw:
        raise LifecycleError("invalid-plan-manifest", "package.planArtifactRoot is required for v2 integrity")
    root = repository_root.resolve()
    if raw == ".":
        candidate = root
    else:
        normalized = normalize_repo_path(raw, label="package.planArtifactRoot")
        candidate = root.joinpath(*PurePosixPath(normalized).parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise LifecycleError("plan-package-root-invalid", "plan package root must remain in the repository") from exc
    if not resolved.is_dir() or candidate.is_symlink():
        raise LifecycleError("plan-package-root-invalid", "plan package root must be a regular directory")
    return resolved


def _resolve_declared_path(repository_root: Path, package_root: Path, path: str) -> Path:
    candidate = repository_root.resolve().joinpath(*PurePosixPath(path).parts)
    try:
        candidate.relative_to(package_root)
    except ValueError as exc:
        raise LifecycleError("plan-file-outside-package", "declared plan file escapes package root", {"path": path}) from exc
    return candidate


def _manifest_path(package_root: Path, repository_root: Path) -> str:
    try:
        return package_root.joinpath("plan.manifest.json").relative_to(repository_root.resolve()).as_posix()
    except ValueError as exc:
        raise LifecycleError("plan-package-root-invalid", "plan package root is outside repository") from exc


def _reject_undeclared_top_level_files(
    manifest: dict[str, Any],
    package_root: Path,
    entries: list[dict[str, Any]],
    *,
    repository_root: Path,
) -> None:
    integrity = manifest.get("packageIntegrity") if isinstance(manifest.get("packageIntegrity"), dict) else {}
    allowed = integrity.get("allowedUnlistedFiles", ["plan.lock.json"])
    if not isinstance(allowed, list) or not all(isinstance(item, str) and item for item in allowed):
        raise LifecycleError("plan-integrity-policy-invalid", "allowedUnlistedFiles must be a list of names")
    package_relative = package_root.relative_to(repository_root.resolve()).as_posix()
    declared_top_level: set[str] = set()
    for entry in entries:
        path = PurePosixPath(entry["path"])
        try:
            relative = path.relative_to(PurePosixPath(package_relative))
        except ValueError:
            continue
        if len(relative.parts) == 1:
            declared_top_level.add(relative.as_posix())
    for child in sorted(package_root.iterdir(), key=lambda item: item.name):
        if child.is_dir() and not child.is_symlink():
            continue
        if child.name in allowed:
            if child.is_symlink():
                raise LifecycleError("plan-file-symlink", "unlisted control files must not be symlinks", {"path": child.name})
            continue
        if child.name not in declared_top_level:
            raise LifecycleError("plan-file-undeclared", "package contains an undeclared top-level file", {"path": child.name})

"""Create-only compact authoring and read-only explanations; no lifecycle authority."""

from __future__ import annotations

import os
import stat
import unicodedata
from pathlib import Path
from typing import Any

from agent_lifecycle.compiler.task_packets import packet_publication_lock
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest, load_json_object
from agent_lifecycle.contracts.authority_io import hold_authority_directory
from agent_lifecycle.contracts.compact_plan_schemas import MAX_COMPACT_INPUT_BYTES
from agent_lifecycle.contracts.execution_target import discard_created_output
from agent_lifecycle.contracts.ownership_paths import (
    normalize_authority_path,
    repository_authority_name,
    require_manifest_authority_paths,
)
from agent_lifecycle.contracts.paths import read_stable_repository_file
from agent_lifecycle.planning.compact_packages import (
    build_plan_package_profiles,
    compile_compact_plan,
    explain_compact_plan,
)

_DRAFT_PREREQUISITE = (
    "Before freeze-prepare: author acceptance-criteria.md from the explicit AC/EV facts "
    "and add it to planFiles. The prepared candidate still needs current independent review before lock-create"
)


def compact_package_profiles() -> dict[str, Any]:
    """Include filesystem authoring prerequisites in the user-facing tier view."""
    body = build_plan_package_profiles()
    body.pop("profileDigest")
    body["draftCompletionPrerequisites"] = [_DRAFT_PREREQUISITE]
    for profile in body["profiles"]:
        if profile["compactSupported"]:
            profile["requiredArtifacts"].append("acceptance-criteria.md explicitly added to planFiles before freeze")
    return {**body, "profileDigest": canonical_digest(body)}


def compact_plan_command(
    *, input_path: str, repository_root: Path, output_path: str | None = None, explain: bool = False
) -> dict[str, Any]:
    """Consume one stable bounded source; publishing never overwrites an artifact."""
    root = repository_root.resolve(strict=True)
    source_name = _name(root, input_path)
    _inspect_path(root, source_name)
    source_version = _version(root / source_name)
    raw = _read(root, source_name)
    if _version(root / source_name) != source_version:
        raise LifecycleError("compact-plan-source-changed", "Compact source changed while being read")
    source = load_json_object(raw, label="compact source")
    package = source.get("package")
    plan_root = package.get("planArtifactRoot") if isinstance(package, dict) else None
    default_output = plan_root + "/plan.manifest.json" if isinstance(plan_root, str) else "plan.manifest.json"
    destination = _name(root, output_path or default_output)
    explanation = None
    if explain:
        explanation = explain_compact_plan(source, source_path=source_name, manifest_path=destination)
        if explanation["status"] != "PASS":
            return explanation
    manifest = compile_compact_plan(source, source_path=source_name, manifest_path=destination)
    require_manifest_authority_paths(manifest, operation_root=root)
    _inspect_manifest_paths(root, manifest)
    if explanation is not None:
        return {**explanation, "nextCommands": [_DRAFT_PREREQUISITE, *explanation["nextCommands"]]}
    prepared = canonical_bytes(manifest) + b"\n"
    _publish(root, source_name, raw, source_version, destination, prepared)
    return {
        "schemaVersion": "agent-compact-plan-compilation.v1",
        "status": "DRAFT",
        "manifestPath": destination,
        "manifestDigest": canonical_digest(manifest),
        "sourcePath": source_name,
        "sourceBytes": len(raw),
        "canonicalOutputBytes": len(prepared),
        "filesWritten": [destination],
        "authorityClaimed": False,
        "modelCallsStarted": False,
        "nextCommands": [_DRAFT_PREREQUISITE, "plan freeze-prepare", "independent plan review", "plan lock-create"],
    }


def _name(root: Path, name: str) -> str:
    return normalize_authority_path(repository_authority_name(root / name, root))


def _read(root: Path, name: str) -> bytes:
    return read_stable_repository_file(root, name, max_bytes=MAX_COMPACT_INPUT_BYTES, label="compact source")


def _inspect_path(root: Path, name: str) -> None:
    """Reject observed link/name ambiguity without probing filesystem rules by writing."""
    current = root
    for part in normalize_authority_path(name).split("/"):
        matches = []
        try:
            with os.scandir(current) as entries:
                for index, entry in enumerate(entries):
                    if index >= 10_000:
                        raise LifecycleError("compact-plan-directory-too-large", "Directory inspection exceeds limit")
                    if unicodedata.normalize("NFC", entry.name).casefold() == part.casefold():
                        matches.append(entry.name)
        except FileNotFoundError:
            return
        if not matches:
            return
        if len(matches) != 1 or unicodedata.normalize("NFC", matches[0]) != part:
            raise LifecycleError("compact-plan-path-alias", "Authority path has an ambiguous or aliased name")
        current = current / part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise LifecycleError("compact-plan-path-alias", "Authority path cannot contain a link")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise LifecycleError("compact-plan-path-alias", "Authority file has multiple hard links")


def _inspect_manifest_paths(root: Path, manifest: dict[str, Any]) -> None:
    names = [*manifest["planFiles"], manifest["package"]["artifactRoot"]]
    names.extend(manifest["readOnly"])
    names.extend(manifest["forbiddenWrites"])
    for task in manifest["workstreams"]:
        names.extend(task["writes"])
    names.extend(entry["artifactPath"] for entry in manifest["acceptance"]["evidence"])
    for name in sorted(set(names)):
        _inspect_path(root, name)


def _version(path: Path) -> tuple[int, ...]:
    info = path.lstat()
    return (*_identity(info), info.st_nlink)


def _identity(info: os.stat_result) -> tuple[int, ...]:
    """Capture the created descriptor's exact fingerprint for guarded rollback."""
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _require_same_source(root: Path, name: str, raw: bytes, version: tuple[int, ...]) -> None:
    _inspect_path(root, name)
    if _version(root / name) != version or _read(root, name) != raw or _version(root / name) != version:
        raise LifecycleError("compact-plan-source-changed", "Compact source changed before publication completed")


def _publish(root: Path, source: str, raw: bytes, version: tuple[int, ...], destination: str, prepared: bytes) -> None:
    path = root / destination
    with packet_publication_lock(path.parent):
        _inspect_path(root, destination)
        if path.exists():
            raise LifecycleError("compact-plan-output-exists", "Canonical output must not already exist")
        _require_same_source(root, source, raw, version)
        created = False
        created_identity = None
        try:
            with hold_authority_directory(path.parent, writable=True) as directory:
                fd = directory.write_child(path.name, append=False, mode=0o644)
                created = True
                created_identity = _identity(os.fstat(fd))
                with os.fdopen(fd, "wb") as stream:
                    try:
                        stream.write(prepared)
                        stream.flush()
                        os.fsync(stream.fileno())
                    finally:
                        created_identity = _identity(os.fstat(stream.fileno()))
                directory.sync()
            _require_same_source(root, source, raw, version)
        except FileExistsError:
            if created and created_identity is not None:
                discard_created_output(
                    root, destination, [prepared], expected_identity=created_identity, allow_partial=True
                )
            raise LifecycleError("compact-plan-output-exists", "Canonical output must not already exist") from None
        except BaseException:
            if created and created_identity is not None:
                discard_created_output(
                    root, destination, [prepared], expected_identity=created_identity, allow_partial=True
                )
            raise

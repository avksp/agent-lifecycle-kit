"""Create a bounded private snapshot of one catalogue-bound closed package."""

from __future__ import annotations

import os
import stat
import subprocess
import unicodedata
from collections import deque
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any, TypeGuard
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest, load_json_object
from agent_lifecycle.contracts.authority_io import (
    create_authority_bytes,
    hold_authority_directory,
    read_authority_bytes,
    resolve_authority_anchor,
)
from agent_lifecycle.contracts.paths import is_under_repo_path, normalize_repo_path
from agent_lifecycle.contracts.workflow_state_authority import decode_workflow_authority
from agent_lifecycle.contracts.workflow_storage_context import StorageOperation
from agent_lifecycle.workflow.artifacts import require_artifact_identity

CATALOGUE_SCHEMA = "agent-local-package-catalogue.v1"
MAX_PACKAGES = 64
MAX_ENTRIES = 1024
MAX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
MAX_CATALOGUE_BYTES = 256 * 1024


@dataclass(frozen=True)
class _Entry:
    package_id: str
    manifest: str
    predecessors: tuple[str, ...]
    state: str | None
    proof: str | None


@dataclass(frozen=True)
class _Member:
    repository_path: str
    archive_path: str
    identity: tuple[int, ...]


def inventory_packages(project_root: Path, catalogue: str, catalogue_sha256: str) -> dict[str, Any]:
    """Inspect all declared edges and closure without writing to the project."""
    root = project_root.resolve(strict=True)
    raw = _read(root, _local_path(catalogue), MAX_CATALOGUE_BYTES)
    if sha256(raw).hexdigest() != catalogue_sha256:
        raise LifecycleError("archive-catalogue-digest-mismatch", "catalogue bytes differ from the pinned SHA-256")
    scope, entries = _entries(load_json_object(raw, label="package catalogue"))
    incoming = {predecessor for entry in entries for predecessor in entry.predecessors}
    packages = [_package_row(root, entry, entry.package_id in incoming) for entry in entries]
    _require_disjoint_roots(packages)
    body = {
        "schemaVersion": "agent-local-package-inventory.v1",
        "status": "PASS",
        "scope": scope,
        "catalogueSha256": catalogue_sha256,
        "packages": packages,
        "globalCoverageClaimed": False,
    }
    return {**body, "inventoryDigest": canonical_digest(body)}


def create_package_archive(
    project_root: Path,
    catalogue: str,
    catalogue_sha256: str,
    inventory_digest: str,
    package_id: str,
    out: Path,
) -> dict[str, Any]:
    """Publish only a verified ZIP sample to a fresh external pathname."""
    root = project_root.resolve(strict=True)
    target = _destination(root, out)
    inventory = inventory_packages(root, catalogue, catalogue_sha256)
    if inventory["inventoryDigest"] != inventory_digest:
        raise LifecycleError("archive-inventory-drift", "package inventory has changed")
    selected = next((item for item in inventory["packages"] if item["id"] == package_id), None)
    if selected is None:
        raise LifecycleError("archive-package-unknown", "selected package is absent from the catalogue")
    if not selected["closureEligible"]:
        raise LifecycleError(
            "archive-package-ineligible", "selected package is ineligible", {"reason": selected["reason"]}
        )
    roots = (selected["planRoot"], selected["workRoot"])
    members = _members(root, *roots)
    _require_plan_files(root, selected, members)
    _require_ignored(root, members)
    payload, manifest = _archive_bytes(root, members, selected, inventory)
    _require_archived_closure(members, selected, manifest["members"])
    if _members(root, *roots) != members:
        raise LifecycleError("archive-source-drift", "package membership or file identity changed during the copy")
    _require_ignored(root, members)
    if inventory_packages(root, catalogue, catalogue_sha256) != inventory:
        raise LifecycleError("archive-inventory-drift", "catalogue or closure changed during the copy")
    target = _destination(root, target)
    try:
        create_authority_bytes(target, payload, root=target.parent, private=True)
    except FileExistsError:
        raise LifecycleError("archive-target-exists", "archive destination already exists") from None
    try:
        retained = read_authority_bytes(target, root=target.parent, max_bytes=len(payload))
    except (LifecycleError, OSError) as exc:
        raise LifecycleError("archive-output-unverified", "the created ZIP could not be read back") from exc
    if retained != payload:
        raise LifecycleError("archive-output-unverified", "written bytes differ from the verified snapshot")
    return {
        "schemaVersion": "agent-local-package-archive.v1",
        "status": "PASS",
        "scope": inventory["scope"],
        "packageId": package_id,
        "inventoryDigest": inventory_digest,
        "archiveSha256": sha256(payload).hexdigest(),
        "manifestDigest": canonical_digest(manifest),
        "memberCount": len(members),
        "sourceBytesReclaimed": 0,
        "authorityClaimed": False,
    }


def _entries(body: dict[str, Any]) -> tuple[str, list[_Entry]]:
    scope, rows = body.get("scope"), body.get("packages")
    if (
        body.keys() != {"schemaVersion", "complete", "scope", "packages"}
        or body["schemaVersion"] != CATALOGUE_SCHEMA
        or body["complete"] is not True
        or not _valid_id(scope)
        or not isinstance(rows, list)
        or not 1 <= len(rows) <= MAX_PACKAGES
    ):
        raise LifecycleError("archive-catalogue-incomplete", "a complete, bounded named catalogue is required")
    entries = [_entry(row) for row in rows]
    if len({entry.package_id.casefold() for entry in entries}) != len(entries):
        raise LifecycleError("archive-catalogue-alias", "catalogue package identities are not unique")
    pending = {entry.package_id: set(entry.predecessors) for entry in entries}
    if any(not dependencies <= pending.keys() for dependencies in pending.values()):
        raise LifecycleError("archive-catalogue-dangling", "catalogue predecessor reference is missing")
    while pending:
        leaves = {key for key, deps in pending.items() if not deps}
        if not leaves:
            raise LifecycleError("archive-catalogue-cycle", "catalogue predecessor references contain a cycle")
        pending = {key: deps - leaves for key, deps in pending.items() if key not in leaves}
    return scope, sorted(entries, key=lambda entry: entry.package_id)


def _entry(row: object) -> _Entry:
    required = {"id", "manifest", "predecessorIds"}
    if not isinstance(row, dict) or not required <= row.keys() or row.keys() - required - {"state", "proof"}:
        raise LifecycleError("archive-catalogue-entry-invalid", "catalogue entry fields are invalid")
    package_id, predecessors = row["id"], row["predecessorIds"]
    if (
        not _valid_id(package_id)
        or not isinstance(predecessors, list)
        or len(predecessors) > MAX_PACKAGES
        or not all(_valid_id(item) for item in predecessors)
        or len(set(predecessors)) != len(predecessors)
    ):
        raise LifecycleError("archive-catalogue-entry-invalid", "catalogue identity or references are invalid")
    state = _local_path(row["state"]) if "state" in row else None
    proof = _local_path(row["proof"]) if "proof" in row else None
    if proof is not None and state is None:
        raise LifecycleError("archive-catalogue-entry-invalid", "a declared proof requires its state")
    return _Entry(package_id, _local_path(row["manifest"]), tuple(predecessors), state, proof)


def _valid_id(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and 0 < len(value) <= 128 and all(c.isalnum() or c in "-_." for c in value)


def _local_path(value: object) -> str:
    if not isinstance(value, str):
        raise LifecycleError("archive-path-invalid", "expected a repository-relative pathname")
    name = normalize_repo_path(value)
    if name != value or any(part.startswith(".") for part in name.split("/")):
        raise LifecycleError("archive-path-invalid", "unsafe or aliased repository pathname")
    return name


def _read(root: Path, name: str, cap: int = MAX_MEMBER_BYTES) -> bytes:
    try:
        return read_authority_bytes(root / name, root=root, max_bytes=cap)
    except OSError as exc:
        raise LifecycleError("archive-source-unavailable", "required archive input could not be read") from exc


def _package_row(root: Path, entry: _Entry, referenced: bool) -> dict[str, Any]:
    raw = _read(root, entry.manifest)
    manifest = load_json_object(raw, label="package manifest")
    package = manifest.get("package")
    if not isinstance(package, dict) or package.get("id") != entry.package_id:
        raise LifecycleError("archive-manifest-mismatch", "catalogue and manifest identify different packages")
    plan = _local_path(package.get("planArtifactRoot"))
    work = _local_path(package.get("artifactRoot"))
    if not plan.startswith(("tasks/", "work/")) or not work.startswith("work/"):
        raise LifecycleError("archive-roots-invalid", "package roots must be local task or work directories")
    if entry.manifest != f"{plan}/plan.manifest.json":
        raise LifecycleError("archive-manifest-mismatch", "catalogue must point to the canonical manifest")
    paths = (path for path in (entry.state, entry.proof) if path is not None)
    if any(path == work or not is_under_repo_path(path, work) for path in paths):
        raise LifecycleError("archive-roots-invalid", "state and final proof must be in the package work root")
    eligible, reason, facts = _closure(root, entry, manifest)
    if referenced:
        eligible, reason = False, "REFERENCED_PREDECESSOR"
    return {
        "id": entry.package_id,
        "planRoot": plan,
        "workRoot": work,
        "manifestPath": entry.manifest,
        "statePath": entry.state,
        "proofPath": entry.proof,
        "manifestSha256": sha256(raw).hexdigest(),
        "closureEligible": eligible,
        "reason": reason,
        **facts,
    }


def _closure(root: Path, entry: _Entry, manifest: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    if entry.state is None:
        return False, "NO_WORKFLOW_STATE", {}
    try:
        raw_state = _read(root, entry.state)
        path = root / entry.state
        pointer = load_json_object(raw_state, label="workflow state")
        if resolve_authority_anchor(path, pointer.get("packageRoot", "."), root=root) != root:
            raise LifecycleError("archive-completion-mismatch", "package state binds a different authority root")
        with StorageOperation(root, state_path=path, run_id=pointer.get("runId")) as operation:
            state = decode_workflow_authority(raw_state, root=root, state_path=path, operation=operation)
        if _read(root, entry.state) != raw_state:
            raise LifecycleError("archive-source-drift", "state changed during inspection")
        facts = {"stateSha256": sha256(raw_state).hexdigest(), "phase": state.get("phase"), "proofSha256": None}
        if state.get("phase") != "COMPLETE" or manifest.get("status") != "FROZEN" or entry.proof is None:
            return False, "NO_BOUND_COMPLETION", facts
        proof_raw = _require_completion(root, entry, manifest, state)
        return True, "COMPLETE", {**facts, "proofSha256": sha256(proof_raw).hexdigest()}
    except (LifecycleError, OSError) as exc:
        detail = exc.code if isinstance(exc, LifecycleError) else "archive-source-unavailable"
        return False, "COMPLETION_UNAVAILABLE", {"closureDiagnostic": detail}


def _require_completion(root: Path, entry: _Entry, manifest: dict[str, Any], state: dict[str, Any]) -> bytes:
    proof_id = state.get("finalProof")
    if (
        not isinstance(proof_id, dict)
        or proof_id.get("path") != entry.proof
        or proof_id.get("semanticStatus") != "READY_FOR_FINALIZATION"
        or state.get("packageId") != entry.package_id
        or state.get("planDigest") != canonical_digest(manifest)
        or state.get("planRevision") != manifest.get("planRevision")
    ):
        raise LifecycleError("archive-completion-mismatch", "state does not bind the package and final proof")
    proof = require_artifact_identity(root, proof_id, label="final proof")
    proof_body = {key: value for key, value in proof.items() if key != "bodyDigest"}
    revision = proof.get("stateRevisionBeforeFinalization")
    lineage = ("runId", "packageId", "planDigest", "planRevision", "sourceRevision")
    if (
        proof.get("schemaVersion") != "agent-run-final-proof.v1"
        or proof.get("semanticStatus") != "READY_FOR_FINALIZATION"
        or proof.get("bodyDigest") != canonical_digest(proof_body)
        or any(not state.get(key) or proof.get(key) != state[key] for key in lineage)
        or type(revision) is not int
        or state.get("stateRevision") != revision + 1
    ):
        raise LifecycleError("archive-completion-mismatch", "final proof lineage does not match terminal state")
    return canonical_bytes(proof) + b"\n"


def _require_disjoint_roots(packages: list[dict[str, Any]]) -> None:
    roots = sorted(
        unicodedata.normalize("NFC", str(item[field])).casefold()
        for item in packages
        for field in ("planRoot", "workRoot")
    )
    for index, root in enumerate(roots):
        if any(is_under_repo_path(later, root) for later in roots[index + 1 :]):
            raise LifecycleError("archive-root-overlap", "package roots overlap or alias one another")


def _destination(root: Path, path: Path) -> Path:
    try:
        parent = path.parent.resolve(strict=True)
        if not path.is_absolute() or parent != path.parent or not parent.is_dir():
            raise LifecycleError("archive-target-invalid", "provide a canonical path in an existing directory")
        if _overlapping_directories(root, parent):
            raise LifecycleError("archive-target-overlap", "archive destination must be disjoint from the project")
        if path.suffix != ".zip" or _local_path(path.name) != path.name:
            raise LifecycleError("archive-target-invalid", "archive target must have a safe .zip name")
        with hold_authority_directory(parent) as directory:
            try:
                directory.stat_child(path.name)
            except FileNotFoundError:
                return path
            raise LifecycleError("archive-target-exists", "archive destination already exists")
    except OSError as exc:
        raise LifecycleError("archive-target-invalid", "archive destination parent is unavailable") from exc


def _overlapping_directories(root: Path, parent: Path) -> bool:
    return any(root.samefile(path) for path in (parent, *parent.parents)) or any(
        parent.samefile(path) for path in root.parents
    )


def _members(root: Path, plan_root: str, work_root: str) -> list[_Member]:
    queue = deque([(plan_root, "plan"), (work_root, "work")])
    seen: set[str] = set()
    result: list[_Member] = []
    total = 0
    try:
        while queue:
            name, prefix = queue.popleft()
            directory = root / name
            with (
                hold_authority_directory(directory, root=root) as held,
                os.scandir(held.fd if held.fd is not None else directory) as entries,
            ):
                for entry in entries:
                    rel = _local_path(f"{name}/{entry.name}")
                    member_name = _local_path(f"{prefix}/{entry.name}")
                    key = unicodedata.normalize("NFC", member_name).casefold()
                    if key in seen:
                        raise LifecycleError("archive-member-alias", "archive member paths collide")
                    seen.add(key)
                    if len(seen) > MAX_ENTRIES:
                        raise LifecycleError("archive-entry-limit", "archive exceeds its entry limit")
                    # Windows DirEntry.stat omits the link count and file identity.
                    info = held.stat_child(entry.name) if held.fd is None else entry.stat(follow_symlinks=False)
                    if getattr(info, "st_file_attributes", 0) & 0x400:
                        raise LifecycleError("archive-member-unsafe", "reparse-point member refused")
                    if stat.S_ISDIR(info.st_mode):
                        queue.append((rel, member_name))
                    else:
                        _require_file(info)
                        total += info.st_size
                        if total > MAX_SNAPSHOT_BYTES:
                            raise LifecycleError("archive-size-limit", "archive exceeds its aggregate byte limit")
                        result.append(_Member(rel, member_name, _identity(info)))
    except OSError as exc:
        raise LifecycleError("archive-source-unavailable", "archive member could not be inventoried") from exc
    return sorted(result, key=lambda member: member.archive_path)


def _require_file(info: os.stat_result) -> None:
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise LifecycleError("archive-member-unsafe", "archive members must be unlinked regular files")
    if info.st_size > MAX_MEMBER_BYTES:
        raise LifecycleError("archive-size-limit", "archive member exceeds its byte limit")


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode


def _require_plan_files(root: Path, selected: dict[str, Any], members: list[_Member]) -> None:
    manifest_raw = _read(root, selected["manifestPath"])
    if sha256(manifest_raw).hexdigest() != selected["manifestSha256"]:
        raise LifecycleError("archive-source-drift", "manifest changed during the copy")
    manifest = load_json_object(manifest_raw, label="package manifest")
    names = manifest.get("planFiles")
    known = {member.repository_path for member in members if member.archive_path.startswith("plan/")}
    if (
        not isinstance(names, list)
        or not names
        or not all(isinstance(name, str) and _local_path(name) in known for name in names)
        or selected["manifestPath"] not in names
    ):
        raise LifecycleError("archive-plan-files-unavailable", "declared plan inventory is incomplete")


def _require_ignored(root: Path, members: list[_Member]) -> None:
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    paths = b"".join(member.repository_path.encode("utf-8") + b"\0" for member in members)
    try:
        git_root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=root, capture_output=True, timeout=10, check=True, env=env
        )
        ignored = subprocess.run(
            ["git", "check-ignore", "-z", "--stdin"],
            cwd=root,
            input=paths,
            capture_output=True,
            timeout=10,
            check=False,
            env=env,
        )
        if Path(os.fsdecode(git_root.stdout.strip())).resolve(strict=True) != root:
            raise LifecycleError("archive-git-root-invalid", "project must be the root of the selected Git worktree")
    except (OSError, subprocess.SubprocessError) as exc:
        raise LifecycleError("archive-git-unavailable", "could not verify the Git index and ignore rules") from exc
    if not paths or ignored.returncode != 0 or set(ignored.stdout.split(b"\0")) != set(paths.split(b"\0")):
        raise LifecycleError(
            "archive-member-tracked-or-unignored", "every archived member must be ignored and untracked"
        )


def _require_archived_closure(
    members: list[_Member], selected: dict[str, Any], entries: dict[str, dict[str, Any]]
) -> None:
    by_repository_path = {member.repository_path: member.archive_path for member in members}
    for kind in ("manifest", "state", "proof"):
        actual = entries.get(by_repository_path.get(selected[f"{kind}Path"], ""), {})
        expected = selected[f"{kind}Sha256"]
        if not expected or actual.get("sha256") != expected:
            raise LifecycleError("archive-source-drift", "archived closure differs from the verified inventory")


def _archive_bytes(
    root: Path, members: list[_Member], selected: dict[str, Any], inventory: dict[str, Any]
) -> tuple[bytes, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    manifest = {
        "schemaVersion": "agent-local-package-archive-manifest.v1",
        "scope": inventory["scope"],
        "packageId": selected["id"],
        "catalogueSha256": inventory["catalogueSha256"],
        "inventoryDigest": inventory["inventoryDigest"],
        "members": entries,
    }
    with BytesIO() as memory:
        with ZipFile(memory, "w", compression=ZIP_STORED) as archive:
            for member in members:
                data = _read(root, member.repository_path)
                if len(data) != member.identity[2]:
                    raise LifecycleError("archive-source-drift", "archive member length changed during copy")
                entries[member.archive_path] = {"bytes": len(data), "sha256": sha256(data).hexdigest()}
                archive.writestr(ZipInfo(member.archive_path), data)
            manifest_raw = canonical_bytes(manifest) + b"\n"
            archive.writestr(ZipInfo("archive-manifest.json"), manifest_raw)
        with ZipFile(memory, "r") as archive:
            if set(archive.namelist()) != {*entries, "archive-manifest.json"}:
                raise LifecycleError("archive-output-unverified", "ZIP member inventory mismatch")
            for name, expected in entries.items():
                raw = archive.read(name)
                if len(raw) != expected["bytes"] or sha256(raw).hexdigest() != expected["sha256"]:
                    raise LifecycleError("archive-output-unverified", "ZIP member digest mismatch")
            if archive.read("archive-manifest.json") != manifest_raw:
                raise LifecycleError("archive-output-unverified", "ZIP manifest digest mismatch")
        return memory.getvalue(), manifest

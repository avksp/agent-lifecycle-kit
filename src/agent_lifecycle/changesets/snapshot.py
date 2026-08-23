"""Bounded Git-backed evidence for task result freshness."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

from agent_lifecycle.changesets.git import GIT_TIMEOUT_SECONDS, changed_files, resolve_revision
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.ownership_paths import is_under_authority_path, normalize_authority_path
from agent_lifecycle.contracts.paths import normalize_repo_path, read_stable_repository_file

MAX_CHANGED_FILES = 10_000
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_GIT_OBJECT_BYTES = MAX_FILE_BYTES


def capture_task_change_set(
    repository_root: Path,
    *,
    baseline: str,
    write_paths: list[str],
) -> dict[str, Any]:
    """Build canonical task-scoped file evidence against a frozen commit."""

    root = repository_root.resolve()
    baseline_sha = resolve_revision(root, baseline, label="task result baseline")
    authority = [normalize_authority_path(path, label="task write path") for path in write_paths]
    all_changed = changed_files(root, base=baseline_sha)
    if len(all_changed) > MAX_CHANGED_FILES:
        raise LifecycleError(
            "task-snapshot-file-limit",
            "changed file count exceeds the task snapshot limit",
            {"count": len(all_changed), "maxFiles": MAX_CHANGED_FILES},
        )
    scoped = [path for path in all_changed if any(is_under_authority_path(path, prefix) for prefix in authority)]
    transitions: list[dict[str, Any]] = []
    current_entries: list[dict[str, Any]] = []
    total_bytes = 0
    for path in scoped:
        normalized = normalize_repo_path(path, label="changed file")
        before = _baseline_entry(root, baseline_sha, normalized)
        current = _current_entry(root, normalized)
        total_bytes += int(before.get("bytes", 0)) + int(current.get("bytes", 0))
        if total_bytes > MAX_TOTAL_BYTES:
            raise LifecycleError(
                "task-snapshot-byte-limit",
                "task snapshot content exceeds the total byte limit",
                {"bytes": total_bytes, "maxBytes": MAX_TOTAL_BYTES},
            )
        transitions.append({"path": normalized, "baseline": before, "current": current})
        current_entries.append({"path": normalized, **current})
    file_set = {"schemaVersion": "agent-task-file-set.v1", "paths": scoped}
    diff = {"schemaVersion": "agent-task-diff-evidence.v1", "entries": transitions}
    snapshot = {"schemaVersion": "agent-task-content-snapshot.v1", "entries": current_entries}
    return {
        "schemaVersion": "agent-task-change-set-evidence.v1",
        "provider": "git-worktree-v2",
        "baselineSha": baseline_sha,
        "changedFiles": scoped,
        "allChangedFiles": all_changed,
        "fileSetHash": canonical_digest(file_set),
        "diffHash": canonical_digest(diff),
        "snapshotHash": canonical_digest(snapshot),
        "changedFileCount": len(scoped),
        "repositoryChangedFileCount": len(all_changed),
        "contentBytes": total_bytes,
    }


def require_current_task_change_set(
    result: dict[str, Any],
    evidence: dict[str, Any],
) -> None:
    """Require a task result to describe the current bounded snapshot exactly."""

    claimed_paths = result.get("changedFiles")
    if claimed_paths != evidence["changedFiles"]:
        raise LifecycleError(
            "task-result-stale-file-set",
            "task result changedFiles do not match the current task-scoped Git snapshot",
            {"expected": evidence["changedFiles"], "actual": claimed_paths},
        )
    change_set = result.get("changeSet")
    if not isinstance(change_set, dict):
        raise LifecycleError("task-result-change-set-missing", "task result changeSet is required")
    expected = {
        "schemaVersion": "agent-task-change-set-claim.v1",
        "provider": evidence["provider"],
        "baselineSha": evidence["baselineSha"],
        "fileSetHash": evidence["fileSetHash"],
        "diffHash": evidence["diffHash"],
        "snapshotHash": evidence["snapshotHash"],
    }
    mismatches = {
        key: {"expected": value, "actual": change_set.get(key)}
        for key, value in expected.items()
        if change_set.get(key) != value
    }
    if mismatches:
        raise LifecycleError(
            "task-result-stale-snapshot",
            "task result changeSet does not match the current repository snapshot",
            {"mismatches": mismatches},
        )


def _baseline_entry(root: Path, baseline_sha: str, path: str) -> dict[str, Any]:
    output = _git_bytes(
        root,
        ["git", "ls-tree", "-z", baseline_sha, "--", path],
        max_bytes=8192,
        label="baseline tree entry",
    )
    if not output:
        return {"kind": "missing", "mode": None, "sha256": None, "bytes": 0}
    rows = [row for row in output.split(b"\0") if row]
    if len(rows) != 1 or b"\t" not in rows[0]:
        raise LifecycleError("task-snapshot-git-shape", "Git returned an ambiguous baseline tree entry")
    metadata, raw_path = rows[0].split(b"\t", 1)
    try:
        mode, object_type, object_id = metadata.decode("ascii").split(" ", 2)
        decoded_path = raw_path.decode("utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError) as exc:
        raise LifecycleError("task-snapshot-git-shape", "Git returned an invalid baseline tree entry") from exc
    if decoded_path != path or object_type != "blob" or mode not in {"100644", "100755", "120000"}:
        raise LifecycleError("task-snapshot-unsupported-entry", "baseline contains an unsupported task entry")
    data = _git_object_data(root, object_id)
    return {
        "kind": "symlink" if mode == "120000" else "file",
        "mode": mode,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def _current_entry(root: Path, path: str) -> dict[str, Any]:
    candidate = root.joinpath(*path.split("/"))
    _reject_parent_symlinks(root, candidate)
    try:
        before = candidate.lstat()
    except FileNotFoundError:
        return {"kind": "missing", "mode": None, "sha256": None, "bytes": 0}
    except OSError as exc:
        raise LifecycleError("task-snapshot-read-failed", "failed to inspect a changed file") from exc
    if stat.S_ISLNK(before.st_mode):
        try:
            target = os.fsencode(candidate.readlink())
            after = candidate.lstat()
        except OSError as exc:
            raise LifecycleError("task-snapshot-read-race", "changed symlink changed during snapshot") from exc
        if _stat_identity(before) != _stat_identity(after):
            raise LifecycleError("task-snapshot-read-race", "changed symlink changed during snapshot")
        return {
            "kind": "symlink",
            "mode": "120000",
            "sha256": hashlib.sha256(target).hexdigest(),
            "bytes": len(target),
        }
    if not stat.S_ISREG(before.st_mode):
        raise LifecycleError("task-snapshot-unsupported-entry", "changed path is not a regular file or symlink")
    data = read_stable_repository_file(root, path, max_bytes=MAX_FILE_BYTES, label="changed task file")
    try:
        after = candidate.lstat()
    except OSError as exc:
        raise LifecycleError("task-snapshot-read-race", "changed file changed during snapshot") from exc
    if _stat_identity(before) != _stat_identity(after):
        raise LifecycleError("task-snapshot-read-race", "changed file changed during snapshot")
    return {
        "kind": "file",
        "mode": "100755" if before.st_mode & stat.S_IXUSR else "100644",
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def _git_bytes(root: Path, argv: list[str], *, max_bytes: int, label: str) -> bytes:
    try:
        completed = subprocess.run(
            argv,
            cwd=root,
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LifecycleError("task-snapshot-git-failed", f"{label}: Git command failed") from exc
    if completed.returncode != 0:
        raise LifecycleError(
            "task-snapshot-git-failed",
            f"{label}: Git command failed",
            {"exitCode": completed.returncode},
        )
    if len(completed.stdout) > max_bytes:
        raise LifecycleError(
            "task-snapshot-byte-limit",
            f"{label}: Git output exceeds the snapshot limit",
            {"bytes": len(completed.stdout), "maxBytes": max_bytes},
        )
    return completed.stdout


def _git_object_data(root: Path, object_id: str) -> bytes:
    raw_size = _git_bytes(
        root,
        ["git", "cat-file", "-s", object_id],
        max_bytes=128,
        label="baseline blob size",
    )
    try:
        size = int(raw_size.strip())
    except ValueError as exc:
        raise LifecycleError("task-snapshot-git-shape", "Git returned an invalid baseline blob size") from exc
    if size < 0 or size > MAX_GIT_OBJECT_BYTES:
        raise LifecycleError(
            "task-snapshot-byte-limit",
            "baseline blob exceeds the snapshot file limit",
            {"bytes": size, "maxBytes": MAX_GIT_OBJECT_BYTES},
        )
    data = _git_bytes(
        root,
        ["git", "cat-file", "blob", object_id],
        max_bytes=MAX_GIT_OBJECT_BYTES,
        label="baseline blob",
    )
    if len(data) != size:
        raise LifecycleError("task-snapshot-git-shape", "Git baseline blob size changed during snapshot")
    return data


def _reject_parent_symlinks(root: Path, candidate: Path) -> None:
    current = candidate.parent
    while current != root:
        if current.is_symlink():
            raise LifecycleError("task-snapshot-path-symlink", "changed path has a symlinked parent")
        if current.parent == current:
            raise LifecycleError("task-snapshot-path-outside-root", "changed path escapes the repository root")
        current = current.parent


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


__all__ = ["capture_task_change_set", "require_current_task_change_set"]

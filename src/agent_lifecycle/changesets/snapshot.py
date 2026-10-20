"""Bounded Git-backed evidence for task result freshness."""

from __future__ import annotations

import hashlib
import os
import stat
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from agent_lifecycle.changesets.git import GIT_TIMEOUT_SECONDS, changed_files, resolve_revision
from agent_lifecycle.changesets.git_io import BoundedProcess, run_bounded_command
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.ownership_paths import (
    is_under_authority_path,
    normalize_authority_path,
    observed_authority_paths,
)
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
    all_changed = observed_authority_paths(all_changed, operation_root=root)
    scoped = [
        path
        for path in all_changed
        if any(is_under_authority_path(path, prefix, operation_root=root) for prefix in authority)
    ]
    transitions: list[dict[str, Any]] = []
    current_entries: list[dict[str, Any]] = []
    total_bytes = 0
    baselines = _baseline_entries(root, baseline_sha, scoped)
    for path in scoped:
        normalized = normalize_repo_path(path, label="changed file")
        before = baselines[normalized]
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
        "entries": current_entries,
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
    """Retain the established single-entry extension point over one batch."""
    return _baseline_entries(root, baseline_sha, [path])[path]


def _path_batches(paths: list[str]) -> Iterator[list[str]]:
    """Keep argv bounded on Windows as well as POSIX; no per-file worker."""
    batch: list[str] = []
    size = 0
    for path in paths:
        cost = len(path.encode("utf-8")) + 3
        if batch and (len(batch) >= 128 or size + cost > 16_384):
            yield batch
            batch, size = [], 0
        batch.append(path)
        size += cost
    if batch:
        yield batch


def _baseline_entries(root: Path, baseline_sha: str, paths: list[str]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {
        path: {"kind": "missing", "mode": None, "sha256": None, "bytes": 0} for path in paths
    }
    objects: dict[str, tuple[str, str, int]] = {}
    for batch in _path_batches(paths):
        output = _git_bytes(
            root,
            ["git", "ls-tree", "-l", "-z", baseline_sha, "--", *batch],
            max_bytes=8192 * len(batch),
            label="baseline tree entry",
        )
        for row in output.split(b"\0"):
            if row:
                path, metadata = _parse_baseline_row(root, row, set(batch))
                if path in objects:
                    raise LifecycleError("task-snapshot-git-shape", "Git returned an ambiguous baseline tree entry")
                objects[path] = metadata
    if objects:
        entries.update(_read_baseline_blobs(root, objects))
    return entries


def _parse_baseline_row(root: Path, row: bytes, requested: set[str]) -> tuple[str, tuple[str, str, int]]:
    try:
        metadata, raw_path = row.split(b"\t", 1)
        mode, object_type, object_id, raw_size = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError) as exc:
        raise LifecycleError("task-snapshot-git-shape", "Git returned an invalid baseline tree entry") from exc
    if path not in requested:
        raise LifecycleError("task-snapshot-git-shape", "Git returned an ambiguous baseline tree entry")
    if object_type != "blob" or mode not in {"100644", "100755", "120000"}:
        raise LifecycleError("task-snapshot-unsupported-entry", "baseline contains an unsupported task entry")
    if len(object_id) not in (40, 64) or any(value not in "0123456789abcdef" for value in object_id):
        raise LifecycleError("task-snapshot-git-shape", "Git returned an invalid baseline tree entry")
    if raw_size == "BAD":
        # Preserve the established typed missing-object failure. This early
        # diagnostic stays within the complete-call process bound.
        _git_object_data(root, object_id)
    try:
        size = int(raw_size)
    except ValueError as exc:
        raise LifecycleError("task-snapshot-git-shape", "Git returned an invalid baseline blob size") from exc
    if size < 0 or size > MAX_GIT_OBJECT_BYTES:
        raise LifecycleError(
            "task-snapshot-byte-limit",
            "baseline blob exceeds the snapshot file limit",
            {"bytes": size, "maxBytes": MAX_GIT_OBJECT_BYTES},
        )
    return path, (mode, object_id, size)


def _read_baseline_blobs(root: Path, objects: dict[str, tuple[str, str, int]]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    try:
        with BoundedProcess(
            ["git", "cat-file", "--batch"],
            cwd=root,
            deadline=time.monotonic() + GIT_TIMEOUT_SECONDS,
            max_stdout_bytes=MAX_TOTAL_BYTES + 257 * len(objects),
            writable=True,
        ) as transport:
            for path, (mode, object_id, size) in objects.items():
                transport.write_request(object_id.encode("ascii") + b"\n")
                header = transport.stdout.readline(256)
                expected = f"{object_id} blob {size}\n".encode("ascii")
                if header != expected:
                    if not header and transport.wait() != 0:
                        raise LifecycleError("task-snapshot-git-failed", "baseline blob: Git command failed")
                    raise LifecycleError("task-snapshot-git-shape", "Git baseline blob size changed during snapshot")
                digest = hashlib.sha256()
                remaining = size
                while remaining:
                    data = transport.stdout.read(min(65_536, remaining))
                    if not data:
                        raise LifecycleError(
                            "task-snapshot-git-shape", "Git baseline blob size changed during snapshot"
                        )
                    digest.update(data)
                    remaining -= len(data)
                if transport.stdout.read(1) != b"\n":
                    raise LifecycleError("task-snapshot-git-shape", "Git baseline blob size changed during snapshot")
                entries[path] = {
                    "kind": "symlink" if mode == "120000" else "file",
                    "mode": mode,
                    "sha256": digest.hexdigest(),
                    "bytes": size,
                }
            transport.write_request(None)
            if transport.stdout.read_all():
                raise LifecycleError("task-snapshot-git-shape", "Git returned trailing baseline blob data")
            if transport.wait() != 0:
                raise LifecycleError("task-snapshot-git-failed", "baseline blob: Git command failed")
    except LifecycleError as exc:
        if exc.code.startswith("bounded-process-"):
            code = (
                "task-snapshot-byte-limit" if exc.code == "bounded-process-output-limit" else "task-snapshot-git-failed"
            )
            raise LifecycleError(code, "baseline blob: Git transport failed closed") from exc
        raise
    except OSError as exc:
        raise LifecycleError("task-snapshot-git-failed", "baseline blob: Git command failed") from exc
    return entries


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
        completed = run_bounded_command(
            argv,
            cwd=root,
            timeout_seconds=GIT_TIMEOUT_SECONDS,
            max_stdout_bytes=max_bytes,
        )
    except LifecycleError as exc:
        code = "task-snapshot-byte-limit" if exc.code == "bounded-process-output-limit" else "task-snapshot-git-failed"
        raise LifecycleError(code, f"{label}: Git transport failed closed", {"maxBytes": max_bytes}) from exc
    except OSError as exc:
        raise LifecycleError("task-snapshot-git-failed", f"{label}: Git command failed") from exc
    if completed.returncode != 0:
        raise LifecycleError(
            "task-snapshot-git-failed",
            f"{label}: Git command failed",
            {"exitCode": completed.returncode},
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

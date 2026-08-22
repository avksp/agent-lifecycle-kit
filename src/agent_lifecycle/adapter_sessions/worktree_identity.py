"""Bounded, stable Git worktree identity capture for planning launches."""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest

MAX_UNTRACKED_FILES = 100_000
MAX_UNTRACKED_BYTES = 4 * 1024 * 1024 * 1024
MAX_HASH_CHUNK_BYTES = 256 * 1024
MAX_CAPTURE_SECONDS = 120.0


def capture_git_worktree_identity(project_root: Path) -> dict[str, Any]:
    """Capture authoritative Git content with bounded streaming reads.

    The five Git commands remain ordered so the before/after launch snapshots
    retain their existing consistency semantics. Ordinary untracked files are
    hashed incrementally; symlinks hash only their link text and other special
    files fail closed.
    """

    root = project_root.resolve()
    deadline = time.monotonic() + MAX_CAPTURE_SECONDS
    head = _git_bytes(root, ["rev-parse", "HEAD"], deadline).decode("ascii", errors="strict").strip()
    staged = _git_bytes(root, ["diff", "--cached", "--binary", "--no-ext-diff"], deadline)
    unstaged = _git_bytes(root, ["diff", "--binary", "--no-ext-diff"], deadline)
    submodules = _git_bytes(root, ["submodule", "status", "--recursive"], deadline)
    untracked_raw = _git_bytes(root, ["ls-files", "--others", "--exclude-standard", "-z"], deadline)
    names = sorted(item for item in untracked_raw.split(b"\0") if item)
    if len(names) > MAX_UNTRACKED_FILES:
        raise LifecycleError(
            "planning-worktree-untracked-limit",
            "untracked file count exceeds the identity budget",
            {"count": len(names), "maxFiles": MAX_UNTRACKED_FILES},
        )
    untracked_rows: list[dict[str, Any]] = []
    total_bytes = 0
    for raw_name in names:
        _require_time(deadline)
        relative = os.fsdecode(raw_name)
        path = root / relative
        before = _lstat_or_race(path)
        path_digest = hashlib.sha256(raw_name).hexdigest()
        if path.is_symlink():
            payload = os.fsencode(path.readlink())
            digest = hashlib.sha256(payload).hexdigest()
            row_bytes = len(payload)
            kind = "symlink"
        elif _is_regular_file(before.st_mode):
            digest, row_bytes = _hash_regular_file(path, deadline)
            kind = "file"
        else:
            raise LifecycleError(
                "planning-worktree-special-file",
                "untracked identity capture rejects special files",
                {"kind": "non-regular"},
            )
        after = _lstat_or_race(path)
        if _stat_identity(before) != _stat_identity(after):
            raise LifecycleError(
                "planning-worktree-read-race",
                "untracked worktree entry changed during identity capture",
            )
        total_bytes += row_bytes
        if total_bytes > MAX_UNTRACKED_BYTES:
            raise LifecycleError(
                "planning-worktree-untracked-limit",
                "untracked byte count exceeds the identity budget",
                {"bytes": total_bytes, "maxBytes": MAX_UNTRACKED_BYTES},
            )
        untracked_rows.append(
            {
                "pathBytesSha256": path_digest,
                "kind": kind,
                "bytes": row_bytes,
                "sha256": digest,
            }
        )
    body = {
        "schemaVersion": "agent-planning-worktree-identity.v1",
        "head": head,
        "stagedDiffSha256": hashlib.sha256(staged).hexdigest(),
        "unstagedDiffSha256": hashlib.sha256(unstaged).hexdigest(),
        "submoduleStateSha256": hashlib.sha256(submodules).hexdigest(),
        "untrackedTreeSha256": canonical_digest({"entries": untracked_rows}),
        "untrackedCount": len(untracked_rows),
        "untrackedBytes": total_bytes,
        "ignoredLocalStateExcluded": True,
    }
    return {**body, "identityDigest": canonical_digest(body)}


def _hash_regular_file(path: Path, deadline: float) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            while True:
                _require_time(deadline)
                chunk = handle.read(MAX_HASH_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UNTRACKED_BYTES:
                    raise LifecycleError(
                        "planning-worktree-untracked-limit",
                        "untracked byte count exceeds the identity budget",
                        {"bytes": total, "maxBytes": MAX_UNTRACKED_BYTES},
                    )
                digest.update(chunk)
    except LifecycleError:
        raise
    except OSError as exc:
        raise LifecycleError(
            "planning-worktree-read-race",
            "failed to capture an untracked worktree entry",
            {"errorType": type(exc).__name__},
        ) from exc
    return digest.hexdigest(), total


def _git_bytes(root: Path, args: list[str], deadline: float) -> bytes:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise LifecycleError("planning-worktree-identity-timeout", "Git identity capture exceeded its deadline")
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=remaining,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LifecycleError(
            "planning-worktree-identity-failed",
            "Git identity capture failed closed",
            {"errorType": type(exc).__name__},
        ) from exc
    if result.returncode != 0:
        raise LifecycleError(
            "planning-worktree-identity-failed",
            "Git identity command failed closed",
            {"command": args[0], "exitCode": result.returncode},
        )
    return result.stdout


def _lstat_or_race(path: Path) -> os.stat_result:
    try:
        return path.lstat()
    except OSError as exc:
        raise LifecycleError(
            "planning-worktree-read-race",
            "failed to inspect an untracked worktree entry",
            {"errorType": type(exc).__name__},
        ) from exc


def _is_regular_file(mode: int) -> bool:
    return (mode & 0o170000) == 0o100000


def _stat_identity(stat_result: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        stat_result.st_dev,
        stat_result.st_ino,
        stat_result.st_mode,
        stat_result.st_size,
        stat_result.st_mtime_ns,
        stat_result.st_ctime_ns,
    )


def _require_time(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise LifecycleError("planning-worktree-identity-timeout", "Git identity capture exceeded its deadline")


__all__ = ["capture_git_worktree_identity"]

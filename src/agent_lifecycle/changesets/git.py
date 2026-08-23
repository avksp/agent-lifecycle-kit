"""Git-backed changed-file discovery."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.paths import normalize_git_revision, normalize_repo_path

MAX_GIT_OUTPUT_BYTES = 16 * 1024 * 1024
GIT_TIMEOUT_SECONDS = 30.0


def changed_files(cwd: Path, *, base: str | None = None) -> list[str]:
    paths: set[str] = set()
    if base is not None:
        revision = _resolve_revision(cwd, base, label="base")
        paths.update(
            _git_paths(
                cwd,
                [
                    "git",
                    "diff",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--name-only",
                    "-z",
                    "--end-of-options",
                    revision,
                    "--",
                ],
            )
        )
    else:
        paths.update(
            _git_paths(
                cwd,
                ["git", "diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", "--"],
            )
        )
        paths.update(
            _git_paths(
                cwd,
                ["git", "diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", "--cached", "--"],
            )
        )
    paths.update(_git_paths(cwd, ["git", "ls-files", "--others", "--exclude-standard", "-z"]))
    return sorted(normalize_repo_path(path) for path in paths if path)


def resolve_revision(cwd: Path, revision: str, *, label: str = "revision") -> str:
    value = normalize_git_revision(revision, label=label)
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--verify", "--end-of-options", f"{value}^{{commit}}"],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise LifecycleError("invalid-git-revision", f"{label}: revision cannot be resolved") from exc
    resolved = completed.stdout.strip().splitlines()
    if len(resolved) != 1 or not resolved[0]:
        raise LifecycleError("invalid-git-revision", f"{label}: revision cannot be resolved")
    return resolved[0]


def _resolve_revision(cwd: Path, revision: str, *, label: str = "revision") -> str:
    """Keep the established repository-input boundary marker."""

    return resolve_revision(cwd, revision, label=label)


def _git_paths(cwd: Path, argv: list[str]) -> list[str]:
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            check=True,
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise LifecycleError("git-command-failed", f"git command failed: {' '.join(argv)}") from exc
    if len(completed.stdout) > MAX_GIT_OUTPUT_BYTES:
        raise LifecycleError(
            "git-output-limit",
            "Git changed-file output exceeds the bounded snapshot limit",
            {"maxBytes": MAX_GIT_OUTPUT_BYTES},
        )
    paths = []
    for raw in completed.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            paths.append(raw.decode("utf-8", errors="strict"))
        except UnicodeDecodeError as exc:
            raise LifecycleError("git-path-encoding", "Git returned a non-UTF-8 repository path") from exc
    return paths


__all__ = ["changed_files", "resolve_revision"]

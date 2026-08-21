"""Git-backed changed-file discovery."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.paths import normalize_git_revision, normalize_repo_path


def changed_files(cwd: Path, *, base: str | None = None) -> list[str]:
    paths: set[str] = set()
    if base is not None:
        revision = _resolve_revision(cwd, base, label="base")
        paths.update(_git_lines(cwd, ["git", "diff", "--no-ext-diff", "--no-textconv", "--name-only", "--end-of-options", revision, "--"]))
    else:
        paths.update(_git_lines(cwd, ["git", "diff", "--no-ext-diff", "--no-textconv", "--name-only", "--"]))
        paths.update(_git_lines(cwd, ["git", "diff", "--no-ext-diff", "--no-textconv", "--name-only", "--cached", "--"]))
    paths.update(_git_lines(cwd, ["git", "ls-files", "--others", "--exclude-standard"]))
    return sorted(normalize_repo_path(path) for path in paths if path)


def _resolve_revision(cwd: Path, revision: str, *, label: str) -> str:
    value = normalize_git_revision(revision, label=label)
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--verify", "--end-of-options", f"{value}^{{commit}}"],
            cwd=cwd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LifecycleError("invalid-git-revision", f"{label}: revision cannot be resolved") from exc
    resolved = completed.stdout.strip().splitlines()
    if len(resolved) != 1 or not resolved[0]:
        raise LifecycleError("invalid-git-revision", f"{label}: revision cannot be resolved")
    return resolved[0]


def _git_lines(cwd: Path, argv: list[str]) -> list[str]:
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LifecycleError("git-command-failed", f"git command failed: {' '.join(argv)}") from exc
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]

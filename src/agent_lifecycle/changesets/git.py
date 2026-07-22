"""Git-backed changed-file discovery."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.paths import normalize_repo_path


def changed_files(cwd: Path, *, base: str | None = None) -> list[str]:
    paths: set[str] = set()
    if base:
        paths.update(_git_lines(cwd, ["git", "diff", "--name-only", base, "--"]))
    else:
        paths.update(_git_lines(cwd, ["git", "diff", "--name-only", "--"]))
        paths.update(_git_lines(cwd, ["git", "diff", "--name-only", "--cached", "--"]))
    paths.update(_git_lines(cwd, ["git", "ls-files", "--others", "--exclude-standard"]))
    return sorted(normalize_repo_path(path) for path in paths if path)


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

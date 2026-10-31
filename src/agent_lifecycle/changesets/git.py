"""Git-backed changed-file discovery."""

from __future__ import annotations

from pathlib import Path

from agent_lifecycle.changesets.git_io import run_bounded_command
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
                    "--no-renames",
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
                ["git", "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "-z", "--"],
            )
        )
        paths.update(
            _git_paths(
                cwd,
                [
                    "git",
                    "diff",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--no-renames",
                    "--name-only",
                    "-z",
                    "--cached",
                    "--",
                ],
            )
        )
    paths.update(_git_paths(cwd, ["git", "ls-files", "--others", "--exclude-standard", "-z"]))
    return sorted(normalize_repo_path(path) for path in paths if path)


def resolve_revision(cwd: Path, revision: str, *, label: str = "revision") -> str:
    value = normalize_git_revision(revision, label=label)
    try:
        # Retry only the observed Windows ownership refusal, once, for this
        # read-only lookup through the same bounded owner.
        for attempt in range(2):
            try:
                completed = run_bounded_command(
                    ["git", "rev-parse", "--verify", "--end-of-options", f"{value}^{{commit}}"],
                    cwd=cwd,
                    timeout_seconds=GIT_TIMEOUT_SECONDS,
                    max_stdout_bytes=128,
                )
                break
            except LifecycleError as exc:
                if (
                    attempt != 0
                    or exc.code != "bounded-process-group-unavailable"
                    or exc.message != "Cannot own the Windows child group"
                ):
                    raise
    except (OSError, LifecycleError) as exc:
        raise LifecycleError("invalid-git-revision", f"{label}: revision cannot be resolved") from exc
    resolved = completed.stdout.strip().splitlines()
    if completed.returncode or len(resolved) != 1 or len(resolved[0]) not in (40, 64):
        raise LifecycleError("invalid-git-revision", f"{label}: revision cannot be resolved")
    try:
        value = resolved[0].decode("ascii")
    except UnicodeDecodeError as exc:
        raise LifecycleError("invalid-git-revision", f"{label}: revision cannot be resolved") from exc
    if any(char not in "0123456789abcdef" for char in value):
        raise LifecycleError("invalid-git-revision", f"{label}: revision cannot be resolved")
    return value


def _resolve_revision(cwd: Path, revision: str, *, label: str = "revision") -> str:
    """Keep the established repository-input boundary marker."""

    return resolve_revision(cwd, revision, label=label)


def _git_paths(cwd: Path, argv: list[str]) -> list[str]:
    try:
        completed = run_bounded_command(
            argv,
            cwd=cwd,
            timeout_seconds=GIT_TIMEOUT_SECONDS,
            max_stdout_bytes=MAX_GIT_OUTPUT_BYTES,
        )
    except LifecycleError as exc:
        code = "git-output-limit" if exc.code == "bounded-process-output-limit" else "git-command-failed"
        raise LifecycleError(code, "Git changed-file command failed closed") from exc
    except OSError as exc:
        raise LifecycleError("git-command-failed", "Git changed-file command could not start") from exc
    if completed.returncode:
        raise LifecycleError("git-command-failed", "Git changed-file command failed")
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

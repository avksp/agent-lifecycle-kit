"""Repository-relative path normalization."""

from __future__ import annotations

from pathlib import PurePosixPath

from agent_lifecycle.contracts.errors import LifecycleError

MAX_REPO_PATH_BYTES = 4096


def normalize_repo_path(path: str, *, label: str = "path") -> str:
    if not isinstance(path, str) or not path:
        raise LifecycleError("invalid-repo-path", f"{label}: path is required")
    if "\x00" in path or "\\" in path or path.startswith("/") or "://" in path:
        raise LifecycleError("invalid-repo-path", f"{label}: path must be repository-relative POSIX")
    if len(path.encode("utf-8")) > MAX_REPO_PATH_BYTES:
        raise LifecycleError("invalid-repo-path", f"{label}: path exceeds {MAX_REPO_PATH_BYTES} bytes")
    pure = PurePosixPath(path)
    parts = pure.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise LifecycleError("invalid-repo-path", f"{label}: path contains traversal")
    if any(part.endswith(".") or part.endswith(" ") for part in parts):
        raise LifecycleError("invalid-repo-path", f"{label}: path has ambiguous suffix")
    return pure.as_posix()

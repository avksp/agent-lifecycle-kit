"""Repository-relative path normalization."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from pathlib import PurePosixPath

from agent_lifecycle.contracts.errors import LifecycleError

MAX_REPO_PATH_BYTES = 4096
MAX_GIT_REVISION_BYTES = 4096


def normalize_repo_path(path: str, *, label: str = "path") -> str:
    if not isinstance(path, str) or not path:
        raise LifecycleError("invalid-repo-path", f"{label}: path is required")
    if "\x00" in path or "\\" in path or path.startswith("/") or "://" in path:
        raise LifecycleError("invalid-repo-path", f"{label}: path must be repository-relative POSIX")
    if len(path.encode("utf-8")) > MAX_REPO_PATH_BYTES:
        raise LifecycleError("invalid-repo-path", f"{label}: path exceeds {MAX_REPO_PATH_BYTES} bytes")
    raw_parts = path.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise LifecycleError("invalid-repo-path", f"{label}: path contains traversal or alias segments")
    pure = PurePosixPath(path)
    parts = pure.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise LifecycleError("invalid-repo-path", f"{label}: path contains traversal")
    if any(part.endswith(".") or part.endswith(" ") for part in parts):
        raise LifecycleError("invalid-repo-path", f"{label}: path has ambiguous suffix")
    return pure.as_posix()


def is_under_repo_path(path: str, root: str) -> bool:
    """Return whether a normalized repository path is equal to or below root."""

    return path == root or path.startswith(root.rstrip("/") + "/")


def normalize_git_revision(revision: str, *, label: str = "revision") -> str:
    """Validate untrusted Git revision text before it reaches argv."""

    if not isinstance(revision, str) or not revision:
        raise LifecycleError("invalid-git-revision", f"{label}: revision is required")
    if "\x00" in revision or revision.startswith("-"):
        raise LifecycleError("invalid-git-revision", f"{label}: option-shaped revisions are not allowed")
    if len(revision.encode("utf-8")) > MAX_GIT_REVISION_BYTES:
        raise LifecycleError("invalid-git-revision", f"{label}: revision exceeds {MAX_GIT_REVISION_BYTES} bytes")
    return revision


def resolve_repository_file(project_root: Path, repo_path: str, *, label: str = "repository file") -> Path:
    """Resolve one contained regular file while rejecting every symlink component."""

    normalized = normalize_repo_path(repo_path, label=label)
    root = project_root.resolve()
    if not root.is_dir():
        raise LifecycleError("repository-root-invalid", f"{label}: repository root is not a regular directory")
    candidate = root.joinpath(*PurePosixPath(normalized).parts)
    _reject_symlink_components(root, candidate, label=label)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise LifecycleError("repository-file-missing", f"{label}: file does not exist") from exc
    if not _is_relative_to(resolved, root):
        raise LifecycleError("repository-file-outside-root", f"{label}: resolved file escapes repository root")
    if not resolved.is_file():
        raise LifecycleError("repository-file-not-regular", f"{label}: file must be regular and non-symlinked")
    return resolved


def read_stable_repository_file(
    project_root: Path,
    repo_path: str,
    *,
    max_bytes: int,
    label: str = "repository file",
) -> bytes:
    """Read a contained regular file with size, identity and race checks."""

    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise LifecycleError("invalid-repository-input-cap", f"{label}: max_bytes must be positive")
    normalized = normalize_repo_path(repo_path, label=label)
    root = project_root.resolve()
    candidate = root.joinpath(*PurePosixPath(normalized).parts)
    resolved = resolve_repository_file(root, normalized, label=label)
    before_path = _regular_stat(candidate, label=label)
    fd: int | None = None
    try:
        fd = _open_repository_file(root, normalized, candidate)
        with os.fdopen(fd, "rb", closefd=True) as handle:
            fd = None
            before_fd = os.fstat(handle.fileno())
            _require_same_identity(before_path, before_fd, label=label)
            if before_fd.st_size > max_bytes:
                raise LifecycleError("repository-input-too-large", f"{label}: input exceeds {max_bytes} bytes")
            data = handle.read(max_bytes + 1)
            after_fd = os.fstat(handle.fileno())
            _require_same_identity(before_fd, after_fd, label=label)
    except LifecycleError:
        raise
    except OSError as exc:
        raise LifecycleError("repository-input-read-failed", f"{label}: stable read failed") from exc
    finally:
        if fd is not None:
            os.close(fd)
    if len(data) > max_bytes:
        raise LifecycleError("repository-input-too-large", f"{label}: input exceeds {max_bytes} bytes")
    after_path = _regular_stat(candidate, label=label)
    try:
        resolved_after = candidate.resolve(strict=True)
    except OSError as exc:
        raise LifecycleError("repository-input-changed-during-read", f"{label}: path changed during read") from exc
    if resolved_after != resolved or not _is_relative_to(resolved_after, root):
        raise LifecycleError("repository-input-changed-during-read", f"{label}: path changed during read")
    _require_same_identity(before_path, after_path, label=label)
    return data


def _reject_symlink_components(root: Path, candidate: Path, *, label: str) -> None:
    current = candidate
    while current != root:
        if current.is_symlink():
            raise LifecycleError("repository-input-symlink", f"{label}: symlinked inputs are not allowed")
        if current.parent == current:
            break
        current = current.parent


def _open_repository_file(root: Path, normalized: str, candidate: Path) -> int:
    """Open a repository file without following intermediate POSIX symlinks."""

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if os.name != "nt" and hasattr(os, "O_DIRECTORY") and os.open in os.supports_dir_fd:
        current_fd: int | None = None
        try:
            current_fd = os.open(os.fspath(root), os.O_RDONLY | os.O_DIRECTORY | nofollow)
            parts = PurePosixPath(normalized).parts
            for index, part in enumerate(parts):
                flags = os.O_RDONLY | nofollow
                if index < len(parts) - 1:
                    flags |= os.O_DIRECTORY
                next_fd = os.open(part, flags, dir_fd=current_fd)
                os.close(current_fd)
                current_fd = next_fd
            return current_fd
        except OSError:
            if current_fd is not None:
                os.close(current_fd)
            raise
    return os.open(os.fspath(candidate), os.O_RDONLY | nofollow)


def _regular_stat(path: Path, *, label: str) -> os.stat_result:
    try:
        result = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise LifecycleError("repository-file-missing", f"{label}: file does not exist") from exc
    if not stat.S_ISREG(result.st_mode):
        raise LifecycleError("repository-file-not-regular", f"{label}: file must be regular and non-symlinked")
    return result


def _require_same_identity(before: os.stat_result, after: os.stat_result, *, label: str) -> None:
    identity = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, field) != getattr(after, field) for field in identity):
        raise LifecycleError("repository-input-changed-during-read", f"{label}: file changed during read")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True

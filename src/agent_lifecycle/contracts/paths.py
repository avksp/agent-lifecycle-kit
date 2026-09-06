"""Repository-relative path normalization."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from agent_lifecycle.contracts.authority_io import (
    MAX_AUTHORITY_PATH_BYTES,
    normalize_authority_path,
    read_authority_bytes,
)
from agent_lifecycle.contracts.errors import LifecycleError

MAX_REPO_PATH_BYTES = MAX_AUTHORITY_PATH_BYTES
MAX_GIT_REVISION_BYTES = 4096


def normalize_repo_path(path: str, *, label: str = "path") -> str:
    return normalize_authority_path(path, label=label)


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
    root = project_root.absolute()
    resolve_repository_file(root, normalized, label=label)
    try:
        return read_authority_bytes(root / normalized, root=root, max_bytes=max_bytes)
    except LifecycleError as exc:
        code = {
            "authority-input-too-large": "repository-input-too-large",
            "authority-input-changed": "repository-input-changed-during-read",
            "authority-input-symlink": "repository-input-symlink",
            "authority-input-not-regular": "repository-file-not-regular",
        }.get(exc.code, "repository-input-read-failed")
        raise LifecycleError(code, f"{label}: stable read failed") from None
    except OSError:
        raise LifecycleError("repository-input-read-failed", f"{label}: stable read failed") from None


def _reject_symlink_components(root: Path, candidate: Path, *, label: str) -> None:
    current = candidate
    while current != root:
        if current.is_symlink():
            raise LifecycleError("repository-input-symlink", f"{label}: symlinked inputs are not allowed")
        if current.parent == current:
            break
        current = current.parent


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True

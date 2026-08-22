"""Strict repository-relative path primitives for plan authority decisions."""

from __future__ import annotations

from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.paths import is_under_repo_path, normalize_repo_path

_GLOB_METACHARACTERS = frozenset("*?[]")


def normalize_authority_path(path: str, *, label: str = "authority path") -> str:
    """Normalize one literal repository prefix used by plan authority."""

    if not isinstance(path, str) or any(character in path for character in _GLOB_METACHARACTERS):
        raise LifecycleError(
            "invalid-authority-path",
            f"{label}: glob-like paths are not supported; use a literal repository prefix",
        )
    if ":" in path:
        raise LifecycleError(
            "invalid-authority-path",
            f"{label}: drive and URI-like paths are not repository-relative",
        )
    return normalize_repo_path(path, label=label)


def is_under_authority_path(path: str, root: str) -> bool:
    """Return whether a normalized path is equal to or below a literal root."""

    return is_under_repo_path(path, root)


def authority_paths_overlap(left: str, right: str) -> bool:
    """Return whether two normalized literal prefixes intersect."""

    return is_under_authority_path(left, right) or is_under_authority_path(right, left)


__all__ = [
    "authority_paths_overlap",
    "is_under_authority_path",
    "normalize_authority_path",
]

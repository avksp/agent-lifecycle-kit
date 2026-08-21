"""Resolve immutable built-in profiles from the installed package."""

from __future__ import annotations

import importlib.resources
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError

_DATA_PACKAGE = "agent_lifecycle.data"
_PROFILE_ROOT = Path("profiles")


def builtin_profile_path(relative_path: str) -> Path:
    """Return a filesystem path for one installed built-in profile.

    Wheels install package data on the filesystem. Refusing non-filesystem
    resources keeps the existing Path-based readers deterministic instead of
    returning a path whose lifetime is shorter than the caller's operation.
    """

    resource = _builtin_resource(relative_path)
    if not isinstance(resource, Path):
        raise LifecycleError(
            "built-in-resource-not-filesystem",
            "built-in profile is not available as a filesystem resource",
            {"resource": _resource_name(relative_path)},
        )
    return resource


def builtin_profile_bytes(relative_path: str) -> bytes:
    """Read one installed built-in profile without consulting the cwd."""

    return _builtin_resource(relative_path).read_bytes()


def _builtin_resource(relative_path: str):
    normalized = _normalize_profile_path(relative_path)
    resource = importlib.resources.files(_DATA_PACKAGE).joinpath(_PROFILE_ROOT.as_posix(), *normalized.parts)
    if not resource.is_file():
        raise LifecycleError(
            "built-in-resource-missing",
            "built-in profile is not installed",
            {"resource": _resource_name(relative_path)},
        )
    return resource


def _normalize_profile_path(relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise LifecycleError("built-in-resource-invalid", "built-in profile path is invalid")
    if candidate.suffix != ".json":
        raise LifecycleError("built-in-resource-invalid", "built-in profile must be a JSON file")
    return candidate


def _resource_name(relative_path: str) -> str:
    return (_PROFILE_ROOT / relative_path).as_posix()

"""Strict repository-relative path primitives for plan authority decisions."""

from __future__ import annotations

import os
import stat
import unicodedata
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts.authority_io import _parent, authority_location
from agent_lifecycle.contracts.authority_text import require_authority_text
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.paths import is_under_repo_path, normalize_repo_path

_GLOB_METACHARACTERS = frozenset("*?[]")


def normalize_authority_path(path: str, *, label: str = "authority path") -> str:
    """Normalize one literal repository prefix used by plan authority."""

    require_authority_text(path)
    if isinstance(path, str) and unicodedata.normalize("NFC", path) != path:
        raise LifecycleError("noncanonical-authority-path", "declared authority path must use NFC spelling")
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


def is_under_authority_path(path: str, root: str, *, operation_root: Path | None = None) -> bool:
    """Compare names without rewriting I/O paths or assuming volume-wide case rules.

    Without an operation root this is an offline NFC comparison, not filesystem
    evidence. Runtime comparisons inspect the actual parent of a differing name.
    """

    left = unicodedata.normalize("NFC", path)
    right = unicodedata.normalize("NFC", root)
    if operation_root is None:
        return is_under_repo_path(left, right)
    normalize_authority_path(left)
    normalize_authority_path(right)
    observed_parts = path.split("/")
    declared_parts = root.split("/")
    if len(observed_parts) < len(declared_parts):
        return False
    anchor, _ = authority_location(operation_root / "comparison-anchor", root=operation_root)
    for index, (observed, declared) in enumerate(zip(observed_parts, declared_parts, strict=False)):
        if unicodedata.normalize("NFC", observed) == unicodedata.normalize("NFC", declared):
            continue
        parent = "/".join(observed_parts[:index])
        if not _same_filesystem_name(anchor, parent, observed, declared):
            return False
    return True


def _same_filesystem_name(root: Path, parent_name: str, left: str, right: str) -> bool:
    """Resolve this pair under the existing WS01 held-parent backend; never probe by writing."""

    relative = f"{parent_name}/{left}" if parent_name else left
    fold_equal = unicodedata.normalize("NFC", left).casefold() == unicodedata.normalize("NFC", right).casefold()
    try:
        with _parent(root, relative) as (parent, _):
            directory: int | Path
            if parent.fd is not None and os.scandir in os.supports_fd:
                directory = parent.fd
            elif os.name == "nt" and parent.fd is None and parent.handle is not None:
                # _parent holds verified directory/ancestor handles with only
                # share-read access, excluding rename and in-place reparse writers.
                directory = parent.path
            else:
                raise LifecycleError("filesystem-policy-unavailable", "held-directory comparison is unavailable")
            identities: list[tuple[int, int, int] | None] = []
            for name in (left, right):
                try:
                    info = parent.stat_child(name)
                except FileNotFoundError:
                    identities.append(None)
                    continue
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise LifecycleError("authority-input-symlink", "authority comparison cannot follow a link")
                identities.append((info.st_dev, info.st_ino, info.st_mode))
            if identities == [None, None]:
                if fold_equal:
                    raise LifecycleError("filesystem-policy-unavailable", "missing names have unknown alias semantics")
                return False
            if identities[0] != identities[1]:
                return False
            # Equal inode numbers alone cannot distinguish aliases from two hard
            # links on a sensitive filesystem. Inspect actual directory entries.
            literal_names = set()
            with os.scandir(directory) as entries:
                for count, entry in enumerate(entries, 1):
                    if count > 10000:
                        raise LifecycleError("filesystem-policy-unavailable", "directory comparison exceeds its bound")
                    if entry.name in (left, right):
                        literal_names.add(entry.name)
            if len(literal_names) != 1:
                raise LifecycleError("ambiguous-authority-path", "multiple names share an authority identity")
            for name, expected in zip((left, right), identities, strict=True):
                info = parent.stat_child(name)
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise LifecycleError("authority-input-symlink", "authority comparison cannot follow a link")
                if (info.st_dev, info.st_ino, info.st_mode) != expected:
                    raise LifecycleError("ambiguous-authority-path", "authority name changed during comparison")
            return True
    except FileNotFoundError:
        if not fold_equal:
            return False
        raise LifecycleError("filesystem-policy-unavailable", "authority parent or alias disappeared") from None
    except OSError:
        raise LifecycleError("filesystem-policy-unavailable", "authority parent cannot be inspected") from None


def observed_authority_paths(paths: list[str], *, operation_root: Path | None = None) -> list[str]:
    """Validate the entire observed set before scoping; retain each original name."""

    by_key: dict[str, str] = {}
    case_groups: dict[str, list[str]] = {}
    for path in paths:
        if not isinstance(path, str):
            raise LifecycleError("invalid-authority-path", "observed path must be a string")
        require_authority_text(path)
        key = normalize_authority_path(unicodedata.normalize("NFC", path))
        previous = by_key.get(key)
        if previous is not None and previous != path:
            raise LifecycleError("ambiguous-authority-path", "observed paths have colliding comparison keys")
        if previous is not None:
            continue
        by_key[key] = path
        group = case_groups.setdefault(key.casefold(), [])
        if operation_root is not None:
            for other in group:
                if is_under_authority_path(path, other, operation_root=operation_root):
                    raise LifecycleError("ambiguous-authority-path", "observed names alias the same authority path")
        group.append(path)
    return sorted(set(paths))


def authority_paths_overlap(left: str, right: str) -> bool:
    """Return whether two normalized literal prefixes intersect."""

    return is_under_authority_path(left, right) or is_under_authority_path(right, left)


def require_manifest_authority_paths(manifest: dict[str, Any], *, operation_root: Path | None = None) -> None:
    """Reject contradictory declarations before any observed path is classified.

    Offline validation checks literal NFC contradictions. Filesystem alias
    collisions additionally require the caller's explicit operation root.
    Nested literal restrictions retain their existing classification precedence.
    """

    workstreams = manifest.get("workstreams")
    containers = [manifest, *(workstreams if isinstance(workstreams, list) else [])]
    declarations: list[tuple[str, str, str]] = []
    for index, container in enumerate(containers):
        if not isinstance(container, dict):
            continue
        owner = str(container.get("id", f"container-{index}"))
        for field in ("writes", "readOnly", "forbiddenWrites"):
            values = container.get(field)
            for value in values if isinstance(values, list) else []:
                if isinstance(value, str):
                    declarations.append(
                        (field, owner if field == "writes" else "policy", normalize_authority_path(value))
                    )
        lead_owned = container.get("leadOwned")
        for item in lead_owned if isinstance(lead_owned, list) else []:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                declarations.append(("leadOwned", "controller", normalize_authority_path(item["path"])))
    declarations = sorted(set(declarations))
    restrictions = {"readOnly", "forbiddenWrites"}
    for index, (left_kind, left_owner, left) in enumerate(declarations):
        for right_kind, right_owner, right in declarations[index + 1 :]:
            if left_kind in restrictions and right_kind in restrictions:
                continue
            if (left_kind, left_owner) == (right_kind, right_owner):
                continue
            if not authority_paths_overlap(left.casefold(), right.casefold()):
                continue
            literal_overlap = authority_paths_overlap(left, right)
            competing_writers = left_kind == right_kind == "writes" and left_owner != right_owner
            if literal_overlap:
                if competing_writers or left == right:
                    raise LifecycleError("ambiguous-authority-path", "ownership declarations have conflicting grants")
                # A narrower literal restriction is not a second grant.
                continue
            if operation_root is None:
                continue
            if is_under_authority_path(left, right, operation_root=operation_root) or is_under_authority_path(
                right, left, operation_root=operation_root
            ):
                raise LifecycleError("ambiguous-authority-path", "filesystem aliases have conflicting ownership")


def _existing_path_check(root: Path, name: str) -> None:
    """Inspect existing ancestors without creating anything or following aliases."""

    candidate = root
    for part in name.split("/"):
        candidate /= part
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            return
        except OSError:
            raise LifecycleError("filesystem-policy-unavailable", "cannot inspect authority destination") from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise LifecycleError("authority-input-symlink", "authority destination must not traverse a link")


def compiler_output_paths(
    manifest: dict[str, Any], *, output_dir: Path | None = None, small: bool = False
) -> list[str]:
    """Enumerate every compiler write before the first directory or file creation."""

    package = manifest.get("package")
    if not isinstance(package, dict) or not isinstance(package.get("artifactRoot"), str):
        raise LifecycleError("invalid-plan-manifest", "package.artifactRoot is required")
    artifact_root = normalize_authority_path(package["artifactRoot"])
    directory = output_dir or Path(artifact_root) / "workflow" / ("small-model-packets" if small else "task-packets")
    suffix = ".small-model-packet.json" if small else ".task-packet.json"
    paths = []
    for task in manifest.get("workstreams", []):
        if not isinstance(task, dict):
            continue
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id or "/" in task_id or "\\" in task_id:
            raise LifecycleError("invalid-authority-path", "packet task ID must be a single path component")
        normalize_authority_path(task_id)
        paths.append((directory / f"{task_id}{suffix}").as_posix())
    paths.append((directory / "index.json").as_posix())
    return paths


def require_output_footprint(
    manifest: dict[str, Any],
    paths: list[str],
    *,
    repository_root: Path | None = None,
    manifest_path: Path | None = None,
) -> None:
    """Reject writes into frozen authority; physical checks are read-only preflight.

    Writers must still use root-bound guarded I/O: this check is not a lease on
    directory identities and never justifies reopening a checked pathname.
    """

    package = manifest.get("package", {})
    plan_root = package.get("planArtifactRoot")
    if not isinstance(plan_root, str):
        return
    plan_root = normalize_authority_path(plan_root)
    protected = [plan_root, f"{plan_root}/plan.lock.json"]
    protected.extend(normalize_authority_path(name) for name in manifest.get("planFiles", []) if isinstance(name, str))
    if manifest_path is not None and repository_root is not None:
        name = repository_authority_name(manifest_path, repository_root)
        protected.append(name)
    normalized = []
    for raw in paths:
        if repository_root is not None:
            raw = repository_authority_name(repository_root / raw, repository_root)
        normalized.append(normalize_authority_path(raw))
    if repository_root is None:
        # Offline checks cannot attest runtime filesystem semantics.
        keys = [path.casefold() for path in normalized]
        if len(set(keys)) != len(keys):
            raise LifecycleError("ambiguous-authority-path", "compiler outputs have colliding comparison keys")
    else:
        observed_authority_paths(normalized, operation_root=repository_root)
    for path in normalized:
        for authority in protected:
            if repository_root is None:
                overlap = authority_paths_overlap(path.casefold(), authority.casefold())
            else:
                overlap = is_under_authority_path(
                    path, authority, operation_root=repository_root
                ) or is_under_authority_path(authority, path, operation_root=repository_root)
            if overlap:
                raise LifecycleError("plan-output-conflict", "compiler output overlaps protected plan authority")
        if repository_root is not None:
            _existing_path_check(repository_root, path)


def repository_authority_name(path: Path, repository_root: Path) -> str:
    """Normalize only backend-owned runtime anchors, then enforce the explicit root."""

    bound_root, _ = authority_location(repository_root / "compiler-root-anchor", root=repository_root)
    anchor, relative = authority_location(path)
    _, name = authority_location(anchor / relative, root=bound_root)
    return name


def require_declared_output_footprint(manifest: dict[str, Any], *, repository_root: Path | None = None) -> None:
    """Check both standard compiler layouts when a manifest declares their roots."""

    require_manifest_authority_paths(manifest, operation_root=repository_root)
    package = manifest.get("package")
    if not isinstance(package, dict) or not all(
        isinstance(package.get(key), str) for key in ("artifactRoot", "planArtifactRoot")
    ):
        return
    for small in (False, True):
        require_output_footprint(
            manifest, compiler_output_paths(manifest, small=small), repository_root=repository_root
        )


__all__ = [
    "authority_paths_overlap",
    "is_under_authority_path",
    "normalize_authority_path",
]

"""Changed-file to frozen write-set ownership report."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, read_json_object
from agent_lifecycle.contracts.ownership_paths import (
    is_under_authority_path,
    normalize_authority_path,
    observed_authority_paths,
    require_manifest_authority_paths,
)
from agent_lifecycle.contracts.paths import normalize_repo_path


def build_ownership_report(
    manifest_path: Path,
    paths: list[str],
    *,
    base: str | None = None,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    manifest = read_json_object(manifest_path, label="plan manifest")
    return build_ownership_report_from_manifest(
        manifest,
        paths,
        manifest_path=manifest_path,
        base=base,
        repository_root=repository_root if repository_root is not None else Path.cwd(),
    )


def build_ownership_report_from_manifest(
    manifest: dict[str, Any],
    paths: list[str],
    *,
    manifest_path: Path | None = None,
    base: str | None = None,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Classify changed paths against an already loaded frozen manifest."""

    require_manifest_authority_paths(manifest, operation_root=repository_root)
    classifiers = _classifiers(manifest, manifest_path, repository_root=repository_root)
    entries = [
        _classify_path(path, classifiers, repository_root=repository_root)
        for path in observed_authority_paths(paths, operation_root=repository_root)
    ]
    categories = Counter(entry["category"] for entry in entries)
    owners = Counter(owner for entry in entries for owner in entry.get("owners", []))
    return {
        "schemaVersion": "agent-ownership-report.v1",
        "packageId": manifest.get("package", {}).get("id"),
        "planRevision": manifest.get("planRevision"),
        "planStatus": manifest.get("status"),
        "base": base,
        "summary": {
            "total": len(entries),
            "byCategory": dict(sorted(categories.items())),
            "byOwner": dict(sorted(owners.items())),
        },
        "entries": entries,
    }


def report_has_category(report: dict[str, Any], categories: set[str]) -> bool:
    return any(entry.get("category") in categories for entry in report.get("entries", []))


def declared_ownership_paths(manifest: dict[str, Any]) -> list[str]:
    """Return literal workstream ownership paths for read-only projections."""

    classifiers = _classifiers(manifest, None)
    paths = {path for roots in classifiers["workstreams"].values() for path in roots}
    return sorted(paths)


def _classifiers(
    manifest: dict[str, Any], manifest_path: Path | None, *, repository_root: Path | None = None
) -> dict[str, Any]:
    package_value = manifest.get("package")
    package = package_value if isinstance(package_value, dict) else {}
    plan_root = package.get("planArtifactRoot")
    workstreams = _list_value(manifest.get("workstreams"))
    manifest_lead_owned = _list_value(manifest.get("leadOwned"))
    manifest_read_only = _list_value(manifest.get("readOnly"))
    manifest_forbidden = _list_value(manifest.get("forbiddenWrites"))
    workstream_paths = {
        "readOnly": [
            path
            for workstream in workstreams
            if isinstance(workstream, dict)
            for path in _list_value(workstream.get("readOnly"))
            if isinstance(path, str)
        ],
        "forbiddenWrites": [
            path
            for workstream in workstreams
            if isinstance(workstream, dict)
            for path in _list_value(workstream.get("forbiddenWrites"))
            if isinstance(path, str)
        ],
        "leadOwned": [
            item["path"]
            for workstream in workstreams
            if isinstance(workstream, dict)
            for item in _list_value(workstream.get("leadOwned"))
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        ],
    }
    return {
        "manifestPath": _repo_relative(manifest_path, repository_root=repository_root),
        "planArtifactRoot": normalize_authority_path(plan_root, label="planArtifactRoot")
        if isinstance(plan_root, str)
        else None,
        "leadOwned": [
            normalize_authority_path(item["path"], label="leadOwned path")
            for item in manifest_lead_owned
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        ]
        + [normalize_authority_path(path, label="workstream leadOwned path") for path in workstream_paths["leadOwned"]],
        "readOnly": [
            normalize_authority_path(path, label="readOnly path")
            for path in manifest_read_only
            if isinstance(path, str)
        ]
        + [normalize_authority_path(path, label="workstream readOnly path") for path in workstream_paths["readOnly"]],
        "forbiddenWrites": [
            normalize_authority_path(path, label="forbiddenWrites path")
            for path in manifest_forbidden
            if isinstance(path, str)
        ]
        + [
            normalize_authority_path(path, label="workstream forbiddenWrites path")
            for path in workstream_paths["forbiddenWrites"]
        ],
        "workstreams": {
            workstream["id"]: [
                normalize_authority_path(path, label="workstream write path")
                for path in _list_value(workstream.get("writes"))
                if isinstance(path, str)
            ]
            for workstream in workstreams
            if isinstance(workstream, dict) and isinstance(workstream.get("id"), str)
        },
    }


def _classify_path(path: str, classifiers: dict[str, Any], *, repository_root: Path | None = None) -> dict[str, Any]:
    normalized = normalize_repo_path(path)
    manifest_path = classifiers["manifestPath"]
    if (
        isinstance(manifest_path, str)
        and normalized.count("/") == manifest_path.count("/")
        and is_under_authority_path(normalized, manifest_path, operation_root=repository_root)
    ):
        return _entry(normalized, "plan-authority", ["controller"])
    plan_root = classifiers["planArtifactRoot"]
    if isinstance(plan_root, str) and is_under_authority_path(normalized, plan_root, operation_root=repository_root):
        return _entry(normalized, "plan-authority", ["controller"])
    lead = [
        root
        for root in classifiers["leadOwned"]
        if is_under_authority_path(normalized, root, operation_root=repository_root)
    ]
    if lead:
        return _entry(normalized, "lead-owned", ["controller"], matched=lead)
    forbidden = [
        root
        for root in classifiers["forbiddenWrites"]
        if is_under_authority_path(normalized, root, operation_root=repository_root)
    ]
    if forbidden:
        return _entry(normalized, "forbidden", [], matched=forbidden)
    read_only = [
        root
        for root in classifiers["readOnly"]
        if is_under_authority_path(normalized, root, operation_root=repository_root)
    ]
    if read_only:
        return _entry(normalized, "read-only", [], matched=read_only)
    owners = []
    for owner, roots in classifiers["workstreams"].items():
        for root in roots:
            if not is_under_authority_path(normalized, root, operation_root=repository_root):
                continue
            if repository_root is not None and not is_under_authority_path(normalized, root):
                raise LifecycleError("ambiguous-authority-path", "filesystem alias would broaden a write grant")
            if owner not in owners:
                owners.append(owner)
    if owners:
        return _entry(normalized, "workstream-owned", owners)
    return _entry(normalized, "unowned", [])


def _entry(
    path: str,
    category: str,
    owners: list[str],
    *,
    matched: list[str] | None = None,
) -> dict[str, Any]:
    value = {"path": path, "category": category, "owners": owners}
    if matched:
        value["matched"] = matched
    return value


def _repo_relative(path: Path | None, *, repository_root: Path | None = None) -> str | None:
    if path is None:
        return None
    try:
        root = repository_root if repository_root is not None else Path.cwd()
        return normalize_repo_path(path.absolute().relative_to(root.absolute()).as_posix())
    except ValueError:
        return None


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []

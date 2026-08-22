"""Changed-file to frozen write-set ownership report."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import read_json_object
from agent_lifecycle.contracts.ownership_paths import is_under_authority_path, normalize_authority_path
from agent_lifecycle.contracts.paths import normalize_repo_path


def build_ownership_report(
    manifest_path: Path,
    paths: list[str],
    *,
    base: str | None = None,
) -> dict[str, Any]:
    manifest = read_json_object(manifest_path, label="plan manifest")
    return build_ownership_report_from_manifest(manifest, paths, manifest_path=manifest_path, base=base)


def build_ownership_report_from_manifest(
    manifest: dict[str, Any],
    paths: list[str],
    *,
    manifest_path: Path | None = None,
    base: str | None = None,
) -> dict[str, Any]:
    """Classify changed paths against an already loaded frozen manifest."""

    classifiers = _classifiers(manifest, manifest_path)
    entries = [_classify_path(path, classifiers) for path in sorted(set(paths))]
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


def _classifiers(manifest: dict[str, Any], manifest_path: Path | None) -> dict[str, Any]:
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
        "manifestPath": _repo_relative(manifest_path),
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


def _classify_path(path: str, classifiers: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_repo_path(path)
    manifest_path = classifiers["manifestPath"]
    if isinstance(manifest_path, str) and normalized == manifest_path:
        return _entry(normalized, "plan-authority", ["controller"])
    plan_root = classifiers["planArtifactRoot"]
    if isinstance(plan_root, str) and is_under_authority_path(normalized, plan_root):
        return _entry(normalized, "plan-authority", ["controller"])
    lead = [root for root in classifiers["leadOwned"] if is_under_authority_path(normalized, root)]
    if lead:
        return _entry(normalized, "lead-owned", ["controller"], matched=lead)
    forbidden = [root for root in classifiers["forbiddenWrites"] if is_under_authority_path(normalized, root)]
    if forbidden:
        return _entry(normalized, "forbidden", [], matched=forbidden)
    read_only = [root for root in classifiers["readOnly"] if is_under_authority_path(normalized, root)]
    if read_only:
        return _entry(normalized, "read-only", [], matched=read_only)
    owners = [
        owner
        for owner, roots in classifiers["workstreams"].items()
        if any(is_under_authority_path(normalized, root) for root in roots)
    ]
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


def _repo_relative(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return normalize_repo_path(str(path.resolve().relative_to(Path.cwd().resolve())))
    except ValueError:
        return None


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []

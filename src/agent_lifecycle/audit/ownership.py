"""Changed-file to frozen write-set ownership report."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import read_json_object
from agent_lifecycle.contracts.paths import normalize_repo_path


def build_ownership_report(
    manifest_path: Path,
    paths: list[str],
    *,
    base: str | None = None,
) -> dict[str, Any]:
    manifest = read_json_object(manifest_path, label="plan manifest")
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


def _classifiers(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    package = manifest.get("package", {})
    plan_root = package.get("planArtifactRoot")
    return {
        "manifestPath": _repo_relative(manifest_path),
        "planArtifactRoot": normalize_repo_path(plan_root) if isinstance(plan_root, str) else None,
        "leadOwned": [
            normalize_repo_path(item["path"])
            for item in manifest.get("leadOwned", [])
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        ],
        "readOnly": [
            normalize_repo_path(path)
            for path in manifest.get("readOnly", [])
            if isinstance(path, str)
        ],
        "forbiddenWrites": [
            normalize_repo_path(path)
            for path in manifest.get("forbiddenWrites", [])
            if isinstance(path, str)
        ],
        "workstreams": {
            workstream["id"]: [
                normalize_repo_path(path)
                for path in workstream.get("writes", [])
                if isinstance(path, str)
            ]
            for workstream in manifest.get("workstreams", [])
            if isinstance(workstream, dict) and isinstance(workstream.get("id"), str)
        },
    }


def _classify_path(path: str, classifiers: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_repo_path(path)
    manifest_path = classifiers["manifestPath"]
    if isinstance(manifest_path, str) and normalized == manifest_path:
        return _entry(normalized, "plan-authority", ["controller"])
    plan_root = classifiers["planArtifactRoot"]
    if isinstance(plan_root, str) and _under(normalized, plan_root):
        return _entry(normalized, "plan-authority", ["controller"])
    lead = [root for root in classifiers["leadOwned"] if _under(normalized, root)]
    if lead:
        return _entry(normalized, "lead-owned", ["controller"], matched=lead)
    forbidden = [root for root in classifiers["forbiddenWrites"] if _under(normalized, root)]
    if forbidden:
        return _entry(normalized, "forbidden", [], matched=forbidden)
    read_only = [root for root in classifiers["readOnly"] if _under(normalized, root)]
    if read_only:
        return _entry(normalized, "read-only", [], matched=read_only)
    owners = [
        owner
        for owner, roots in classifiers["workstreams"].items()
        if any(_under(normalized, root) for root in roots)
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


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def _repo_relative(path: Path) -> str | None:
    try:
        return normalize_repo_path(str(path.resolve().relative_to(Path.cwd().resolve())))
    except ValueError:
        return None

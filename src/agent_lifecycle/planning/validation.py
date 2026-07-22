"""Validate portable plan manifest structure and write ownership."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.paths import normalize_repo_path


def validate_plan_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    _require_package(manifest)
    workstreams = _workstreams(manifest)
    overlaps = _write_overlaps(workstreams)
    if overlaps:
        raise LifecycleError("plan-write-overlap", "workstream write sets overlap", {"overlaps": overlaps})
    return {
        "schemaVersion": "agent-plan-validation.v1",
        "packageId": manifest["package"]["id"],
        "planRevision": manifest.get("planRevision"),
        "status": manifest.get("status"),
        "workstreamCount": len(workstreams),
        "planDigest": canonical_digest(manifest),
    }


def _require_package(manifest: dict[str, Any]) -> None:
    package = manifest.get("package")
    if not isinstance(package, dict) or not isinstance(package.get("id"), str):
        raise LifecycleError("invalid-plan-manifest", "package.id is required")
    if manifest.get("status") not in {"DRAFT", "REOPENED", "FROZEN"}:
        raise LifecycleError("invalid-plan-manifest", "plan status is invalid")
    if not isinstance(manifest.get("planRevision"), int):
        raise LifecycleError("invalid-plan-manifest", "planRevision is required")


def _workstreams(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    workstreams = manifest.get("workstreams")
    if not isinstance(workstreams, list) or not workstreams:
        raise LifecycleError("invalid-plan-manifest", "workstreams are required")
    return [item for item in workstreams if isinstance(item, dict)]


def _write_overlaps(workstreams: list[dict[str, Any]]) -> list[dict[str, str]]:
    seen: list[tuple[str, str]] = []
    overlaps: list[dict[str, str]] = []
    for workstream in workstreams:
        owner = workstream.get("id")
        for raw_path in workstream.get("writes", []):
            path = normalize_repo_path(raw_path)
            overlaps.extend(_overlaps(owner, path, seen))
            seen.append((owner, path))
    return overlaps


def _overlaps(owner: str, path: str, seen: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [
        {"leftOwner": prior_owner, "left": prior_path, "rightOwner": owner, "right": path}
        for prior_owner, prior_path in seen
        if prior_owner != owner and (_under(path, prior_path) or _under(prior_path, path))
    ]


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")

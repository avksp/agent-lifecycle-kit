"""Compact read-only status views."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object, sha256_hex

STATUS_VIEW_SCHEMA = "agent-readonly-status-view.v1"


def build_status_view(
    *,
    project_root: Path,
    artifact_paths: list[Path],
    max_items: int = 12,
    target_window: str = "8k",
) -> dict[str, Any]:
    """Render a compact view from existing artifacts without owning state."""

    root = project_root.resolve()
    if max_items <= 0:
        raise LifecycleError("invalid-status-view-cap", "max items must be positive")
    blockers: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    if not artifact_paths:
        blockers.append({"code": "status-view-artifacts-missing", "message": "at least one artifact is required"})
    for raw_path in artifact_paths[:max_items]:
        items.append(_status_item(root, raw_path, blockers))
    if len(artifact_paths) > max_items:
        blockers.append({"code": "status-view-item-cap-exceeded", "count": len(artifact_paths), "maxItems": max_items})
    status_counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("artifactStatus") or item.get("status") or "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1
    body = {
        "schemaVersion": STATUS_VIEW_SCHEMA,
        "status": "PASS" if not blockers and not _has_failed_artifact(items) else "FAIL",
        "sourceOfTruth": False,
        "projectRoot": "<checkout>",
        "targetWindow": target_window,
        "estimatedTokens": _estimate_tokens(items),
        "itemCount": len(items),
        "statusCounts": status_counts,
        "items": items,
        "blockers": blockers,
        "nextActions": _next_actions(blockers, items),
        "productionPromotionClaimed": False,
    }
    return {**body, "viewDigest": canonical_digest(body)}


def require_status_view_pass(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") == "FAIL":
        raise LifecycleError("status-view-validation-failed", "status view validation failed", {"validation": payload})
    return payload


def _status_item(root: Path, raw_path: Path, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    path = raw_path if raw_path.is_absolute() else root / raw_path
    display_path = _display_path(path, root)
    if not path.is_file():
        blockers.append({"code": "status-view-artifact-missing", "path": display_path})
        return {"path": display_path, "status": "MISSING", "identity": None, "blockerCodes": ["status-view-artifact-missing"]}
    data = path.read_bytes()
    identity = {"path": display_path, "sha256": sha256_hex(data), "bytes": len(data)}
    try:
        payload = load_json_object(data, label=display_path)
    except LifecycleError as error:
        blockers.append({"code": error.code, "path": display_path, "message": error.message})
        return {"path": display_path, "status": "INVALID", "identity": identity, "blockerCodes": [error.code]}
    artifact_status = payload.get("status")
    blocker_codes = _blocker_codes(payload)
    if artifact_status == "FAIL":
        blockers.append({"code": "status-view-artifact-failed", "path": display_path})
    return {
        "path": display_path,
        "status": "PASS",
        "identity": identity,
        "schemaVersion": payload.get("schemaVersion"),
        "artifactStatus": artifact_status,
        "blockerCodes": blocker_codes,
        "summaryDigest": canonical_digest(
            {
                "schemaVersion": payload.get("schemaVersion"),
                "status": artifact_status,
                "blockerCodes": blocker_codes,
            }
        ),
    }


def _blocker_codes(payload: dict[str, Any]) -> list[str]:
    blockers = payload.get("blockers")
    if not isinstance(blockers, list):
        return []
    return [
        str(item.get("code"))
        for item in blockers
        if isinstance(item, dict) and isinstance(item.get("code"), str) and item.get("code")
    ][:8]


def _has_failed_artifact(items: list[dict[str, Any]]) -> bool:
    return any(item.get("artifactStatus") == "FAIL" or item.get("status") in {"MISSING", "INVALID"} for item in items)


def _estimate_tokens(items: list[dict[str, Any]]) -> int:
    return max(1, len(str(items).encode("utf-8")) // 4)


def _next_actions(blockers: list[dict[str, Any]], items: list[dict[str, Any]]) -> list[str]:
    if blockers:
        return ["inspect failed source artifact", "regenerate validation evidence before final review"]
    if not items:
        return ["provide at least one source artifact"]
    return ["continue with review using source artifacts for authority"]


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name

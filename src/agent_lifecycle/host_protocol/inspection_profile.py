"""Bounded, data-only profiles for adapter capability inspection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.validation import load_bounded_literal_profile

INSPECTION_PROFILE_SCHEMA = "agent-host-adapter-inspection-profile.v1"
INSPECTION_PROFILE_FILENAME = "inspection_profile.py"
INSPECTION_PROFILE_MAX_BYTES = 32768
INSPECTION_HANDLER_IDS = frozenset(
    {
        "claude",
        "codex",
        "cursor",
        "gemini-cli",
        "hermes",
        "kimi-code",
        "opencode",
        "qwen-code",
    }
)
INSPECTION_PROFILE_STATUSES = frozenset({"SUPPORTED", "UNSUPPORTED"})
_PROFILE_KEYS = frozenset(
    {
        "schemaVersion",
        "adapterId",
        "host",
        "binary",
        "status",
        "handler",
        "profileId",
        "productionPromotionClaimed",
        "modelCallsStarted",
    }
)


def load_inspection_profile(
    adapter_id: str,
    *,
    descriptor_path: Path | None,
    project_root: Path,
    host: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and validate an adapter-owned profile without importing it."""

    if descriptor_path is None:
        raise LifecycleError("adapter-inspection-profile-missing", "inspection requires an adapter descriptor path")
    adapter_root = descriptor_path.parent
    profile_path = adapter_root / INSPECTION_PROFILE_FILENAME
    profile = load_bounded_literal_profile(
        Path(INSPECTION_PROFILE_FILENAME),
        root=adapter_root,
        error_prefix="adapter-inspection-profile",
        max_bytes=INSPECTION_PROFILE_MAX_BYTES,
    )
    validation = validate_inspection_profile(profile, adapter_id=adapter_id, host=host)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "adapter-inspection-profile-invalid",
            "adapter inspection profile failed validation",
            {"validation": validation},
        )
    return profile, {
        "path": _display_path(profile_path, project_root),
        "profileDigest": canonical_digest(profile),
        "status": profile["status"],
        "handler": profile.get("handler"),
    }


def validate_inspection_profile(
    profile: Any,
    *,
    adapter_id: str | None = None,
    host: str | None = None,
) -> dict[str, Any]:
    """Validate profile metadata and reject authority-bearing fields."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(profile, dict):
        blockers.append({"code": "inspection-profile-object-required"})
        return _validation(profile, blockers)
    unknown = sorted(set(profile) - _PROFILE_KEYS)
    if unknown:
        blockers.append({"code": "inspection-profile-unknown-fields", "fields": unknown})
    if profile.get("schemaVersion") != INSPECTION_PROFILE_SCHEMA:
        blockers.append({"code": "inspection-profile-schema-invalid"})
    if not isinstance(profile.get("adapterId"), str) or not profile.get("adapterId"):
        blockers.append({"code": "inspection-profile-adapter-invalid"})
    elif adapter_id is not None and profile["adapterId"] != adapter_id:
        blockers.append({"code": "inspection-profile-adapter-mismatch"})
    if not isinstance(profile.get("host"), str) or not profile.get("host"):
        blockers.append({"code": "inspection-profile-host-invalid"})
    elif host is not None and profile["host"] != host:
        blockers.append({"code": "inspection-profile-host-mismatch"})
    if not isinstance(profile.get("binary"), str) or not profile.get("binary"):
        blockers.append({"code": "inspection-profile-binary-invalid"})
    status = profile.get("status")
    if status not in INSPECTION_PROFILE_STATUSES:
        blockers.append({"code": "inspection-profile-status-invalid"})
    handler = profile.get("handler")
    if status == "SUPPORTED" and handler not in INSPECTION_HANDLER_IDS:
        blockers.append({"code": "inspection-profile-handler-invalid"})
    if status == "UNSUPPORTED" and handler is not None:
        blockers.append({"code": "inspection-profile-unsupported-handler"})
    if profile.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "inspection-profile-authority-forbidden"})
    if profile.get("modelCallsStarted") is not False:
        blockers.append({"code": "inspection-profile-live-call-forbidden"})
    if not isinstance(profile.get("profileId"), str) or not profile.get("profileId"):
        blockers.append({"code": "inspection-profile-id-invalid"})
    return _validation(profile, blockers)


def _validation(profile: Any, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": "agent-host-adapter-inspection-profile-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "adapterId": profile.get("adapterId") if isinstance(profile, dict) else None,
        "handler": profile.get("handler") if isinstance(profile, dict) else None,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name

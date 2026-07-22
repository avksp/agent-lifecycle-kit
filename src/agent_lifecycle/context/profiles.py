"""Validate compact context profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object

WINDOWS = {"8k": 8192, "16k": 16384, "32k": 32768, "64k": 65536}
REQUIRED_SUMMARY_FIELDS = {
    "latestUserIntent",
    "activeDecisions",
    "openBlockers",
    "acceptedEvidence",
    "changedFiles",
    "nextRequiredAction",
    "doNotDo",
}


def load_context_profile(path: Path) -> dict[str, Any]:
    return validate_context_profile(read_json_object(path, label="context profile"))


def validate_context_profile(profile: dict[str, Any]) -> dict[str, Any]:
    if profile.get("schemaVersion") != "agent-small-context-profile.v1":
        raise LifecycleError("invalid-context-profile", "unsupported context profile schema")
    profile_id = profile.get("profileId")
    if not isinstance(profile_id, str) or not profile_id:
        raise LifecycleError("invalid-context-profile", "profileId is required")
    default_window = profile.get("defaultWindow")
    windows = profile.get("windows")
    if default_window not in WINDOWS or not isinstance(windows, dict) or default_window not in windows:
        raise LifecycleError("invalid-context-profile", "defaultWindow must reference a supported window")
    checked_windows = {name: _validate_window(name, value) for name, value in windows.items()}
    summary_fields = set(profile.get("requiredSummaryFields", []))
    if not REQUIRED_SUMMARY_FIELDS.issubset(summary_fields):
        raise LifecycleError("invalid-context-profile", "required summary fields are incomplete")
    return {
        "schemaVersion": "agent-small-context-profile-validation.v1",
        "profileId": profile_id,
        "defaultWindow": default_window,
        "windows": checked_windows,
        "requiredSummaryFields": sorted(summary_fields),
        "profileDigest": canonical_digest(profile),
    }


def resolve_window(profile: dict[str, Any], window: str | None) -> dict[str, Any]:
    validation = validate_context_profile(profile)
    selected = window or validation["defaultWindow"]
    if selected not in validation["windows"]:
        raise LifecycleError("unknown-context-window", f"context window is not supported: {selected}")
    return {"name": selected, **validation["windows"][selected]}


def _validate_window(name: str, value: Any) -> dict[str, Any]:
    if name not in WINDOWS or not isinstance(value, dict):
        raise LifecycleError("invalid-context-profile", f"invalid window profile: {name}")
    limits = value.get("limits")
    overflow = value.get("overflowPolicy")
    if not isinstance(limits, dict) or not isinstance(overflow, dict):
        raise LifecycleError("invalid-context-profile", f"window {name} requires limits and overflowPolicy")
    required_limits = {
        "maxRenderedEnvelopeTokens",
        "reservedOutputTokens",
        "maxActivePacketTokens",
        "maxStateSummaryTokens",
        "maxEvidenceSummaryTokens",
        "maxToolOutputTokens",
        "maxRecentUserTurnsVerbatim",
    }
    missing = sorted(item for item in required_limits if not isinstance(limits.get(item), int))
    if missing:
        raise LifecycleError("invalid-context-profile", f"window {name} is missing numeric limits", {"missing": missing})
    if limits["maxRenderedEnvelopeTokens"] + limits["reservedOutputTokens"] > WINDOWS[name]:
        raise LifecycleError("invalid-context-profile", f"window {name} exceeds target context size")
    if overflow.get("truncateAllowed") is not False:
        raise LifecycleError("invalid-context-profile", "compact context truncation must be forbidden")
    default_action = overflow.get("defaultAction")
    allowed = overflow.get("allowedActions")
    if default_action not in {"split-task", "request-larger-context", "block"}:
        raise LifecycleError("invalid-context-profile", "invalid overflow default action")
    if not isinstance(allowed, list) or default_action not in allowed:
        raise LifecycleError("invalid-context-profile", "overflow allowedActions must include defaultAction")
    return {
        "targetContextWindowTokens": WINDOWS[name],
        "limits": limits,
        "overflowPolicy": {
            "defaultAction": default_action,
            "allowedActions": list(allowed),
            "truncateAllowed": False,
        },
    }

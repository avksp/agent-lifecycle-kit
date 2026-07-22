"""Deterministic compact context envelopes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.context.profiles import REQUIRED_SUMMARY_FIELDS, resolve_window, validate_context_profile
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest, read_json_object

OPTIONAL_SUMMARY_FIELDS = {"toolOutputs"}


def render_context(
    profile: dict[str, Any],
    task_packet: dict[str, Any],
    state_summary: dict[str, Any],
    *,
    latest_user: str = "",
    window: str | None = None,
) -> dict[str, Any]:
    validate_context_profile(profile)
    selected = resolve_window(profile, window)
    summary = _summary_projection(state_summary)
    packet = _packet_projection(task_packet)
    envelope = {
        "schemaVersion": "agent-context-envelope.v1",
        "mode": "compact",
        "profileId": profile["profileId"],
        "window": selected["name"],
        "latestUserInstruction": latest_user,
        "stateSummary": summary,
        "activeTaskPacket": packet,
        "omitted": _omitted(task_packet),
    }
    receipt = _receipt(profile, selected, envelope, packet, summary)
    return {
        "schemaVersion": "agent-context-render-result.v1",
        "status": receipt["status"],
        "envelope": envelope,
        "receipt": receipt,
    }


def check_context(
    profile_path: Path,
    task_packet_path: Path,
    summary_path: Path,
    *,
    latest_user: str = "",
    window: str | None = None,
) -> dict[str, Any]:
    profile = read_json_object(profile_path, label="context profile")
    packet = read_json_object(task_packet_path, label="task packet")
    summary = read_json_object(summary_path, label="state summary")
    rendered = render_context(profile, packet, summary, latest_user=latest_user, window=window)
    return {
        "schemaVersion": "agent-context-check.v1",
        "status": rendered["status"],
        "receipt": rendered["receipt"],
    }


def estimate_tokens(value: Any) -> int:
    return max(1, (len(canonical_bytes(value)) + 3) // 4)


def _summary_projection(summary: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(field for field in REQUIRED_SUMMARY_FIELDS if field not in summary)
    if missing:
        raise LifecycleError("invalid-context-summary", "compact summary is missing required fields", {"missing": missing})
    projected = {field: summary[field] for field in sorted(REQUIRED_SUMMARY_FIELDS)}
    for field in sorted(OPTIONAL_SUMMARY_FIELDS):
        if field in summary:
            projected[field] = summary[field]
    return projected


def _packet_projection(packet: dict[str, Any]) -> dict[str, Any]:
    if packet.get("schemaVersion") != "agent-task-packet.v1":
        raise LifecycleError("invalid-task-packet", "task packet schema is unsupported")
    return {
        "plan": dict(packet.get("plan", {})),
        "task": dict(packet.get("task", {})),
        "ownership": dict(packet.get("ownership", {})),
        "specification": dict(packet.get("specification", {})),
        "validation": dict(packet.get("validation", {})),
        "acceptance": list(packet.get("acceptance", [])),
        "contextRefs": list(packet.get("context", {}).get("refs", [])),
    }


def _omitted(packet: dict[str, Any]) -> list[dict[str, Any]]:
    omitted: list[dict[str, Any]] = []
    for key in sorted(set(packet) - {"schemaVersion", "plan", "task", "ownership", "specification", "validation", "acceptance", "context"}):
        omitted.append({"path": key, "reason": "not-required-for-compact-active-task"})
    return omitted


def _receipt(
    profile: dict[str, Any],
    selected: dict[str, Any],
    envelope: dict[str, Any],
    packet: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    limits = selected["limits"]
    envelope_tokens = estimate_tokens(envelope)
    packet_tokens = estimate_tokens(packet)
    summary_tokens = estimate_tokens(summary)
    evidence_tokens = _optional_tokens(summary["acceptedEvidence"])
    tool_output_tokens = _optional_tokens(summary.get("toolOutputs", []))
    recent_user_turns = _recent_user_turn_count(envelope.get("latestUserInstruction", ""))
    reserved_output_budget = envelope_tokens + limits["reservedOutputTokens"]
    checks = [
        _check("rendered-envelope", envelope_tokens, limits["maxRenderedEnvelopeTokens"]),
        _check("reserved-output-budget", reserved_output_budget, selected["targetContextWindowTokens"]),
        _check("active-packet", packet_tokens, limits["maxActivePacketTokens"]),
        _check("state-summary", summary_tokens, limits["maxStateSummaryTokens"]),
        _check("evidence-summary", evidence_tokens, limits["maxEvidenceSummaryTokens"]),
        _check("tool-output", tool_output_tokens, limits["maxToolOutputTokens"]),
        _check_count("recent-user-turns-verbatim", recent_user_turns, limits["maxRecentUserTurnsVerbatim"]),
    ]
    status = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    return {
        "schemaVersion": "agent-context-render-receipt.v1",
        "status": status,
        "profileId": profile["profileId"],
        "profileDigest": canonical_digest(profile),
        "window": selected["name"],
        "estimatedTokens": {
            "renderedEnvelope": envelope_tokens,
            "reservedOutputBudget": reserved_output_budget,
            "activePacket": packet_tokens,
            "stateSummary": summary_tokens,
            "evidenceSummary": evidence_tokens,
            "toolOutput": tool_output_tokens,
        },
        "counts": {
            "recentUserTurnsVerbatim": recent_user_turns,
        },
        "limits": limits,
        "checks": checks,
        "overflowPolicy": selected["overflowPolicy"],
        "envelopeDigest": canonical_digest(envelope),
    }


def _check(name: str, value: int, limit: int) -> dict[str, Any]:
    return {
        "id": name,
        "status": "PASS" if value <= limit else "FAIL",
        "estimatedTokens": value,
        "limit": limit,
    }


def _check_count(name: str, value: int, limit: int) -> dict[str, Any]:
    return {
        "id": name,
        "status": "PASS" if value <= limit else "FAIL",
        "count": value,
        "limit": limit,
    }


def _optional_tokens(value: Any) -> int:
    if value in (None, "", [], {}):
        return 0
    return estimate_tokens(value)


def _recent_user_turn_count(latest_user: Any) -> int:
    if isinstance(latest_user, str):
        return 1 if latest_user else 0
    if isinstance(latest_user, list):
        return len([item for item in latest_user if item])
    return 0

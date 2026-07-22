"""Deterministic SDD tier resolution."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest

RISK_FLAGS = {
    "architecture",
    "security",
    "performance",
    "browser",
    "externalEnvironment",
}
BOUNDED_MECHANICAL = "bounded-mechanical"
S1_EMBEDDED_REQUIREMENTS_BYTES = 32768


def resolve_sdd_tier(request: dict[str, Any]) -> dict[str, Any]:
    task_count = _positive_int(request.get("taskCount"), "taskCount")
    owners = _owners(request.get("executableOwners"))
    hints = set(_strings(request.get("capabilityHints", []), "capabilityHints"))
    risks = _risk_flags(request.get("riskFlags", {}))
    requirements_bytes = _nonnegative_int(request.get("requirementsBytes", 0), "requirementsBytes")
    reasons: list[str] = []

    if len(owners) > 1:
        reasons.append("multiple-executable-owners")
    for name in sorted(RISK_FLAGS):
        if risks.get(name):
            reasons.append(f"{name}-risk")
    if request.get("externalSpecification") is True:
        reasons.append("external-specification-required")
    if requirements_bytes > S1_EMBEDDED_REQUIREMENTS_BYTES:
        reasons.append("embedded-requirements-byte-ceiling-exceeded")
    if reasons:
        return _result("S2", reasons, request)

    if task_count == 1 and len(owners) == 1 and BOUNDED_MECHANICAL in hints:
        return _result("S0", ["single-owner-bounded-mechanical-low-risk"], request)
    return _result("S1", ["single-owner-standard-work"], request)


def _result(tier: str, reasons: list[str], request: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": "agent-sdd-tier-resolution.v1",
        "tier": tier,
        "reasons": reasons,
        "requestDigest": canonical_digest(request),
        "rules": {
            "S0": "exactly one executable owner, exactly one task, bounded-mechanical, no elevated risk",
            "S1": "single executable owner, embedded requirements at or below 32768 bytes, no elevated risk",
            "S2": "multiple executable owners or architecture/security/performance/browser/external-environment risk",
        },
    }


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or value < 1:
        raise LifecycleError("invalid-tier-request", f"{label} must be a positive integer")
    return value


def _nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise LifecycleError("invalid-tier-request", f"{label} must be a non-negative integer")
    return value


def _owners(value: Any) -> list[str]:
    owners = _strings(value, "executableOwners")
    if not owners:
        raise LifecycleError("invalid-tier-request", "executableOwners must not be empty")
    return sorted(set(owners))


def _strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise LifecycleError("invalid-tier-request", f"{label} must be a list of strings")
    return value


def _risk_flags(value: Any) -> dict[str, bool]:
    if not isinstance(value, dict):
        raise LifecycleError("invalid-tier-request", "riskFlags must be an object")
    return {name: bool(value.get(name, False)) for name in RISK_FLAGS}

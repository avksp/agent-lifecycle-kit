"""Validate portable SDD specification envelopes."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest

SDD_TIERS = {"S0", "S1", "S2"}
SPEC_STATUSES = {"DRAFT", "READY", "FROZEN", "REOPENED"}


def validate_specification(specification: dict[str, Any]) -> dict[str, Any]:
    tier = specification.get("tier")
    if tier not in SDD_TIERS:
        raise LifecycleError("invalid-specification", "specification tier must be S0, S1, or S2")
    status = specification.get("status")
    if status not in SPEC_STATUSES:
        raise LifecycleError("invalid-specification", "specification status is invalid")
    requirements = specification.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        raise LifecycleError("invalid-specification", "specification requirements are required")
    ids = [_requirement_id(item) for item in requirements]
    if len(ids) != len(set(ids)):
        raise LifecycleError("invalid-specification", "requirement ids must be unique")
    return {
        "schemaVersion": "agent-specification-validation.v1",
        "tier": tier,
        "status": status,
        "requirementCount": len(ids),
        "requirementSetDigest": canonical_digest({"requirements": ids}),
    }


def _requirement_id(item: Any) -> str:
    if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
        raise LifecycleError("invalid-specification", "each requirement requires an id")
    if item.get("required") is False:
        raise LifecycleError("invalid-specification", "optional requirements are not accepted in frozen core")
    return item["id"]

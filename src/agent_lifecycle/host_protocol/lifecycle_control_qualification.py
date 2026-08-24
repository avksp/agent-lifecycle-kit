"""Semantic qualification checks for adapter lifecycle-control evidence.

The core contract validator checks envelope shape and digests. This module
checks the stronger claim made by a qualification receipt: exact host-version
coverage, operation coverage, and proof that denied actions had no side effect.
It never launches a host and never promotes an adapter automatically.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.lifecycle_control_definitions import (
    CONTROL_LEVELS,
    CONTROL_OPERATIONS,
    LIFECYCLE_CONTROL_QUALIFICATION_SCHEMA,
    QUALIFICATION_STATUSES,
)
from agent_lifecycle.contracts.lifecycle_control_schemas import (
    build_lifecycle_control_qualification_receipt,
    validate_lifecycle_control_qualification_receipt,
)

QUALIFICATION_MATRIX_SCHEMA = "agent-lifecycle-control-qualification-matrix.v1"
QUALIFICATION_LEVEL_ORDER = {level: index for index, level in enumerate(CONTROL_LEVELS)}

POSITIVE_SCENARIOS = (
    "pre-action-allow",
    "post-action-bind",
    "stop-accept",
)
NEGATIVE_SCENARIOS = (
    "direct-file-edit",
    "shell-write",
    "stale-state",
    "missing-alk",
    "timeout",
    "malformed-output",
    "disabled-control",
    "modified-control",
    "replay",
    "producer-crash",
)
ALL_SCENARIOS = POSITIVE_SCENARIOS + NEGATIVE_SCENARIOS


def build_fixture_evidence(
    *,
    host: str,
    host_version: str,
    operation: str,
    source: str = "fixture",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build bounded synthetic evidence that is explicitly non-promoting."""

    positive = [
        {
            "scenarioId": scenario,
            "adapterId": "claude",
            "host": host,
            "hostVersion": host_version,
            "operation": operation,
            "source": source,
            "syntheticReplayUsed": True,
            "status": "PASS",
            "deniedBeforeEffect": False,
            "sideEffectObserved": False,
            "evidenceDigest": canonical_digest({"scenarioId": scenario, "operation": operation, "source": source}),
        }
        for scenario in POSITIVE_SCENARIOS
    ]
    negative = [
        {
            "scenarioId": scenario,
            "adapterId": "claude",
            "host": host,
            "hostVersion": host_version,
            "operation": operation,
            "source": source,
            "syntheticReplayUsed": True,
            "status": "BLOCKED",
            "deniedBeforeEffect": True,
            "sideEffectObserved": False,
            "processEvidence": {"started": False, "exitCode": None},
            "evidenceDigest": canonical_digest({"scenarioId": scenario, "operation": operation, "source": source}),
        }
        for scenario in NEGATIVE_SCENARIOS
    ]
    return positive, negative


def build_qualification_receipt(
    *,
    adapter_id: str,
    host: str,
    host_version: str,
    expected_host_version: str,
    operation: str,
    declared_level: str,
    supported_level: str,
    positive_evidence: list[dict[str, Any]],
    negative_evidence: list[dict[str, Any]],
    evidence_refs: list[str],
    live_evidence: bool,
    unavailable: bool = False,
) -> dict[str, Any]:
    """Build a qualification receipt without silently promoting a level."""

    evidence_is_live = live_evidence and _evidence_is_live(positive_evidence + negative_evidence)
    blockers = _matrix_blockers(
        adapter_id=adapter_id,
        host=host,
        host_version=host_version,
        expected_host_version=expected_host_version,
        operation=operation,
        declared_level=declared_level,
        supported_level=supported_level,
        qualified_level=supported_level if evidence_is_live else "GUIDANCE_ONLY",
        positive_evidence=positive_evidence,
        negative_evidence=negative_evidence,
        live_evidence=evidence_is_live,
    )
    if unavailable:
        blockers.append({"code": "control-qualification-live-unavailable"})
    if supported_level == "ENFORCED" and not evidence_is_live:
        blockers.append({"code": "control-qualification-enforced-needs-live"})
    status = (
        "QUALIFIED"
        if evidence_is_live and not blockers
        else "NO_RECOMMENDATION"
        if unavailable or not evidence_is_live
        else "BLOCKED"
    )
    qualified_level = supported_level if status == "QUALIFIED" else "GUIDANCE_ONLY"
    return build_lifecycle_control_qualification_receipt(
        adapter_id=adapter_id,
        host=host,
        host_version=host_version,
        operation=operation,
        declared_level=declared_level,
        supported_level=supported_level,
        qualified_level=qualified_level,
        status=status,
        positive_evidence=positive_evidence,
        negative_evidence=negative_evidence,
        evidence_refs=evidence_refs,
        blockers=blockers,
    )


def validate_qualification_receipt(
    receipt: dict[str, Any],
    *,
    expected_host_version: str | None = None,
    expected_operation: str | None = None,
    require_live: bool = False,
) -> dict[str, Any]:
    """Validate envelope and semantic qualification evidence together."""

    base = validate_lifecycle_control_qualification_receipt(receipt)
    blockers = list(base.get("blockers", []))
    if receipt.get("schemaVersion") != LIFECYCLE_CONTROL_QUALIFICATION_SCHEMA:
        return _result("UNAVAILABLE", blockers)
    if expected_host_version is not None and receipt.get("hostVersion") != expected_host_version:
        blockers.append(
            {
                "code": "control-qualification-host-version-mismatch",
                "expected": expected_host_version,
                "actual": receipt.get("hostVersion"),
            }
        )
    if expected_operation is not None and receipt.get("operation") != expected_operation:
        blockers.append(
            {
                "code": "control-qualification-operation-mismatch",
                "expected": expected_operation,
                "actual": receipt.get("operation"),
            }
        )
    live_evidence = _has_live_evidence(receipt)
    blockers.extend(
        _matrix_blockers(
            adapter_id=receipt.get("adapterId"),
            host=receipt.get("host"),
            host_version=receipt.get("hostVersion"),
            expected_host_version=expected_host_version or receipt.get("hostVersion"),
            operation=receipt.get("operation"),
            declared_level=receipt.get("declaredLevel"),
            supported_level=receipt.get("supportedLevel"),
            qualified_level=receipt.get("qualifiedLevel"),
            positive_evidence=receipt.get("positiveEvidence"),
            negative_evidence=receipt.get("negativeEvidence"),
            live_evidence=live_evidence,
            require_live=require_live,
        )
    )
    if receipt.get("status") == "QUALIFIED" and not live_evidence:
        blockers.append({"code": "control-qualification-qualified-needs-live"})
    status = receipt.get("status") if not blockers else "BLOCKED"
    status_value = status if isinstance(status, str) and status in QUALIFICATION_STATUSES else "UNAVAILABLE"
    return _result(status_value, _deduplicate_blockers(blockers))


def validate_capability_level_claims(
    capability_manifest: dict[str, Any],
    *,
    descriptor: dict[str, Any],
) -> dict[str, Any]:
    """Validate operation-specific lifecycle levels before attribution."""

    blockers: list[dict[str, Any]] = []
    descriptor_operations = {
        item.get("name"): item
        for item in descriptor.get("operations", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    capabilities = capability_manifest.get("capabilities")
    levels: dict[str, str] = {}
    if not isinstance(capabilities, list):
        blockers.append({"code": "capability-levels-missing"})
        capabilities = []
    for item in capabilities:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            blockers.append({"code": "capability-level-entry-invalid"})
            continue
        name = item["name"]
        descriptor_operation = descriptor_operations.get(name)
        if not isinstance(descriptor_operation, dict):
            blockers.append({"code": "capability-level-operation-unknown", "operation": name})
            continue
        operation_blockers: list[dict[str, Any]] = []
        declared = item.get("declaredLevel")
        supported = item.get("supportedLevel")
        qualified = item.get("qualifiedLevel")
        if any(level not in CONTROL_LEVELS for level in (declared, supported, qualified)):
            operation_blockers.append({"code": "capability-level-invalid", "operation": name})
        elif not (
            QUALIFICATION_LEVEL_ORDER[str(declared)]
            >= QUALIFICATION_LEVEL_ORDER[str(supported)]
            >= QUALIFICATION_LEVEL_ORDER[str(qualified)]
        ):
            operation_blockers.append({"code": "capability-level-escalation", "operation": name})
        for field in ("declaredLevel", "supportedLevel", "qualifiedLevel", "qualificationStatus"):
            if field in descriptor_operation and item.get(field) != descriptor_operation.get(field):
                operation_blockers.append(
                    {
                        "code": "capability-level-descriptor-drift",
                        "operation": name,
                        "field": field,
                    }
                )
        if qualified in {"OBSERVED", "ENFORCED"} and item.get("qualificationStatus") != "QUALIFIED":
            operation_blockers.append(
                {"code": "capability-level-qualification-required", "operation": name}
            )
        if operation_blockers:
            blockers.extend(operation_blockers)
            levels[name] = "UNAVAILABLE"
        else:
            levels[name] = str(qualified)
    return {
        "schemaVersion": "agent-capability-level-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "levels": levels,
        "blockers": blockers,
        "productionPromotionClaimed": False,
        "validationDigest": canonical_digest(
            {
                "schemaVersion": "agent-capability-level-validation.v1",
                "status": "PASS" if not blockers else "FAIL",
                "levels": levels,
                "blockers": blockers,
                "productionPromotionClaimed": False,
            }
        ),
    }


def _matrix_blockers(
    *,
    adapter_id: Any,
    host: Any,
    host_version: Any,
    expected_host_version: Any,
    operation: Any,
    declared_level: Any,
    supported_level: Any,
    qualified_level: Any,
    positive_evidence: Any,
    negative_evidence: Any,
    live_evidence: bool,
    require_live: bool = False,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(adapter_id, str) or not adapter_id:
        blockers.append({"code": "control-qualification-adapter"})
    if not isinstance(host, str) or not host:
        blockers.append({"code": "control-qualification-host"})
    if not isinstance(host_version, str) or not host_version:
        blockers.append({"code": "control-qualification-host-version"})
    elif isinstance(expected_host_version, str) and host_version != expected_host_version:
        blockers.append(
            {
                "code": "control-qualification-host-version-mismatch",
                "expected": expected_host_version,
                "actual": host_version,
            }
        )
    if operation not in CONTROL_OPERATIONS:
        blockers.append({"code": "control-qualification-operation"})
    levels = (declared_level, supported_level, qualified_level)
    if any(level not in CONTROL_LEVELS for level in levels):
        blockers.append({"code": "control-qualification-level"})
    elif not (
        QUALIFICATION_LEVEL_ORDER[str(declared_level)]
        >= QUALIFICATION_LEVEL_ORDER[str(supported_level)]
        >= QUALIFICATION_LEVEL_ORDER[str(qualified_level)]
    ):
        blockers.append({"code": "control-qualification-level-escalation"})
    positive = _evidence_by_scenario(positive_evidence, "positive", blockers)
    negative = _evidence_by_scenario(negative_evidence, "negative", blockers)
    _require_scenarios(positive, POSITIVE_SCENARIOS, "positive", blockers)
    _require_scenarios(negative, NEGATIVE_SCENARIOS, "negative", blockers)
    for item in list(positive.values()) + list(negative.values()):
        if item.get("hostVersion") != host_version:
            blockers.append(
                {"code": "control-qualification-evidence-host-version", "scenarioId": item.get("scenarioId")}
            )
        if item.get("operation") != operation:
            blockers.append({"code": "control-qualification-evidence-operation", "scenarioId": item.get("scenarioId")})
        if item.get("adapterId") != adapter_id:
            blockers.append({"code": "control-qualification-evidence-adapter", "scenarioId": item.get("scenarioId")})
    for scenario, item in negative.items():
        if item.get("status") != "BLOCKED":
            blockers.append({"code": "control-qualification-denial-status", "scenarioId": scenario})
        if item.get("deniedBeforeEffect") is not True:
            blockers.append({"code": "control-qualification-denial-timing", "scenarioId": scenario})
        if item.get("sideEffectObserved") is not False:
            blockers.append({"code": "control-qualification-side-effect", "scenarioId": scenario})
        process = item.get("processEvidence")
        if not isinstance(process, dict) or process.get("started") is not False:
            blockers.append({"code": "control-qualification-process-evidence", "scenarioId": scenario})
        if not live_evidence and item.get("syntheticReplayUsed") is not True:
            blockers.append({"code": "control-qualification-source-metadata", "scenarioId": scenario})
    if require_live and not live_evidence:
        blockers.append({"code": "control-qualification-live-evidence-required"})
    if qualified_level == "ENFORCED" and not live_evidence:
        blockers.append({"code": "control-qualification-enforced-needs-live"})
    return blockers


def _evidence_by_scenario(value: Any, kind: str, blockers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        blockers.append({"code": "control-qualification-evidence-shape", "kind": kind})
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("scenarioId"), str) or not item.get("scenarioId"):
            blockers.append({"code": "control-qualification-evidence-item", "kind": kind})
            continue
        scenario = item["scenarioId"]
        allowed = POSITIVE_SCENARIOS if kind == "positive" else NEGATIVE_SCENARIOS
        if scenario not in allowed:
            blockers.append(
                {"code": "control-qualification-evidence-scenario-unknown", "kind": kind, "scenarioId": scenario}
            )
        if scenario in result:
            blockers.append({"code": "control-qualification-evidence-duplicate", "kind": kind, "scenarioId": scenario})
        else:
            result[scenario] = item
    return result


def _require_scenarios(
    evidence: dict[str, dict[str, Any]], required: Iterable[str], kind: str, blockers: list[dict[str, Any]]
) -> None:
    missing = sorted(set(required).difference(evidence))
    if missing:
        blockers.append({"code": "control-qualification-scenarios-missing", "kind": kind, "scenarios": missing})


def _has_live_evidence(receipt: dict[str, Any]) -> bool:
    evidence = list(receipt.get("positiveEvidence", [])) + list(receipt.get("negativeEvidence", []))
    return _evidence_is_live(evidence)


def _evidence_is_live(evidence: Any) -> bool:
    return (
        isinstance(evidence, list)
        and bool(evidence)
        and all(
            isinstance(item, dict) and item.get("syntheticReplayUsed") is False and item.get("source") == "live"
            for item in evidence
        )
    )


def _deduplicate_blockers(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for blocker in blockers:
        key = repr(sorted(blocker.items()))
        if key not in seen:
            seen.add(key)
            result.append(blocker)
    return result


def _result(status: str, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    body = {
        "schemaVersion": QUALIFICATION_MATRIX_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "qualificationStatus": status,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


__all__ = [
    "ALL_SCENARIOS",
    "NEGATIVE_SCENARIOS",
    "POSITIVE_SCENARIOS",
    "QUALIFICATION_MATRIX_SCHEMA",
    "build_fixture_evidence",
    "build_qualification_receipt",
    "validate_capability_level_claims",
    "validate_qualification_receipt",
]

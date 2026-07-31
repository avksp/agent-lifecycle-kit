"""Phase-level token and resource measurements."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.metrics.usage_export import usage_export_totals, validate_usage_export

PHASE_RESOURCE_MEASUREMENT_SCHEMA = "agent-phase-resource-measurement.v1"
PHASE_RESOURCE_MEASUREMENT_VALIDATION_SCHEMA = "agent-phase-resource-measurement-validation.v1"

TOKEN_KEYS = ("input", "output", "total")
RESOURCE_KEYS = {"contextBytes", "filesChanged", "toolCalls", "validationRuns", "cpuMs", "memoryMb"}
MONEY_KEYS = {"costUsd", "cost_usd", "usd", "budgetUsd", "money", "monetary", "hostReportedCost"}


def build_phase_resource_measurement(
    phases: list[dict[str, Any]],
    *,
    lineage: dict[str, Any] | None = None,
    source_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a phase measurement using the usage-export entry envelope."""

    if not isinstance(phases, list) or not phases:
        raise LifecycleError("invalid-phase-resource-measurement", "phases must be a non-empty list")
    entries = [_phase_entry(index, phase) for index, phase in enumerate(phases)]
    usage_export = {
        "schemaVersion": "agent-usage-export.v1",
        "status": "PASS",
        "generatedBy": "agent-lifecycle metrics phase-resources",
        "sourceArtifacts": list(source_artifacts or []),
        "lineage": dict(lineage or {}),
        "entries": entries,
        "totals": usage_export_totals(entries),
        "blockers": [],
        "productionPromotionClaimed": False,
    }
    usage_export = {**usage_export, "exportDigest": canonical_digest(usage_export)}
    body = {
        "schemaVersion": PHASE_RESOURCE_MEASUREMENT_SCHEMA,
        "status": "PASS",
        "phaseCount": len(entries),
        "phases": entries,
        "usageExport": usage_export,
        "totals": usage_export["totals"],
        "blockers": [],
        "productionPromotionClaimed": False,
    }
    return {**body, "measurementDigest": canonical_digest(body)}


def validate_phase_resource_measurement(measurement: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(measurement, dict):
        raise LifecycleError("invalid-phase-resource-measurement", "phase resource measurement must be an object")
    if measurement.get("schemaVersion") != PHASE_RESOURCE_MEASUREMENT_SCHEMA:
        blockers.append({"code": "phase-resource-schema-invalid"})
    status = measurement.get("status")
    if status not in {"PASS", "FAIL"}:
        blockers.append({"code": "phase-resource-status-invalid", "status": status})
    phases = measurement.get("phases")
    if not isinstance(phases, list) or not phases:
        blockers.append({"code": "phase-resource-phases-invalid"})
        phases = []
    for index, phase in enumerate(phases):
        _validate_phase_entry(index, phase, blockers)
    if measurement.get("phaseCount") != len(phases):
        blockers.append({"code": "phase-resource-count-mismatch"})
    usage_export = measurement.get("usageExport")
    if not isinstance(usage_export, dict):
        blockers.append({"code": "phase-resource-usage-export-invalid"})
    else:
        export_validation = validate_usage_export(usage_export)
        if export_validation["status"] != "PASS":
            blockers.append({"code": "phase-resource-usage-export-failed", "validation": export_validation})
        if usage_export.get("entries") != phases:
            blockers.append({"code": "phase-resource-usage-export-entry-mismatch"})
        if measurement.get("totals") != usage_export.get("totals"):
            blockers.append({"code": "phase-resource-total-mismatch"})
    if measurement.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "phase-resource-production-claim"})
    _check_object_list(measurement.get("blockers", []), "phase-resource-blockers-invalid", blockers)
    expected_digest = canonical_digest({key: value for key, value in measurement.items() if key != "measurementDigest"})
    if measurement.get("measurementDigest") != expected_digest:
        blockers.append({"code": "phase-resource-digest-mismatch"})
    body = {
        "schemaVersion": PHASE_RESOURCE_MEASUREMENT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "measurementStatus": status if isinstance(status, str) else None,
        "phaseCount": len(phases),
        "totals": measurement.get("totals") if isinstance(measurement.get("totals"), dict) else {},
        "blockers": blockers,
        "measurementDigest": measurement.get("measurementDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_phase_resource_measurement_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS" or validation.get("measurementStatus") != "PASS":
        raise LifecycleError("phase-resource-validation-failed", "phase resource measurement did not pass", {"validation": validation})
    return validation


def _phase_entry(index: int, phase: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(phase, dict):
        raise LifecycleError("invalid-phase-resource-measurement", "phase entries must be objects")
    if any(key in phase for key in MONEY_KEYS):
        raise LifecycleError("invalid-phase-resource-measurement", "phase resources must not use monetary fields")
    tokens = _tokens(phase.get("tokens", {}))
    resources = _resources(phase.get("resources", {}))
    return {
        "entryId": f"phase-{index + 1}",
        "phaseId": _required_string(phase.get("phaseId"), label="phaseId"),
        "phaseKind": _required_string(phase.get("phaseKind"), label="phaseKind"),
        "taskId": _optional_string(phase.get("taskId")),
        "operationId": _optional_string(phase.get("operationId")),
        "tokens": tokens,
        "steps": _non_negative_int(phase.get("steps"), label="steps"),
        "resources": resources,
        "durationMs": _non_negative_int(phase.get("durationMs"), label="durationMs"),
        "receiptDigests": _digest_list(phase.get("receiptDigests", [])),
    }


def _validate_phase_entry(index: int, phase: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(phase, dict):
        blockers.append({"code": "phase-resource-entry-invalid", "index": index})
        return
    for key in MONEY_KEYS:
        if key in phase:
            blockers.append({"code": "phase-resource-monetary-field", "index": index, "field": key})
    for key in ("entryId", "phaseId", "phaseKind"):
        if not isinstance(phase.get(key), str) or not phase[key]:
            blockers.append({"code": "phase-resource-field-missing", "index": index, "field": key})
    tokens = phase.get("tokens")
    if not isinstance(tokens, dict):
        blockers.append({"code": "phase-resource-tokens-invalid", "index": index})
    else:
        for key in TOKEN_KEYS:
            if not isinstance(tokens.get(key), int) or isinstance(tokens.get(key), bool) or tokens[key] < 0:
                blockers.append({"code": "phase-resource-token-invalid", "index": index, "field": key})
    resources = phase.get("resources")
    if not isinstance(resources, dict):
        blockers.append({"code": "phase-resource-resources-invalid", "index": index})
    else:
        for key, value in resources.items():
            if key not in RESOURCE_KEYS:
                blockers.append({"code": "phase-resource-resource-unsupported", "index": index, "field": key})
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                blockers.append({"code": "phase-resource-resource-invalid", "index": index, "field": key})
    for key in ("steps", "durationMs"):
        if not isinstance(phase.get(key), int) or isinstance(phase.get(key), bool) or phase[key] < 0:
            blockers.append({"code": "phase-resource-counter-invalid", "index": index, "field": key})
    _check_digest_list(phase.get("receiptDigests", []), "phase-resource-receipt-digests-invalid", blockers)


def _tokens(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise LifecycleError("invalid-phase-resource-measurement", "tokens must be an object")
    result = {key: _non_negative_int(value.get(key, 0), label=f"tokens.{key}") for key in TOKEN_KEYS}
    if result["total"] == 0:
        result["total"] = result["input"] + result["output"]
    return result


def _resources(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise LifecycleError("invalid-phase-resource-measurement", "resources must be an object")
    result: dict[str, int] = {}
    for key, item in value.items():
        if key not in RESOURCE_KEYS:
            raise LifecycleError("invalid-phase-resource-measurement", "resource field is unsupported", {"field": key})
        result[key] = _non_negative_int(item, label=f"resources.{key}")
    return dict(sorted(result.items()))


def _required_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError("invalid-phase-resource-measurement", f"{label} is required")
    return value


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _non_negative_int(value: Any, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LifecycleError("invalid-phase-resource-measurement", f"{label} must be a non-negative integer")
    return value


def _digest_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and len(item) == 64 for item in value):
        raise LifecycleError("invalid-phase-resource-measurement", "receiptDigests must be a list of digests")
    return list(value)


def _check_digest_list(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) and len(item) == 64 for item in value):
        blockers.append({"code": code})


def _check_object_list(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        blockers.append({"code": code})

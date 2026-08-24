"""Contracts for measured, provider-neutral structured result capabilities."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.canonical import canonical_digest
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.schema_builders import open_object_schema

STRUCTURED_RESULT_CAPABILITY_SCHEMA = "agent-structured-result-capability.v1"
STRUCTURED_RESULT_SELECTION_SCHEMA = "agent-structured-result-selection.v1"
STRUCTURED_RESULT_OUTPUT_CONTRACT_SCHEMA = "agent-structured-result-output-contract.v1"
STRUCTURED_RESULT_VALIDATION_SCHEMA = "agent-structured-result-validation.v1"

STRUCTURED_RESULT_MODES = ("SCHEMA_ENFORCED", "JSON_ENFORCED", "VALIDATED_TEXT", "UNAVAILABLE")
STRUCTURED_RESULT_QUALIFICATION_STATUSES = ("QUALIFIED", "NO_RECOMMENDATION", "UNAVAILABLE")
MAX_STRUCTURED_RESULT_REPAIR_ATTEMPTS = 2

_MODE_RANK = {
    "SCHEMA_ENFORCED": 3,
    "JSON_ENFORCED": 2,
    "VALIDATED_TEXT": 1,
    "UNAVAILABLE": 0,
}
_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}

STRUCTURED_RESULT_SCHEMAS: dict[str, dict[str, Any]] = {
    STRUCTURED_RESULT_CAPABILITY_SCHEMA: open_object_schema(
        STRUCTURED_RESULT_CAPABILITY_SCHEMA,
        required=[
            "schemaVersion",
            "operationId",
            "adapterId",
            "descriptorDigest",
            "hostVersion",
            "modelClass",
            "capabilityLevel",
            "qualificationStatus",
            "capabilityManifestDigest",
            "evidenceDigest",
            "measuredRunCount",
            "productionPromotionClaimed",
            "capabilityDigest",
        ],
        properties={
            "operationId": {"type": "string", "minLength": 1},
            "adapterId": {"type": "string", "minLength": 1},
            "descriptorDigest": _DIGEST,
            "hostVersion": {"type": "string", "minLength": 1},
            "modelClass": {"type": "string", "minLength": 1},
            "capabilityLevel": {"enum": list(STRUCTURED_RESULT_MODES)},
            "qualificationStatus": {"enum": list(STRUCTURED_RESULT_QUALIFICATION_STATUSES)},
            "capabilityManifestDigest": _DIGEST,
            "evidenceDigest": _DIGEST,
            "measuredRunCount": {"type": "integer", "minimum": 0},
            "productionPromotionClaimed": {"const": False},
            "capabilityDigest": _DIGEST,
        },
    ),
    STRUCTURED_RESULT_SELECTION_SCHEMA: open_object_schema(
        STRUCTURED_RESULT_SELECTION_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "operationId",
            "requiredMode",
            "selectedMode",
            "adapterId",
            "descriptorDigest",
            "hostVersion",
            "modelClass",
            "capabilityManifestDigest",
            "requiredSchemaDigest",
            "candidateModes",
            "selectionReason",
            "lineage",
            "productionPromotionClaimed",
            "selectionDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "operationId": {"type": "string", "minLength": 1},
            "requiredMode": {"enum": list(STRUCTURED_RESULT_MODES)},
            "selectedMode": {"enum": list(STRUCTURED_RESULT_MODES)},
            "adapterId": {"type": "string", "minLength": 1},
            "descriptorDigest": _DIGEST,
            "hostVersion": {"type": "string", "minLength": 1},
            "modelClass": {"type": "string", "minLength": 1},
            "capabilityManifestDigest": _DIGEST,
            "requiredSchemaDigest": _DIGEST,
            "candidateModes": {"type": "array", "items": {"enum": list(STRUCTURED_RESULT_MODES)}},
            "selectedCapabilityDigest": {"type": ["string", "null"], "minLength": 0, "maxLength": 64},
            "selectionReason": {"type": "string", "minLength": 1},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "lineage": {"type": ["object", "null"]},
            "productionPromotionClaimed": {"const": False},
            "selectionDigest": _DIGEST,
        },
    ),
    STRUCTURED_RESULT_OUTPUT_CONTRACT_SCHEMA: open_object_schema(
        STRUCTURED_RESULT_OUTPUT_CONTRACT_SCHEMA,
        required=[
            "schemaVersion",
            "operationId",
            "requiredMode",
            "resultSchemaVersion",
            "requiredFields",
            "selectionDigest",
            "schemaDigest",
            "maxRepairAttempts",
            "productionPromotionClaimed",
            "contractDigest",
        ],
        properties={
            "operationId": {"type": "string", "minLength": 1},
            "requiredMode": {"enum": list(STRUCTURED_RESULT_MODES)},
            "resultSchemaVersion": {"type": "string", "minLength": 1},
            "requiredFields": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "selectionDigest": _DIGEST,
            "schemaDigest": _DIGEST,
            "lineage": {"type": ["object", "null"]},
            "maxRepairAttempts": {
                "type": "integer",
                "minimum": 0,
                "maximum": MAX_STRUCTURED_RESULT_REPAIR_ATTEMPTS,
            },
            "forbiddenFields": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "productionPromotionClaimed": {"const": False},
            "contractDigest": _DIGEST,
        },
    ),
    STRUCTURED_RESULT_VALIDATION_SCHEMA: open_object_schema(
        STRUCTURED_RESULT_VALIDATION_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "operationId",
            "selectionDigest",
            "attempt",
            "repairAttempts",
            "maxRepairAttempts",
            "outputDigest",
            "errors",
            "productionPromotionClaimed",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "operationId": {"type": "string", "minLength": 1},
            "selectionDigest": _DIGEST,
            "attempt": {"type": "integer", "minimum": 1},
            "repairAttempts": {
                "type": "integer",
                "minimum": 0,
                "maximum": MAX_STRUCTURED_RESULT_REPAIR_ATTEMPTS,
            },
            "maxRepairAttempts": {
                "type": "integer",
                "minimum": 0,
                "maximum": MAX_STRUCTURED_RESULT_REPAIR_ATTEMPTS,
            },
            "outputDigest": _DIGEST,
            "errors": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
}


def build_structured_result_capability(
    *,
    operation_id: str,
    adapter_id: str,
    descriptor_digest: str,
    host_version: str,
    model_class: str,
    capability_level: str,
    qualification_status: str,
    capability_manifest_digest: str,
    evidence_digest: str,
    measured_run_count: int,
) -> dict[str, Any]:
    """Build one operation-bound capability claim from measured evidence."""

    body = {
        "schemaVersion": STRUCTURED_RESULT_CAPABILITY_SCHEMA,
        "operationId": operation_id,
        "adapterId": adapter_id,
        "descriptorDigest": descriptor_digest,
        "hostVersion": host_version,
        "modelClass": model_class,
        "capabilityLevel": capability_level,
        "qualificationStatus": qualification_status,
        "capabilityManifestDigest": capability_manifest_digest,
        "evidenceDigest": evidence_digest,
        "measuredRunCount": measured_run_count,
        "productionPromotionClaimed": False,
    }
    result = {**body, "capabilityDigest": canonical_digest(body)}
    _raise_if_invalid(validate_structured_result_capability(result))
    return result


def validate_structured_result_capability(
    capability: dict[str, Any],
    *,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one measured capability and its optional exact bindings."""

    blockers: list[dict[str, Any]] = []
    for field in (
        "operationId",
        "adapterId",
        "descriptorDigest",
        "hostVersion",
        "modelClass",
        "capabilityLevel",
        "qualificationStatus",
        "capabilityManifestDigest",
        "evidenceDigest",
    ):
        if field not in capability:
            blockers.append({"code": "structured-result-capability-field-missing", "field": field})
    if capability.get("capabilityLevel") not in STRUCTURED_RESULT_MODES:
        blockers.append({"code": "structured-result-capability-level-invalid"})
    if capability.get("qualificationStatus") not in STRUCTURED_RESULT_QUALIFICATION_STATUSES:
        blockers.append({"code": "structured-result-qualification-status-invalid"})
    if capability.get("qualificationStatus") == "QUALIFIED":
        if capability.get("capabilityLevel") == "UNAVAILABLE":
            blockers.append({"code": "structured-result-qualified-unavailable"})
        if not isinstance(capability.get("measuredRunCount"), int) or capability.get("measuredRunCount", 0) < 1:
            blockers.append({"code": "structured-result-measurement-missing"})
    elif capability.get("capabilityLevel") != "UNAVAILABLE":
        blockers.append({"code": "structured-result-unqualified-level"})
    if capability.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "structured-result-production-claim"})
    for field in ("descriptorDigest", "capabilityManifestDigest", "evidenceDigest"):
        if not _is_digest(capability.get(field)):
            blockers.append({"code": "structured-result-capability-digest-invalid", "field": field})
    if expected:
        for field in (
            "operationId",
            "adapterId",
            "descriptorDigest",
            "hostVersion",
            "modelClass",
            "capabilityManifestDigest",
        ):
            if field in expected and capability.get(field) != expected[field]:
                blockers.append({"code": "structured-result-capability-lineage-mismatch", "field": field})
    expected_digest = canonical_digest({key: value for key, value in capability.items() if key != "capabilityDigest"})
    if capability.get("capabilityDigest") != expected_digest:
        blockers.append({"code": "structured-result-capability-digest-mismatch"})
    body = {
        "schemaVersion": "agent-structured-result-capability-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "operationId": capability.get("operationId"),
        "capabilityDigest": capability.get("capabilityDigest"),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def select_structured_result_mode(
    capabilities: list[dict[str, Any]],
    *,
    operation_id: str,
    required_mode: str,
    adapter_id: str,
    descriptor_digest: str,
    host_version: str,
    model_class: str,
    capability_manifest_digest: str,
    required_schema_digest: str,
    lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select the strongest exact-bound capability without a silent downgrade."""

    blockers: list[dict[str, Any]] = []
    if required_mode not in STRUCTURED_RESULT_MODES or required_mode == "UNAVAILABLE":
        blockers.append({"code": "structured-result-required-mode-invalid"})
    expected = {
        "operationId": operation_id,
        "adapterId": adapter_id,
        "descriptorDigest": descriptor_digest,
        "hostVersion": host_version,
        "modelClass": model_class,
        "capabilityManifestDigest": capability_manifest_digest,
    }
    valid: list[dict[str, Any]] = []
    candidate_modes: list[str] = []
    for capability in capabilities:
        validation = validate_structured_result_capability(capability, expected=expected)
        mode = capability.get("capabilityLevel")
        if mode in STRUCTURED_RESULT_MODES:
            candidate_modes.append(mode)
        if validation["status"] == "PASS" and capability.get("qualificationStatus") == "QUALIFIED":
            valid.append(capability)
    if not blockers:
        valid = [item for item in valid if _MODE_RANK[item["capabilityLevel"]] >= _MODE_RANK[required_mode]]
    selected = max(valid, key=lambda item: _MODE_RANK[item["capabilityLevel"]], default=None)
    if selected is None and not blockers:
        blockers.append({"code": "structured-result-required-capability-unavailable"})
    body = {
        "schemaVersion": STRUCTURED_RESULT_SELECTION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "operationId": operation_id,
        "requiredMode": required_mode if required_mode in STRUCTURED_RESULT_MODES else "UNAVAILABLE",
        "selectedMode": selected["capabilityLevel"] if selected else "UNAVAILABLE",
        "adapterId": adapter_id,
        "descriptorDigest": descriptor_digest,
        "hostVersion": host_version,
        "modelClass": model_class,
        "capabilityManifestDigest": capability_manifest_digest,
        "requiredSchemaDigest": required_schema_digest,
        "candidateModes": sorted(set(candidate_modes), key=lambda item: (-_MODE_RANK[item], item)),
        "selectedCapabilityDigest": selected.get("capabilityDigest") if selected else None,
        "selectionReason": "strongest-qualified-mode" if selected else "required-capability-unavailable",
        "blockers": blockers,
        "lineage": dict(lineage) if isinstance(lineage, dict) else None,
        "productionPromotionClaimed": False,
    }
    return {**body, "selectionDigest": canonical_digest(body)}


def validate_structured_result_selection(
    selection: dict[str, Any],
    *,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate selection lineage and reject a weaker-than-required mode."""

    blockers: list[dict[str, Any]] = []
    required = selection.get("requiredMode")
    selected = selection.get("selectedMode")
    if required not in STRUCTURED_RESULT_MODES or selected not in STRUCTURED_RESULT_MODES:
        blockers.append({"code": "structured-result-selection-mode-invalid"})
    elif selection.get("status") == "PASS" and _MODE_RANK[selected] < _MODE_RANK[required]:
        blockers.append({"code": "structured-result-selection-downgrade"})
    if selection.get("status") == "PASS" and selected == "UNAVAILABLE":
        blockers.append({"code": "structured-result-selection-unavailable"})
    if selection.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "structured-result-selection-production-claim"})
    if expected:
        for field in (
            "operationId",
            "adapterId",
            "descriptorDigest",
            "hostVersion",
            "modelClass",
            "capabilityManifestDigest",
            "requiredSchemaDigest",
        ):
            if field in expected and selection.get(field) != expected[field]:
                blockers.append({"code": "structured-result-selection-lineage-mismatch", "field": field})
    expected_digest = canonical_digest({key: value for key, value in selection.items() if key != "selectionDigest"})
    if selection.get("selectionDigest") != expected_digest:
        blockers.append({"code": "structured-result-selection-digest-mismatch"})
    body = {
        "schemaVersion": "agent-structured-result-selection-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "selectionDigest": selection.get("selectionDigest"),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _raise_if_invalid(validation: dict[str, Any]) -> None:
    if validation["status"] != "PASS":
        raise LifecycleError("structured-result-contract-invalid", "structured-result contract is invalid", validation)


__all__ = [
    "MAX_STRUCTURED_RESULT_REPAIR_ATTEMPTS",
    "STRUCTURED_RESULT_CAPABILITY_SCHEMA",
    "STRUCTURED_RESULT_MODES",
    "STRUCTURED_RESULT_OUTPUT_CONTRACT_SCHEMA",
    "STRUCTURED_RESULT_QUALIFICATION_STATUSES",
    "STRUCTURED_RESULT_SCHEMAS",
    "STRUCTURED_RESULT_SELECTION_SCHEMA",
    "STRUCTURED_RESULT_VALIDATION_SCHEMA",
    "build_structured_result_capability",
    "select_structured_result_mode",
    "validate_structured_result_capability",
    "validate_structured_result_selection",
]

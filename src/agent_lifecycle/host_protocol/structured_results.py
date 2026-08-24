"""Provider-neutral structured-result selection and output validation."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.canonical import canonical_digest
from agent_lifecycle.contracts.structured_result_schemas import (
    MAX_STRUCTURED_RESULT_REPAIR_ATTEMPTS,
    STRUCTURED_RESULT_OUTPUT_CONTRACT_SCHEMA,
    STRUCTURED_RESULT_VALIDATION_SCHEMA,
    select_structured_result_mode,
    validate_structured_result_selection,
)


def select_result_mode(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Select a qualified result mode without introducing host authority."""

    return select_structured_result_mode(*args, **kwargs)


def validate_structured_result_output(
    output: dict[str, Any],
    contract: dict[str, Any],
    selection: dict[str, Any],
    *,
    attempt: int,
    repair_attempts: int,
) -> dict[str, Any]:
    """Validate one result envelope against a selected, frozen contract."""

    errors: list[dict[str, Any]] = []
    selection_validation = validate_structured_result_selection(selection)
    if selection_validation["status"] != "PASS":
        errors.append({"code": "structured-result-selection-invalid"})
    if contract.get("schemaVersion") != STRUCTURED_RESULT_OUTPUT_CONTRACT_SCHEMA:
        errors.append({"code": "structured-result-output-contract-schema"})
    if contract.get("selectionDigest") != selection.get("selectionDigest"):
        errors.append({"code": "structured-result-selection-digest-mismatch"})
    if output.get("schemaVersion") != contract.get("resultSchemaVersion"):
        errors.append({"code": "structured-result-output-schema"})
    if output.get("operationId") != contract.get("operationId"):
        errors.append({"code": "structured-result-output-operation-mismatch"})
    if output.get("selectionDigest") != selection.get("selectionDigest"):
        errors.append({"code": "structured-result-output-selection-mismatch"})
    for field in contract.get("requiredFields", []):
        if not isinstance(field, str) or not field:
            errors.append({"code": "structured-result-contract-field-invalid"})
        elif field not in output:
            errors.append({"code": "structured-result-output-field-missing", "field": field})
    for field in contract.get("forbiddenFields", []):
        if isinstance(field, str) and field in output:
            errors.append({"code": "structured-result-output-forbidden-field", "field": field})
    max_repairs = contract.get("maxRepairAttempts", MAX_STRUCTURED_RESULT_REPAIR_ATTEMPTS)
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        errors.append({"code": "structured-result-attempt-invalid"})
    if (
        not isinstance(repair_attempts, int)
        or isinstance(repair_attempts, bool)
        or repair_attempts < 0
        or not isinstance(max_repairs, int)
        or max_repairs < 0
        or max_repairs > MAX_STRUCTURED_RESULT_REPAIR_ATTEMPTS
        or repair_attempts > max_repairs
    ):
        errors.append({"code": "structured-result-repair-budget-exceeded"})
    if output.get("productionPromotionClaimed") is not False:
        errors.append({"code": "structured-result-output-production-claim"})
    body = {
        "schemaVersion": STRUCTURED_RESULT_VALIDATION_SCHEMA,
        "status": "PASS" if not errors else "FAIL",
        "operationId": contract.get("operationId"),
        "selectionDigest": selection.get("selectionDigest"),
        "attempt": attempt,
        "repairAttempts": repair_attempts,
        "maxRepairAttempts": max_repairs,
        "outputDigest": canonical_digest(output),
        "errors": errors,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


__all__ = ["select_result_mode", "validate_structured_result_output"]

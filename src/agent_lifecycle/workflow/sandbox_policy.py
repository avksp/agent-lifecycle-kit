"""Fail-closed sandbox evidence policy for high-risk workflow tasks."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.workflow.sandbox_receipts import SANDBOX_STATUSES, validate_sandbox_receipt

SANDBOX_REQUIREMENT_SCHEMA = "agent-sandbox-requirement.v1"
SANDBOX_REQUIREMENT_VALIDATION_SCHEMA = "agent-sandbox-requirement-validation.v1"
DEFAULT_HIGH_RISK_CLASSES = (
    "S2",
    "security",
    "release",
    "external-environment",
    "architecture",
    "performance",
)
DEFAULT_SANDBOX_REQUIREMENT_POLICY = {
    "schemaVersion": SANDBOX_REQUIREMENT_SCHEMA,
    "mode": "required",
    "requireForHighRisk": True,
    "highRiskClasses": list(DEFAULT_HIGH_RISK_CLASSES),
    "acceptedSandboxStatuses": ["PASS"],
    "failClosed": True,
    "productionPromotionClaimed": False,
}


def build_sandbox_requirement_policy(
    *,
    mode: str = "required",
    require_for_high_risk: bool = True,
    high_risk_classes: list[str] | None = None,
    accepted_sandbox_statuses: list[str] | None = None,
) -> dict[str, Any]:
    """Build the default sandbox evidence policy used by workflow gates."""

    body = {
        "schemaVersion": SANDBOX_REQUIREMENT_SCHEMA,
        "mode": mode,
        "requireForHighRisk": require_for_high_risk,
        "highRiskClasses": list(high_risk_classes or DEFAULT_HIGH_RISK_CLASSES),
        "acceptedSandboxStatuses": list(accepted_sandbox_statuses or ["PASS"]),
        "failClosed": True,
        "productionPromotionClaimed": False,
    }
    _validate_policy_shape(body)
    return {**body, "policyDigest": canonical_digest(body)}


def sandbox_evidence_required(task: dict[str, Any], policy: dict[str, Any] | None = None) -> bool:
    """Return whether task execution requires a sandbox receipt."""

    policy = _policy(policy)
    if policy["mode"] == "off":
        return False
    task_policy = _task_sandbox_policy(task)
    if task_policy.get("required") is True or task.get("sandboxRequired") is True:
        return True
    if task_policy.get("required") is False or task.get("sandboxRequired") is False:
        return False
    return policy["mode"] == "required" and policy["requireForHighRisk"] is True and _is_high_risk_task(task, policy)


def validate_task_sandbox_evidence(
    task: dict[str, Any],
    *,
    receipt: dict[str, Any] | None,
    policy: dict[str, Any] | None = None,
    expected_lineage: dict[str, Any] | None = None,
    attempt: int | None = None,
) -> dict[str, Any]:
    """Validate task sandbox evidence and fail closed when the policy requires it."""

    policy = _policy(policy)
    required = sandbox_evidence_required(task, policy)
    blockers: list[dict[str, Any]] = []
    receipt_validation: dict[str, Any] | None = None
    task_id = task.get("id") if isinstance(task.get("id"), str) else None
    accepted_sandbox_statuses = _accepted_sandbox_statuses(task, policy, blockers)
    if receipt is None:
        if required:
            blockers.append({"code": "sandbox-receipt-required", "taskId": task_id})
    else:
        receipt_validation = validate_sandbox_receipt(
            receipt,
            expected_lineage=expected_lineage,
            task_id=task_id,
            attempt=attempt,
        )
        if receipt_validation["status"] != "PASS":
            blockers.append({"code": "sandbox-receipt-invalid", "validation": receipt_validation})
        if required and receipt_validation.get("sandboxStatus") not in accepted_sandbox_statuses:
            blockers.append(
                {
                    "code": "sandbox-receipt-not-accepted",
                    "acceptedSandboxStatuses": accepted_sandbox_statuses,
                    "sandboxStatus": receipt_validation.get("sandboxStatus"),
                }
            )
    body = {
        "schemaVersion": SANDBOX_REQUIREMENT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "required": required,
        "taskId": task_id,
        "sandboxStatus": receipt_validation.get("sandboxStatus") if receipt_validation else None,
        "acceptedSandboxStatuses": accepted_sandbox_statuses,
        "blockers": blockers,
        "policyDigest": policy["policyDigest"],
        "receiptDigest": receipt_validation.get("receiptDigest") if receipt_validation else None,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_task_sandbox_evidence_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError(
            "sandbox-policy-validation-failed", "sandbox policy validation failed", {"validation": validation}
        )
    return validation


def _policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    if policy is None:
        return build_sandbox_requirement_policy()
    _validate_policy_shape(policy)
    if "policyDigest" in policy:
        expected = canonical_digest({key: value for key, value in policy.items() if key != "policyDigest"})
        if policy["policyDigest"] != expected:
            raise LifecycleError("invalid-sandbox-policy", "sandbox policyDigest does not match policy")
        return dict(policy)
    return {**dict(policy), "policyDigest": canonical_digest(policy)}


def _validate_policy_shape(policy: dict[str, Any]) -> None:
    if not isinstance(policy, dict):
        raise LifecycleError("invalid-sandbox-policy", "sandbox policy must be an object")
    if policy.get("schemaVersion") != SANDBOX_REQUIREMENT_SCHEMA:
        raise LifecycleError("invalid-sandbox-policy", "sandbox policy schemaVersion is unsupported")
    if policy.get("mode") not in {"off", "advisory", "required"}:
        raise LifecycleError("invalid-sandbox-policy", "sandbox policy mode is unsupported")
    if not isinstance(policy.get("requireForHighRisk"), bool):
        raise LifecycleError("invalid-sandbox-policy", "requireForHighRisk must be boolean")
    high_risk = policy.get("highRiskClasses")
    if not isinstance(high_risk, list) or not all(isinstance(item, str) and item for item in high_risk):
        raise LifecycleError("invalid-sandbox-policy", "highRiskClasses must be a string array")
    accepted = policy.get("acceptedSandboxStatuses")
    if not isinstance(accepted, list) or not accepted or not all(isinstance(item, str) and item for item in accepted):
        raise LifecycleError("invalid-sandbox-policy", "acceptedSandboxStatuses must be a non-empty string array")
    if policy.get("failClosed") is not True:
        raise LifecycleError("invalid-sandbox-policy", "sandbox policy must fail closed")
    if policy.get("productionPromotionClaimed") is not False:
        raise LifecycleError("invalid-sandbox-policy", "sandbox policy must not claim production promotion")


def _task_sandbox_policy(task: dict[str, Any]) -> dict[str, Any]:
    execution_policy = task.get("executionPolicy")
    if not isinstance(execution_policy, dict):
        return {}
    sandbox = execution_policy.get("sandbox")
    return sandbox if isinstance(sandbox, dict) else {}


def _accepted_sandbox_statuses(
    task: dict[str, Any],
    policy: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> list[str]:
    task_policy = _task_sandbox_policy(task)
    value = task_policy.get("acceptedSandboxStatuses")
    if value is None:
        return list(policy["acceptedSandboxStatuses"])
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        blockers.append({"code": "sandbox-task-accepted-statuses-invalid", "value": value})
        return list(policy["acceptedSandboxStatuses"])
    unknown = sorted(set(value).difference(SANDBOX_STATUSES))
    if unknown:
        blockers.append({"code": "sandbox-task-accepted-statuses-unknown", "statuses": unknown})
        return list(policy["acceptedSandboxStatuses"])
    return list(value)


def _is_high_risk_task(task: dict[str, Any], policy: dict[str, Any]) -> bool:
    high_risk = {str(item) for item in policy.get("highRiskClasses", [])}
    return any(value in high_risk for value in _task_classifiers(task))


def _task_classifiers(task: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for key in ("tier", "risk", "riskLevel", "taskType", "qualityProfile"):
        _add_value(values, task.get(key))
    specification = task.get("specification")
    if isinstance(specification, dict):
        _add_value(values, specification.get("tier"))
        _add_value(values, specification.get("risk"))
        _add_value(values, specification.get("riskLevel"))
    risk_flags = task.get("riskFlags")
    if isinstance(risk_flags, dict):
        values.update(str(key) for key, enabled in risk_flags.items() if enabled)
    elif isinstance(risk_flags, list):
        values.update(str(item) for item in risk_flags if isinstance(item, str) and item)
    labels = task.get("labels")
    if isinstance(labels, list):
        values.update(str(item) for item in labels if isinstance(item, str) and item)
    return values


def _add_value(values: set[str], value: Any) -> None:
    if isinstance(value, str) and value:
        values.add(value)

"""Closed ALK A5-limited records. Validation grants no host protection or dispatch.

Release 2.16 has no strong-positive A5 variant: every accepted v1 policy and
context explicitly records that continuous host input protection is unproven.
"""

from __future__ import annotations

import re
from typing import Any, NoReturn
from typing import cast as _validated_cast

from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest, load_json_object
from agent_lifecycle.contracts.errors import LifecycleError

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_PROTECTION = {"NONE", "STRONG_A5"}
_ENTRY = {
    "ALK_TASK_START",
    "ALK_MANAGED_TASK_LAUNCH",
    "ALK_PLANNING_TASK_LAUNCH",
    "ALK_PLANNING_QUALIFICATION",
    "EXTERNAL_ALREADY_RUNNING",
}
_OPERATIONS = {
    "MANAGED_TASK": "FROZEN_WORKFLOW_TASK",
    "PLANNING_TASK": "EXPLICIT_PLANNING_CALL",
    "PLANNING_QUALIFICATION": "FIXED_QUALIFICATION_CALL",
    "VERSION_PREFLIGHT": "VERSION_ONLY_PREFLIGHT",
}
_ADAPTERS = {
    "codex",
    "claude",
    "opencode",
    "grok-build",
    "gemini-cli",
    "pi",
    "hermes",
    "qwen-code",
    "kimi-code",
    "cursor",
    "goose",
    "openinterpreter",
}
_LIMITS = {
    "policy": 8192,
    "decision": 8192,
    "invocationContext": 16384,
    "adoptionBinding": 8192,
}


def _fail(detail: str) -> NoReturn:
    raise LifecycleError("a5-context-invalid", detail)


def _object(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        _fail(f"{label} has missing or unknown fields")
    return value


def _bounded(value: dict[str, Any], limit: int) -> None:
    try:
        size = len(canonical_bytes(value))
    except (TypeError, OverflowError) as exc:
        raise LifecycleError("a5-context-invalid", "A5 record cannot be canonicalized") from exc
    if size > limit:
        _fail("A5 record exceeds its byte limit")


def _text(value: Any, label: str, maximum: int = 256) -> str:
    if type(value) is not str or not 1 <= len(value) <= maximum:
        _fail(f"{label} must be a bounded string")
    return value


def _digest(value: Any, label: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not str or not _HEX.fullmatch(value):
        _fail(f"{label} must be a SHA-256 digest")
    return value


def _enum(value: Any, allowed: set[str], label: str) -> str:
    if type(value) is not str or value not in allowed:
        _fail(f"{label} has an unsupported value")
    return value


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        _fail(f"{label} must be a positive integer")
    return value


def _self_digest(record: dict[str, Any], field: str) -> None:
    _digest(record[field], field)
    if record[field] != canonical_digest({key: value for key, value in record.items() if key != field}):
        _fail(f"{field} does not bind its record")


def validate_a5_subject(value: Any) -> dict[str, Any]:
    fields = {
        "runId",
        "packageId",
        "taskId",
        "targetAttempt",
        "operationId",
        "stateRevision",
        "planDigest",
        "sourceRevision",
    }
    subject = _object(value, fields, "A5 subject")
    for field in ("runId", "packageId", "taskId", "operationId", "sourceRevision"):
        _text(subject[field], field)
    for field in ("targetAttempt", "stateRevision"):
        _positive_int(subject[field], field)
    _digest(subject["planDigest"], "planDigest")
    return subject


def validate_a5_policy(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion",
        "mode",
        "adapterId",
        "expectationId",
        "targetVersion",
        "entrySurface",
        "frozenTaskRequirement",
        "policyDigest",
        "boundaryRecordDigest",
        "strongAdmissionSupported",
    }
    policy = _object(value, fields, "A5 policy")
    _bounded(policy, _LIMITS["policy"])
    if policy["schemaVersion"] != "agent-a5-limited-policy.v1" or policy["mode"] != "A5_LIMITED":
        _fail("Unsupported A5 policy version or mode")
    for field in ("adapterId", "expectationId", "targetVersion"):
        _text(policy[field], field)
    _enum(policy["entrySurface"], _ENTRY, "entrySurface")
    _enum(policy["frozenTaskRequirement"], _PROTECTION, "frozenTaskRequirement")
    if policy["strongAdmissionSupported"] is not False:
        _fail("Strong-positive A5 is unavailable in v1")
    _digest(policy["boundaryRecordDigest"], "boundaryRecordDigest")
    _self_digest(policy, "policyDigest")
    return policy


def validate_a5_request(value: Any) -> dict[str, Any]:
    fields = {"schemaVersion", "subject", "requestedProtection", "expectedPolicyDigest", "expectedBoundaryRecordDigest"}
    request = _object(value, fields, "A5 request")
    _bounded(request, _LIMITS["policy"])
    if request["schemaVersion"] != "agent-a5-limited-request.v1":
        _fail("Unsupported A5 request version")
    validate_a5_subject(request["subject"])
    _enum(request["requestedProtection"], _PROTECTION, "requestedProtection")
    _digest(request["expectedPolicyDigest"], "expectedPolicyDigest")
    _digest(request["expectedBoundaryRecordDigest"], "expectedBoundaryRecordDigest")
    return request


def validate_a5_decision(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion",
        "subject",
        "policyDigest",
        "boundaryRecordDigest",
        "requestDigest",
        "effectiveRequirement",
        "disposition",
        "reason",
        "strongProtectionGranted",
        "scope",
        "decisionDigest",
    }
    decision = _object(value, fields, "A5 decision")
    _bounded(decision, _LIMITS["decision"])
    if decision["schemaVersion"] != "agent-a5-limited-decision.v1":
        _fail("Unsupported A5 decision version")
    validate_a5_subject(decision["subject"])
    for field in ("policyDigest", "boundaryRecordDigest", "requestDigest"):
        _digest(decision[field], field)
    _enum(decision["effectiveRequirement"], _PROTECTION, "effectiveRequirement")
    pairs = {
        ("DENY_STRONG", "STRONG_UNPROVEN"),
        ("DENY_CONTEXT", "CONTEXT_INVALID"),
        ("ORDINARY_NO_A5", "NO_STRONG_REQUIREMENT"),
    }
    if (
        type(decision["disposition"]) is not str
        or type(decision["reason"]) is not str
        or (decision["disposition"], decision["reason"]) not in pairs
    ):
        _fail("A5 decision disposition and reason disagree")
    if decision["disposition"] == "DENY_STRONG" and decision["effectiveRequirement"] != "STRONG_A5":
        _fail("Strong denial requires a strong effective requirement")
    if decision["disposition"] == "ORDINARY_NO_A5" and decision["effectiveRequirement"] != "NONE":
        _fail("Ordinary classification requires no strong requirement")
    if decision["strongProtectionGranted"] is not False or decision["scope"] != "ALK_ADMISSION_CLASSIFICATION_ONLY":
        _fail("A5 decision cannot claim host protection or authority")
    _self_digest(decision, "decisionDigest")
    return decision


def validate_a5_decision_binding(decision: Any, policy: Any, request: Any) -> dict[str, Any]:
    """Check exact records before a consumer uses a negative/ordinary classification."""
    result = validate_a5_decision(decision)
    selected_policy = validate_a5_policy(policy)
    selected_request = validate_a5_request(request)
    if (
        result["subject"] != selected_request["subject"]
        or result["policyDigest"] != selected_policy["policyDigest"]
        or result["boundaryRecordDigest"] != selected_policy["boundaryRecordDigest"]
        or selected_request["expectedPolicyDigest"] != selected_policy["policyDigest"]
        or selected_request["expectedBoundaryRecordDigest"] != selected_policy["boundaryRecordDigest"]
        or result["requestDigest"] != canonical_digest(selected_request)
    ):
        _fail("A5 decision is not bound to the selected policy and request")
    effective = (
        "STRONG_A5"
        if "STRONG_A5" in (selected_policy["frozenTaskRequirement"], selected_request["requestedProtection"])
        else "NONE"
    )
    if result["effectiveRequirement"] != effective:
        _fail("A5 effective requirement was lowered or changed")
    if result["disposition"] == "ORDINARY_NO_A5" and effective != "NONE":
        _fail("Strong A5 cannot become ordinary")
    if result["disposition"] == "DENY_STRONG" and effective != "STRONG_A5":
        _fail("Strong denial has no strong requirement")
    return result


def validate_a5_plan_policy(value: Any) -> dict[str, Any]:
    policy = _object(value, {"schemaVersion", "mode", "defaultRequirement", "contractDigest"}, "A5 plan policy")
    if policy["schemaVersion"] != "agent-a5-plan-policy.v1" or policy["mode"] != "A5_LIMITED":
        _fail("Unsupported A5 plan policy")
    _enum(policy["defaultRequirement"], _PROTECTION, "defaultRequirement")
    _digest(policy["contractDigest"], "contractDigest")
    return policy


def validate_a5_invocation_request(value: Any) -> dict[str, Any]:
    request = _object(value, {"schemaVersion", "requestedProtection"}, "A5 invocation request")
    if request["schemaVersion"] != "agent-a5-invocation-request.v1":
        _fail("Unsupported A5 invocation request")
    _enum(request["requestedProtection"], _PROTECTION, "requestedProtection")
    return request


def _artifact_ref(value: Any) -> dict[str, Any]:
    ref = _object(value, {"path", "sha256"}, "A5 artifact reference")
    _text(ref["path"], "path", 4096)
    _digest(ref["sha256"], "sha256")
    return ref


def validate_a5_invocation_context(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion",
        "invocationId",
        "operation",
        "origin",
        "workflowSubject",
        "frozenAuthorityRefs",
        "adapterId",
        "sessionId",
        "requestedProtection",
        "expectedProtection",
        "policyDigest",
        "boundaryRecordDigest",
        "normalizedRequestDigest",
        "taskInputDigest",
        "profileDigest",
        "strongProtectionGranted",
        "contextDigest",
    }
    context = _object(value, fields, "A5 invocation context")
    _bounded(context, _LIMITS["invocationContext"])
    if context["schemaVersion"] != "agent-a5-invocation-context.v1":
        _fail("Unsupported A5 context version")
    for field in ("invocationId", "adapterId"):
        _text(context[field], field)
    operation = _enum(context["operation"], set(_OPERATIONS), "operation")
    if context["origin"] != _OPERATIONS[operation]:
        _fail("A5 operation and origin disagree")
    refs = context["frozenAuthorityRefs"]
    if type(refs) is not list or len(refs) > 3:
        _fail("A5 authority references are malformed")
    for ref in refs:
        _artifact_ref(ref)
    if operation == "MANAGED_TASK":
        validate_a5_subject(context["workflowSubject"])
        if len(refs) != 3:
            _fail("Managed task requires exact frozen authority references")
    elif context["workflowSubject"] is not None or refs:
        _fail("Standalone A5 context cannot borrow workflow authority")
    if context["sessionId"] is not None:
        _text(context["sessionId"], "sessionId")
    for field in ("requestedProtection", "expectedProtection"):
        _enum(context[field], _PROTECTION, field)
    for field in ("policyDigest", "boundaryRecordDigest", "taskInputDigest", "profileDigest"):
        _digest(context[field], field, nullable=True)
    _digest(context["normalizedRequestDigest"], "normalizedRequestDigest")
    if context["strongProtectionGranted"] is not False:
        _fail("Context cannot claim strong host protection")
    _self_digest(context, "contextDigest")
    return context


def validate_a5_adoption_binding(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion",
        "runId",
        "taskId",
        "actualAttempt",
        "originalPlanDigest",
        "currentPlanDigest",
        "originalPolicyDigest",
        "currentPolicyDigest",
        "originalDecisionDigest",
        "compatibilityReceiptDigest",
        "classification",
        "strongProtectionGranted",
        "bindingDigest",
    }
    binding = _object(value, fields, "A5 adoption binding")
    _bounded(binding, _LIMITS["adoptionBinding"])
    if binding["schemaVersion"] != "agent-a5-adoption-binding.v1":
        _fail("Unsupported A5 adoption binding")
    for field in ("runId", "taskId"):
        _text(binding[field], field)
    _positive_int(binding["actualAttempt"], "actualAttempt")
    for field in ("originalPlanDigest", "currentPlanDigest", "compatibilityReceiptDigest"):
        _digest(binding[field], field)
    for field in ("originalPolicyDigest", "currentPolicyDigest", "originalDecisionDigest"):
        _digest(binding[field], field, nullable=True)
    _enum(binding["classification"], {"PRESERVED_ORDINARY_NO_A5", "PRESERVED_LEGACY_NO_A5"}, "classification")
    if binding["classification"] == "PRESERVED_LEGACY_NO_A5" and (
        binding["originalPolicyDigest"] is not None or binding["originalDecisionDigest"] is not None
    ):
        _fail("Legacy adoption cannot invent an original A5 policy or decision")
    if binding["classification"] == "PRESERVED_ORDINARY_NO_A5" and (
        binding["originalPolicyDigest"] is None or binding["originalDecisionDigest"] is None
    ):
        _fail("Ordinary A5 adoption requires its original policy and decision")
    if binding["strongProtectionGranted"] is not False:
        _fail("Adoption cannot create strong A5 protection")
    _self_digest(binding, "bindingDigest")
    return binding


def validate_a5_boundary_registry(value: Any) -> dict[str, Any]:
    registry = _object(value, {"schemaVersion", "records", "registryDigest"}, "A5 boundary registry")
    if registry["schemaVersion"] != "agent-a5-boundary-registry.v1":
        _fail("Unsupported A5 boundary registry")
    records = registry["records"]
    if type(records) is not list or len(records) != 12:
        _fail("A5 registry requires exactly 12 adapter records")
    expected = {
        "adapterId",
        "expectationId",
        "targetVersion",
        "mode",
        "strongAdmissionSupported",
        "strongCapability",
        "sourceDigest",
        "boundaryRecordDigest",
    }
    seen: set[str] = set()
    for item in records:
        record = _object(item, expected, "A5 boundary record")
        for field in ("adapterId", "expectationId", "targetVersion"):
            _text(record[field], field)
        if record["adapterId"] in seen:
            _fail("Duplicate A5 adapter boundary")
        seen.add(record["adapterId"])
        if record["mode"] != "A5_LIMITED" or record["strongAdmissionSupported"] is not False:
            _fail("A5 boundary cannot claim strong admission")
        if record["strongCapability"] != "UNPROVEN":
            _fail("A5 boundary cannot claim unqualified support")
        _digest(record["sourceDigest"], "sourceDigest")
        _self_digest(record, "boundaryRecordDigest")
    if seen != _ADAPTERS:
        _fail("A5 registry does not cover the selected 12 adapters")
    _self_digest(registry, "registryDigest")
    return registry


def _validate_a5_state(state: dict[str, Any]) -> None:
    """Recognized A5 slots stay closed even though the outer state is extensible."""
    marked = "immutableInput" in state
    plan_policy = validate_a5_plan_policy(state["immutableInput"]) if marked else None
    for task in state["tasks"]:
        if not isinstance(task, dict):
            continue  # The ordinary task validator reports this first for v4.
        slots = {"immutableInput", "immutableInputAdmission", "immutableInputAdoption"}
        if not marked:
            if slots.intersection(task):
                raise LifecycleError("a5-context-invalid", "A5 task slots require a marked plan policy")
            continue
        if "immutableInput" not in task:
            raise LifecycleError("a5-context-invalid", "Marked state has a task without A5 policy")
        policy = validate_a5_policy(task["immutableInput"])
        if (
            _validated_cast(dict[str, Any], plan_policy)["defaultRequirement"] == "STRONG_A5"
            and policy["frozenTaskRequirement"] != "STRONG_A5"
        ):
            raise LifecycleError("a5-context-invalid", "Task policy lowers the frozen A5 default")
        if policy["frozenTaskRequirement"] == "STRONG_A5" and task.get("status") in {
            "RUNNING",
            "VERIFYING",
            "REWORK",
            "ACCEPTED",
        }:
            raise LifecycleError("a5-context-invalid", "Unproven strong A5 task cannot have an executed outcome")
        admission = None
        if "immutableInputAdmission" in task:
            admission = validate_a5_decision(task["immutableInputAdmission"])
            if admission["disposition"] != "ORDINARY_NO_A5":
                raise LifecycleError("a5-context-invalid", "Denied A5 decision cannot be a successful task admission")
            if policy["frozenTaskRequirement"] != "NONE":
                raise LifecycleError("a5-context-invalid", "Strong frozen task cannot carry an ordinary admission")
            subject = admission["subject"]
            if (
                subject["runId"] != state.get("runId")
                or subject["taskId"] != task.get("id")
                or subject["targetAttempt"] != task.get("attempt")
                or admission["boundaryRecordDigest"] != policy["boundaryRecordDigest"]
            ):
                raise LifecycleError("a5-context-invalid", "A5 admission subject or boundary differs from task")
        if "immutableInputAdoption" in task:
            binding = validate_a5_adoption_binding(task["immutableInputAdoption"])
            if (
                task.get("status") != "ACCEPTED"
                or binding["runId"] != state.get("runId")
                or binding["taskId"] != task.get("id")
                or binding["actualAttempt"] != task.get("attempt")
                or binding["currentPlanDigest"] != state.get("planDigest")
                or binding["currentPolicyDigest"] != policy["policyDigest"]
            ):
                raise LifecycleError("a5-context-invalid", "A5 adoption does not preserve the original admission")
            if binding["classification"] == "PRESERVED_ORDINARY_NO_A5" and (
                admission is None
                or binding["actualAttempt"] != admission["subject"]["targetAttempt"]
                or binding["originalPlanDigest"] != admission["subject"]["planDigest"]
                or binding["originalPolicyDigest"] != admission["policyDigest"]
                or binding["originalDecisionDigest"] != admission["decisionDigest"]
            ):
                raise LifecycleError("a5-context-invalid", "Ordinary A5 adoption lost its original admission")
            if binding["classification"] == "PRESERVED_LEGACY_NO_A5" and admission is not None:
                raise LifecycleError("a5-context-invalid", "Legacy adoption cannot invent an A5 admission")
        elif admission is not None and (
            admission["subject"]["planDigest"] != state.get("planDigest")
            or admission["policyDigest"] != policy["policyDigest"]
        ):
            raise LifecycleError("a5-context-invalid", "A5 admission differs from the current frozen task")


_VALIDATORS = {
    "subject": validate_a5_subject,
    "policy": validate_a5_policy,
    "request": validate_a5_request,
    "decision": validate_a5_decision,
    "planPolicy": validate_a5_plan_policy,
    "invocationRequest": validate_a5_invocation_request,
    "invocationContext": validate_a5_invocation_context,
    "adoptionBinding": validate_a5_adoption_binding,
    "boundaryRegistry": validate_a5_boundary_registry,
}


def parse_a5_record(raw: bytes, kind: str) -> dict[str, Any]:
    """Reject duplicate JSON members before applying a closed v1 record contract."""
    if kind not in _VALIDATORS:
        _fail("Unknown A5 record kind")
    return _VALIDATORS[kind](load_json_object(raw, label=f"A5 {kind}"))

"""Closed D-RESOURCE limit records and pure ordinary headroom classification."""

from __future__ import annotations

import re
from typing import Any, NoReturn

from agent_lifecycle.contracts.canonical import canonical_bytes
from agent_lifecycle.contracts.errors import LifecycleError

_MAX = (1 << 63) - 1
_DIGEST = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_UINT = {"type": "integer", "minimum": 0, "maximum": _MAX}
CAP_BINDING_V1 = "agent-closing-cap-binding.v1"
LIMIT_PROPOSAL_V1 = "agent-closing-limit-proposal.v1"
OPERATION_BINDING_V1 = "agent-closing-operation-binding.v1"
CLAIM_REQUEST_V1 = "agent-closing-claim-request.v1"
_REVISION = {"type": "integer", "minimum": 0, "maximum": (1 << 53) - 1}
_TEXT256 = {"type": "string", "minLength": 1, "maxLength": 256}
_ACTION_ORDER = (
    "read-evidence",
    "assess-evidence",
    "report",
    "final-audit",
    "final-check",
    "apply-final-outcome",
    "finalize",
    "accounting-closeout",
)
_ACTIONS = frozenset(_ACTION_ORDER)
_CAP_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": CAP_BINDING_V1,
    "oneOf": [
        {
            "type": "object",
            "required": ["kind"],
            "properties": {"kind": {"const": "ABSENT"}},
            "additionalProperties": False,
        },
        {
            "type": "object",
            "required": ["kind", "value"],
            "properties": {"kind": {"const": "FINITE"}, "value": _UINT},
            "additionalProperties": False,
        },
    ],
}
_OWNER_SCHEMA = {
    "type": "object",
    "required": ["scopeKind", "taskId"],
    "additionalProperties": False,
    "properties": {"scopeKind": {"enum": ["RUN", "TASK"]}, "taskId": {"anyOf": [_TEXT256, {"type": "null"}]}},
}
_ARTIFACT_SCHEMA = {
    "type": "object",
    "required": ["path", "sha256", "bytes"],
    "additionalProperties": False,
    "properties": {
        "path": {"type": "string", "minLength": 1, "maxLength": 4096},
        "sha256": _DIGEST,
        "bytes": {"type": "integer", "minimum": 1, "maximum": 1048576},
    },
}
_UNIT_SCHEMA = {
    "type": "object",
    "required": ["metric", "unitDefinitionId", "definitionDigest", "sourceQualificationDigest"],
    "additionalProperties": False,
    "properties": {
        "metric": {"const": "reportedTokens"},
        "unitDefinitionId": _TEXT256,
        "definitionDigest": _DIGEST,
        "sourceQualificationDigest": _DIGEST,
    },
}
_OPERATION_FIELDS = (
    "schemaVersion",
    "bindingId",
    "runId",
    "budgetScopeId",
    "closingWindowId",
    "policyEffectDigest",
    "operationId",
    "nativeOperationRef",
    "nativeOperationDigest",
    "action",
    "owner",
    "unit",
    "upperBound",
    "expectedJournalRevision",
    "expectedWorkflowRevision",
    "expectedAuthorityEpoch",
    "expectedGuardStateDigest",
)
_CLAIM_FIELDS = (
    "schemaVersion",
    "bindingId",
    "budgetScopeId",
    "closingWindowId",
    "operationId",
    "closingOperationDigest",
    "claimId",
    "expectedJournalRevision",
    "expectedWorkflowRevision",
    "expectedAuthorityEpoch",
)
CLOSING_RESOURCE_SCHEMAS: dict[str, dict[str, Any]] = {
    CAP_BINDING_V1: _CAP_SCHEMA,
    LIMIT_PROPOSAL_V1: {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": LIMIT_PROPOSAL_V1,
        "type": "object",
        "additionalProperties": False,
        "required": [
            "scope",
            "participation",
            "oldCap",
            "knownSpentAtAnchor",
            "approvedAdditional",
            "prospectiveCumulativeCeiling",
            "capDisposition",
            "priorViolationSetDigest",
        ],
        "properties": {
            "scope": _OWNER_SCHEMA,
            "participation": {"enum": ["CLOSING_ENABLED", "RETAIN_ONLY"]},
            "oldCap": {"$ref": CAP_BINDING_V1},
            "knownSpentAtAnchor": _UINT,
            "approvedAdditional": {"anyOf": [_UINT, {"type": "null"}]},
            "prospectiveCumulativeCeiling": {"anyOf": [_UINT, {"type": "null"}]},
            "capDisposition": {"enum": ["SUPERSEDE_BY_CLOSING_POLICY", "RETAIN_BINDING"]},
            "priorViolationSetDigest": _DIGEST,
        },
    },
    OPERATION_BINDING_V1: {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": OPERATION_BINDING_V1,
        "$defs": {"ArtifactRef": _ARTIFACT_SCHEMA, "Owner": _OWNER_SCHEMA, "Unit": _UNIT_SCHEMA},
        "type": "object",
        "required": list(_OPERATION_FIELDS),
        "additionalProperties": False,
        "properties": {
            "schemaVersion": {"const": OPERATION_BINDING_V1},
            **{name: _TEXT256 for name in ("bindingId", "runId", "budgetScopeId", "closingWindowId", "operationId")},
            **{name: _DIGEST for name in ("policyEffectDigest", "nativeOperationDigest", "expectedGuardStateDigest")},
            "nativeOperationRef": {"$ref": "#/$defs/ArtifactRef"},
            "action": {"enum": list(_ACTION_ORDER)},
            "owner": {"$ref": "#/$defs/Owner"},
            "unit": {"$ref": "#/$defs/Unit"},
            "upperBound": _UINT,
            **{
                name: _REVISION
                for name in ("expectedJournalRevision", "expectedWorkflowRevision", "expectedAuthorityEpoch")
            },
        },
    },
    CLAIM_REQUEST_V1: {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": CLAIM_REQUEST_V1,
        "type": "object",
        "required": list(_CLAIM_FIELDS),
        "additionalProperties": False,
        "properties": {
            "schemaVersion": {"const": CLAIM_REQUEST_V1},
            **{name: _TEXT256 for name in ("bindingId", "budgetScopeId", "closingWindowId", "operationId", "claimId")},
            "closingOperationDigest": _DIGEST,
            **{
                name: _REVISION
                for name in ("expectedJournalRevision", "expectedWorkflowRevision", "expectedAuthorityEpoch")
            },
        },
    },
}


def _invalid(detail: str) -> NoReturn:
    raise LifecycleError("closing-resource-invalid", detail)


def _uint(value: Any, label: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX:
        _invalid(f"{label} must be a bounded unsigned integer")
    return value


def _closed(value: Any, fields: tuple[str, ...], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != set(fields):
        _invalid(f"{label} has missing or unknown fields")
    return value


def _text(value: Any, label: str, *, limit: int = 256) -> str:
    if type(value) is not str or not 1 <= len(value) <= limit:
        _invalid(f"{label} must be bounded nonempty text")
    return value


def _digest_value(value: Any, label: str) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        _invalid(f"{label} must be a lowercase SHA-256 digest")
    return value


def _revision_value(value: Any, label: str) -> int:
    if _uint(value, label) > (1 << 53) - 1:
        _invalid(f"{label} exceeds safe integer range")
    return value


def _wire_bound(value: dict[str, Any]) -> None:
    if len(canonical_bytes(value)) > 1_048_576:
        _invalid("Closing resource input exceeds wire byte bound")


def validate_closing_operation_binding(value: Any) -> dict[str, Any]:
    """Check the closed sidecar shape; current authority and native identity remain external."""
    item = _closed(value, _OPERATION_FIELDS, "ClosingOperationBinding")
    if item["schemaVersion"] != OPERATION_BINDING_V1:
        _invalid("ClosingOperationBinding protocol is unsupported")
    for name in ("bindingId", "runId", "budgetScopeId", "closingWindowId", "operationId"):
        _text(item[name], name)
    for name in ("policyEffectDigest", "nativeOperationDigest", "expectedGuardStateDigest"):
        _digest_value(item[name], name)
    ref = _closed(item["nativeOperationRef"], ("path", "sha256", "bytes"), "nativeOperationRef")
    _text(ref["path"], "native operation path", limit=4096)
    _digest_value(ref["sha256"], "native operation SHA-256")
    if not 1 <= _uint(ref["bytes"], "native operation bytes") <= 1_048_576:
        _invalid("Native operation bytes exceed artifact bound")
    if type(item["action"]) is not str or item["action"] not in _ACTIONS:
        _invalid("Closing operation action is unsupported")
    owner = _closed(item["owner"], ("scopeKind", "taskId"), "owner")
    if owner["scopeKind"] == "RUN":
        if owner["taskId"] is not None:
            _invalid("Run owner cannot name a task")
    elif owner["scopeKind"] == "TASK":
        _text(owner["taskId"], "task owner")
    else:
        _invalid("Closing owner kind is unsupported")
    unit = _closed(
        item["unit"], ("metric", "unitDefinitionId", "definitionDigest", "sourceQualificationDigest"), "unit"
    )
    if unit["metric"] != "reportedTokens":
        _invalid("Closing resource metric is unsupported")
    _text(unit["unitDefinitionId"], "unit definition")
    _digest_value(unit["definitionDigest"], "unit definition digest")
    _digest_value(unit["sourceQualificationDigest"], "source qualification digest")
    _uint(item["upperBound"], "upper bound")
    for name in ("expectedJournalRevision", "expectedWorkflowRevision", "expectedAuthorityEpoch"):
        _revision_value(item[name], name)
    _wire_bound(item)
    return item


def validate_closing_claim_request(value: Any) -> dict[str, Any]:
    """Check claim request shape without granting a dispatch or replay entitlement."""
    item = _closed(value, _CLAIM_FIELDS, "ClaimRequest")
    if item["schemaVersion"] != CLAIM_REQUEST_V1:
        _invalid("ClaimRequest protocol is unsupported")
    for name in ("bindingId", "budgetScopeId", "closingWindowId", "operationId", "claimId"):
        _text(item[name], name)
    _digest_value(item["closingOperationDigest"], "closing operation digest")
    for name in ("expectedJournalRevision", "expectedWorkflowRevision", "expectedAuthorityEpoch"):
        _revision_value(item[name], name)
    _wire_bound(item)
    return item


def validate_cap_binding(value: Any) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("CapBinding must be an object")
    if value == {"kind": "ABSENT"}:
        return value
    if set(value) != {"kind", "value"} or value["kind"] != "FINITE":
        _invalid("CapBinding has an unsupported or ambiguous shape")
    _uint(value["value"], "cap value")
    return value


def validate_limit_proposal(value: Any) -> dict[str, Any]:
    fields = set(CLOSING_RESOURCE_SCHEMAS[LIMIT_PROPOSAL_V1]["required"])
    if type(value) is not dict or set(value) != fields:
        _invalid("LimitProposal has missing or unknown fields")
    scope = value["scope"]
    if type(scope) is not dict or set(scope) != {"scopeKind", "taskId"}:
        _invalid("LimitProposal owner is malformed")
    kind, task = scope["scopeKind"], scope["taskId"]
    if (kind == "RUN" and task is not None) or (
        kind == "TASK" and (type(task) is not str or not 1 <= len(task) <= 256)
    ):
        _invalid("LimitProposal owner kind and task differ")
    if kind not in {"RUN", "TASK"}:
        _invalid("LimitProposal owner kind is unsupported")
    old = validate_cap_binding(value["oldCap"])
    spent = _uint(value["knownSpentAtAnchor"], "anchor spend")
    if (
        type(value["priorViolationSetDigest"]) is not str
        or re.fullmatch(r"[0-9a-f]{64}", value["priorViolationSetDigest"]) is None
    ):
        _invalid("Prior violation digest is invalid")
    participation = value["participation"]
    disposition = value["capDisposition"]
    if participation == "RETAIN_ONLY":
        if (
            kind != "TASK"
            or disposition != "RETAIN_BINDING"
            or value["approvedAdditional"] is not None
            or value["prospectiveCumulativeCeiling"] is not None
        ):
            _invalid("Retained task cannot receive new-window entitlement")
        return value
    if participation != "CLOSING_ENABLED" or disposition not in {"RETAIN_BINDING", "SUPERSEDE_BY_CLOSING_POLICY"}:
        _invalid("LimitProposal participation or disposition is unsupported")
    if old["kind"] != "FINITE":
        _invalid("Enabled owner requires a qualified finite old cap")
    additional = _uint(value["approvedAdditional"], "approved addition")
    ceiling = _uint(value["prospectiveCumulativeCeiling"], "cumulative ceiling")
    if spent + additional > _MAX or ceiling != spent + additional:
        _invalid("Cumulative ceiling must equal signed anchor spend plus addition")
    return value


def evaluate_ordinary_headroom(proposal: dict[str, Any], frame: dict[str, Any], upper_bound: int) -> dict[str, Any]:
    """Classify one owner row; native inventory, attribution and commit remain required."""
    selected = validate_limit_proposal(proposal)
    if selected["participation"] != "CLOSING_ENABLED":
        _invalid("Retained owner has no new-window operation entitlement")
    fields = {
        "cumulativeSpent",
        "activeReservations",
        "protectedCloseout",
        "windowSpent",
        "windowReservations",
        "windowProtectedCloseout",
    }
    if type(frame) is not dict or set(frame) != fields:
        _invalid("Headroom frame is incomplete")
    amounts = {key: _uint(frame[key], key) for key in fields}
    amount = _uint(upper_bound, "operation upper bound")
    if (
        amounts["cumulativeSpent"] < selected["knownSpentAtAnchor"]
        or amounts["windowSpent"] > amounts["cumulativeSpent"] - selected["knownSpentAtAnchor"]
        or amounts["windowReservations"] > amounts["activeReservations"]
        or amounts["windowProtectedCloseout"] > amounts["protectedCloseout"]
    ):
        _invalid("Window balances cannot exceed their cumulative owner projection")
    cumulative = sum(amounts[key] for key in ("cumulativeSpent", "activeReservations", "protectedCloseout")) + amount
    window = sum(amounts[key] for key in ("windowSpent", "windowReservations", "windowProtectedCloseout")) + amount
    if max(cumulative, window) > _MAX:
        _invalid("Headroom arithmetic overflows the supported domain")
    cap = selected["prospectiveCumulativeCeiling"]
    old = selected["oldCap"]
    retained_cap = old["value"] if selected["capDisposition"] == "RETAIN_BINDING" else cap
    return {
        "schemaVersion": "agent-closing-headroom-classification.v1",
        "disposition": "DATA_CANDIDATE"
        if cumulative <= min(cap, retained_cap) and window <= selected["approvedAdditional"]
        else "REFUSED",
        "cumulativeAfterUpperBound": cumulative,
        "windowAfterUpperBound": window,
        "financialAdmission": False,
        "requiresQualifiedFullInventoryAndAtomicClaim": True,
    }


def evaluate_nested_ordinary_headroom(
    run_proposal: dict[str, Any],
    run_frame: dict[str, Any],
    task_id: str | None,
    task_proposal: dict[str, Any] | None,
    task_frame: dict[str, Any] | None,
    upper_bound: int,
) -> dict[str, Any]:
    """Apply one bound to run and its exact task projection without adding two charges."""
    if validate_limit_proposal(run_proposal)["scope"] != {"scopeKind": "RUN", "taskId": None}:
        _invalid("Run proposal does not describe the run owner")
    run_result = evaluate_ordinary_headroom(run_proposal, run_frame, upper_bound)
    if task_id is None:
        if task_proposal is not None or task_frame is not None:
            _invalid("Run-owned operation cannot borrow a task projection")
        task_result = None
    else:
        if type(task_id) is not str or not task_id or task_proposal is None or task_frame is None:
            _invalid("Task-attributed operation needs its exact task owner")
        if validate_limit_proposal(task_proposal)["scope"] != {"scopeKind": "TASK", "taskId": task_id}:
            _invalid("Task projection does not match original attribution")
        task_result = evaluate_ordinary_headroom(task_proposal, task_frame, upper_bound)
    admitted_by_data = run_result["disposition"] == "DATA_CANDIDATE" and (
        task_result is None or task_result["disposition"] == "DATA_CANDIDATE"
    )
    return {
        "schemaVersion": "agent-closing-nested-headroom-classification.v1",
        "disposition": "DATA_CANDIDATE" if admitted_by_data else "REFUSED",
        "run": run_result,
        "task": task_result,
        "upperBoundCountedOnce": True,
        "financialAdmission": False,
        "requiresQualifiedFullInventoryAndAtomicClaim": True,
    }


def evaluate_own_closeout_headroom(
    proposal: dict[str, Any],
    frame: dict[str, Any],
    upper_bound: int,
    own_protected: int,
    own_window_protected: int,
) -> dict[str, Any]:
    """Classify one same-owner protection transfer; never consume the pool."""
    selected = validate_limit_proposal(proposal)
    if selected["participation"] != "CLOSING_ENABLED":
        _invalid("Retained owner has no closeout entitlement")
    required = {
        "cumulativeSpent",
        "activeReservations",
        "protectedCloseout",
        "windowSpent",
        "windowReservations",
        "windowProtectedCloseout",
    }
    if type(frame) is not dict or set(frame) != required:
        _invalid("Closeout frame is incomplete")
    amounts = {key: _uint(frame[key], key) for key in required}
    upper = _uint(upper_bound, "operation upper bound")
    owner_pool = _uint(own_protected, "own protected balance")
    own_window_pool = _uint(own_window_protected, "own window protected balance")
    if (
        amounts["cumulativeSpent"] < selected["knownSpentAtAnchor"]
        or amounts["windowSpent"] > amounts["cumulativeSpent"] - selected["knownSpentAtAnchor"]
        or amounts["windowReservations"] > amounts["activeReservations"]
        or amounts["windowProtectedCloseout"] > amounts["protectedCloseout"]
        or owner_pool > amounts["protectedCloseout"]
        or own_window_pool > amounts["windowProtectedCloseout"]
    ):
        _invalid("Closeout owner pools exceed their parent balances")
    if upper > owner_pool or upper > own_window_pool:
        return {"disposition": "REFUSED", "financialAdmission": False, "requiresSameOwnerAtomicTransfer": True}
    cumulative = sum(amounts[key] for key in ("cumulativeSpent", "activeReservations", "protectedCloseout"))
    window = sum(amounts[key] for key in ("windowSpent", "windowReservations", "windowProtectedCloseout"))
    if max(cumulative, window) > _MAX:
        _invalid("Closeout arithmetic overflows the supported domain")
    cap = selected["prospectiveCumulativeCeiling"]
    retained_cap = selected["oldCap"]["value"] if selected["capDisposition"] == "RETAIN_BINDING" else cap
    candidate = cumulative <= min(cap, retained_cap) and window <= selected["approvedAdditional"]
    return {
        "disposition": "DATA_CANDIDATE" if candidate else "REFUSED",
        "cumulativeAfterTransfer": cumulative,
        "windowAfterTransfer": window,
        "protectedTransfer": upper,
        "financialAdmission": False,
        "requiresSameOwnerAtomicTransfer": True,
    }


def evaluate_claim_headroom(
    proposal: dict[str, Any],
    frame: dict[str, Any],
    upper_bound: int,
) -> dict[str, Any]:
    """Classify supplied aggregate totals; operation membership remains unproven."""
    selected = validate_limit_proposal(proposal)
    if selected["participation"] != "CLOSING_ENABLED":
        _invalid("Retained owner has no new-window claim entitlement")
    fields = {
        "cumulativeSpent",
        "activeReservations",
        "protectedCloseout",
        "windowSpent",
        "windowReservations",
        "windowProtectedCloseout",
    }
    if type(frame) is not dict or set(frame) != fields:
        _invalid("Claim frame is incomplete")
    amounts = {key: _uint(frame[key], key) for key in fields}
    upper = _uint(upper_bound, "operation upper bound")
    if (
        amounts["cumulativeSpent"] < selected["knownSpentAtAnchor"]
        or amounts["windowSpent"] > amounts["cumulativeSpent"] - selected["knownSpentAtAnchor"]
        or amounts["windowReservations"] > amounts["activeReservations"]
        or amounts["windowProtectedCloseout"] > amounts["protectedCloseout"]
    ):
        _invalid("Claim window balances cannot exceed cumulative owner projection")
    cumulative = sum(amounts[key] for key in ("cumulativeSpent", "activeReservations", "protectedCloseout"))
    window = sum(amounts[key] for key in ("windowSpent", "windowReservations", "windowProtectedCloseout"))
    if max(cumulative, window) > _MAX:
        _invalid("Claim headroom arithmetic overflows the supported domain")
    cap = selected["prospectiveCumulativeCeiling"]
    retained_cap = selected["oldCap"]["value"] if selected["capDisposition"] == "RETAIN_BINDING" else cap
    reservation_observed = upper <= amounts["activeReservations"] and upper <= amounts["windowReservations"]
    candidate = (
        reservation_observed and cumulative <= min(cap, retained_cap) and window <= selected["approvedAdditional"]
    )
    return {
        "schemaVersion": "agent-closing-claim-headroom-classification.v1",
        "disposition": "DATA_CANDIDATE" if candidate else "REFUSED",
        "currentCumulativeBound": cumulative,
        "currentWindowBound": window,
        "aggregateReservationCoversUpperBound": reservation_observed,
        "financialAdmission": False,
        "requiresCurrentOperationMembership": True,
        "requiresQualifiedCurrentAuthorityGuardRouteAndAtomicClaim": True,
    }


def evaluate_nested_claim_headroom(
    run_proposal: dict[str, Any],
    run_frame: dict[str, Any],
    task_id: str | None,
    task_proposal: dict[str, Any] | None,
    task_frame: dict[str, Any] | None,
    upper_bound: int,
) -> dict[str, Any]:
    """Recheck run and exact task projections of one already reserved operation."""
    if validate_limit_proposal(run_proposal)["scope"] != {"scopeKind": "RUN", "taskId": None}:
        _invalid("Run claim proposal does not describe the run owner")
    run_result = evaluate_claim_headroom(run_proposal, run_frame, upper_bound)
    if task_id is None:
        if task_proposal is not None or task_frame is not None:
            _invalid("Run-owned claim cannot borrow a task projection")
        task_result = None
    else:
        if type(task_id) is not str or not task_id or task_proposal is None or task_frame is None:
            _invalid("Task claim needs its exact task owner")
        if validate_limit_proposal(task_proposal)["scope"] != {"scopeKind": "TASK", "taskId": task_id}:
            _invalid("Task claim projection differs from original attribution")
        task_result = evaluate_claim_headroom(task_proposal, task_frame, upper_bound)
    candidate = run_result["disposition"] == "DATA_CANDIDATE" and (
        task_result is None or task_result["disposition"] == "DATA_CANDIDATE"
    )
    return {
        "schemaVersion": "agent-closing-nested-claim-headroom-classification.v1",
        "disposition": "DATA_CANDIDATE" if candidate else "REFUSED",
        "run": run_result,
        "task": task_result,
        "upperBoundCountedOnce": True,
        "financialAdmission": False,
        "requiresQualifiedCurrentAuthorityGuardRouteAndAtomicClaim": True,
    }


__all__ = [
    "CAP_BINDING_V1",
    "CLAIM_REQUEST_V1",
    "CLOSING_RESOURCE_SCHEMAS",
    "LIMIT_PROPOSAL_V1",
    "OPERATION_BINDING_V1",
    "evaluate_claim_headroom",
    "evaluate_nested_claim_headroom",
    "evaluate_nested_ordinary_headroom",
    "evaluate_ordinary_headroom",
    "evaluate_own_closeout_headroom",
    "validate_cap_binding",
    "validate_closing_claim_request",
    "validate_closing_operation_binding",
    "validate_limit_proposal",
]

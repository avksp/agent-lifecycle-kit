"""Schemas and validation for exact-lineage workflow authorization receipts."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from agent_lifecycle.contracts.canonical import canonical_digest
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.schema_builders import open_object_schema

WORKFLOW_AUTHORIZATION_RECEIPT = "agent-workflow-authorization-receipt.v1"
WORKFLOW_AUTHORIZATION_RENEWAL_RECEIPT = "agent-workflow-authorization-renewal-receipt.v1"

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}
_IDENTITY = {"type": "string", "minLength": 1, "maxLength": 256}

WORKFLOW_AUTHORIZATION_SCHEMAS: dict[str, dict[str, Any]] = {
    WORKFLOW_AUTHORIZATION_RECEIPT: open_object_schema(
        WORKFLOW_AUTHORIZATION_RECEIPT,
        required=[
            "schemaVersion",
            "status",
            "decision",
            "authorizationId",
            "runId",
            "packageId",
            "planRevision",
            "planDigest",
            "sourceRevision",
            "stateRevision",
            "authorizedBy",
            "issuedAt",
            "expiresAt",
            "receiptDigest",
        ],
        properties={
            "status": {"const": "PASS"},
            "decision": {"const": "ALLOW"},
            "authorizationId": _IDENTITY,
            "runId": _IDENTITY,
            "packageId": _IDENTITY,
            "planRevision": {"type": "integer", "minimum": 1},
            "planDigest": _DIGEST,
            "sourceRevision": _IDENTITY,
            "stateRevision": {"type": "integer", "minimum": 1},
            "authorizedBy": _IDENTITY,
            "issuedAt": _IDENTITY,
            "expiresAt": _IDENTITY,
            "reason": {"type": "string", "maxLength": 2048},
            "receiptDigest": _DIGEST,
        },
    )
}

_RENEWAL_PROPERTIES = {
    **WORKFLOW_AUTHORIZATION_SCHEMAS[WORKFLOW_AUTHORIZATION_RECEIPT]["properties"],
    "schemaVersion": {"const": WORKFLOW_AUTHORIZATION_RENEWAL_RECEIPT},
    "reason": {"type": "string", "minLength": 1, "maxLength": 2048},
    "purpose": {"const": "RENEW_SAME_RUN_AUTHORIZATION"},
    "previousAuthorizationReceipt": {
        "type": "object",
        "additionalProperties": False,
        "required": ["path", "sha256", "bytes"],
        "properties": {
            "path": _IDENTITY,
            "sha256": {**_DIGEST, "pattern": "^[0-9a-f]{64}$"},
            "bytes": {"type": "integer", "minimum": 1, "maximum": 1_048_576},
        },
    },
    "previousExpiresAt": _IDENTITY,
    **{
        name: {**_DIGEST, "pattern": "^[0-9a-f]{64}$"}
        for name in (
            "budgetsDigest",
            "originalClocksDigest",
            "taskSubjectDigest",
        )
    },
}
WORKFLOW_AUTHORIZATION_SCHEMAS[WORKFLOW_AUTHORIZATION_RENEWAL_RECEIPT] = {
    **open_object_schema(
        WORKFLOW_AUTHORIZATION_RENEWAL_RECEIPT,
        required=list(_RENEWAL_PROPERTIES),
        properties=_RENEWAL_PROPERTIES,
    ),
    "additionalProperties": False,
}


def authorization_renewal_bindings(state: dict[str, Any]) -> dict[str, Any]:
    """One canonical binding for declared-user receipts; this is not a signature."""
    clocks = {name: state.get(name) for name in ("runStartedAt", "runDeadlineAt")}
    clocks["tasks"] = [
        {
            name: task.get(name)
            for name in (
                "id",
                "attempt",
                "attemptStartedAt",
                "attemptDeadlineAt",
            )
        }
        for task in state.get("tasks", [])
    ]
    authorization = state.get("authorization", {})
    return {
        **{
            name: state.get(name)
            for name in (
                "runId",
                "packageId",
                "planRevision",
                "planDigest",
                "sourceRevision",
                "stateRevision",
            )
        },
        "previousAuthorizationReceipt": authorization.get("authorizationReceipt"),
        "previousExpiresAt": authorization.get("expiresAt"),
        "budgetsDigest": canonical_digest(state.get("budgets", {})),
        "originalClocksDigest": canonical_digest(clocks),
        # Binding the entire current tasks also protects scope, attempts and all
        # result/review/audit identities, including compact storage references.
        "taskSubjectDigest": canonical_digest(state.get("tasks", [])),
    }


def _renewal_error(message: str) -> LifecycleError:
    return LifecycleError("invalid-authorization-renewal", message)


def _validate_previous_identity(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"path", "sha256", "bytes"}:
        raise _renewal_error("Previous receipt identity is invalid")
    if not isinstance(value["path"], str) or not value["path"] or len(value["path"]) > 256:
        raise _renewal_error("Previous receipt path is invalid")
    if type(value["bytes"]) is not int or not 1 <= value["bytes"] <= 1_048_576:
        raise _renewal_error("Previous receipt byte count is invalid")
    if not isinstance(value["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None:
        raise _renewal_error("Previous receipt digest is invalid")


def _validate_renewal_shape(receipt: dict[str, Any]) -> None:
    if set(receipt) != set(_RENEWAL_PROPERTIES):
        raise _renewal_error("Renewal receipt requires exactly its declared fields")
    for name in _RENEWAL_PROPERTIES:
        value = receipt[name]
        if name == "previousAuthorizationReceipt":
            _validate_previous_identity(value)
        elif name in {"planRevision", "stateRevision"}:
            if type(value) is not int or value < 1:
                raise _renewal_error(f"Renewal {name} must be a positive integer")
        elif not isinstance(value, str) or not value or len(value) > (2048 if name == "reason" else 256):
            raise _renewal_error(f"Renewal {name} is invalid")
        elif name.endswith("Digest") and re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise _renewal_error(f"Renewal {name} must be a SHA256 digest")
    for name, expected in (
        ("schemaVersion", WORKFLOW_AUTHORIZATION_RENEWAL_RECEIPT),
        ("status", "PASS"),
        ("decision", "ALLOW"),
        ("purpose", "RENEW_SAME_RUN_AUTHORIZATION"),
    ):
        if receipt[name] != expected:
            raise _renewal_error(f"Renewal {name} is unsupported")
    if canonical_digest({k: v for k, v in receipt.items() if k != "receiptDigest"}) != receipt["receiptDigest"]:
        raise LifecycleError("authorization-receipt-digest-mismatch", "Renewal receipt digest mismatch")


def _require_renewable_phase(state: dict[str, Any]) -> None:
    if state.get("schemaVersion") not in {"agent-workflow-state.v4", "agent-workflow-state.v5"}:
        raise _renewal_error("Renewal requires supported v4/v5 state")
    if state.get("startMode") == "plan-only":
        raise LifecycleError("plan-only-not-executable", "Plan-only workflows cannot renew execution authority")
    if state.get("closingWindow") is not None:
        raise _renewal_error("Renewal cannot change a closing window")
    tasks = state.get("tasks", [])
    if state.get("blocker") is not None or any(task.get("status") == "BLOCKED" for task in tasks):
        raise _renewal_error("Renewal cannot resolve a blocked workflow")
    running = state.get("phase") == "RUNNING" and any(
        task.get("status") == "VERIFYING" and isinstance(task.get("result"), dict) for task in tasks
    )
    final = state.get("phase") == "FINAL_AUDIT" and all(
        task.get("status") == "ACCEPTED" for task in tasks if task.get("required", True)
    )
    if not (running or final):
        raise LifecycleError("invalid-phase", "Renewal requires RUNNING/VERIFYING or FINAL_AUDIT")


def _require_renewable_state(state: dict[str, Any]) -> dict[str, Any]:
    _require_renewable_phase(state)
    grant = state.get("authorization")
    if not isinstance(grant, dict) or grant.get("granted") is not True or grant.get("required") is not False:
        raise _renewal_error("Renewal requires an explicitly consumed grant")
    if grant.get("revoked") or grant.get("revokedAt") is not None:
        raise _renewal_error("A revoked grant cannot be renewed")
    if not isinstance(grant.get("expiresAt"), str) or not isinstance(grant.get("authorizationReceipt"), dict):
        raise _renewal_error("Legacy unreceipted or unbounded grants cannot be renewed")
    return grant


def _validate_initial_history(previous: dict[str, Any]) -> None:
    fields = WORKFLOW_AUTHORIZATION_SCHEMAS[WORKFLOW_AUTHORIZATION_RECEIPT]["required"]
    if any(name not in previous for name in fields):
        raise _renewal_error("Historical authorization receipt is incomplete")
    for name in fields:
        if name in {"stateRevision", "planRevision"}:
            if type(previous[name]) is not int or previous[name] < 1:
                raise _renewal_error("Historical authorization revision is invalid")
        elif not isinstance(previous[name], str) or not previous[name] or len(previous[name]) > 256:
            raise _renewal_error("Historical authorization field is invalid")
        elif name.endswith("Digest") and re.fullmatch(r"[0-9a-f]{64}", previous[name]) is None:
            raise _renewal_error("Historical authorization digest is invalid")
    if canonical_digest({k: v for k, v in previous.items() if k != "receiptDigest"}) != previous["receiptDigest"]:
        raise _renewal_error("Historical authorization digest differs")


def _validate_historical_grant(previous: dict[str, Any], state: dict[str, Any], grant: dict[str, Any]) -> None:
    """Check consumed historical integrity without re-authorizing old lineage."""
    schema = previous.get("schemaVersion")
    if schema == WORKFLOW_AUTHORIZATION_RENEWAL_RECEIPT:
        _validate_renewal_shape(previous)
    elif schema == WORKFLOW_AUTHORIZATION_RECEIPT:
        _validate_initial_history(previous)
    else:
        raise _renewal_error("Historical authorization schema is unsupported")
    if previous.get("status") != "PASS" or previous.get("decision") != "ALLOW":
        raise _renewal_error("Historical receipt did not grant execution")
    if any(previous.get(name) != state.get(name) for name in ("runId", "packageId")):
        raise _renewal_error("Historical receipt belongs to another run")
    if previous["stateRevision"] >= state["stateRevision"]:
        raise _renewal_error("Historical receipt was not consumed before this revision")
    if previous["expiresAt"] != grant["expiresAt"] or previous["authorizedBy"] != grant.get("grantedBy"):
        raise _renewal_error("Historical receipt does not match the consumed grant")
    if _parse_timestamp(previous["issuedAt"], "issuedAt") >= _parse_timestamp(previous["expiresAt"], "expiresAt"):
        raise _renewal_error("Historical grant dates are invalid")


def validate_workflow_authorization_renewal_receipt(
    receipt: dict[str, Any],
    *,
    state: dict[str, Any],
    previous_receipt: dict[str, Any],
    used_authorization_ids: set[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate a fresh exact user grant without changing scope, clocks or budgets."""
    grant = _require_renewable_state(state)
    _validate_renewal_shape(receipt)
    _validate_historical_grant(previous_receipt, state, grant)
    for name, value in authorization_renewal_bindings(state).items():
        if receipt[name] != value:
            raise LifecycleError("authorization-lineage-mismatch", f"Renewal {name} mismatch")
    if receipt["authorizationId"] in {previous_receipt["authorizationId"], *(used_authorization_ids or set())}:
        raise LifecycleError("authorization-receipt-replayed", "Authorization identity was already consumed")
    current = now or datetime.now(UTC)
    issued = _parse_timestamp(receipt["issuedAt"], "issuedAt")
    expires = _parse_timestamp(receipt["expiresAt"], "expiresAt")
    old_expiry = _parse_timestamp(grant["expiresAt"], "previousExpiresAt")
    if issued > current:
        raise _renewal_error("Renewal issuance cannot be in the future")
    if expires <= max(issued, current, old_expiry):
        raise LifecycleError("authorization-expired", "Renewal must advance expiry beyond the current time")
    return {"authorizedBy": receipt["authorizedBy"], "expiresAt": receipt["expiresAt"]}


def validate_workflow_authorization_receipt(
    receipt: dict[str, Any],
    *,
    state: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate receipt integrity, expiry and workflow lineage."""

    if receipt.get("schemaVersion") != WORKFLOW_AUTHORIZATION_RECEIPT:
        raise LifecycleError("invalid-authorization-receipt", "authorization receipt schema is unsupported")
    if receipt.get("status") != "PASS" or receipt.get("decision") != "ALLOW":
        raise LifecycleError("invalid-authorization-receipt", "authorization receipt does not grant execution")
    expected = {
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
        "stateRevision": state.get("stateRevision"),
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise LifecycleError("authorization-lineage-mismatch", f"authorization receipt {key} mismatch")
    for key in ("authorizationId", "authorizedBy", "issuedAt", "expiresAt", "receiptDigest"):
        if not isinstance(receipt.get(key), str) or not receipt[key]:
            raise LifecycleError("invalid-authorization-receipt", f"authorization receipt {key} is required")
    body = {key: value for key, value in receipt.items() if key != "receiptDigest"}
    if receipt["receiptDigest"] != canonical_digest(body):
        raise LifecycleError("authorization-receipt-digest-mismatch", "authorization receipt digest mismatch")
    issued_at = _parse_timestamp(receipt["issuedAt"], "issuedAt")
    expires_at = _parse_timestamp(receipt["expiresAt"], "expiresAt")
    if expires_at <= issued_at:
        raise LifecycleError("invalid-authorization-receipt", "authorization expiry must be after issuance")
    current = now or datetime.now(UTC)
    if expires_at <= current:
        raise LifecycleError("authorization-expired", "authorization receipt has expired")
    return {
        "status": "PASS",
        "authorizationId": receipt["authorizationId"],
        "authorizedBy": receipt["authorizedBy"],
        "expiresAt": receipt["expiresAt"],
    }


def _parse_timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LifecycleError("invalid-authorization-receipt", f"authorization {label} is invalid") from exc
    if parsed.tzinfo is None:
        raise LifecycleError("invalid-authorization-receipt", f"authorization {label} must include a timezone")
    return parsed.astimezone(UTC)


__all__ = [
    "WORKFLOW_AUTHORIZATION_RECEIPT",
    "WORKFLOW_AUTHORIZATION_RENEWAL_RECEIPT",
    "WORKFLOW_AUTHORIZATION_SCHEMAS",
    "authorization_renewal_bindings",
    "validate_workflow_authorization_receipt",
    "validate_workflow_authorization_renewal_receipt",
]

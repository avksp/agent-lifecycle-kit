"""Schemas and validation for exact-lineage workflow authorization receipts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agent_lifecycle.contracts.canonical import canonical_digest
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.schema_builders import open_object_schema

WORKFLOW_AUTHORIZATION_RECEIPT = "agent-workflow-authorization-receipt.v1"

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
    "WORKFLOW_AUTHORIZATION_SCHEMAS",
    "validate_workflow_authorization_receipt",
]

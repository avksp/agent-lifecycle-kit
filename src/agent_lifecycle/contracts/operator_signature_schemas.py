"""Closed public operator-signature data; no key custody or execution authority."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from agent_lifecycle.contracts.canonical import canonical_digest
from agent_lifecycle.contracts.deadline_schemas import utc_microseconds
from agent_lifecycle.contracts.ed25519 import fingerprint
from agent_lifecycle.contracts.errors import LifecycleError

POLICY = "agent-operator-signature-policy.v1"
AUTHORITY = "agent-operator-signature-authority.v1"
ROOT = "agent-operator-trust-root.v1"
PAYLOAD = "agent-operator-decision.v1"
ENVELOPE = "agent-operator-signature.v1"
VALIDATION = "agent-operator-signature-validation.v1"
WORKFLOW_STATE_V7 = "agent-workflow-state.v7"
KINDS = frozenset({"freeze", "authorize", "accept"})
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_FINGERPRINT = re.compile(r"ed25519:[0-9a-f]{64}\Z")


def operator_error(message: str, *, code: str = "operator-signature-invalid") -> LifecycleError:
    return LifecycleError(code, message)


def _closed(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise operator_error(f"{label} has missing or unknown fields")
    return value


def _text(value: Any, label: str, maximum: int = 256) -> str:
    if type(value) is not str or not 1 <= len(value) <= maximum:
        raise operator_error(f"{label} must be bounded text")
    if any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise operator_error(f"{label} contains unsupported text")
    return value


def _hex(value: Any, pattern: re.Pattern[str], label: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise operator_error(f"{label} has an invalid encoding")
    return value


def operator_interval(value: dict[str, Any]) -> tuple[datetime, datetime]:
    for name in ("validFrom", "expiresAt"):
        _text(value[name], name, 64)
    try:
        start = utc_microseconds(value["validFrom"])
        end = utc_microseconds(value["expiresAt"])
    except LifecycleError as exc:
        raise operator_error("Operator validity timestamp is invalid") from exc
    if start >= end:
        raise operator_error("Operator validity interval is empty")
    return start, end


def validate_operator_root(value: Any) -> dict[str, Any]:
    root = _closed(value, {"schemaVersion", "rootId", "keys"}, "Operator root")
    if root["schemaVersion"] != ROOT:
        raise operator_error("Operator root schema is unsupported")
    _text(root["rootId"], "rootId")
    keys = root["keys"]
    if type(keys) is not list or not 1 <= len(keys) <= 16:
        raise operator_error("Operator root needs one to sixteen keys")
    names: list[str] = []
    public_keys: list[str] = []
    for raw in keys:
        key = _closed(raw, {"publicKeyHex", "fingerprint", "validFrom", "expiresAt"}, "Operator key")
        public = _hex(key["publicKeyHex"], _DIGEST, "publicKeyHex")
        name = _hex(key["fingerprint"], _FINGERPRINT, "fingerprint")
        if fingerprint(bytes.fromhex(public)) != name:
            raise operator_error("Operator fingerprint differs from its public key")
        operator_interval(key)
        names.append(name)
        public_keys.append(public)
    if names != sorted(set(names)) or len(set(public_keys)) != len(keys):
        raise operator_error("Operator keys must be unique and sorted by fingerprint")
    return root


def validate_operator_policy(value: Any) -> dict[str, Any] | None:
    if type(value) is not dict:
        raise operator_error("Operator policy must be an object")
    fields = {"schemaVersion", "mode"}
    if value.get("mode") != "off":
        fields.add("trustRoot")
    policy = _closed(value, fields, "Operator policy")
    if (
        policy["schemaVersion"] != POLICY
        or type(policy["mode"]) is not str
        or policy["mode"] not in {"off", "advisory", "required"}
    ):
        raise operator_error("Operator policy schema or mode is unsupported")
    if policy["mode"] == "off":
        return None
    validate_operator_root(policy["trustRoot"])
    return policy


def operator_authority_marker(policy: dict[str, Any]) -> dict[str, Any]:
    selected = validate_operator_policy(policy)
    if selected is None or selected["mode"] != "required":
        raise operator_error("Only a required operator policy has an authority marker")
    return {
        "schemaVersion": AUTHORITY,
        "policyDigest": canonical_digest(selected),
        "stateSchemaVersion": WORKFLOW_STATE_V7,
    }


def require_operator_authority(container: dict[str, Any], *, state: bool = False) -> dict[str, Any] | None:
    policy = (
        validate_operator_policy(container["operatorSignaturePolicy"])
        if "operatorSignaturePolicy" in container
        else None
    )
    required = policy is not None and policy["mode"] == "required"
    marker = container.get("operatorSignatureAuthority")
    if required and policy is not None:
        if marker != operator_authority_marker(policy):
            raise operator_error("Required operator policy needs its exact authority marker")
        if not state:
            integrity = container.get("packageIntegrity")
            if (
                type(integrity) is not dict
                or integrity.get("required") is not True
                or integrity.get("lockSchemaVersion") != "agent-plan-lock.v2"
            ):
                raise operator_error("Required operator policy needs whole-package integrity")
    elif "operatorSignatureAuthority" in container:
        raise operator_error("Off or advisory operator policy must omit its authority marker")
    if state and (container.get("schemaVersion") == WORKFLOW_STATE_V7) != required:
        raise operator_error("Required operator policy and native v7 must occur together")
    return policy


def validate_operator_payload(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion",
        "decisionKind",
        "packageId",
        "planRevision",
        "planDigest",
        "sourceRevision",
        "runId",
        "expectedStateRevision",
        "operationId",
        "subjectDigest",
        "policyDigest",
        "trustRootDigest",
        "signerFingerprint",
        "validFrom",
        "expiresAt",
    }
    payload = _closed(value, fields, "Operator payload")
    if (
        payload["schemaVersion"] != PAYLOAD
        or type(payload["decisionKind"]) is not str
        or payload["decisionKind"] not in KINDS
    ):
        raise operator_error("Operator decision schema or kind is unsupported")
    for field in ("packageId", "sourceRevision", "operationId"):
        _text(payload[field], field)
    if type(payload["planRevision"]) is not int or payload["planRevision"] < 1:
        raise operator_error("Operator plan revision must be positive")
    for field in ("planDigest", "subjectDigest", "policyDigest", "trustRootDigest"):
        _hex(payload[field], _DIGEST, field)
    _hex(payload["signerFingerprint"], _FINGERPRINT, "signerFingerprint")
    if payload["decisionKind"] == "freeze":
        if payload["runId"] is not None or payload["expectedStateRevision"] is not None:
            raise operator_error("Freeze must not invent a native run revision")
    else:
        _text(payload["runId"], "runId")
        revision = payload["expectedStateRevision"]
        if type(revision) is not int or revision < 1:
            raise operator_error("Operator state revision must be positive")
    operator_interval(payload)
    return payload


def validate_operator_envelope(value: Any) -> dict[str, Any]:
    envelope = _closed(value, {"schemaVersion", "payload", "signatureHex"}, "Operator signature")
    if envelope["schemaVersion"] != ENVELOPE:
        raise operator_error("Operator signature schema is unsupported")
    validate_operator_payload(envelope["payload"])
    signature = envelope["signatureHex"]
    if type(signature) is not str or re.fullmatch(r"[0-9a-f]{128}", signature) is None:
        raise operator_error("Operator signature encoding is invalid")
    return envelope


def _schema(schema_id: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "type": "object",
        "additionalProperties": False,
        "required": ["schemaVersion", *properties],
        "properties": {"schemaVersion": {"const": schema_id}, **properties},
    }


_TEXT = {"type": "string", "minLength": 1, "maxLength": 256}
_HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_ROOT_SCHEMA = _schema(
    ROOT,
    {
        "rootId": _TEXT,
        "keys": {
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["publicKeyHex", "fingerprint", "validFrom", "expiresAt"],
                "properties": {"publicKeyHex": _HASH, "fingerprint": _TEXT, "validFrom": _TEXT, "expiresAt": _TEXT},
            },
        },
    },
)
OPERATOR_SIGNATURE_SCHEMAS = {
    ROOT: _ROOT_SCHEMA,
    POLICY: {
        "$schema": _ROOT_SCHEMA["$schema"],
        "$id": POLICY,
        "anyOf": [
            _schema(POLICY, {"mode": {"const": "off"}}),
            _schema(POLICY, {"mode": {"enum": ["advisory", "required"]}, "trustRoot": _ROOT_SCHEMA}),
        ],
    },
    AUTHORITY: _schema(
        AUTHORITY,
        {
            "policyDigest": _HASH,
            "stateSchemaVersion": {"const": WORKFLOW_STATE_V7},
        },
    ),
    PAYLOAD: _schema(
        PAYLOAD,
        {
            "decisionKind": {"enum": sorted(KINDS)},
            "packageId": _TEXT,
            "planRevision": {"type": "integer", "minimum": 1},
            "planDigest": _HASH,
            "sourceRevision": _TEXT,
            "runId": {"type": ["string", "null"]},
            "expectedStateRevision": {"type": ["integer", "null"]},
            "operationId": _TEXT,
            "subjectDigest": _HASH,
            "policyDigest": _HASH,
            "trustRootDigest": _HASH,
            "signerFingerprint": _TEXT,
            "validFrom": _TEXT,
            "expiresAt": _TEXT,
        },
    ),
    ENVELOPE: _schema(
        ENVELOPE,
        {
            "payload": {"type": "object"},
            "signatureHex": {"type": "string", "pattern": "^[0-9a-f]{128}$"},
        },
    ),
}

"""Closed reviewer provenance records; trusted caller selection is external."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, NoReturn

from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest
from agent_lifecycle.contracts.errors import LifecycleError

TRUST_ROOT_V1 = "agent-reviewer-trust-root.v1"
ATTESTATION_V1 = "agent-reviewer-attestation.v1"
CLAIMS_V1 = "agent-reviewer-identity-claims.v1"
PROVENANCE_VALIDATION_V1 = "agent-reviewer-provenance-validation.v1"
REVIEWER_ATTESTATION_POLICY_V1 = "agent-reviewer-attestation-policy.v1"
REVIEWER_ATTESTATION_AUTHORITY_V1 = "agent-reviewer-attestation-authority.v1"
REVIEWER_REQUIRED_LOCK = "agent-plan-lock.v4"
REVIEWER_REQUIRED_STATE = "agent-workflow-state.v8"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_SIGNATURE = re.compile(r"[0-9a-f]{128}\Z")
_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
_PHASES = {"plan-review", "task-review", "final-review"}
_CLAIM_FIELDS = {
    "schemaVersion",
    "issuerId",
    "actorId",
    "sessionId",
    "phase",
    "assignmentId",
    "assignmentDigest",
    "subjectDigest",
    "trustRootDigest",
    "nonce",
    "issuedAt",
    "expiresAt",
}
_ISSUER_FIELDS = {"issuerId", "fingerprint", "publicKeyHex", "actorIds", "phases"}
_ASSIGNMENT_FIELDS = {
    "issuerId",
    "reviewerActorId",
    "reviewerSessionId",
    "authorActorId",
    "authorSessionId",
    "authorFingerprint",
    "validFrom",
    "expiresAt",
}


def _schema(schema_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "type": "object",
        "additionalProperties": False,
        "required": list(fields),
        "properties": fields,
    }


_TEXT = {"type": "string", "minLength": 1, "maxLength": 128}
_HEX = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_UTC = {"type": "string", "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"}
REVIEWER_IDENTITY_SCHEMAS = {
    TRUST_ROOT_V1: _schema(
        TRUST_ROOT_V1,
        {
            "schemaVersion": {"const": TRUST_ROOT_V1},
            "revision": {"type": "integer", "minimum": 1},
            "authorizedIssuers": {
                "type": "array",
                "minItems": 1,
                "maxItems": 64,
                "items": _schema(
                    "agent-reviewer-authorized-issuer.v1",
                    {
                        "issuerId": _TEXT,
                        "fingerprint": {"type": "string", "pattern": "^ed25519:[0-9a-f]{64}$"},
                        "publicKeyHex": _HEX,
                        "actorIds": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 64,
                            "uniqueItems": True,
                            "items": _TEXT,
                        },
                        "phases": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 3,
                            "uniqueItems": True,
                            "items": {"enum": sorted(_PHASES)},
                        },
                    },
                ),
            },
        },
    ),
    CLAIMS_V1: _schema(
        CLAIMS_V1,
        {
            "schemaVersion": {"const": CLAIMS_V1},
            **{name: _TEXT for name in ("issuerId", "actorId", "sessionId", "assignmentId")},
            "phase": {"enum": sorted(_PHASES)},
            **{name: _HEX for name in ("assignmentDigest", "subjectDigest", "trustRootDigest", "nonce")},
            "issuedAt": _UTC,
            "expiresAt": _UTC,
        },
    ),
    ATTESTATION_V1: _schema(
        ATTESTATION_V1,
        {
            "schemaVersion": {"const": ATTESTATION_V1},
            "claims": {"$ref": CLAIMS_V1},
            "signer": _schema(
                "agent-reviewer-signer.v1",
                {
                    "algorithm": {"const": "Ed25519"},
                    "fingerprint": {"type": "string", "pattern": "^ed25519:[0-9a-f]{64}$"},
                },
            ),
            "signature": {"type": "string", "pattern": "^[0-9a-f]{128}$"},
        },
    ),
    PROVENANCE_VALIDATION_V1: _schema(
        PROVENANCE_VALIDATION_V1,
        {
            "schemaVersion": {"const": PROVENANCE_VALIDATION_V1},
            "status": {"enum": ["PASS", "FAIL", "UNSUPPORTED"]},
            "guarantee": {"enum": ["ATTESTED", "UNAVAILABLE"]},
            **{
                name: {"type": ["string", "null"]}
                for name in (
                    "attestationDigest",
                    "claimsDigest",
                    "trustRootDigest",
                    "assignmentDigest",
                    "subjectDigest",
                )
            },
            "blockers": {
                "type": "array",
                "maxItems": 64,
                "items": _schema(
                    "agent-reviewer-provenance-blocker.v1",
                    {
                        "code": _TEXT,
                        "field": _TEXT,
                    },
                ),
            },
        },
    ),
}

REVIEWER_IDENTITY_SCHEMAS[REVIEWER_ATTESTATION_POLICY_V1] = {
    **_schema(
        REVIEWER_ATTESTATION_POLICY_V1,
        {
            "schemaVersion": {"const": REVIEWER_ATTESTATION_POLICY_V1},
            "mode": {"enum": ["off", "advisory", "required"]},
            "trustRoot": {"$ref": TRUST_ROOT_V1},
            "trustRootDigest": _HEX,
            "assignments": {
                "type": "object",
                "minProperties": 1,
                "maxProperties": 512,
                "additionalProperties": _schema(
                    "agent-reviewer-decision-assignment.v1",
                    {
                        **{name: _TEXT for name in sorted(_ASSIGNMENT_FIELDS - {"validFrom", "expiresAt"})},
                        "validFrom": _UTC,
                        "expiresAt": _UTC,
                    },
                ),
            },
        },
    ),
    "required": ["schemaVersion", "mode"],
    "if": {"properties": {"mode": {"const": "off"}}},
    "then": {"maxProperties": 2},
    "else": {"required": ["trustRoot", "trustRootDigest", "assignments"]},
}
REVIEWER_IDENTITY_SCHEMAS[REVIEWER_ATTESTATION_AUTHORITY_V1] = _schema(
    REVIEWER_ATTESTATION_AUTHORITY_V1,
    {
        "schemaVersion": {"const": REVIEWER_ATTESTATION_AUTHORITY_V1},
        "policyDigest": _HEX,
        "lockSchemaVersion": {"const": REVIEWER_REQUIRED_LOCK},
        "stateSchemaVersion": {"const": REVIEWER_REQUIRED_STATE},
    },
)


def _invalid(field: str) -> NoReturn:
    raise LifecycleError("reviewer-provenance-shape-invalid", f"Invalid {field}")


def _closed(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        _invalid(label)
    return value


def _text(value: Any, field: str) -> str:
    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= 128:
        _invalid(field)
    return value


def _digest(value: Any, field: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        _invalid(field)
    return value


def parse_reviewer_utc(value: Any) -> datetime:
    if type(value) is not str or _TIME.fullmatch(value) is None:
        _invalid("UTC time")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _invalid("UTC calendar time")


def validate_reviewer_trust_root(value: Any) -> dict[str, Any]:
    root = _closed(value, {"schemaVersion", "revision", "authorizedIssuers"}, "trustRoot")
    if root["schemaVersion"] != TRUST_ROOT_V1 or type(root["revision"]) is not int or root["revision"] < 1:
        _invalid("trustRoot revision")
    issuers = root["authorizedIssuers"]
    if type(issuers) is not list or not 1 <= len(issuers) <= 64:
        _invalid("authorizedIssuers")
    ids, fingerprints = set(), set()
    for issuer in issuers:
        item = _closed(issuer, _ISSUER_FIELDS, "issuer")
        issuer_id = _text(item["issuerId"], "issuerId")
        _digest(item["publicKeyHex"], "publicKeyHex")
        fingerprint = item["fingerprint"]
        if type(fingerprint) is not str or not fingerprint.startswith("ed25519:"):
            _invalid("issuer fingerprint")
        _digest(fingerprint[8:], "issuer fingerprint")
        if issuer_id in ids or fingerprint in fingerprints:
            _invalid("duplicate issuer binding")
        ids.add(issuer_id)
        fingerprints.add(fingerprint)
        for field, allowed in (("actorIds", None), ("phases", _PHASES)):
            values = item[field]
            if type(values) is not list or not 1 <= len(values) <= 64 or any(type(v) is not str for v in values):
                _invalid(field)
            if len(set(values)) != len(values) or (allowed is not None and not set(values).issubset(allowed)):
                _invalid(field)
            for entry in values:
                _text(entry, field)
    if len(canonical_bytes(root)) > 65_536:
        _invalid("trustRoot byte limit")
    return root


def validate_reviewer_attestation_policy(value: Any) -> dict[str, Any]:
    """Validate the frozen, operator-selected public policy."""
    fields = {"schemaVersion", "mode"}
    if not isinstance(value, dict) or value.get("mode") != "off":
        fields.update({"trustRoot", "trustRootDigest", "assignments"})
    policy = _closed(value, fields, "reviewer attestation policy")
    mode = policy["mode"]
    if policy["schemaVersion"] != REVIEWER_ATTESTATION_POLICY_V1 or mode not in ("off", "advisory", "required"):
        _invalid("reviewer attestation mode")
    if mode == "off":
        return policy
    root = validate_reviewer_trust_root(policy["trustRoot"])
    if policy["trustRootDigest"] != canonical_digest(root):
        _invalid("reviewer trust root pin")
    assignments = policy["assignments"]
    if type(assignments) is not dict or not 1 <= len(assignments) <= 512:
        _invalid("reviewer assignments")
    for key, assignment in assignments.items():
        _text(key, "assignment")
        entry = _closed(assignment, _ASSIGNMENT_FIELDS, "reviewer assignment")
        for field in sorted(_ASSIGNMENT_FIELDS - {"validFrom", "expiresAt", "authorFingerprint"}):
            _text(entry[field], field)
        author = entry["authorFingerprint"]
        if not isinstance(author, str) or not author.startswith("ed25519:"):
            _invalid("author fingerprint")
        _digest(author[8:], "author fingerprint")
        if parse_reviewer_utc(entry["validFrom"]) >= parse_reviewer_utc(entry["expiresAt"]):
            _invalid("reviewer key validity")
    if len(canonical_bytes(policy)) > 262_144:
        _invalid("reviewer policy byte limit")
    return policy


def reviewer_attestation_authority(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": REVIEWER_ATTESTATION_AUTHORITY_V1,
        "policyDigest": canonical_digest(policy),
        "lockSchemaVersion": REVIEWER_REQUIRED_LOCK,
        "stateSchemaVersion": REVIEWER_REQUIRED_STATE,
    }


def require_reviewer_attestation_authority(container: dict[str, Any], *, state: bool = False) -> dict[str, Any] | None:
    policy = (
        validate_reviewer_attestation_policy(container["reviewerAttestationPolicy"])
        if "reviewerAttestationPolicy" in container
        else None
    )
    required = policy is not None and policy["mode"] == "required"
    if required and policy is not None:
        if container.get("reviewerAttestationAuthority") != reviewer_attestation_authority(policy):
            _invalid("required reviewer authority marker")
        if not state:
            integrity = container.get("packageIntegrity")
            extensions = container.get("extensions")
            if not isinstance(integrity, dict) or integrity.get("required") is not True:
                _invalid("reviewer authority requires whole-package integrity")
            if integrity.get("lockSchemaVersion") != "agent-plan-lock.v2":
                _invalid("reviewer authority requires the full-package lock inventory")
            if container.get("reviewMesh") or (isinstance(extensions, dict) and extensions.get("reviewPolicy")):
                _invalid("unsupported strict reviewer and composite review combination")
    elif "reviewerAttestationAuthority" in container:
        _invalid("reviewer authority marker without required policy")
    if state and (container.get("schemaVersion") == REVIEWER_REQUIRED_STATE) != required:
        _invalid("required reviewer policy and native v8 must occur together")
    return policy if policy is not None and policy["mode"] != "off" else None


def validate_reviewer_attestation_shape(value: Any) -> dict[str, Any]:
    attestation = _closed(value, {"schemaVersion", "claims", "signer", "signature"}, "attestation")
    if attestation["schemaVersion"] != ATTESTATION_V1:
        _invalid("attestation version")
    claims = _closed(attestation["claims"], _CLAIM_FIELDS, "claims")
    if claims["schemaVersion"] != CLAIMS_V1 or type(claims["phase"]) is not str or claims["phase"] not in _PHASES:
        _invalid("claims version or phase")
    for name in ("issuerId", "actorId", "sessionId", "assignmentId"):
        _text(claims[name], name)
    for name in ("assignmentDigest", "subjectDigest", "trustRootDigest", "nonce"):
        _digest(claims[name], name)
    parse_reviewer_utc(claims["issuedAt"])
    parse_reviewer_utc(claims["expiresAt"])
    signer = _closed(attestation["signer"], {"algorithm", "fingerprint"}, "signer")
    if (
        signer["algorithm"] != "Ed25519"
        or type(signer["fingerprint"]) is not str
        or not signer["fingerprint"].startswith("ed25519:")
    ):
        _invalid("signer")
    _digest(signer["fingerprint"][8:], "signer fingerprint")
    if type(attestation["signature"]) is not str or _SIGNATURE.fullmatch(attestation["signature"]) is None:
        _invalid("signature")
    if len(canonical_bytes(attestation)) > 16_384:
        _invalid("attestation byte limit")
    return attestation


__all__ = [
    "ATTESTATION_V1",
    "CLAIMS_V1",
    "PROVENANCE_VALIDATION_V1",
    "REVIEWER_ATTESTATION_AUTHORITY_V1",
    "REVIEWER_ATTESTATION_POLICY_V1",
    "REVIEWER_IDENTITY_SCHEMAS",
    "REVIEWER_REQUIRED_LOCK",
    "REVIEWER_REQUIRED_STATE",
    "TRUST_ROOT_V1",
    "parse_reviewer_utc",
    "require_reviewer_attestation_authority",
    "reviewer_attestation_authority",
    "validate_reviewer_attestation_policy",
    "validate_reviewer_attestation_shape",
    "validate_reviewer_trust_root",
]

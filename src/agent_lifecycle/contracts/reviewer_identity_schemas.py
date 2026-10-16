"""Closed reviewer provenance records; trusted caller selection is external."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, NoReturn

from agent_lifecycle.contracts.canonical import canonical_bytes
from agent_lifecycle.contracts.errors import LifecycleError

TRUST_ROOT_V1 = "agent-reviewer-trust-root.v1"
ATTESTATION_V1 = "agent-reviewer-attestation.v1"
CLAIMS_V1 = "agent-reviewer-identity-claims.v1"
PROVENANCE_VALIDATION_V1 = "agent-reviewer-provenance-validation.v1"
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
    "REVIEWER_IDENTITY_SCHEMAS",
    "TRUST_ROOT_V1",
    "parse_reviewer_utc",
    "validate_reviewer_attestation_shape",
    "validate_reviewer_trust_root",
]

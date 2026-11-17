"""Public wire shapes for offline verification of a selected native run."""

from __future__ import annotations

import re
from typing import Any

from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.paths import normalize_repo_path

BUNDLE = "agent-chain-verification-bundle.v1"
TRUST = "agent-chain-verification-trust.v1"
ANCHOR = "agent-chain-terminal-anchor.v1"
REPORT = "agent-chain-verification-report.v1"

_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_PATH_FIELDS = ("manifest", "lock", "state", "journal", "chain")
_ANCHOR_DIGESTS = (
    "planDigest",
    "bundleSha256",
    "lockSha256",
    "stateSha256",
    "journalSha256",
    "chainSha256",
    "trustConfigSha256",
)


def _closed(schema: str, fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema,
        "type": "object",
        "additionalProperties": False,
        "required": ["schemaVersion", *fields],
        "properties": {"schemaVersion": {"const": schema}, **fields},
    }


_TEXT = {"type": "string", "minLength": 1, "maxLength": 128}
_HEX = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
CHAIN_VERIFICATION_SCHEMAS = {
    BUNDLE: _closed(BUNDLE, {field: {"type": "string", "minLength": 1} for field in _PATH_FIELDS}),
    TRUST: _closed(
        TRUST,
        {
            "reviewerPolicyDigest": _HEX,
            "operatorPolicyDigest": {"anyOf": [_HEX, {"type": "null"}]},
        },
    ),
    ANCHOR: _closed(
        ANCHOR,
        {
            "runId": _TEXT,
            "packageId": _TEXT,
            "sourceRevision": _TEXT,
            "terminalRevision": {"type": "integer", "minimum": 2},
            "terminalPhase": {"const": "COMPLETE"},
            **{field: _HEX for field in _ANCHOR_DIGESTS},
        },
    ),
    REPORT: _closed(
        REPORT,
        {
            "status": {"enum": ["VERIFIED", "MISMATCH", "NOT_CHECKED", "INVALID_INPUT"]},
            "exitCode": {"enum": [0, 1, 2]},
            "checks": {"type": "array", "items": {"type": "object"}},
            "firstFailure": {"type": ["object", "null"]},
            "scope": {"type": "string"},
            "authorityGranted": {"const": False},
        },
    ),
}


def validate_chain_input(value: dict[str, Any], schema: str) -> dict[str, Any]:
    expected = set(CHAIN_VERIFICATION_SCHEMAS[schema]["required"])
    if set(value) != expected or value["schemaVersion"] != schema:
        raise LifecycleError("chain-verification-input-shape", "Invalid chain verification input shape")
    if schema == BUNDLE:
        names = []
        for field in _PATH_FIELDS:
            raw = value[field]
            if not isinstance(raw, str) or normalize_repo_path(raw) != raw:
                raise LifecycleError("chain-verification-input-path", "Noncanonical evidence selector")
            names.append(raw.casefold())
        if len(set(names)) != len(names):
            raise LifecycleError("chain-verification-input-alias", "Evidence input selectors alias")
    elif schema == TRUST:
        _check_digest(value["reviewerPolicyDigest"])
        if value["operatorPolicyDigest"] is not None:
            _check_digest(value["operatorPolicyDigest"])
    elif schema == ANCHOR:
        for field in _ANCHOR_DIGESTS:
            _check_digest(value[field])
        if (
            value["terminalPhase"] != "COMPLETE"
            or type(value["terminalRevision"]) is not int
            or value["terminalRevision"] < 2
            or any(
                not isinstance(value[key], str) or not 1 <= len(value[key]) <= 128
                for key in ("runId", "packageId", "sourceRevision")
            )
        ):
            raise LifecycleError("chain-terminal-anchor-invalid", "Invalid terminal anchor lineage")
    return value


def _check_digest(value: Any) -> None:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise LifecycleError("chain-verification-input-digest", "Expected SHA-256 digest")

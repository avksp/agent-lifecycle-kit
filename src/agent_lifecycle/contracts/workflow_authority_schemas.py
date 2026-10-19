"""Closed D-AUTH wire shapes; parsing alone never authenticates a grant."""

from __future__ import annotations

import hashlib
import re
from typing import Any, NoReturn

from agent_lifecycle.contracts.deadline_schemas import utc_microseconds
from agent_lifecycle.contracts.errors import LifecycleError

BOOTSTRAP_PIN_V1 = "agent-workflow-authority-pin.v1"
AUTHORITY_SNAPSHOT_V1 = "agent-workflow-authority-snapshot.v1"
INSTALL_SNAPSHOT_REQUEST_V1 = "agent-workflow-authority-install.v1"
WINDOW_GRANT_V1 = "agent-workflow-closing-grant.v1"
AUTHORITY_INPUT_BUNDLE_V1 = "agent-workflow-authority-input.v1"
AUTHORITY_DECISION_V1 = "agent-workflow-authority-decision.v1"
RUN_OUTPUT_ANCHOR_V1 = "agent-run-output-anchor.v1"
PERMISSION_SCOPE_V1 = "agent-workflow-permission-scope.v1"
SIGNATURE_V1 = "agent-workflow-ed25519-signature.v1"
ISSUER_PERMISSION_V1 = "agent-workflow-issuer-permission.v1"
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_SIGNATURE_HEX = re.compile(r"[0-9a-f]{128}\Z")
_FINGERPRINT = re.compile(r"ed25519:[0-9a-f]{64}\Z")
_ACTIONS = frozenset(
    {
        "read-evidence",
        "assess-evidence",
        "report",
        "final-audit",
        "final-check",
        "apply-final-outcome",
        "finalize",
        "accounting-closeout",
    }
)
_SCOPE_TEXT = ("runId", "packageId", "budgetScopeId", "journalIdentity", "bindingId", "sourceRevision")
_SCOPE_DIGEST = ("originalPlanDigest", "effectivePlanDigest", "evidenceSubjectDigest")
_PIN_TEXT = ("authorityDomain", "rootId", "rootGeneration", "bindingId", "runId", "budgetScopeId", "journalIdentity")
_PIN_FIELDS = {
    "schemaVersion",
    *_PIN_TEXT,
    "rootPublicKeyHex",
    "rootFingerprint",
    "expectedInitialSnapshotDigest",
    "clockPolicy",
    "qualificationRef",
    "trustMode",
}
_GRANT_TEXT = ("authorityDomain", "rootId", "rootGeneration", "issuerId", "issuerGeneration", "closingWindowId")
_GRANT_DIGEST = (
    "nonce",
    "windowIntentDigest",
    "originalAuthorizationDigest",
    "originalDeadlineDigest",
    "originalBlockerDigest",
    "allowedWritesDigest",
    "resourceApprovalDigest",
    "issuedUnderSnapshotDigest",
)
_GRANT_FIELDS = {
    "schemaVersion",
    *_GRANT_TEXT,
    *_GRANT_DIGEST,
    "scope",
    "permission",
    "expectedWorkflowRevision",
    "allowedActions",
    "validFrom",
    "expiresAt",
    "issuedUnderEpoch",
    "signature",
}
_ISSUER_FIELDS = {
    "issuerId",
    "issuerGeneration",
    "publicKeyHex",
    "fingerprint",
    "validFrom",
    "expiresAt",
    "scope",
    "permissions",
    "allowedActions",
    "resourceApprovalDigest",
    "allowedWritesDigest",
}
_SNAPSHOT_FIELDS = {
    "schemaVersion",
    "authorityDomain",
    "rootId",
    "rootGeneration",
    "bindingId",
    "journalIdentity",
    "epoch",
    "previousSnapshotDigest",
    "validFrom",
    "expiresAt",
    "activeIssuers",
    "revokedIssuers",
    "revokedGrants",
    "signature",
}
_AUTHORITY_INPUT_FIELDS = {
    "schemaVersion",
    "bindingId",
    "pinDigest",
    "grantRef",
    "issuanceSnapshotDigest",
    "expectedCurrentEpoch",
    "windowRequestRef",
    "resourceApprovalRef",
    "allowedWritesRef",
    "deadlineInputRef",
}
_AUTHORITY_DECISION_FIELDS = {
    "schemaVersion",
    "decisionId",
    "bindingId",
    "journalIdentity",
    "authorityDomain",
    "rootFingerprint",
    "issuerId",
    "issuerGeneration",
    "nonce",
    "grantDigest",
    "currentSnapshotDigest",
    "authorityEpoch",
    "operationId",
    "requestDigest",
    "expectedWorkflowRevision",
    "authorizedAt",
    "expiresAt",
    "permission",
    "windowIntentDigest",
    "resourceApprovalDigest",
    "allowedWritesDigest",
    "decisionKind",
    "claimId",
    "action",
    "clockObservationDigest",
}
_TEXT_SCHEMA = {"type": "string", "minLength": 1, "maxLength": 256}
_DIGEST_SCHEMA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}


def _schema(name: str, props: dict[str, Any]) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": name,
        "type": "object",
        "additionalProperties": False,
        "required": list(props),
        "properties": props,
    }


_RUN_OUTPUT_ANCHOR_FIELDS = frozenset(
    {
        "schemaVersion",
        "bindingDigest",
        "runId",
        "adoptedStateDigest",
        "journalIdentity",
        "storageProtocolVersion",
        "artifactAuthorityRootPath",
        "artifactAuthorityRootIdentity",
        "canonicalStatePath",
        "packageRoot",
        "resolvedPackageRootRelativePath",
        "eventLog",
        "runOutputRootRelativePath",
    }
)


def validate_run_output_anchor(value: Any) -> dict[str, Any]:
    """Validate anchored data shape; root custody and path identity need separate proof."""

    def invalid(name: str) -> None:
        raise LifecycleError("workflow-output-anchor-invalid", f"Invalid {name}")

    if type(value) is not dict or set(value) != _RUN_OUTPUT_ANCHOR_FIELDS:
        invalid("RunOutputAnchor fields")
    if value["schemaVersion"] != RUN_OUTPUT_ANCHOR_V1 or value["storageProtocolVersion"] != "6":
        invalid("RunOutputAnchor protocol")
    for name in ("bindingDigest", "adoptedStateDigest"):
        if type(value[name]) is not str or re.fullmatch(r"[0-9a-f]{64}", value[name]) is None:
            invalid(name)
    for name, limit in (
        ("runId", 256),
        ("journalIdentity", 256),
        ("artifactAuthorityRootPath", 4096),
        ("canonicalStatePath", 4096),
        ("packageRoot", 4096),
        ("resolvedPackageRootRelativePath", 4096),
        ("eventLog", 4096),
        ("runOutputRootRelativePath", 4096),
    ):
        item = value[name]
        if type(item) is not str or not 1 <= len(item) <= limit:
            invalid(name)
    identity = value["artifactAuthorityRootIdentity"]
    if type(identity) is not dict or set(identity) != {"platform", "volumeId", "fileId"}:
        invalid("artifactAuthorityRootIdentity")
    if type(identity["platform"]) is not str or identity["platform"] not in {"POSIX", "WINDOWS"}:
        invalid("artifactAuthorityRootIdentity.platform")
    for name in ("volumeId", "fileId"):
        if type(identity[name]) is not str or not 1 <= len(identity[name]) <= 256:
            invalid(f"artifactAuthorityRootIdentity.{name}")
    return value


WORKFLOW_AUTHORITY_SCHEMAS = {
    RUN_OUTPUT_ANCHOR_V1: {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": RUN_OUTPUT_ANCHOR_V1,
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schemaVersion",
            "bindingDigest",
            "runId",
            "adoptedStateDigest",
            "journalIdentity",
            "storageProtocolVersion",
            "artifactAuthorityRootPath",
            "artifactAuthorityRootIdentity",
            "canonicalStatePath",
            "packageRoot",
            "resolvedPackageRootRelativePath",
            "eventLog",
            "runOutputRootRelativePath",
        ],
        "properties": {
            "schemaVersion": {"const": RUN_OUTPUT_ANCHOR_V1},
            "bindingDigest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "runId": {"type": "string", "minLength": 1, "maxLength": 256},
            "adoptedStateDigest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "journalIdentity": {"type": "string", "minLength": 1, "maxLength": 256},
            "storageProtocolVersion": {"const": "6"},
            "artifactAuthorityRootPath": {"type": "string", "minLength": 1, "maxLength": 4096},
            "artifactAuthorityRootIdentity": {
                "type": "object",
                "additionalProperties": False,
                "required": ["platform", "volumeId", "fileId"],
                "properties": {
                    "platform": {"enum": ["POSIX", "WINDOWS"]},
                    "volumeId": {"type": "string", "minLength": 1, "maxLength": 256},
                    "fileId": {"type": "string", "minLength": 1, "maxLength": 256},
                },
            },
            **{
                name: {"type": "string", "minLength": 1, "maxLength": 4096}
                for name in (
                    "canonicalStatePath",
                    "packageRoot",
                    "resolvedPackageRootRelativePath",
                    "eventLog",
                    "runOutputRootRelativePath",
                )
            },
        },
    },
    AUTHORITY_DECISION_V1: {
        **_schema(
            AUTHORITY_DECISION_V1,
            {
                "schemaVersion": {"const": AUTHORITY_DECISION_V1},
                **{name: _TEXT_SCHEMA for name in ("decisionId", "bindingId", "journalIdentity", "authorityDomain")},
                "rootFingerprint": {"type": "string", "pattern": "^ed25519:[0-9a-f]{64}$"},
                "issuerId": _TEXT_SCHEMA,
                "issuerGeneration": _TEXT_SCHEMA,
                **{name: _DIGEST_SCHEMA for name in ("nonce", "grantDigest", "currentSnapshotDigest")},
                "authorityEpoch": {"type": "integer", "minimum": 0, "maximum": (1 << 63) - 1},
                "operationId": _TEXT_SCHEMA,
                "requestDigest": _DIGEST_SCHEMA,
                "expectedWorkflowRevision": {"type": "integer", "minimum": 0, "maximum": (1 << 63) - 1},
                **{
                    name: {
                        "type": "string",
                        "format": "date-time",
                        "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$",
                    }
                    for name in ("authorizedAt", "expiresAt")
                },
                "permission": {"const": "closing.activate"},
                **{
                    name: _DIGEST_SCHEMA
                    for name in ("windowIntentDigest", "resourceApprovalDigest", "allowedWritesDigest")
                },
                "decisionKind": {"enum": ["ACTIVATION", "CLAIM", "PRODUCE_PROOF", "FINALIZE"]},
                "claimId": {"anyOf": [_TEXT_SCHEMA, {"type": "null"}]},
                "action": {
                    "anyOf": [
                        {
                            "enum": [
                                "read-evidence",
                                "assess-evidence",
                                "report",
                                "final-audit",
                                "final-check",
                                "apply-final-outcome",
                                "finalize",
                                "accounting-closeout",
                            ]
                        },
                        {"type": "null"},
                    ]
                },
                "clockObservationDigest": _DIGEST_SCHEMA,
            },
        ),
        "allOf": [
            {
                "if": {"properties": {"decisionKind": {"const": "ACTIVATION"}}},
                "then": {"properties": {"claimId": {"type": "null"}, "action": {"type": "null"}}},
            },
            {
                "if": {"properties": {"decisionKind": {"const": "CLAIM"}}},
                "then": {
                    "properties": {
                        "claimId": _TEXT_SCHEMA,
                        "action": {
                            "enum": [
                                "read-evidence",
                                "assess-evidence",
                                "report",
                                "final-audit",
                                "final-check",
                                "apply-final-outcome",
                                "finalize",
                                "accounting-closeout",
                            ]
                        },
                    }
                },
            },
            {
                "if": {"properties": {"decisionKind": {"enum": ["PRODUCE_PROOF", "FINALIZE"]}}},
                "then": {"properties": {"claimId": {"type": "null"}, "action": {"const": "finalize"}}},
            },
        ],
    },
    AUTHORITY_INPUT_BUNDLE_V1: {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": AUTHORITY_INPUT_BUNDLE_V1,
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schemaVersion",
            "bindingId",
            "pinDigest",
            "grantRef",
            "issuanceSnapshotDigest",
            "expectedCurrentEpoch",
            "windowRequestRef",
            "resourceApprovalRef",
            "allowedWritesRef",
            "deadlineInputRef",
        ],
        "$defs": {
            "ArtifactRef": {
                "type": "object",
                "additionalProperties": False,
                "required": ["path", "sha256", "bytes"],
                "properties": {
                    "path": {"type": "string", "minLength": 1, "maxLength": 4096},
                    "sha256": _DIGEST_SCHEMA,
                    "bytes": {"type": "integer", "minimum": 1, "maximum": 1_048_576},
                },
            }
        },
        "properties": {
            "schemaVersion": {"const": AUTHORITY_INPUT_BUNDLE_V1},
            "bindingId": _TEXT_SCHEMA,
            "pinDigest": _DIGEST_SCHEMA,
            "grantRef": {"$ref": "#/$defs/ArtifactRef"},
            "issuanceSnapshotDigest": _DIGEST_SCHEMA,
            "expectedCurrentEpoch": {"type": "integer", "minimum": 0, "maximum": (1 << 63) - 1},
            **{
                name: {"$ref": "#/$defs/ArtifactRef"}
                for name in ("windowRequestRef", "resourceApprovalRef", "allowedWritesRef", "deadlineInputRef")
            },
        },
    },
    INSTALL_SNAPSHOT_REQUEST_V1: _schema(
        INSTALL_SNAPSHOT_REQUEST_V1,
        {
            "schemaVersion": {"const": INSTALL_SNAPSHOT_REQUEST_V1},
            "bindingId": _TEXT_SCHEMA,
            "operationId": _TEXT_SCHEMA,
            "expectedAuthorityEpoch": {
                "anyOf": [
                    {"type": "integer", "minimum": 0, "maximum": (1 << 63) - 1},
                    {"type": "null"},
                ]
            },
            "snapshotRef": {
                "type": "object",
                "additionalProperties": False,
                "required": ["path", "sha256", "bytes"],
                "properties": {
                    "path": {"type": "string", "minLength": 1, "maxLength": 4096},
                    "sha256": _DIGEST_SCHEMA,
                    "bytes": {"type": "integer", "minimum": 1, "maximum": 1_048_576},
                },
            },
        },
    ),
    PERMISSION_SCOPE_V1: _schema(
        PERMISSION_SCOPE_V1,
        {
            **{name: _TEXT_SCHEMA for name in _SCOPE_TEXT},
            **{name: _DIGEST_SCHEMA for name in _SCOPE_DIGEST},
        },
    ),
    SIGNATURE_V1: _schema(
        SIGNATURE_V1,
        {
            "algorithm": {"const": "Ed25519"},
            "signerFingerprint": {"type": "string", "pattern": "^ed25519:[0-9a-f]{64}$"},
            "valueHex": {"type": "string", "pattern": "^[0-9a-f]{128}$"},
        },
    ),
    ISSUER_PERMISSION_V1: _schema(
        ISSUER_PERMISSION_V1,
        {
            "issuerId": _TEXT_SCHEMA,
            "issuerGeneration": _TEXT_SCHEMA,
            "publicKeyHex": _DIGEST_SCHEMA,
            "fingerprint": {"type": "string", "pattern": "^ed25519:[0-9a-f]{64}$"},
            "validFrom": {"type": "string"},
            "expiresAt": {"type": "string"},
            "scope": {"$ref": PERMISSION_SCOPE_V1},
            "permissions": {"type": "array", "items": {"const": "closing.activate"}, "minItems": 1, "maxItems": 1},
            "allowedActions": {
                "type": "array",
                "items": {"enum": sorted(_ACTIONS)},
                "minItems": 1,
                "maxItems": 8,
                "uniqueItems": True,
            },
            "resourceApprovalDigest": _DIGEST_SCHEMA,
            "allowedWritesDigest": _DIGEST_SCHEMA,
        },
    ),
    BOOTSTRAP_PIN_V1: _schema(
        BOOTSTRAP_PIN_V1,
        {
            "schemaVersion": {"const": BOOTSTRAP_PIN_V1},
            **{name: _TEXT_SCHEMA for name in _PIN_TEXT},
            "rootPublicKeyHex": _DIGEST_SCHEMA,
            "rootFingerprint": {"type": "string", "pattern": "^ed25519:[0-9a-f]{64}$"},
            "expectedInitialSnapshotDigest": _DIGEST_SCHEMA,
            "clockPolicy": {"const": "QUALIFIED_HOST_UTC_NONDECREASING"},
            "qualificationRef": {"type": "object"},
            "trustMode": {"const": "QUALIFIED_LOCAL_OPERATOR"},
        },
    ),
    AUTHORITY_SNAPSHOT_V1: _schema(
        AUTHORITY_SNAPSHOT_V1,
        {
            "schemaVersion": {"const": AUTHORITY_SNAPSHOT_V1},
            **{
                name: _TEXT_SCHEMA
                for name in ("authorityDomain", "rootId", "rootGeneration", "bindingId", "journalIdentity")
            },
            "epoch": {"type": "integer", "minimum": 0, "maximum": (1 << 63) - 1},
            "previousSnapshotDigest": {"anyOf": [_DIGEST_SCHEMA, {"type": "null"}]},
            "validFrom": {"type": "string"},
            "expiresAt": {"type": "string"},
            "activeIssuers": {"type": "array", "maxItems": 256, "items": {"$ref": ISSUER_PERMISSION_V1}},
            "revokedIssuers": {
                "type": "array",
                "maxItems": 4096,
                "items": {
                    "type": "object",
                    "required": ["issuerId", "issuerGeneration"],
                    "additionalProperties": False,
                    "properties": {"issuerId": _TEXT_SCHEMA, "issuerGeneration": _TEXT_SCHEMA},
                },
            },
            "revokedGrants": {
                "type": "array",
                "maxItems": 4096,
                "items": {
                    "type": "object",
                    "required": ["issuerId", "issuerGeneration", "nonce"],
                    "additionalProperties": False,
                    "properties": {"issuerId": _TEXT_SCHEMA, "issuerGeneration": _TEXT_SCHEMA, "nonce": _DIGEST_SCHEMA},
                },
            },
            "signature": {"$ref": SIGNATURE_V1},
        },
    ),
    WINDOW_GRANT_V1: _schema(
        WINDOW_GRANT_V1,
        {
            "schemaVersion": {"const": WINDOW_GRANT_V1},
            **{name: _TEXT_SCHEMA for name in _GRANT_TEXT},
            **{name: _DIGEST_SCHEMA for name in _GRANT_DIGEST},
            "scope": {"$ref": PERMISSION_SCOPE_V1},
            "permission": {"const": "closing.activate"},
            "expectedWorkflowRevision": {"type": "integer", "minimum": 0, "maximum": (1 << 63) - 1},
            "allowedActions": {
                "type": "array",
                "items": {"enum": sorted(_ACTIONS)},
                "minItems": 1,
                "maxItems": 8,
                "uniqueItems": True,
            },
            "validFrom": {"type": "string"},
            "expiresAt": {"type": "string"},
            "issuedUnderEpoch": {"type": "integer", "minimum": 0, "maximum": (1 << 63) - 1},
            "signature": {"$ref": SIGNATURE_V1},
        },
    ),
}


def _invalid(detail: str) -> NoReturn:
    raise LifecycleError("workflow-authority-invalid", detail)


def _closed(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        _invalid(f"{label} has missing or unknown fields")
    return value


def _text(value: Any, label: str) -> None:
    if type(value) is not str or not 1 <= len(value) <= 256:
        _invalid(f"{label} is invalid")


def _hex(value: Any, label: str) -> None:
    if type(value) is not str or _HEX.fullmatch(value) is None:
        _invalid(f"{label} is not a lowercase digest")


def _artifact_ref(value: Any) -> None:
    ref = _closed(value, {"path", "sha256", "bytes"}, "ArtifactRef")
    if type(ref["path"]) is not str or not 1 <= len(ref["path"]) <= 4096:
        _invalid("ArtifactRef path is invalid")
    _hex(ref["sha256"], "ArtifactRef digest")
    if type(ref["bytes"]) is not int or not 1 <= ref["bytes"] <= 1_048_576:
        _invalid("ArtifactRef bytes are invalid")


def validate_authority_input_bundle(value: Any) -> dict[str, Any]:
    """Validate selected D-AUTH input bytes without qualifying their source."""
    selected = _closed(value, _AUTHORITY_INPUT_FIELDS, "AuthorityInputBundle")
    if selected["schemaVersion"] != AUTHORITY_INPUT_BUNDLE_V1:
        _invalid("AuthorityInputBundle protocol is unsupported")
    _text(selected["bindingId"], "bindingId")
    for name in ("pinDigest", "issuanceSnapshotDigest"):
        _hex(selected[name], name)
    epoch = selected["expectedCurrentEpoch"]
    if type(epoch) is not int or not 0 <= epoch <= (1 << 63) - 1:
        _invalid("Expected current authority epoch is invalid")
    for name in ("grantRef", "windowRequestRef", "resourceApprovalRef", "allowedWritesRef", "deadlineInputRef"):
        _artifact_ref(selected[name])
    return selected


def validate_authority_decision_shape(value: Any) -> dict[str, Any]:
    """Validate a decision record, never its issuer or transactional provenance."""
    selected = _closed(value, _AUTHORITY_DECISION_FIELDS, "AuthorityDecision")
    if selected["schemaVersion"] != AUTHORITY_DECISION_V1 or selected["permission"] != "closing.activate":
        _invalid("AuthorityDecision protocol is unsupported")
    for name in (
        "decisionId",
        "bindingId",
        "journalIdentity",
        "authorityDomain",
        "issuerId",
        "issuerGeneration",
        "operationId",
    ):
        _text(selected[name], name)
    if type(selected["rootFingerprint"]) is not str or _FINGERPRINT.fullmatch(selected["rootFingerprint"]) is None:
        _invalid("Root fingerprint is invalid")
    for name in (
        "nonce",
        "grantDigest",
        "currentSnapshotDigest",
        "requestDigest",
        "windowIntentDigest",
        "resourceApprovalDigest",
        "allowedWritesDigest",
        "clockObservationDigest",
    ):
        _hex(selected[name], name)
    for name in ("authorityEpoch", "expectedWorkflowRevision"):
        item = selected[name]
        if type(item) is not int or not 0 <= item <= (1 << 63) - 1:
            _invalid(f"{name} is invalid")
    if utc_microseconds(selected["authorizedAt"]) >= utc_microseconds(selected["expiresAt"]):
        _invalid("AuthorityDecision interval is invalid")
    kind, claim_id, action = selected["decisionKind"], selected["claimId"], selected["action"]
    if kind == "ACTIVATION":
        if claim_id is not None or action is not None:
            _invalid("Activation decision has claim or action")
    elif kind == "CLAIM":
        _text(claim_id, "claimId")
        if type(action) is not str or action not in _ACTIONS:
            _invalid("Claim action is invalid")
    elif kind in {"PRODUCE_PROOF", "FINALIZE"}:
        if claim_id is not None or action != "finalize":
            _invalid("Local proof/final decision identity is invalid")
    else:
        _invalid("AuthorityDecision kind is unsupported")
    return selected


def validate_permission_scope(value: Any) -> dict[str, Any]:
    scope = _closed(value, set(_SCOPE_TEXT + _SCOPE_DIGEST), "PermissionScope")
    for name in _SCOPE_TEXT:
        _text(scope[name], name)
    for name in _SCOPE_DIGEST:
        _hex(scope[name], name)
    return scope


def validate_signature_shape(value: Any) -> dict[str, Any]:
    signature = _closed(value, {"algorithm", "signerFingerprint", "valueHex"}, "Signature")
    if (
        signature["algorithm"] != "Ed25519"
        or type(signature["signerFingerprint"]) is not str
        or _FINGERPRINT.fullmatch(signature["signerFingerprint"]) is None
        or type(signature["valueHex"]) is not str
        or _SIGNATURE_HEX.fullmatch(signature["valueHex"]) is None
    ):
        _invalid("Signature shape is unsupported")
    return signature


def validate_bootstrap_pin(value: Any) -> dict[str, Any]:
    pin = _closed(value, _PIN_FIELDS, "BootstrapPin")
    if (
        pin["schemaVersion"] != BOOTSTRAP_PIN_V1
        or pin["clockPolicy"] != "QUALIFIED_HOST_UTC_NONDECREASING"
        or pin["trustMode"] != "QUALIFIED_LOCAL_OPERATOR"
    ):
        _invalid("BootstrapPin protocol is unsupported")
    for name in _PIN_TEXT:
        _text(pin[name], name)
    _hex(pin["rootPublicKeyHex"], "rootPublicKeyHex")
    _hex(pin["expectedInitialSnapshotDigest"], "expectedInitialSnapshotDigest")
    expected = "ed25519:" + hashlib.sha256(bytes.fromhex(pin["rootPublicKeyHex"])).hexdigest()
    if pin["rootFingerprint"] != expected:
        _invalid("Pinned public key and root fingerprint differ")
    _artifact_ref(pin["qualificationRef"])
    return pin


def validate_install_snapshot_request(value: Any) -> dict[str, Any]:
    request = _closed(
        value,
        {"schemaVersion", "bindingId", "operationId", "expectedAuthorityEpoch", "snapshotRef"},
        "InstallSnapshotRequest",
    )
    if request["schemaVersion"] != INSTALL_SNAPSHOT_REQUEST_V1:
        _invalid("InstallSnapshotRequest protocol is unsupported")
    _text(request["bindingId"], "bindingId")
    _text(request["operationId"], "operationId")
    epoch = request["expectedAuthorityEpoch"]
    if epoch is not None and (type(epoch) is not int or not 0 <= epoch <= (1 << 63) - 1):
        _invalid("Expected authority epoch is invalid")
    _artifact_ref(request["snapshotRef"])
    return request


def validate_window_grant_shape(value: Any) -> dict[str, Any]:
    grant = _closed(value, _GRANT_FIELDS, "WindowGrant")
    if grant["schemaVersion"] != WINDOW_GRANT_V1 or grant["permission"] != "closing.activate":
        _invalid("WindowGrant protocol is unsupported")
    for name in _GRANT_TEXT:
        _text(grant[name], name)
    for name in _GRANT_DIGEST:
        _hex(grant[name], name)
    validate_permission_scope(grant["scope"])
    validate_signature_shape(grant["signature"])
    for name in ("expectedWorkflowRevision", "issuedUnderEpoch"):
        if type(grant[name]) is not int or not 0 <= grant[name] <= (1 << 63) - 1:
            _invalid(f"{name} is invalid")
    actions = grant["allowedActions"]
    if (
        type(actions) is not list
        or not actions
        or len(actions) > 8
        or any(type(action) is not str for action in actions)
        or len(set(actions)) != len(actions)
        or set(actions) - _ACTIONS
    ):
        _invalid("WindowGrant action set is invalid")
    if utc_microseconds(grant["validFrom"]) >= utc_microseconds(grant["expiresAt"]):
        _invalid("WindowGrant interval is invalid")
    return grant


def validate_issuer_permission_shape(value: Any) -> dict[str, Any]:
    issuer = _closed(value, _ISSUER_FIELDS, "IssuerPermission")
    _text(issuer["issuerId"], "issuerId")
    _text(issuer["issuerGeneration"], "issuerGeneration")
    _hex(issuer["publicKeyHex"], "issuer public key")
    fingerprint = "ed25519:" + hashlib.sha256(bytes.fromhex(issuer["publicKeyHex"])).hexdigest()
    if issuer["fingerprint"] != fingerprint:
        _invalid("Issuer public key and fingerprint differ")
    validate_permission_scope(issuer["scope"])
    if issuer["permissions"] != ["closing.activate"]:
        _invalid("Issuer has unsupported permission")
    actions = issuer["allowedActions"]
    if (
        type(actions) is not list
        or not actions
        or len(actions) > 8
        or any(type(action) is not str for action in actions)
        or len(set(actions)) != len(actions)
        or set(actions) - _ACTIONS
    ):
        _invalid("Issuer action set is invalid")
    for key in ("resourceApprovalDigest", "allowedWritesDigest"):
        _hex(issuer[key], key)
    if utc_microseconds(issuer["validFrom"]) >= utc_microseconds(issuer["expiresAt"]):
        _invalid("Issuer validity interval is invalid")
    return issuer


def validate_authority_snapshot_shape(value: Any) -> dict[str, Any]:
    snapshot = _closed(value, _SNAPSHOT_FIELDS, "AuthoritySnapshot")
    if snapshot["schemaVersion"] != AUTHORITY_SNAPSHOT_V1:
        _invalid("AuthoritySnapshot protocol is unsupported")
    for name in ("authorityDomain", "rootId", "rootGeneration", "bindingId", "journalIdentity"):
        _text(snapshot[name], name)
    epoch = snapshot["epoch"]
    if type(epoch) is not int or not 0 <= epoch <= (1 << 63) - 1:
        _invalid("AuthoritySnapshot epoch is invalid")
    predecessor = snapshot["previousSnapshotDigest"]
    if (epoch == 0 and predecessor is not None) or (epoch > 0 and predecessor is None):
        _invalid("AuthoritySnapshot predecessor is invalid")
    if predecessor is not None:
        _hex(predecessor, "previousSnapshotDigest")
    if utc_microseconds(snapshot["validFrom"]) >= utc_microseconds(snapshot["expiresAt"]):
        _invalid("AuthoritySnapshot interval is invalid")
    issuers = snapshot["activeIssuers"]
    revoked_issuers = snapshot["revokedIssuers"]
    revoked_grants = snapshot["revokedGrants"]
    if (
        type(issuers) is not list
        or len(issuers) > 256
        or type(revoked_issuers) is not list
        or len(revoked_issuers) > 4096
        or type(revoked_grants) is not list
        or len(revoked_grants) > 4096
    ):
        _invalid("AuthoritySnapshot list limit is invalid")
    active_keys = []
    for issuer in issuers:
        validate_issuer_permission_shape(issuer)
        active_keys.append((issuer["issuerId"], issuer["issuerGeneration"]))
    revoked_keys = []
    for key in revoked_issuers:
        item = _closed(key, {"issuerId", "issuerGeneration"}, "RevokedIssuer")
        _text(item["issuerId"], "issuerId")
        _text(item["issuerGeneration"], "issuerGeneration")
        revoked_keys.append((item["issuerId"], item["issuerGeneration"]))
    grant_keys = []
    for key in revoked_grants:
        item = _closed(key, {"issuerId", "issuerGeneration", "nonce"}, "RevokedGrant")
        _text(item["issuerId"], "issuerId")
        _text(item["issuerGeneration"], "issuerGeneration")
        _hex(item["nonce"], "nonce")
        grant_keys.append((item["issuerId"], item["issuerGeneration"], item["nonce"]))
    if (
        len(set(active_keys)) != len(active_keys)
        or len(set(revoked_keys)) != len(revoked_keys)
        or len(set(grant_keys)) != len(grant_keys)
        or set(active_keys) & set(revoked_keys)
    ):
        _invalid("AuthoritySnapshot identities are duplicated or revoked")
    validate_signature_shape(snapshot["signature"])
    return snapshot


__all__ = [
    "AUTHORITY_SNAPSHOT_V1",
    "BOOTSTRAP_PIN_V1",
    "INSTALL_SNAPSHOT_REQUEST_V1",
    "ISSUER_PERMISSION_V1",
    "PERMISSION_SCOPE_V1",
    "RUN_OUTPUT_ANCHOR_V1",
    "SIGNATURE_V1",
    "WINDOW_GRANT_V1",
    "WORKFLOW_AUTHORITY_SCHEMAS",
    "validate_authority_snapshot_shape",
    "validate_bootstrap_pin",
    "validate_install_snapshot_request",
    "validate_issuer_permission_shape",
    "validate_permission_scope",
    "validate_run_output_anchor",
    "validate_signature_shape",
    "validate_window_grant_shape",
]

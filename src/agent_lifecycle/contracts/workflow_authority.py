"""Pure D-AUTH envelope binding; signed snapshot and native transaction are separate."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from agent_lifecycle.contracts.canonical import canonical_digest, load_json_object
from agent_lifecycle.contracts.deadline_schemas import utc_microseconds
from agent_lifecycle.contracts.ed25519 import verify
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.workflow_authority_schemas import (
    validate_authority_snapshot_shape,
    validate_bootstrap_pin,
    validate_issuer_permission_shape,
    validate_permission_scope,
    validate_window_grant_shape,
)
from agent_lifecycle.contracts.workflow_state_schemas import validate_runtime_binding

_SNAPSHOT_DOMAIN = b"agent-lifecycle-workflow-authority-snapshot-v1\x00"
_GRANT_DOMAIN = b"agent-lifecycle-workflow-closing-grant-v1\x00"


def validate_initial_authority_inputs(
    binding: dict[str, Any], expected_binding_digest: str, expected_pin_digest: str,
    pin_raw: bytes, qualification_raw: bytes, snapshot: dict[str, Any], *, observed_at: str,
) -> dict[str, Any]:
    """Check exact initial inputs before adoption; caller/root provenance is still unproved."""
    validate_runtime_binding(binding)
    if (
        type(expected_binding_digest) is not str
        or type(expected_pin_digest) is not str
        or re.fullmatch(r"[0-9a-f]{64}", expected_binding_digest) is None
        or re.fullmatch(r"[0-9a-f]{64}", expected_pin_digest) is None
        or canonical_digest(binding) != expected_binding_digest
    ):
        raise LifecycleError("workflow-authority-invalid", "Independent binding or pin digest differs")
    if type(pin_raw) is not bytes or len(pin_raw) > 1_048_576:
        raise LifecycleError("workflow-authority-invalid", "Pin artifact bytes are invalid")
    pin_ref = binding["workflowAuthorityPinRef"]
    if len(pin_raw) != pin_ref["bytes"] or hashlib.sha256(pin_raw).hexdigest() != pin_ref["sha256"]:
        raise LifecycleError("workflow-authority-invalid", "Pin artifact identity differs")
    pin = validate_bootstrap_pin(load_json_object(pin_raw, label="workflow authority pin"))
    if canonical_digest(pin) != expected_pin_digest:
        raise LifecycleError("workflow-authority-invalid", "Independently selected root pin differs")
    for field in ("bindingId", "runId", "budgetScopeId", "journalIdentity"):
        if pin[field] != binding[field]:
            raise LifecycleError("workflow-authority-invalid", f"Pin {field} differs from runtime binding")
    if type(qualification_raw) is not bytes or len(qualification_raw) > 8_388_608:
        raise LifecycleError("workflow-authority-invalid", "Qualification artifact bytes are invalid")
    qualification_ref = pin["qualificationRef"]
    if (
        len(qualification_raw) != qualification_ref["bytes"]
        or hashlib.sha256(qualification_raw).hexdigest() != qualification_ref["sha256"]
    ):
        raise LifecycleError("workflow-authority-invalid", "Qualification artifact identity differs")
    if type(snapshot) is not dict or snapshot.get("epoch") != 0 or snapshot.get("previousSnapshotDigest") is not None:
        raise LifecycleError("workflow-authority-invalid", "Initial snapshot must be epoch zero")
    verified = verify_signed_authority_snapshot(pin, snapshot, observed_at=observed_at)
    return {
        "schemaVersion": "agent-workflow-initial-authority-inputs.v1",
        "status": "DATA_CANDIDATE",
        "bindingDigest": expected_binding_digest,
        "pinDigest": expected_pin_digest,
        "snapshotDigest": verified["snapshotDigest"],
        "qualificationDigest": qualification_ref["sha256"],
        "signatureVerified": True,
        "bootstrapQualified": False,
        "nativePermissionGranted": False,
    }


def _verified_signature(document: dict[str, Any], key_hex: str, domain: bytes, fingerprint: str) -> bool:
    signature = document["signature"]
    if signature["signerFingerprint"] != fingerprint:
        return False
    unsigned = {key: value for key, value in document.items() if key != "signature"}
    message = domain + canonical_digest(unsigned).encode("ascii")
    return verify(bytes.fromhex(key_hex), message, bytes.fromhex(signature["valueHex"]))


def verify_signed_authority_snapshot(
    pin: dict[str, Any], snapshot: dict[str, Any], *, observed_at: str,
) -> dict[str, Any]:
    """Verify a pinned signature; caller qualification and journal history remain separate."""
    selected_pin = validate_bootstrap_pin(pin)
    selected = validate_authority_snapshot_shape(snapshot)
    for field in ("authorityDomain", "rootId", "rootGeneration", "bindingId", "journalIdentity"):
        if selected[field] != selected_pin[field]:
            raise LifecycleError("workflow-authority-invalid", f"Snapshot {field} differs from pin")
    if selected["epoch"] == 0 and canonical_digest(selected) != selected_pin["expectedInitialSnapshotDigest"]:
        raise LifecycleError("workflow-authority-invalid", "Initial snapshot is not pinned")
    now = utc_microseconds(observed_at)
    if not utc_microseconds(selected["validFrom"]) <= now < utc_microseconds(selected["expiresAt"]):
        raise LifecycleError("workflow-authority-invalid", "Snapshot is not valid at observation")
    if not _verified_signature(selected, selected_pin["rootPublicKeyHex"], _SNAPSHOT_DOMAIN,
                               selected_pin["rootFingerprint"]):
        raise LifecycleError("workflow-authority-invalid", "Snapshot root signature is invalid")
    return {"schemaVersion": "agent-workflow-snapshot-crypto-validation.v1", "status": "DATA_CANDIDATE",
            "snapshotDigest": canonical_digest(selected), "signatureVerified": True,
            "bootstrapQualified": False, "historyVerified": False, "nativePermissionGranted": False}


def verify_signed_window_grant(
    pin: dict[str, Any], issuance: dict[str, Any], current: dict[str, Any], grant: dict[str, Any],
    *, expected_scope: dict[str, Any], observed_at: str,
) -> dict[str, Any]:
    """Verify signed bytes and current permission; no native nonce or claim authority."""
    selected_grant = validate_window_grant_shape(grant)
    verify_signed_authority_snapshot(pin, issuance, observed_at=selected_grant["validFrom"])
    verify_signed_authority_snapshot(pin, current, observed_at=observed_at)
    if (selected_grant["issuedUnderEpoch"] != issuance["epoch"]
            or selected_grant["issuedUnderSnapshotDigest"] != canonical_digest(issuance)):
        raise LifecycleError("workflow-authority-invalid", "Grant issuance snapshot differs")
    key = (selected_grant["issuerId"], selected_grant["issuerGeneration"])
    issued = _selected_issuer(issuance, key)
    active = _selected_issuer(current, key)
    if issued != active:
        raise LifecycleError("workflow-authority-invalid", "Issuer permission changed")
    if {"issuerId": key[0], "issuerGeneration": key[1]} in current["revokedIssuers"] or {
        "issuerId": key[0], "issuerGeneration": key[1], "nonce": selected_grant["nonce"]
    } in current["revokedGrants"]:
        raise LifecycleError("workflow-authority-invalid", "Issuer or grant is revoked")
    validate_selected_grant_envelope(pin, issued, selected_grant, expected_scope, canonical_digest(issuance))
    now = utc_microseconds(observed_at)
    if not utc_microseconds(selected_grant["validFrom"]) <= now < utc_microseconds(selected_grant["expiresAt"]):
        raise LifecycleError("workflow-authority-invalid", "Grant is not valid at observation")
    if not _verified_signature(selected_grant, issued["publicKeyHex"], _GRANT_DOMAIN, issued["fingerprint"]):
        raise LifecycleError("workflow-authority-invalid", "Grant issuer signature is invalid")
    return {"schemaVersion": "agent-workflow-grant-crypto-validation.v1", "status": "DATA_CANDIDATE",
            "grantDigest": canonical_digest(selected_grant), "signatureVerified": True,
            "bootstrapQualified": False, "historyVerified": False, "nonceConsumed": False,
            "nativePermissionGranted": False}


def _selected_issuer(snapshot: dict[str, Any], key: tuple[str, str]) -> dict[str, Any]:
    matches = [issuer for issuer in snapshot["activeIssuers"]
               if (issuer["issuerId"], issuer["issuerGeneration"]) == key]
    if len(matches) != 1:
        raise LifecycleError("workflow-authority-invalid", "Grant issuer is not active")
    return matches[0]


def validate_selected_grant_envelope(
    pin: dict[str, Any], issuer: dict[str, Any], grant: dict[str, Any],
    expected_scope: dict[str, Any], selected_snapshot_digest: str,
) -> dict[str, Any]:
    """Refuse envelope drift without mistaking caller-supplied inputs for trust."""
    selected_pin = validate_bootstrap_pin(pin)
    selected_issuer = validate_issuer_permission_shape(issuer)
    selected_grant = validate_window_grant_shape(grant)
    scope = validate_permission_scope(expected_scope)
    if selected_grant["scope"] != scope or selected_issuer["scope"] != scope:
        raise LifecycleError("workflow-authority-invalid", "Grant or issuer scope differs from selected run binding")
    for field in ("authorityDomain", "rootId", "rootGeneration"):
        if selected_grant[field] != selected_pin[field]:
            raise LifecycleError("workflow-authority-invalid", f"Grant {field} differs from the selected pin")
    for field in ("runId", "budgetScopeId", "journalIdentity", "bindingId"):
        if scope[field] != selected_pin[field]:
            raise LifecycleError("workflow-authority-invalid", f"Permission {field} differs from the selected pin")
    if (
        selected_grant["issuerId"] != selected_issuer["issuerId"]
        or selected_grant["issuerGeneration"] != selected_issuer["issuerGeneration"]
        or selected_grant["signature"]["signerFingerprint"] != selected_issuer["fingerprint"]
        or selected_grant["issuedUnderSnapshotDigest"] != selected_snapshot_digest
        or selected_grant["resourceApprovalDigest"] != selected_issuer["resourceApprovalDigest"]
        or selected_grant["allowedWritesDigest"] != selected_issuer["allowedWritesDigest"]
    ):
        raise LifecycleError("workflow-authority-invalid", "Grant issuer, snapshot or approval digests differ")
    if not set(selected_grant["allowedActions"]).issubset(selected_issuer["allowedActions"]):
        raise LifecycleError("workflow-authority-invalid", "Grant expands issuer actions")
    if (
        utc_microseconds(selected_grant["validFrom"]) < utc_microseconds(selected_issuer["validFrom"])
        or utc_microseconds(selected_grant["expiresAt"]) > utc_microseconds(selected_issuer["expiresAt"])
    ):
        raise LifecycleError("workflow-authority-invalid", "Grant expands issuer validity interval")
    return {
        "schemaVersion": "agent-workflow-grant-envelope-check.v1",
        "disposition": "DATA_CANDIDATE",
        "signatureVerified": False,
        "rootSelectionVerified": False,
        "currentSnapshotVerified": False,
        "nonceConsumed": False,
        "nativePermissionGranted": False,
    }


__all__ = [
    "validate_initial_authority_inputs", "validate_selected_grant_envelope",
    "verify_signed_authority_snapshot", "verify_signed_window_grant",
]

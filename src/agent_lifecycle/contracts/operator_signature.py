"""Public detached decisions using existing crypto, authority I/O and native subjects."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts.canonical import canonical_digest, load_json_object
from agent_lifecycle.contracts.deadline_schemas import utc_microseconds
from agent_lifecycle.contracts.ed25519 import verify
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.operator_signature_schemas import (
    KINDS,
    PAYLOAD,
    VALIDATION,
    operator_error,
    operator_interval,
    require_operator_authority,
    validate_operator_envelope,
    validate_operator_payload,
    validate_operator_policy,
)
from agent_lifecycle.contracts.paths import normalize_repo_path, read_stable_repository_file

MAX_SIGNATURE_BYTES = 1_048_576
FREEZE_SIGNATURE_NAME = "operator-freeze-signature.json"
_EXPECTED_FIELDS = {
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
}


def operator_observed_at() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def operator_signing_message(payload: dict[str, Any]) -> bytes:
    selected = validate_operator_payload(payload)
    domain = f"agent-lifecycle-operator-{selected['decisionKind']}-v1\0"
    return domain.encode("ascii") + canonical_digest(selected).encode("ascii")


def expected_operator_decision(
    container: dict[str, Any],
    kind: str,
    *,
    operation_id: str | None = None,
    subject: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if type(kind) is not str or kind not in KINDS:
        raise operator_error("Operator decision kind is unsupported")
    policy = require_operator_authority(container, state=kind != "freeze")
    if policy is None:
        raise operator_error("Operator signature profile is off")
    freeze = kind == "freeze"
    digest = canonical_digest(container) if freeze else container["planDigest"]
    if not freeze and (subject is None or operation_id is None):
        raise operator_error("Native operator decision needs its actual subject and operation")
    package_value = container.get("package") if freeze else container
    package = package_value if isinstance(package_value, dict) else {}
    base = container.get("baseRevision")
    source = base.get("sha") if freeze and isinstance(base, dict) else container.get("sourceRevision")
    return {
        "schemaVersion": PAYLOAD,
        "decisionKind": kind,
        "packageId": package.get("id") if freeze else container.get("packageId"),
        "planRevision": container.get("planRevision"),
        "planDigest": digest,
        "sourceRevision": source,
        "runId": None if freeze else container.get("runId"),
        "expectedStateRevision": None if freeze else container.get("stateRevision"),
        "operationId": "freeze:" + digest if freeze else operation_id,
        "subjectDigest": digest if freeze else canonical_digest(subject),
        "policyDigest": canonical_digest(policy),
        "trustRootDigest": canonical_digest(policy["trustRoot"]),
    }


def build_operator_payload(
    container: dict[str, Any],
    kind: str,
    *,
    signer_fingerprint: str,
    valid_from: str,
    expires_at: str,
    operation_id: str | None = None,
    subject: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        **expected_operator_decision(container, kind, operation_id=operation_id, subject=subject),
        "signerFingerprint": signer_fingerprint,
        "validFrom": valid_from,
        "expiresAt": expires_at,
    }
    return validate_operator_payload(payload)


def verify_operator_envelope(
    policy: dict[str, Any],
    envelope: dict[str, Any],
    expected: dict[str, Any],
    *,
    observed_at: str,
) -> dict[str, Any]:
    selected = validate_operator_policy(policy)
    if selected is None:
        raise operator_error("Operator signature profile is off")
    if type(expected) is not dict or set(expected) != _EXPECTED_FIELDS:
        raise operator_error("Expected operator binding is incomplete")
    receipt: dict[str, Any] = {
        "schemaVersion": VALIDATION,
        "mode": selected["mode"],
        "decisionKind": expected["decisionKind"],
        "policyDigest": canonical_digest(selected),
        "trustRootDigest": canonical_digest(selected["trustRoot"]),
        "payloadDigest": None,
        "signerFingerprint": None,
        "signatureVerified": False,
        "status": "INVALID",
        "reason": None,
        "claimStrength": "Declared",
        "rootSelectionStrength": "Declared",
        "keyCustodyVerified": False,
        "nativePermissionGranted": False,
        "claimScope": "Exact signed bytes under the selected public root; not operator identity or custody",
    }
    try:
        if expected["policyDigest"] != canonical_digest(selected) or expected["trustRootDigest"] != canonical_digest(
            selected["trustRoot"]
        ):
            raise operator_error("Expected operator root differs from selected policy")
        signed = validate_operator_envelope(envelope)
        payload = signed["payload"]
        if any(payload.get(key) != value for key, value in expected.items()):
            raise operator_error("Operator signature subject or decision binding differs")
        matches = [k for k in selected["trustRoot"]["keys"] if k["fingerprint"] == payload["signerFingerprint"]]
        if len(matches) != 1:
            raise operator_error("Operator key is not pinned")
        key = matches[0]
        start, end = operator_interval(payload)
        key_start, key_end = operator_interval(key)
        now = utc_microseconds(observed_at)
        if not key_start <= now < key_end:
            raise operator_error("Operator key is expired or not yet valid")
        if start < key_start or end > key_end or not start <= now < end:
            raise operator_error("Operator decision is expired, future or outside key eligibility")
        if not verify(
            bytes.fromhex(key["publicKeyHex"]), operator_signing_message(payload), bytes.fromhex(signed["signatureHex"])
        ):
            raise operator_error("Operator signature is invalid")
        receipt.update(
            payloadDigest=canonical_digest(payload),
            signerFingerprint=payload["signerFingerprint"],
            signatureVerified=True,
            status="VALID",
            claimStrength="Externally attested",
            verificationStrength="Enforced locally",
        )
    except (LifecycleError, ValueError, TypeError, KeyError, RecursionError):
        receipt["reason"] = "operator-signature-invalid"
    return receipt


def _invalid_public_artifact(policy: dict[str, Any], expected: dict[str, Any], code: str) -> dict[str, Any]:
    receipt = verify_operator_envelope(policy, {}, expected, observed_at="1970-01-01T00:00:00.000000Z")
    receipt["reason"] = code
    return receipt


def verify_operator_subject(
    container: dict[str, Any],
    kind: str,
    *,
    root: Path,
    signature_path: str,
    observed_at: str,
    operation_id: str | None = None,
    subject: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    policy = require_operator_authority(container, state=kind != "freeze")
    if policy is None:
        return None
    expected = expected_operator_decision(container, kind, operation_id=operation_id, subject=subject)
    try:
        relative = normalize_repo_path(signature_path, label="operator signature")
        (root / relative).lstat()
        raw = read_stable_repository_file(root, relative, max_bytes=MAX_SIGNATURE_BYTES, label="operator signature")
        envelope = load_json_object(raw, label="operator signature")
        receipt = verify_operator_envelope(policy, envelope, expected, observed_at=observed_at)
        receipt["artifact"] = {"path": relative, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    except FileNotFoundError:
        receipt = _invalid_public_artifact(policy, expected, "operator-signature-missing")
    except (LifecycleError, OSError, ValueError, TypeError, RecursionError):
        receipt = _invalid_public_artifact(policy, expected, "operator-signature-invalid")
    if policy["mode"] == "required" and not receipt["signatureVerified"]:
        raise LifecycleError(receipt["reason"], "Required operator signature did not verify", {"verification": receipt})
    return receipt


def verify_operator_freeze(manifest: dict[str, Any], *, root: Path, observed_at: str) -> dict[str, Any] | None:
    if require_operator_authority(manifest) is None:
        return None
    plan_root = normalize_repo_path(manifest.get("package", {}).get("planArtifactRoot"))
    return verify_operator_subject(
        manifest,
        "freeze",
        root=root,
        signature_path=plan_root + "/" + FREEZE_SIGNATURE_NAME,
        observed_at=observed_at,
    )


def require_operator_adoption(
    state: dict[str, Any], manifest: dict[str, Any], *, start_mode: str
) -> dict[str, Any] | None:
    current = require_operator_authority(state, state=True)
    selected = require_operator_authority(manifest)
    if (
        current is not None
        and current["mode"] == "required"
        and (selected is None or canonical_digest(current) != canonical_digest(selected))
    ):
        raise operator_error("Adoption cannot remove, downgrade or replace required operator policy")
    if selected is not None and selected["mode"] == "required" and start_mode != "approval-required":
        raise operator_error("Required operator policy needs separate execution authorization")
    return selected

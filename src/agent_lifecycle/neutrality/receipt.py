"""Detached neutrality receipt generation and verification."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .authority import RECEIPT_DOMAIN
from .canonical import canonical_bytes, load_json, sha256_hex
from .ed25519 import fingerprint, verify
from .errors import NeutralityError
from .paths import stable_read_bytes


def build_claims(
    *,
    operation: dict[str, Any],
    report: dict[str, Any],
    authority_digest: str,
    primary_path: str,
    receipt_path: str,
    policy: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    zero_counters = {
        key: int(report["counters"].get(key, 0))
        for key in [
            "findings",
            "skippedInputs",
            "opaqueInputs",
            "readRaces",
            "incompleteScans",
            "unsupportedArchives",
            "archiveLimitBreaches",
            "occupiedOutputConflicts",
            "pathAliasConflicts",
        ]
    }
    output_manifest = [
        {
            "publicationOrder": 1,
            "role": "primary-artifact",
            "path": primary_path,
            "required": True,
            "mustBeUnique": True,
            "contentIdentityRule": "sha256",
        },
        {
            "publicationOrder": 2,
            "role": "detached-commit-receipt",
            "path": receipt_path,
            "required": True,
            "mustBeUnique": True,
            "contentIdentityRule": "canonical-signed-envelope",
        },
    ]
    return {
        "schemaVersion": "agent-neutrality-claims.v3",
        "operation": operation,
        "projectionSchemaVersion": "agent-neutrality-subject-projection.v2",
        "profileDigest": sha256_hex(canonical_bytes(profile)),
        "scopeProfileDigest": sha256_hex(canonical_bytes({"scope": report["scope"]})),
        "archivePolicyDigest": sha256_hex(canonical_bytes(policy.get("archives", {}))),
        "externalAuthorityContractDigest": sha256_hex(canonical_bytes({"contract": "AGENT_LIFECYCLE_NEUTRALITY_*"})),
        "operationOutputManifestDigest": sha256_hex(canonical_bytes(output_manifest)),
        "primaryArtifactManifestDigest": sha256_hex(canonical_bytes({"primary": primary_path})),
        "workingTreeDigest": report["digests"]["workingTreeDigest"],
        "gitObjectSetDigest": report["digests"]["gitObjectSetDigest"],
        "subjectDigest": report["digests"]["subjectDigest"],
        "authorityDigest": authority_digest,
        "zeroCounters": zero_counters,
    }


def build_receipt(
    *,
    operation: dict[str, Any],
    claims: dict[str, Any],
    primary_sha256: str,
    primary_bytes: int,
    signer_fingerprint: str,
    signature: str,
) -> dict[str, Any]:
    claims_digest = sha256_hex(canonical_bytes(claims))
    return {
        "schemaVersion": "agent-neutrality-detached-receipt.v3",
        "operation": operation,
        "claimsDigest": claims_digest,
        "primaryArtifact": {"sha256": primary_sha256, "bytes": primary_bytes},
        "signer": {"algorithm": "Ed25519", "fingerprint": signer_fingerprint},
        "signature": signature,
    }


def verify_existing_receipt(
    *,
    receipt_path: Path,
    primary_path: Path,
    expected_operation: dict[str, Any] | None,
    trust_root_path: Path,
    expected_signer_fingerprint: str,
) -> bool:
    receipt = load_json(stable_read_bytes(receipt_path))
    primary = stable_read_bytes(primary_path)
    if receipt.get("schemaVersion") != "agent-neutrality-detached-receipt.v3":
        return False
    if expected_operation is not None and receipt.get("operation") != expected_operation:
        return False
    primary_identity = receipt.get("primaryArtifact")
    if not isinstance(primary_identity, dict):
        return False
    if primary_identity.get("sha256") != sha256_hex(primary):
        return False
    if primary_identity.get("bytes") != len(primary):
        return False
    trust_root = load_json(stable_read_bytes(trust_root_path))
    public_key = _public_key_for_fingerprint(trust_root, expected_signer_fingerprint)
    claims_digest = receipt.get("claimsDigest")
    signature = receipt.get("signature")
    if not isinstance(claims_digest, str) or not isinstance(signature, str):
        return False
    return verify(public_key, RECEIPT_DOMAIN + claims_digest.encode("ascii"), bytes.fromhex(signature))


def _public_key_for_fingerprint(trust_root: dict[str, Any], expected_fingerprint: str) -> bytes:
    if trust_root.get("schemaVersion") != "agent-neutrality-trust-root.v1":
        raise NeutralityError("unsupported trust root schemaVersion")
    for signer in trust_root.get("authorizedSigners", []):
        if not isinstance(signer, dict) or signer.get("fingerprint") != expected_fingerprint:
            continue
        public_key = bytes.fromhex(str(signer.get("publicKeyHex")))
        if fingerprint(public_key) != expected_fingerprint:
            raise NeutralityError("trust root signer fingerprint mismatch")
        return public_key
    raise NeutralityError("expected signer is not authorized by trust root")

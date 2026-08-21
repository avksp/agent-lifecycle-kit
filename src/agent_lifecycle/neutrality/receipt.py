"""Detached neutrality receipt generation and verification."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .authority import RECEIPT_V4_DOMAIN
from .canonical import canonical_bytes, load_json, sha256_hex
from .ed25519 import fingerprint, verify
from .errors import NeutralityError
from .paths import stable_read_bytes

REQUIRED_COMPLETENESS_COUNTERS = (
    "findings",
    "skippedInputs",
    "opaqueInputs",
    "readRaces",
    "incompleteScans",
    "unsupportedArchives",
    "archiveLimitBreaches",
    "occupiedOutputConflicts",
    "pathAliasConflicts",
)

CLAIMS_SCHEMA_VERSION = "agent-neutrality-claims.v4"
ENVELOPE_SCHEMA_VERSION = "agent-neutrality-receipt-envelope.v4"
RECEIPT_SCHEMA_VERSION = "agent-neutrality-detached-receipt.v4"


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
    zero_counters = require_zero_completeness_counters(report)
    scope_binding = _scope_binding(report)
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
        "schemaVersion": CLAIMS_SCHEMA_VERSION,
        "operation": operation,
        "projectionSchemaVersion": "agent-neutrality-subject-projection.v2",
        "profileDigest": sha256_hex(canonical_bytes(profile)),
        "scopeProfileDigest": sha256_hex(canonical_bytes(scope_binding)),
        "scopeBinding": scope_binding,
        "scopeBindingDigest": sha256_hex(canonical_bytes(scope_binding)),
        "deprecatedScope": scope_binding["deprecatedScope"],
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
    envelope = {
        "schemaVersion": ENVELOPE_SCHEMA_VERSION,
        "operation": operation,
        "claims": claims,
        "claimsDigest": claims_digest,
        "primaryArtifact": {"sha256": primary_sha256, "bytes": primary_bytes},
    }
    return {
        "schemaVersion": RECEIPT_SCHEMA_VERSION,
        "envelope": envelope,
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
    try:
        receipt = load_json(stable_read_bytes(receipt_path))
        primary = stable_read_bytes(primary_path)
        report = load_json(primary)
        trust_root = load_json(stable_read_bytes(trust_root_path))
        public_key = _public_key_for_fingerprint(trust_root, expected_signer_fingerprint)
    except (OSError, NeutralityError, TypeError, ValueError):
        return False
    if receipt.get("schemaVersion") != RECEIPT_SCHEMA_VERSION:
        return False
    if set(receipt) != {"schemaVersion", "envelope", "signer", "signature"}:
        return False
    envelope = receipt.get("envelope")
    if not isinstance(envelope, dict) or set(envelope) != {
        "schemaVersion",
        "operation",
        "claims",
        "claimsDigest",
        "primaryArtifact",
    }:
        return False
    if envelope.get("schemaVersion") != ENVELOPE_SCHEMA_VERSION:
        return False
    operation = envelope.get("operation")
    if not isinstance(operation, dict):
        return False
    if expected_operation is not None and operation != expected_operation:
        return False
    if report.get("operation") != operation:
        return False
    claims = envelope.get("claims")
    if not isinstance(claims, dict) or claims.get("schemaVersion") != CLAIMS_SCHEMA_VERSION:
        return False
    if claims.get("operation") != operation:
        return False
    claims_digest = envelope.get("claimsDigest")
    if not isinstance(claims_digest, str) or sha256_hex(canonical_bytes(claims)) != claims_digest:
        return False
    if report.get("claimsDigest") != claims_digest:
        return False
    primary_identity = envelope.get("primaryArtifact")
    if not isinstance(primary_identity, dict) or set(primary_identity) != {"sha256", "bytes"}:
        return False
    if primary_identity.get("sha256") != sha256_hex(primary):
        return False
    if primary_identity.get("bytes") != len(primary):
        return False
    try:
        zero_counters = require_zero_completeness_counters(report)
        actual_subject_digest = _report_subject_digest(report)
        scope_binding = _scope_binding(report)
    except NeutralityError:
        return False
    if (
        report.get("digests", {}).get("subjectDigest") != actual_subject_digest
        or claims.get("subjectDigest") != actual_subject_digest
        or claims.get("scopeBinding") != scope_binding
        or claims.get("scopeBindingDigest") != sha256_hex(canonical_bytes(scope_binding))
        or claims.get("scopeProfileDigest") != sha256_hex(canonical_bytes(scope_binding))
        or claims.get("deprecatedScope") != scope_binding["deprecatedScope"]
        or claims.get("zeroCounters") != zero_counters
    ):
        return False
    signer = receipt.get("signer")
    signature = receipt.get("signature")
    if (
        not isinstance(signer, dict)
        or set(signer) != {"algorithm", "fingerprint"}
        or signer.get("algorithm") != "Ed25519"
        or signer.get("fingerprint") != expected_signer_fingerprint
        or not isinstance(signature, str)
    ):
        return False
    try:
        signature_bytes = bytes.fromhex(signature)
    except ValueError:
        return False
    try:
        return verify(public_key, RECEIPT_V4_DOMAIN + canonical_bytes(envelope), signature_bytes)
    except (TypeError, ValueError):
        return False


def require_zero_completeness_counters(report: dict[str, Any]) -> dict[str, int]:
    """Return required counters only when every declared completeness value is zero."""

    counters = report.get("counters")
    if not isinstance(counters, dict):
        raise NeutralityError("neutrality scan counters are non-zero")
    zero_counters: dict[str, int] = {}
    for key in REQUIRED_COMPLETENESS_COUNTERS:
        value = counters.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value != 0:
            raise NeutralityError("neutrality scan counters are non-zero")
        zero_counters[key] = value
    return zero_counters


def _scope_binding(report: dict[str, Any]) -> dict[str, Any]:
    binding = report.get("scopeBinding")
    if isinstance(binding, dict):
        required = {
            "scope",
            "sourceClass",
            "sourceRevision",
            "trackedEntryDigest",
            "deprecatedScope",
            "includeLocalArtifacts",
            "localArtifactRoots",
            "localArtifactRootsDigest",
        }
        if set(binding) != required or binding.get("scope") != report.get("scope"):
            raise NeutralityError("neutrality scope binding is invalid")
        return binding
    scope = report.get("scope")
    if scope not in ("current-tree-complete", "full-repository"):
        raise NeutralityError("neutrality scope binding is missing")
    return {
        "scope": scope,
        "sourceClass": "legacy-unspecified",
        "sourceRevision": None,
        "trackedEntryDigest": "0" * 64,
        "deprecatedScope": True,
        "includeLocalArtifacts": False,
        "localArtifactRoots": [],
        "localArtifactRootsDigest": "0" * 64,
    }


def _report_subject_digest(report: dict[str, Any]) -> str:
    digests = report.get("digests")
    counters = report.get("counters")
    scanned = report.get("scanned")
    findings = report.get("findings")
    if not isinstance(digests, dict) or not isinstance(counters, dict) or not isinstance(scanned, dict):
        raise NeutralityError("neutrality report subject projection is invalid")
    if not isinstance(findings, list):
        raise NeutralityError("neutrality report findings are invalid")
    projection_digests = {key: value for key, value in digests.items() if key != "subjectDigest"}
    finding_details: list[dict[str, str]] = []
    for finding in findings:
        if (
            not isinstance(finding, dict)
            or set(finding) != {"source", "ruleId", "category"}
            or not all(isinstance(finding.get(key), str) for key in ("source", "ruleId", "category"))
        ):
            raise NeutralityError("neutrality report finding is invalid")
        finding_details.append(
            {
                "source": finding["source"],
                "ruleId": finding["ruleId"],
                "category": finding["category"],
            }
        )
    return sha256_hex(
        canonical_bytes(
            {
                "scopeBinding": _scope_binding(report),
                "counters": counters,
                "scanned": scanned,
                "digests": projection_digests,
                "findings": finding_details,
            }
        )
    )


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

"""External authority loading and validation for neutrality receipts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, load_json, sha256_hex
from .ed25519 import fingerprint, publickey_from_seed, sign, verify
from .errors import NeutralityError
from .paths import ensure_external_regular_file, stable_read_bytes

DENY_DOMAIN = b"agent-lifecycle-neutrality-deny-authority-v1\0"
RECEIPT_DOMAIN = b"agent-lifecycle-neutrality-claims-v3\0"


@dataclass(frozen=True)
class AuthorityBundle:
    """Runtime-only authority material.

    The deny authority and trust root are read by both producer and verifier.
    The signing seed is producer-only and is never included in durable outputs.
    """

    deny_authority: dict[str, Any]
    trust_root: dict[str, Any]
    signer_fingerprint: str
    signer_public_key_hex: str
    signing_seed: bytes | None
    authority_digest: str

    @property
    def deny_literals(self) -> list[str]:
        return list(self.deny_authority.get("denyLiterals", []))

    @property
    def deny_regexes(self) -> list[str]:
        return list(self.deny_authority.get("denyRegexes", []))

    def sign_claims_digest(self, claims_digest: str) -> str:
        if self.signing_seed is None:
            raise NeutralityError("signing key is required to produce a receipt")
        return sign(self.signing_seed, RECEIPT_DOMAIN + claims_digest.encode("ascii")).hex()


def load_authority_bundle(
    *,
    deny_authority_path: Path,
    trust_root_path: Path,
    signing_key_path: Path | None,
    expected_signer_fingerprint: str,
    workspace_root: Path,
    artifact_root: Path,
    release_root: Path | None = None,
    now: datetime | None = None,
) -> AuthorityBundle:
    """Load and verify the external neutrality authority contract."""

    now = now or datetime.now(UTC)
    deny_path = ensure_external_regular_file(
        deny_authority_path,
        workspace_root=workspace_root,
        artifact_root=artifact_root,
        release_root=release_root,
    )
    trust_path = ensure_external_regular_file(
        trust_root_path,
        workspace_root=workspace_root,
        artifact_root=artifact_root,
        release_root=release_root,
    )
    deny_authority = load_json_from_stable_path(deny_path)
    trust_root = load_json_from_stable_path(trust_path)
    _validate_fresh_document(deny_authority, "agent-neutrality-deny-authority.v1", now, 86_400)
    _validate_fresh_document(trust_root, "agent-neutrality-trust-root.v1", now, 31_622_400)
    signer = _find_signer(trust_root, expected_signer_fingerprint)
    _verify_deny_authority_signature(deny_authority, signer["publicKeyHex"], expected_signer_fingerprint)

    signing_seed: bytes | None = None
    signer_public_key_hex = signer["publicKeyHex"]
    if signing_key_path is not None:
        key_path = ensure_external_regular_file(
            signing_key_path,
            workspace_root=workspace_root,
            artifact_root=artifact_root,
            release_root=release_root,
        )
        signing_key = load_json_from_stable_path(key_path)
        _validate_fresh_document(signing_key, "agent-neutrality-signing-key.v1", now, 86_400)
        signing_seed = bytes.fromhex(_required_string(signing_key, "seedHex"))
        derived_public_key = publickey_from_seed(signing_seed).hex()
        derived_fingerprint = fingerprint(bytes.fromhex(derived_public_key))
        if derived_fingerprint != expected_signer_fingerprint:
            raise NeutralityError("signing key fingerprint does not match expected signer")
        if derived_public_key != signer_public_key_hex:
            raise NeutralityError("signing key public key is not authorized by trust root")

    authority_projection = {
        "denyAuthorityDigest": sha256_hex(canonical_bytes(_redacted_deny_projection(deny_authority))),
        "trustRootDigest": sha256_hex(canonical_bytes(_redacted_trust_projection(trust_root))),
        "signerFingerprint": expected_signer_fingerprint,
    }
    return AuthorityBundle(
        deny_authority=deny_authority,
        trust_root=trust_root,
        signer_fingerprint=expected_signer_fingerprint,
        signer_public_key_hex=signer_public_key_hex,
        signing_seed=signing_seed,
        authority_digest=sha256_hex(canonical_bytes(authority_projection)),
    )


def load_json_from_stable_path(path: Path) -> dict[str, Any]:
    return load_json(stable_read_bytes(path))


def sign_deny_authority(seed: bytes, payload: dict[str, Any]) -> dict[str, Any]:
    """Return a deny-authority payload signed by ``seed``.

    This helper is used by the negative/conformance tests and local host
    fixtures. It does not persist private material.
    """

    public_key = publickey_from_seed(seed)
    signer_fingerprint = fingerprint(public_key)
    unsigned = {k: v for k, v in payload.items() if k != "signature"}
    digest = sha256_hex(canonical_bytes(unsigned))
    signature = sign(seed, DENY_DOMAIN + digest.encode("ascii")).hex()
    signed = dict(unsigned)
    signed["signature"] = {
        "algorithm": "Ed25519",
        "signerFingerprint": signer_fingerprint,
        "value": signature,
    }
    return signed


def trust_root_for_seed(seed: bytes, *, issued_at: datetime, expires_at: datetime) -> dict[str, Any]:
    public_key = publickey_from_seed(seed)
    return {
        "schemaVersion": "agent-neutrality-trust-root.v1",
        "issuedAt": _format_time(issued_at),
        "expiresAt": _format_time(expires_at),
        "authorizedSigners": [
            {
                "fingerprint": fingerprint(public_key),
                "publicKeyHex": public_key.hex(),
            }
        ],
    }


def signing_key_for_seed(seed: bytes, *, issued_at: datetime, expires_at: datetime) -> dict[str, Any]:
    public_key = publickey_from_seed(seed)
    return {
        "schemaVersion": "agent-neutrality-signing-key.v1",
        "issuedAt": _format_time(issued_at),
        "expiresAt": _format_time(expires_at),
        "fingerprint": fingerprint(public_key),
        "seedHex": seed.hex(),
    }


def _verify_deny_authority_signature(
    deny_authority: dict[str, Any],
    public_key_hex: str,
    expected_signer_fingerprint: str,
) -> None:
    signature = deny_authority.get("signature")
    if not isinstance(signature, dict):
        raise NeutralityError("deny authority is missing signature")
    if signature.get("algorithm") != "Ed25519":
        raise NeutralityError("deny authority uses unsupported signature algorithm")
    if signature.get("signerFingerprint") != expected_signer_fingerprint:
        raise NeutralityError("deny authority signer fingerprint mismatch")
    signature_hex = _required_string(signature, "value")
    unsigned = {k: v for k, v in deny_authority.items() if k != "signature"}
    digest = sha256_hex(canonical_bytes(unsigned))
    if not verify(
        bytes.fromhex(public_key_hex),
        DENY_DOMAIN + digest.encode("ascii"),
        bytes.fromhex(signature_hex),
    ):
        raise NeutralityError("deny authority signature verification failed")


def _find_signer(trust_root: dict[str, Any], expected_fingerprint: str) -> dict[str, str]:
    signers = trust_root.get("authorizedSigners")
    if not isinstance(signers, list):
        raise NeutralityError("trust root authorizedSigners must be a list")
    for signer in signers:
        if not isinstance(signer, dict):
            continue
        if signer.get("fingerprint") == expected_fingerprint:
            public_key_hex = _required_string(signer, "publicKeyHex")
            if fingerprint(bytes.fromhex(public_key_hex)) != expected_fingerprint:
                raise NeutralityError("trust root signer public key does not match fingerprint")
            return {"fingerprint": expected_fingerprint, "publicKeyHex": public_key_hex}
    raise NeutralityError("expected signer is not authorized by trust root")


def _validate_fresh_document(
    document: dict[str, Any],
    schema_version: str,
    now: datetime,
    max_validity_seconds: int,
) -> None:
    if document.get("schemaVersion") != schema_version:
        raise NeutralityError(f"expected {schema_version}")
    issued_at = _parse_time(_required_string(document, "issuedAt"))
    expires_at = _parse_time(_required_string(document, "expiresAt"))
    if expires_at <= issued_at:
        raise NeutralityError("authority expiresAt must be after issuedAt")
    if expires_at - issued_at > timedelta(seconds=max_validity_seconds):
        raise NeutralityError("authority validity window is too wide")
    if now < issued_at - timedelta(seconds=300):
        raise NeutralityError("authority issuedAt is in the future")
    if now > expires_at + timedelta(seconds=300):
        raise NeutralityError("authority is stale")


def _redacted_deny_projection(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": document.get("schemaVersion"),
        "issuedAt": document.get("issuedAt"),
        "expiresAt": document.get("expiresAt"),
        "denyLiteralCount": len(document.get("denyLiterals", [])),
        "denyRegexCount": len(document.get("denyRegexes", [])),
        "signature": document.get("signature"),
    }


def _redacted_trust_projection(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": document.get("schemaVersion"),
        "issuedAt": document.get("issuedAt"),
        "expiresAt": document.get("expiresAt"),
        "authorizedSignerFingerprints": [
            signer.get("fingerprint")
            for signer in document.get("authorizedSigners", [])
            if isinstance(signer, dict)
        ],
    }


def _required_string(document: dict[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        raise NeutralityError(f"{key} must be a non-empty string")
    return value


def _parse_time(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise NeutralityError("timestamps must include timezone")
    return parsed.astimezone(UTC)


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

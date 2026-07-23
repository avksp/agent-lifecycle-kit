"""Neutrality-specific exceptions."""

from __future__ import annotations

from typing import Any, TextIO

from agent_lifecycle.contracts.canonical import canonical_bytes
from agent_lifecycle.contracts.errors import LifecycleError

_CODE_RULES: tuple[tuple[str, str], ...] = (
    ("signing key is required", "neutrality-signing-key-required"),
    ("signing key fingerprint does not match", "neutrality-signing-key-mismatch"),
    ("signing key public key is not authorized", "neutrality-signing-key-unauthorized"),
    ("missing signature", "neutrality-authority-missing-signature"),
    ("unsupported signature algorithm", "neutrality-unsupported-signature-algorithm"),
    ("signer fingerprint mismatch", "neutrality-authority-signer-mismatch"),
    ("gate receipt signature verification failed", "neutrality-gate-signature-invalid"),
    ("deny authority signature verification failed", "neutrality-authority-signature-invalid"),
    ("signature verification failed", "neutrality-signature-invalid"),
    ("authorizedsigners must be a list", "neutrality-trust-root-invalid"),
    ("trust root signer public key does not match", "neutrality-trust-root-signer-mismatch"),
    ("expected signer is not authorized", "neutrality-signer-unauthorized"),
    ("unsupported trust root schemaversion", "neutrality-trust-root-schema-unsupported"),
    ("unsupported neutrality policy schemaversion", "neutrality-policy-schema-unsupported"),
    ("expected agent-neutrality", "neutrality-authority-schema-mismatch"),
    ("expiresat must be after issuedat", "neutrality-authority-invalid-window"),
    ("validity window is too wide", "neutrality-authority-invalid-window"),
    ("issuedat is in the future", "neutrality-authority-not-yet-valid"),
    ("authority is stale", "neutrality-authority-stale"),
    ("timestamps must include timezone", "neutrality-timestamp-invalid"),
    ("must be a non-empty string", "neutrality-field-invalid"),
    ("must be an object", "neutrality-field-invalid"),
    ("must be a list of strings", "neutrality-field-invalid"),
    ("must be a positive integer", "neutrality-field-invalid"),
    ("external authority paths must be absolute", "neutrality-external-authority-path-invalid"),
    ("external authority path is inside a forbidden root", "neutrality-external-authority-forbidden-root"),
    ("external authority path must not be a symlink", "neutrality-external-authority-symlink"),
    ("external authority path must be a regular file", "neutrality-external-authority-not-regular"),
    ("external authority path must not have multiple hard links", "neutrality-external-authority-hard-link"),
    ("not a regular file", "neutrality-input-not-regular"),
    ("file exceeds max bytes", "neutrality-input-too-large"),
    ("read exceeds max bytes", "neutrality-input-too-large"),
    ("stable read identity changed", "neutrality-stable-read-race"),
    ("invalid repository-relative path", "neutrality-repository-path-invalid"),
    ("repository-relative path is too long", "neutrality-repository-path-invalid"),
    ("output path alias conflict", "neutrality-output-alias-conflict"),
    ("operation request claims are missing", "neutrality-operation-request-invalid"),
    ("operation request protocoloutputs are missing", "neutrality-operation-request-invalid"),
    ("report path is not authorized", "neutrality-output-not-authorized"),
    ("requested report path is not authorized", "neutrality-output-not-authorized"),
    ("existing output paths do not match", "neutrality-output-occupied"),
    ("operation output path is occupied", "neutrality-output-occupied"),
    ("neutrality findings are non-zero", "neutrality-findings-nonzero"),
    ("neutrality scan counters are non-zero", "neutrality-counters-nonzero"),
    ("neutrality gate counters are non-zero", "neutrality-counters-nonzero"),
    ("receipt verification failed", "neutrality-receipt-verification-failed"),
    ("gate receipt path is already occupied", "neutrality-gate-receipt-occupied"),
    ("gate receipt generatedat is missing", "neutrality-gate-generated-at-missing"),
    ("gate receipt attestation is missing", "neutrality-gate-attestation-missing"),
    ("gate receipt attestation binding mismatch", "neutrality-gate-attestation-mismatch"),
    ("gate receipt", "neutrality-gate-binding-mismatch"),
    ("operation output must match receipt", "neutrality-gate-output-mismatch"),
    ("gate receipt must be repository-relative", "neutrality-gate-receipt-path-invalid"),
    ("gate receipt escapes workspace", "neutrality-gate-receipt-path-invalid"),
    ("operation outputs must be repository-relative", "neutrality-output-path-invalid"),
    ("operation output escapes workspace", "neutrality-output-path-invalid"),
    ("required environment variable is not set", "neutrality-env-missing"),
    ("invalid json", "neutrality-invalid-json"),
    ("expected object", "neutrality-json-object-required"),
)


class NeutralityError(LifecycleError):
    """A fail-closed neutrality contract violation."""

    def __init__(self, message: str, *, code: str | None = None, details: dict[str, Any] | None = None):
        super().__init__(code or neutrality_error_code(message), message, details or {})


def neutrality_error_code(message: str) -> str:
    normalized = message.casefold()
    for marker, code in _CODE_RULES:
        if marker in normalized:
            return code
    return "neutrality-contract-violation"


def write_neutrality_error(exc: NeutralityError, stream: TextIO) -> None:
    stream.write(canonical_bytes(exc.to_json()).decode("utf-8") + "\n")

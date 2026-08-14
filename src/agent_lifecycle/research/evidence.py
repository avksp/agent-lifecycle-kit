"""Input and digest helpers for bounded research evidence packages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object, sha256_hex


MAX_SOURCE_RECORDS = 128
MAX_CLAIM_RECORDS = 256
MAX_CITATION_RECORDS = 256
MAX_PROVENANCE_EDGES = 512
MAX_EVIDENCE_BYTES = 33_554_432
MAX_SNAPSHOT_BYTES = 33_554_432


def load_evidence_package(path: Path, *, max_bytes: int = MAX_EVIDENCE_BYTES) -> dict[str, Any]:
    """Load one explicit local package without fetching or following locators."""

    if not path.is_file():
        raise LifecycleError("research-package-missing", "research evidence package was not found", {"path": path.name})
    try:
        size = path.stat().st_size
        if size > max_bytes:
            raise LifecycleError(
                "research-package-too-large",
                "research evidence package exceeds the byte limit",
                {"byteCount": size, "maxBytes": max_bytes},
            )
        return load_json_object(path.read_bytes(), label="research evidence package")
    except OSError as exc:
        raise LifecycleError("research-package-read-failed", "research evidence package could not be read") from exc


def read_source_snapshot(path: Path, *, max_bytes: int = MAX_SNAPSHOT_BYTES) -> bytes:
    """Read a caller-supplied snapshot; the caller decides which source it supports."""

    if not path.is_file():
        raise LifecycleError("research-snapshot-missing", "source snapshot was not found", {"path": path.name})
    try:
        size = path.stat().st_size
        if size > max_bytes:
            raise LifecycleError(
                "research-snapshot-too-large",
                "source snapshot exceeds the byte limit",
                {"byteCount": size, "maxBytes": max_bytes},
            )
        return path.read_bytes()
    except OSError as exc:
        raise LifecycleError("research-snapshot-read-failed", "source snapshot could not be read") from exc


def package_digest(package: dict[str, Any]) -> str:
    """Return the digest of a package body without its self-digest field."""

    return canonical_digest({key: value for key, value in package.items() if key != "packageDigest"})


def claim_digest(claim: str) -> str:
    """Return a stable digest for the normalized claim text."""

    return canonical_digest({"claim": claim})


def quote_digest(quote: str | bytes) -> str:
    """Return a byte digest for a quoted source fragment."""

    data = quote.encode("utf-8") if isinstance(quote, str) else quote
    return sha256_hex(data)


def snapshot_digest(snapshot: str | bytes) -> str:
    """Return a byte digest for a supplied source snapshot."""

    data = snapshot.encode("utf-8") if isinstance(snapshot, str) else snapshot
    return sha256_hex(data)


def decode_snapshot(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LifecycleError("research-snapshot-not-utf8", "source snapshot must be UTF-8") from exc

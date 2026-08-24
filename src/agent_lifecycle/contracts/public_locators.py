"""Canonical, offline validation for public HTTP(S) evidence locators."""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.schema_builders import open_object_schema

PUBLIC_LOCATOR_SCHEMA = "agent-public-evidence-locator.v1"
MAX_PUBLIC_LOCATOR_BYTES = 4096
PUBLIC_LOCATOR_SCHEMES = ("http", "https")

_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")

PUBLIC_LOCATOR_SCHEMAS: dict[str, dict[str, Any]] = {
    PUBLIC_LOCATOR_SCHEMA: open_object_schema(
        PUBLIC_LOCATOR_SCHEMA,
        required=["schemaVersion", "status", "value", "scheme", "host"],
        properties={
            "status": {"const": "PASS"},
            "value": {"type": "string", "minLength": 1, "maxLength": MAX_PUBLIC_LOCATOR_BYTES},
            "scheme": {"enum": list(PUBLIC_LOCATOR_SCHEMES)},
            "host": {"type": "string", "minLength": 1, "maxLength": 253},
            "port": {"type": ["integer", "null"], "minimum": 1, "maximum": 65535},
            "blockers": {"type": "array", "maxItems": 16, "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
        },
    )
}


def normalize_public_locator(value: str, *, label: str = "public locator") -> str:
    """Return one canonical HTTP(S) locator without granting network authority."""

    parsed = _parse_public_locator(value, label=label)
    hostname = _normalize_hostname(parsed.hostname, label=label)
    port = _validated_port(parsed, label=label)
    if port in {80, 443} and parsed.scheme.lower() == ("http" if port == 80 else "https"):
        port = None
    netloc = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None:
        netloc = f"{netloc}:{port}"
    normalized = urlunsplit((parsed.scheme.lower(), netloc, parsed.path, parsed.query, parsed.fragment))
    if len(normalized.encode("utf-8")) > MAX_PUBLIC_LOCATOR_BYTES:
        raise LifecycleError(
            "public-locator-too-large",
            f"{label}: locator exceeds {MAX_PUBLIC_LOCATOR_BYTES} bytes",
        )
    return normalized


def validate_public_locator(value: Any, *, label: str = "public locator") -> dict[str, Any]:
    """Return a stable validation envelope for one public locator."""

    try:
        normalized = normalize_public_locator(value, label=label)
        parsed = urlsplit(normalized)
        return {
            "schemaVersion": PUBLIC_LOCATOR_SCHEMA,
            "status": "PASS",
            "value": normalized,
            "scheme": parsed.scheme,
            "host": parsed.hostname,
            "port": parsed.port,
            "blockers": [],
            "productionPromotionClaimed": False,
        }
    except LifecycleError as exc:
        body = {
            "schemaVersion": PUBLIC_LOCATOR_SCHEMA,
            "status": "FAIL",
            "value": value if isinstance(value, str) else None,
            "scheme": None,
            "host": None,
            "port": None,
            "blockers": [{"code": exc.code, "message": exc.message}],
            "productionPromotionClaimed": False,
        }
        return body


def require_public_locator(value: Any, *, label: str = "public locator") -> str:
    """Validate a locator or raise its stable lifecycle error."""

    return normalize_public_locator(value, label=label)


def _parse_public_locator(value: Any, *, label: str) -> SplitResult:
    if not isinstance(value, str) or not value:
        raise LifecycleError("public-locator-required", f"{label}: HTTP(S) locator is required")
    if len(value.encode("utf-8")) > MAX_PUBLIC_LOCATOR_BYTES:
        raise LifecycleError(
            "public-locator-too-large",
            f"{label}: locator exceeds {MAX_PUBLIC_LOCATOR_BYTES} bytes",
        )
    if any(character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise LifecycleError(
            "public-locator-control-character", f"{label}: whitespace or control characters are not allowed"
        )
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise LifecycleError("public-locator-invalid", f"{label}: locator cannot be parsed") from exc
    scheme = parsed.scheme.lower()
    if scheme not in PUBLIC_LOCATOR_SCHEMES:
        raise LifecycleError("public-locator-scheme-unsupported", f"{label}: only HTTP(S) locators are allowed")
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise LifecycleError("public-locator-credentials-forbidden", f"{label}: URL credentials are not allowed")
    try:
        hostname = parsed.hostname
    except ValueError as exc:
        raise LifecycleError("public-locator-host-invalid", f"{label}: host is invalid") from exc
    if not hostname:
        raise LifecycleError("public-locator-host-required", f"{label}: host is required")
    return parsed


def _normalize_hostname(hostname: str | None, *, label: str) -> str:
    if not hostname:
        raise LifecycleError("public-locator-host-required", f"{label}: host is required")
    host = hostname.rstrip(".")
    if not host:
        raise LifecycleError("public-locator-host-invalid", f"{label}: host is invalid")
    if ":" in host:
        try:
            return ipaddress.IPv6Address(host).compressed.lower()
        except ValueError as exc:
            raise LifecycleError("public-locator-host-invalid", f"{label}: IPv6 host is invalid") from exc
    try:
        ascii_host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise LifecycleError("public-locator-host-invalid", f"{label}: host encoding is invalid") from exc
    labels = ascii_host.split(".")
    if len(ascii_host) > 253 or any(not _HOST_LABEL.fullmatch(part) for part in labels):
        raise LifecycleError("public-locator-host-invalid", f"{label}: host is invalid")
    return ascii_host


def _validated_port(parsed: Any, *, label: str) -> int | None:
    try:
        port = parsed.port
    except ValueError as exc:
        raise LifecycleError("public-locator-port-invalid", f"{label}: port is invalid") from exc
    if port is not None and not 1 <= port <= 65535:
        raise LifecycleError("public-locator-port-invalid", f"{label}: port is invalid")
    return port


__all__ = [
    "MAX_PUBLIC_LOCATOR_BYTES",
    "PUBLIC_LOCATOR_SCHEMA",
    "PUBLIC_LOCATOR_SCHEMAS",
    "PUBLIC_LOCATOR_SCHEMES",
    "normalize_public_locator",
    "require_public_locator",
    "validate_public_locator",
]

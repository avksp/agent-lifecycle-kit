"""Host-operation receipt normalization helpers for adapters."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.host_protocol.contracts import HostOperationReceipt

REDACTED_VALUE = "<redacted>"
SENSITIVE_EXACT_KEYS = {
    "api_key",
    "apikey",
    "access_token",
    "authorization",
    "credential",
    "id_token",
    "password",
    "refresh_token",
    "secret",
    "session_token",
    "token",
}
SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
)


def normalize_host_operation_receipt(payload: dict[str, Any], *, redact_sensitive: bool = True) -> dict[str, Any]:
    """Return a closed host-operation receipt with optional sensitive redaction."""

    receipt = HostOperationReceipt.from_json(payload).to_json()
    if not redact_sensitive:
        return receipt
    return _redact(receipt)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                redacted[key] = REDACTED_VALUE
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.replace("-", "_").lower()
    return normalized in SENSITIVE_EXACT_KEYS or any(part in normalized for part in SENSITIVE_KEY_PARTS)

"""Shared redaction primitives for receipts that may carry host output."""

from __future__ import annotations

import re
from typing import Any

REDACTED_VALUE = "<redacted>"
LOCAL_PATH_REDACTION = "<local-path>"

_SENSITIVE_EXACT_KEYS = {
    "access_token",
    "accesstoken",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "credentials",
    "id_token",
    "idtoken",
    "password",
    "private_key",
    "privatekey",
    "refresh_token",
    "refreshtoken",
    "secret",
    "session_token",
    "sessiontoken",
    "token",
}
_SENSITIVE_SUFFIXES = (
    "_access_token",
    "_api_key",
    "_credential",
    "_key",
    "_password",
    "_private_key",
    "_refresh_token",
    "_secret",
    "_session_token",
    "_token",
)
_PRIVATE_KEY = re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", re.DOTALL)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_BARE_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}|"
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|"
    r"gh[pousr]_[A-Za-z0-9_]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{16,}|"
    r"AKIA[0-9A-Z]{16}"
    r")(?![A-Za-z0-9_-])"
)
_KEY_VALUE = re.compile(
    r"(?P<key>[\"']?[A-Za-z][A-Za-z0-9_.-]*[\"']?)(?P<separator>\s*[:=]\s*)(?P<value>Bearer\s+[^\s,;}\]]+|\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*'|[^\s,;}\]]+)",
    re.IGNORECASE,
)
_LOCAL_PATH = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:"
    r"[A-Za-z]:[\\/](?:[A-Za-z0-9._~@+ -]+[\\/])*[A-Za-z0-9._~@+ -]+|"
    r"\\\\[^\s\"'<>]+|"
    r"\\(?:[A-Za-z0-9._~@+ -]+[\\/])+[A-Za-z0-9._~@+ -]+|"
    r"file:/+[^\s\"'<>]+|"
    r"/(?:[A-Za-z0-9._~@+-]+/)*[A-Za-z0-9._~@+-]+"
    r")",
    re.IGNORECASE,
)


def redact_text(value: str) -> tuple[str, bool]:
    """Redact common secret and local-path forms from text and report a change."""

    redacted, changed, _stats = redact_text_with_stats(value)
    return redacted.replace(LOCAL_PATH_REDACTION, REDACTED_VALUE), changed


def redact_text_with_stats(value: str) -> tuple[str, bool, dict[str, int]]:
    """Redact shared forms and expose coarse category counts to importers."""

    redacted = _PRIVATE_KEY.sub(REDACTED_VALUE, value)
    secret_count = len(_PRIVATE_KEY.findall(value))
    redacted = _BEARER.sub(f"Bearer {REDACTED_VALUE}", redacted)
    secret_count += len(_BEARER.findall(value))
    redacted = _BARE_TOKEN.sub(REDACTED_VALUE, redacted)
    secret_count += len(_BARE_TOKEN.findall(value))
    redacted, assignment_count = _KEY_VALUE.subn(_replace_sensitive_assignment, redacted)
    secret_count += assignment_count
    path_count = len(_LOCAL_PATH.findall(redacted))
    redacted = _LOCAL_PATH.sub(LOCAL_PATH_REDACTION, redacted)
    return redacted, redacted != value, {
        "secretLikeMarkersRedacted": secret_count,
        "localPathsRedacted": path_count,
    }


def contains_local_absolute_path(value: str) -> bool:
    """Return whether text contains a local absolute path or file URI."""

    return bool(_LOCAL_PATH.search(value))


def redact_value(value: Any) -> tuple[Any, bool]:
    """Redact nested receipt values while preserving JSON-compatible structure."""

    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        changed = False
        for key, item in value.items():
            if isinstance(key, str) and is_sensitive_key(key):
                result[key] = REDACTED_VALUE
                changed = True
                continue
            nested, nested_changed = redact_value(item)
            result[key] = nested
            changed = changed or nested_changed
        return result, changed
    if isinstance(value, list):
        result = []
        changed = False
        for item in value:
            nested, nested_changed = redact_value(item)
            result.append(nested)
            changed = changed or nested_changed
        return result, changed
    if isinstance(value, str):
        return redact_text(value)
    return value, False


def is_sensitive_key(key: str) -> bool:
    """Return whether a JSON key denotes a value that must not be retained."""

    normalized = key.replace("-", "_").lower()
    return normalized in _SENSITIVE_EXACT_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES)


def _replace_sensitive_assignment(match: re.Match[str]) -> str:
    key = match.group("key")
    if not is_sensitive_key(key.strip("\"'")):
        return match.group(0)
    value = match.group("value")
    replacement = _quoted_redaction(value)
    return f"{key}{match.group('separator')}{replacement}"


def _quoted_redaction(value: str) -> str:
    if value.startswith('"'):
        return f'"{REDACTED_VALUE}"'
    if value.startswith("'"):
        return f"'{REDACTED_VALUE}'"
    return REDACTED_VALUE

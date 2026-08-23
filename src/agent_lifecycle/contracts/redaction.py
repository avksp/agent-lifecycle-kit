"""Shared redaction primitives for receipts that may carry host output."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote_plus, urlsplit, urlunsplit

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
_HTTP_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
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

    redacted, urls, url_secret_count = _protect_http_urls(value)
    redacted, private_key_count = _replace_matches(_PRIVATE_KEY, redacted, REDACTED_VALUE)
    redacted, bearer_count = _replace_matches(_BEARER, redacted, f"Bearer {REDACTED_VALUE}")
    redacted, token_count = _replace_matches(_BARE_TOKEN, redacted, REDACTED_VALUE)
    redacted, assignment_count = _redact_sensitive_assignments(redacted)
    secret_count = url_secret_count + private_key_count + bearer_count + token_count + assignment_count
    path_count = len(_LOCAL_PATH.findall(redacted))
    redacted = _LOCAL_PATH.sub(LOCAL_PATH_REDACTION, redacted)
    redacted = _restore_http_urls(redacted, urls)
    return redacted, redacted != value, {
        "secretLikeMarkersRedacted": secret_count,
        "localPathsRedacted": path_count,
    }


def contains_local_absolute_path(value: str) -> bool:
    """Return whether text contains a local absolute path or file URI."""

    protected = _HTTP_URL.sub("__alk_http_url__", value)
    return bool(_LOCAL_PATH.search(protected))


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


def _replace_matches(pattern: re.Pattern[str], value: str, replacement: str) -> tuple[str, int]:
    """Apply a fixed replacement and count only matches in the input."""

    matches = list(pattern.finditer(value))
    return pattern.sub(replacement, value), len(matches)


def _redact_sensitive_assignments(value: str) -> tuple[str, int]:
    """Redact sensitive assignments without counting safe key/value pairs."""

    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        replacement = _replace_sensitive_assignment(match)
        if replacement != match.group(0):
            count += 1
        return replacement

    return _KEY_VALUE.sub(replace, value), count


def _protect_http_urls(value: str) -> tuple[str, list[str], int]:
    """Redact secrets inside HTTP URLs while shielding their paths from path matching."""

    urls: list[str] = []
    secret_count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal secret_count
        redacted, count = _redact_http_url(match.group(0))
        urls.append(redacted)
        secret_count += count
        return f"__alk_http_url_{len(urls) - 1}__"

    return _HTTP_URL.sub(replace, value), urls, secret_count


def _restore_http_urls(value: str, urls: list[str]) -> str:
    """Restore URL spans after non-URL path and assignment processing."""

    for index, url in enumerate(urls):
        value = value.replace(f"__alk_http_url_{index}__", url)
    return value


def _redact_http_url(value: str) -> tuple[str, int]:
    """Redact URL credentials, sensitive query values and provider tokens."""

    try:
        parsed = urlsplit(value)
    except ValueError:
        return value, 0
    netloc = parsed.netloc
    secret_count = 0
    if "@" in netloc:
        _userinfo, host = netloc.rsplit("@", 1)
        netloc = f"{REDACTED_VALUE}@{host}"
        secret_count += 1
    query, query_count = _redact_url_query(parsed.query)
    fragment, fragment_count = _redact_url_query(parsed.fragment)
    secret_count += query_count + fragment_count
    redacted = urlunsplit((parsed.scheme, netloc, parsed.path, query, fragment))
    redacted, private_key_count = _replace_matches(_PRIVATE_KEY, redacted, REDACTED_VALUE)
    redacted, bearer_count = _replace_matches(_BEARER, redacted, f"Bearer {REDACTED_VALUE}")
    redacted, token_count = _replace_matches(_BARE_TOKEN, redacted, REDACTED_VALUE)
    return redacted, secret_count + private_key_count + bearer_count + token_count


def _redact_url_query(value: str) -> tuple[str, int]:
    """Redact values for sensitive URL query or fragment keys without normalizing safe text."""

    if not value:
        return value, 0
    parts = value.split("&")
    count = 0
    for index, part in enumerate(parts):
        if "=" not in part:
            continue
        key, _raw_value = part.split("=", 1)
        if is_sensitive_key(unquote_plus(key).strip("\"'")):
            parts[index] = f"{key}={REDACTED_VALUE}"
            count += 1
    return "&".join(parts), count


def _quoted_redaction(value: str) -> str:
    if value.startswith('"'):
        return f'"{REDACTED_VALUE}"'
    if value.startswith("'"):
        return f"'{REDACTED_VALUE}'"
    return REDACTED_VALUE

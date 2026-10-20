"""Shared redaction primitives for receipts that may carry host output."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import unquote, unquote_plus, urlsplit, urlunsplit

from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.public_locators import normalize_public_locator

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
    "proxy_authorization",
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
# Query signatures grant access to a signed URL. A public cryptographic
# signature in a structured receipt does not have the same secret meaning.
_SENSITIVE_QUERY_KEYS = {
    "awsaccesskeyid",
    "googleaccessid",
    "sig",
    "signature",
    "x_amz_credential",
    "x_amz_security_token",
    "x_amz_signature",
    "x_goog_credential",
    "x_goog_signature",
}
_PRIVATE_KEY = re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", re.DOTALL)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_BARE_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}|"
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|"
    r"gh[pousr]_[A-Za-z0-9_]{20,}|"
    r"glpat-[A-Za-z0-9_-]{20,}|"
    r"npm_[A-Za-z0-9]{20,}|"
    r"(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}|"
    r"hf_[A-Za-z0-9]{20,}|"
    r"AIza[A-Za-z0-9_-]{35,}|"
    r"xox[baprs]-[A-Za-z0-9-]{16,}|"
    r"AKIA[0-9A-Z]{16}"
    r")(?![A-Za-z0-9_-])"
)
_SENSITIVE_ASSIGNMENT_KEY = (
    "(?:"
    + "|".join(re.escape(key).replace("_", "[-_]") for key in sorted(_SENSITIVE_EXACT_KEYS))
    + "|[A-Za-z][A-Za-z0-9_.-]*(?:"
    + "|".join(re.escape(suffix).replace("_", "[-_]") for suffix in _SENSITIVE_SUFFIXES)
    + "))"
)
_KEY_VALUE = re.compile(
    r"(?<![A-Za-z0-9_.-])(?P<key>(?:\\*[\"'])?" + _SENSITIVE_ASSIGNMENT_KEY + r"(?:\\*[\"'])?)(?P<separator>\s*[:=]\s*)"
    r"(?P<value>(?:Bearer|Basic)\s+[^\s,;}\]]+|"
    r"(?P<escaped_quote>\\+[\"'])(?:\\.|[^\\])*?(?P=escaped_quote)|"
    r"\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*'|[^\s,;}\]]+)",
    re.IGNORECASE,
)
# Authentication headers may carry either a single opaque credential or
# several comma-separated parameters (for example Digest authentication).
_AUTH_PARAMETER = (
    r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\s*=\s*"
    r'(?:"(?:\\.|[^"\\])*"|[^\s,;}\]]+(?:;[^\s,;}\]]+)*)'
)
_AUTHORIZATION_HEADER = re.compile(
    r"(?<![A-Za-z0-9_.-])(?P<key>(?:[\"'])?(?:proxy[-_])?authorization(?:[\"'])?)"
    r"(?P<separator>\s*[:=]\s*)"
    r"[A-Za-z][A-Za-z0-9_.-]*\s+"
    r"(?:" + _AUTH_PARAMETER + r"(?:\s*,\s*" + _AUTH_PARAMETER + r")*|[^\s,;}\]]+)",
    re.IGNORECASE,
)
_HTTP_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_HTTP_AUTHORITY = re.compile(r"https?://[^/?#]*", re.IGNORECASE)
_MAX_NESTED_URL_DEPTH = 8
_MAX_QUERY_DECODE_PASSES = 8
_LOCAL_PATH = re.compile(
    r"(?<![\w.-])(?:"
    r"[A-Za-z]:[\\/](?:[^\r\n\\/\"'<>:*?|]+[\\/])*[^\r\n\\/\"'<>:*?|]+|"
    r"\\\\[^\s\"'<>]+|"
    r"\\(?:[^\r\n\\/\"'<>:*?|]+[\\/])+[^\r\n\\/\"'<>:*?|]+|"
    r"file:/+[^\s\"'<>]+|"
    r"/(?:[^\s\\/\"'<>:;,{}\[\]()]+/)*[^\s\\/\"'<>:;,{}\[\]()]+"
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
    redacted, marker_count = _redact_common_secret_markers(redacted)
    redacted, assignment_count = _redact_sensitive_assignments(redacted)
    secret_count = url_secret_count + marker_count + assignment_count
    path_count = len(_LOCAL_PATH.findall(redacted))
    redacted = _LOCAL_PATH.sub(LOCAL_PATH_REDACTION, redacted)
    redacted = _restore_http_urls(redacted, urls)
    return (
        redacted,
        redacted != value,
        {
            "secretLikeMarkersRedacted": secret_count,
            "localPathsRedacted": path_count,
        },
    )


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
        result_list: list[Any] = []
        changed = False
        for item in value:
            nested, nested_changed = redact_value(item)
            result_list.append(nested)
            changed = changed or nested_changed
        return result_list, changed
    if isinstance(value, str):
        return redact_text(value)
    return value, False


def is_sensitive_key(key: str) -> bool:
    """Return whether a JSON key denotes a value that must not be retained."""

    normalized = key.replace("-", "_").lower()
    return normalized in _SENSITIVE_EXACT_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES)


def _replace_sensitive_assignment(match: re.Match[str]) -> str:
    key = match.group("key")
    if not is_sensitive_key(key.strip("\\\"'")):
        return match.group(0)
    value = match.group("value")
    replacement = _quoted_redaction(value)
    return f"{key}{match.group('separator')}{replacement}"


def _replace_matches(pattern: re.Pattern[str], value: str, replacement: str) -> tuple[str, int]:
    """Apply a fixed replacement and count only matches in the input."""

    matches = list(pattern.finditer(value))
    return pattern.sub(replacement, value), len(matches)


def _redact_common_secret_markers(value: str) -> tuple[str, int]:
    value, private_key_count = _replace_matches(_PRIVATE_KEY, value, REDACTED_VALUE)
    value, bearer_count = _replace_matches(_BEARER, value, f"Bearer {REDACTED_VALUE}")
    value, token_count = _replace_matches(_BARE_TOKEN, value, REDACTED_VALUE)
    return value, private_key_count + bearer_count + token_count


def _has_secret_outside_urls(value: str, url_spans: list[tuple[int, int]]) -> bool:
    for pattern in (_KEY_VALUE, _PRIVATE_KEY, _BEARER, _BARE_TOKEN):
        span_index = 0
        for match in pattern.finditer(value):
            if pattern is _KEY_VALUE and not is_sensitive_key(match.group("key").strip("\\\"'")):
                continue
            while span_index < len(url_spans) and url_spans[span_index][1] <= match.start():
                span_index += 1
            if span_index == len(url_spans) or match.start() < url_spans[span_index][0]:
                return True
    return False


def _redact_sensitive_assignments(value: str, *, structured_only: bool = False) -> tuple[str, int]:
    """Redact sensitive assignments without counting safe key/value pairs."""

    count = 0
    if not structured_only:
        value, count = _AUTHORIZATION_HEADER.subn(
            lambda match: match.group("key") + match.group("separator") + REDACTED_VALUE, value
        )

    parts: list[str] = []
    cursor = 0
    for match in _KEY_VALUE.finditer(value):
        if match.start() < cursor:
            continue
        if structured_only and not match.group("value").startswith(("[", "{")):
            continue
        replacement = _replace_sensitive_assignment(match)
        end = match.end()
        if replacement != match.group(0) and match.group("value").startswith(("[", "{")):
            try:
                _container, end = json.JSONDecoder().raw_decode(value, match.start("value"))
            except (ValueError, RecursionError, MemoryError):
                # An ambiguous container boundary cannot safely retain a tail.
                end = len(value)
        if replacement != value[match.start() : end]:
            count += 1
        parts.extend((value[cursor : match.start()], replacement))
        cursor = end

    parts.append(value[cursor:])
    return "".join(parts), count


def _protect_http_urls(value: str) -> tuple[str, dict[str, str], int]:
    """Redact secrets inside HTTP URLs while shielding their paths from path matching."""

    urls: dict[str, str] = {}
    secret_count = 0
    token_index = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal secret_count, token_index
        redacted, count = _redact_http_url(match.group(0))
        token = f"__alk_http_url_{token_index}__"
        while token in value:
            token_index += 1
            token = f"__alk_http_url_{token_index}__"
        token_index += 1
        urls[token] = redacted
        secret_count += count
        return token

    return _HTTP_URL.sub(replace, value), urls, secret_count


def _restore_http_urls(value: str, urls: dict[str, str]) -> str:
    """Restore URL spans after non-URL path and assignment processing."""

    if not urls:
        return value
    # One substitution pass cannot revisit tokens inside restored URL values.
    tokens = "|".join(re.escape(token) for token in urls)
    return re.sub(tokens, lambda match: urls[match.group(0)], value)


def _redact_http_url(value: str, *, depth: int = 0) -> tuple[str, int]:
    """Redact URL credentials, sensitive query values and provider tokens."""

    if depth >= _MAX_NESTED_URL_DEPTH:
        return REDACTED_VALUE, 1
    try:
        parsed = urlsplit(value)
    except ValueError:
        # Invalid URL syntax cannot safely identify credential boundaries.
        # Keep surrounding diagnostics, but never restore this raw span.
        return REDACTED_VALUE, 1
    netloc = parsed.netloc
    host_authority = netloc.rsplit("@", 1)[-1]
    try:
        normalize_public_locator(urlunsplit((parsed.scheme, host_authority, "", "", "")), label="URL authority")
    except LifecycleError:
        # Userinfo does not make a missing host or malformed port valid.
        return REDACTED_VALUE, 1
    secret_count = 0
    if "@" in netloc:
        _userinfo, host = netloc.rsplit("@", 1)
        netloc = f"{REDACTED_VALUE}@{host}"
        secret_count += 1
    query, query_count = _redact_url_query(parsed.query, depth=depth)
    fragment, fragment_count = _redact_url_query(parsed.fragment, depth=depth)
    path, nested_path_count = _redact_nested_http_urls(parsed.path, depth=depth)
    path, path_count = _redact_sensitive_assignments(unquote_plus(path))
    path_count += nested_path_count
    if not path_count:
        path = parsed.path
    secret_count += query_count + fragment_count + path_count
    redacted = urlunsplit((parsed.scheme, netloc, path, query, fragment))
    redacted, marker_count = _redact_common_secret_markers(redacted)
    if "@" not in netloc:
        try:
            redacted = normalize_public_locator(redacted, label="redacted URL")
        except LifecycleError:
            # Parseable malformed authorities can hide credentials in the
            # path. Never restore a span whose authority cannot be validated.
            return REDACTED_VALUE, 1
    return redacted, secret_count + marker_count


def _redact_nested_http_urls(value: str, *, depth: int, decode_passes: int = 0) -> tuple[str, int]:
    # Keep visible URLs intact while exposing adjacent encoded spans. A safe
    # visible URL must not stop decoding a different span in the component.
    matches = list(_HTTP_URL.finditer(value))
    if not matches:
        # Expose percent-encoded markers without turning their literal '+'
        # into a form separator. Refuse a still-encoded sensitive component
        # instead of rewriting a marker that may precede an encoded URI.
        marker_view = unquote(value)
        redacted, assignment_count = _redact_sensitive_assignments(marker_view)
        redacted, marker_count = _redact_common_secret_markers(redacted)
        count = assignment_count + marker_count
        decoded = unquote_plus(value)
        if count:
            return (REDACTED_VALUE if marker_view != value or decoded != value else redacted), count
        if decoded == value:
            return value, 0
        if any(
            any(char.isspace() or char in "\"'<>" for char in match.group(0))
            for match in _HTTP_AUTHORITY.finditer(decoded)
        ):
            return REDACTED_VALUE, 1
        if decode_passes >= _MAX_QUERY_DECODE_PASSES:
            return REDACTED_VALUE, 1
        redacted, count = _redact_nested_http_urls(decoded, depth=depth, decode_passes=decode_passes + 1)
        return (redacted if count else value), count
    # Consume complete sensitive containers before splitting embedded URLs.
    # Undecoded container openers must survive until their boundary is visible.
    structured, structured_count = _redact_sensitive_assignments(value, structured_only=True)
    if structured_count:
        redacted, count = _redact_nested_http_urls(structured, depth=depth, decode_passes=decode_passes)
        return redacted, structured_count + count
    # Inspect decoded views before splitting a sensitive value across URL spans.
    # Return only a tombstone for ambiguous components, never decoded userinfo.
    decoded_view = value
    for pass_index in range(_MAX_QUERY_DECODE_PASSES + 1):
        url_spans = [(match.start(), match.end()) for match in _HTTP_URL.finditer(decoded_view)]
        if _has_secret_outside_urls(decoded_view, url_spans):
            return REDACTED_VALUE, 1
        next_view = unquote_plus(decoded_view)
        if next_view == decoded_view:
            break
        if pass_index == _MAX_QUERY_DECODE_PASSES:
            return REDACTED_VALUE, 1
        decoded_view = next_view
    pieces = []
    cursor = 0
    count = 0
    for match in matches:
        prefix, prefix_count = _redact_nested_http_urls(
            value[cursor : match.start()], depth=depth, decode_passes=decode_passes
        )
        redacted_url, removed = _redact_http_url(match.group(0), depth=depth + 1)
        if redacted_url == REDACTED_VALUE:
            return REDACTED_VALUE, 1
        pieces.extend([prefix, redacted_url])
        count += prefix_count + removed
        cursor = match.end()
    suffix, suffix_count = _redact_nested_http_urls(value[cursor:], depth=depth, decode_passes=decode_passes)
    pieces.append(suffix)
    count += suffix_count
    return ("".join(pieces) if count else value), count


def _redact_url_query(value: str, *, depth: int = 0) -> tuple[str, int]:
    """Redact values for sensitive URL query or fragment keys without normalizing safe text."""

    if not value:
        return value, 0
    count = 0
    prefix, separator, routed_query = value.partition("?")
    if separator and ("=" not in prefix or prefix.startswith("/")):
        prefix, prefix_count = _redact_nested_http_urls(prefix, depth=depth)
        count += prefix_count
        prefix += separator
        value = routed_query
    else:
        prefix = ""
    parts = value.split("&")
    for index, part in enumerate(parts):
        key, separator, _raw_value = part.partition("=")
        if separator and _is_sensitive_query_key(key):
            parts[index] = f"{key}={REDACTED_VALUE}"
            count += 1
        else:
            redacted, nested_count = _redact_nested_http_urls(part, depth=depth)
            redacted, assignment_count = _redact_sensitive_assignments(unquote_plus(redacted))
            nested_count += assignment_count
            if nested_count:
                parts[index] = redacted
                count += nested_count
    return prefix + "&".join(parts), count


def _is_sensitive_query_key(key: str) -> bool:
    """Recognize signed query keys through bounded percent-encoding layers."""

    for _ in range(_MAX_QUERY_DECODE_PASSES + 1):
        normalized = key.strip("\"'").replace("-", "_").lower()
        if is_sensitive_key(normalized) or normalized in _SENSITIVE_QUERY_KEYS:
            return True
        decoded = unquote_plus(key)
        if decoded == key:
            return False
        key = decoded
    # Deeper encoding has an ambiguous key; do not retain its potential secret.
    return True


def _quoted_redaction(value: str) -> str:
    quote = re.match(r"\\*[\"']", value)
    if quote:
        return f"{quote[0]}{REDACTED_VALUE}{quote[0]}"
    return REDACTED_VALUE

"""Strict bounded JSON and closed schema validation shared by active readers."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from typing import cast as _validated_cast

from agent_lifecycle.contracts import LifecycleError, canonical_digest


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise LifecycleError(code, message)


def _r11_role_schema_matches(value: Any, schema: dict[str, Any], *, depth: int = 0) -> bool:
    """Strict supported keyword subset for pinned role schemas; unknown refuses.

    In addition to JSON Schema character limits, string maxima also bound UTF-8
    bytes. Date-time is validated as an actual UTC RFC3339 value, not annotation.
    No third-party validator or permissive fallback is used at runtime.
    """
    allowed = {
        "$schema",
        "title",
        "type",
        "enum",
        "anyOf",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minLength",
        "maxLength",
        "pattern",
        "minimum",
        "maximum",
        "multipleOf",
        "format",
    }
    if depth > 64 or not isinstance(schema, dict) or not set(schema) <= allowed:
        return False
    if "anyOf" in schema:
        branches = schema["anyOf"]
        if not isinstance(branches, list) or not branches or set(schema) - {"anyOf", "$schema", "title"}:
            return False
        return any(_r11_role_schema_matches(value, branch, depth=depth + 1) for branch in branches)
    kind = schema.get("type")
    if kind is not None:
        types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool, "null": type(None)}
        if kind not in types or type(value) is not types[kind]:
            return False
    elif "enum" not in schema:
        return False
    if "enum" in schema and not any(
        type(value) is type(candidate) and value == candidate for candidate in schema["enum"]
    ):
        return False
    if isinstance(value, dict):
        props = schema.get("properties")
        required = schema.get("required")
        if (
            schema.get("additionalProperties") is not False
            or not isinstance(props, dict)
            or not isinstance(required, list)
            or len(required) != len(set(required))
            or set(required) != set(props)
            or set(value) != set(props)
        ):
            return False
        return all(_r11_role_schema_matches(value[key], props[key], depth=depth + 1) for key in props)
    if isinstance(value, list):
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 65_536):
            return False
        if schema.get("uniqueItems") is True:
            try:
                if len({canonical_digest(item) for item in value}) != len(value):
                    return False
            except (TypeError, ValueError, UnicodeError):
                return False
        if "items" not in schema:
            return schema.get("maxItems") == 0 and not value
        return all(_r11_role_schema_matches(item, schema["items"], depth=depth + 1) for item in value)
    if isinstance(value, str):
        try:
            size = len(value.encode("utf-8"))
        except UnicodeError:
            return False
        if len(value) < schema.get("minLength", 0) or size > schema.get("maxLength", 2_097_152):
            return False
        if "pattern" in schema:
            try:
                if re.fullmatch(schema["pattern"], value) is None:
                    return False
            except (re.error, TypeError):
                return False
        if "format" in schema:
            if (
                schema["format"] != "date-time"
                or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|\+00:00)", value) is None
            ):
                return False
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                offset = parsed.utcoffset()
                if offset is None or offset.total_seconds() != 0:
                    return False
            except ValueError:
                return False
    if type(value) is int:
        if not schema.get("minimum", value) <= value <= schema.get("maximum", value):
            return False
        if "multipleOf" in schema:
            step = schema["multipleOf"]
            if type(step) is not int or step <= 0 or value % step:
                return False
    return True


def _r11_json(raw: bytes, *, limit: int) -> dict[str, Any]:
    """Bounded JSON object with duplicate-key/nonfinite rejection at every depth."""
    _require(
        isinstance(raw, bytes) and 0 < len(raw) <= limit,
        "r11-review-evidence",
        "raw JSON is missing or exceeds its bound",
    )
    raw = _validated_cast(bytes, raw)

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value = {}
        for key, item in items:
            _require(key not in value, "r11-review-evidence", "duplicate JSON object key")
            value[key] = item
        return value

    def constant(_value: str) -> None:
        raise LifecycleError("r11-review-evidence", "nonfinite JSON value")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        # JSON escapes may encode lone surrogates, and 1e999 may decode to inf.
        json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise LifecycleError("r11-review-evidence", "raw JSON cannot be decoded") from exc
    _require(isinstance(value, dict), "r11-review-evidence", "JSON object is required")
    value = _validated_cast(dict[str, Any], value)
    return value


load_bounded_json = _r11_json
matches_closed_schema = _r11_role_schema_matches

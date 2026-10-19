"""Bounded stdlib evaluator for the pinned H04 profile schema vocabulary.

Only the internal profile consumer uses this subset. Schema authority remains
the frozen package lock; matching a schema never grants a capability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent_lifecycle.accounting.contracts import canonical

_MAX_DEPTH = 64
_MAX_REFERENCES = 64
_MAX_VISITS = 65536
_KEYWORDS = frozenset(
    {
        "$ref",
        "type",
        "const",
        "enum",
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
        "allOf",
        "anyOf",
        "if",
        "then",
    }
)
_TYPES = frozenset({"null", "boolean", "integer", "number", "string", "array", "object"})


class _Refusal(ValueError):
    """Malformed, unsupported or over-budget schema/input; never a branch miss."""


@dataclass
class _Budget:
    remaining: int = _MAX_VISITS

    def visit(self, depth: int, references: int = 0) -> None:
        self.remaining -= 1
        if self.remaining < 0 or depth > _MAX_DEPTH or references > _MAX_REFERENCES:
            raise _Refusal("H04 schema evaluation bound exceeded")


def _json_key(value: Any, budget: _Budget, depth: int = 0, active: frozenset = frozenset()) -> tuple:
    """JSON equality keeps booleans distinct from integers and object order irrelevant."""
    budget.visit(depth)
    if value is None:
        return ("null",)
    if type(value) is bool:
        return ("boolean", value)
    if type(value) is int:
        return ("number", value)
    if isinstance(value, str):
        value.encode("utf-8")
        return ("string", value)
    if id(value) in active:
        raise _Refusal("Cyclic JSON input")
    active = active | {id(value)}
    if isinstance(value, list):
        return ("array", tuple(_json_key(v, budget, depth + 1, active) for v in value))
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return (
            "object",
            tuple(
                sorted(
                    (_json_key(k, budget, depth + 1, active), _json_key(v, budget, depth + 1, active))
                    for k, v in value.items()
                )
            ),
        )
    raise _Refusal("Expected canonical JSON without floats")


def _reference(schema: dict, definitions: dict) -> str:
    value = schema["$ref"]
    if not isinstance(value, str) or not value.startswith("#/$defs/"):
        raise _Refusal("Only local H04 definition references are supported")
    name = value[len("#/$defs/") :]
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) or name not in definitions:
        raise _Refusal("Unknown local H04 definition")
    return name


def _check_keyword_shapes(schema: dict, budget: _Budget) -> None:
    if set(schema) - _KEYWORDS:
        raise _Refusal("Unsupported H04 schema keyword")
    if "type" in schema:
        kinds = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not kinds or any(not isinstance(k, str) or k not in _TYPES for k in kinds) or len(set(kinds)) != len(kinds):
            raise _Refusal("Malformed schema type")
    for key in ("minItems", "maxItems", "minLength", "maxLength"):
        if key in schema and (type(schema[key]) is not int or schema[key] < 0):
            raise _Refusal("Malformed schema length bound")
    for key in ("minimum", "maximum"):
        if key in schema and type(schema[key]) is not int:
            raise _Refusal("Unsupported noninteger schema bound")
    for key in ("additionalProperties", "uniqueItems"):
        if key in schema and type(schema[key]) is not bool:
            raise _Refusal("Malformed schema boolean")
    if "pattern" in schema:
        if not isinstance(schema["pattern"], str):
            raise _Refusal("Malformed schema pattern")
        re.compile(schema["pattern"])
    if "required" in schema:
        required = schema["required"]
        if (
            not isinstance(required, list)
            or any(not isinstance(k, str) for k in required)
            or len(set(required)) != len(required)
        ):
            raise _Refusal("Malformed required properties")
    if "const" in schema:
        _json_key(schema["const"], budget)
    if "enum" in schema:
        values = schema["enum"]
        if not isinstance(values, list) or not values:
            raise _Refusal("Malformed schema enum")
        keys = [_json_key(v, budget) for v in values]
        if len(set(keys)) != len(keys):
            raise _Refusal("Duplicate schema enum value")


def _check_schema(schema: Any, definitions: dict, budget: _Budget, *, depth: int = 0, references: tuple = ()) -> None:
    budget.visit(depth, max(0, len(references) - 1))
    if type(schema) is bool:
        return
    if not isinstance(schema, dict):
        raise _Refusal("Malformed schema")
    _check_keyword_shapes(schema, budget)
    if "$ref" in schema:
        name = _reference(schema, definitions)
        if name in references:
            raise _Refusal("Cyclic schema reference")
        _check_schema(definitions[name], definitions, budget, depth=depth + 1, references=(*references, name))
    properties = schema.get("properties", {})
    if not isinstance(properties, dict) or any(not isinstance(k, str) for k in properties):
        raise _Refusal("Malformed schema properties")
    for value in properties.values():
        _check_schema(value, definitions, budget, depth=depth + 1, references=references)
    for key in ("allOf", "anyOf"):
        if key in schema:
            values = schema[key]
            if not isinstance(values, list) or not values:
                raise _Refusal("Malformed schema applicator")
            for child in values:
                _check_schema(child, definitions, budget, depth=depth + 1, references=references)
    for key in ("items", "if", "then"):
        if key in schema:
            _check_schema(schema[key], definitions, budget, depth=depth + 1, references=references)


def _has_type(value: Any, kind: str) -> bool:
    return {
        "null": value is None,
        "boolean": type(value) is bool,
        "integer": type(value) is int,
        "number": type(value) is int,
        "string": isinstance(value, str),
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
    }[kind]


def _scalar_matches(value: Any, schema: dict, budget: _Budget) -> bool:
    if "type" in schema:
        kinds = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_has_type(value, kind) for kind in kinds):
            return False
    if "const" in schema and _json_key(value, budget) != _json_key(schema["const"], budget):
        return False
    if "enum" in schema and _json_key(value, budget) not in [_json_key(v, budget) for v in schema["enum"]]:
        return False
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", len(value)):
            return False
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            return False
    return not (type(value) is int and (value < schema.get("minimum", value) or value > schema.get("maximum", value)))


def _matches(
    value: Any, schema: Any, definitions: dict, budget: _Budget, *, depth: int = 0, references: int = 0
) -> bool:
    budget.visit(depth, references)
    if type(schema) is bool:
        return schema
    if "$ref" in schema and not _matches(
        value, definitions[_reference(schema, definitions)], definitions, budget, depth=depth, references=references + 1
    ):
        return False
    if not _scalar_matches(value, schema, budget):
        return False
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if any(key not in value for key in schema.get("required", [])):
            return False
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            return False
        for key in set(value) & set(properties):
            if not _matches(value[key], properties[key], definitions, budget, depth=depth + 1, references=references):
                return False
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", len(value)):
            return False
        if schema.get("uniqueItems") is True:
            keys = [_json_key(v, budget) for v in value]
            if len(set(keys)) != len(keys):
                return False
        if "items" in schema:
            for child in value:
                if not _matches(child, schema["items"], definitions, budget, depth=depth + 1, references=references):
                    return False
    if "allOf" in schema and not all(
        _matches(value, child, definitions, budget, depth=depth, references=references) for child in schema["allOf"]
    ):
        return False
    if "anyOf" in schema and not any(
        _matches(value, child, definitions, budget, depth=depth, references=references) for child in schema["anyOf"]
    ):
        return False
    return not (
        "if" in schema
        and _matches(value, schema["if"], definitions, budget, depth=depth, references=references)
        and "then" in schema
        and not _matches(value, schema["then"], definitions, budget, depth=depth, references=references)
    )


def matches_profile_schema(value: Any, definitions: dict, name: str) -> bool:
    """Refuse unsupported syntax and exhaustion, including in an unselected branch."""
    budget = _Budget()
    try:
        _json_key(value, budget)
        canonical(value)  # Retain the profile consumer's no-coercion JSON domain.
        if not isinstance(definitions, dict) or not isinstance(name, str) or name not in definitions:
            return False
        for key, schema in definitions.items():
            if not isinstance(key, str):
                return False
            _check_schema(schema, definitions, budget, references=(key,))
        return _matches(value, definitions[name], definitions, budget)
    except (_Refusal, ValueError, TypeError, OverflowError, RecursionError, re.error):
        return False

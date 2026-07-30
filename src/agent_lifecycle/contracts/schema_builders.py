"""Shared helpers for built-in JSON schema definitions."""

from __future__ import annotations

from typing import Any


def open_object_schema(
    schema_id: str,
    *,
    required: list[str],
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {"schemaVersion": {"const": schema_id}}
    fields.update(properties or {})
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "type": "object",
        "additionalProperties": True,
        "required": required,
        "properties": fields,
    }

"""Bounded structured authoring requests; serialization grants no authority."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.canonical import prepare_json_object
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.schema_builders import open_object_schema

AUTHORING_REQUEST = "agent-artifact-authoring-request.v1"
AUTHORING_KINDS = ("json", "task-result", "evidence")
MAX_AUTHORING_BYTES = 262_144
ARTIFACT_AUTHORING_SCHEMAS = {
    AUTHORING_REQUEST: {
        **open_object_schema(
            AUTHORING_REQUEST,
            required=["schemaVersion", "kind", "value", "redactAdvisory"],
            properties={
                "kind": {"enum": list(AUTHORING_KINDS)},
                "value": {"type": "object"},
                "redactAdvisory": {"type": "boolean"},
            },
        ),
        "additionalProperties": False,
    }
}


def validate_authoring_request(value: Any) -> dict[str, Any]:
    """Check the whole request before any output directory can be created."""
    if (
        type(value) is not dict
        or set(value) != {"schemaVersion", "kind", "value", "redactAdvisory"}
        or value["schemaVersion"] != AUTHORING_REQUEST
        or type(value["kind"]) is not str
        or value["kind"] not in AUTHORING_KINDS
        or type(value["value"]) is not dict
        or type(value["redactAdvisory"]) is not bool
    ):
        raise LifecycleError("artifact-authoring-invalid", "Invalid structured authoring request")
    if len(prepare_json_object(value)) > MAX_AUTHORING_BYTES:
        raise LifecycleError("artifact-authoring-too-large", "Authoring request exceeds its byte limit")
    return value

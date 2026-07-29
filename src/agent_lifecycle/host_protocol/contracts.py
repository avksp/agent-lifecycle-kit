"""Closed host-operation envelopes used by adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from agent_lifecycle.contracts.errors import LifecycleError

HostOperationStatus = Literal["PASS", "FAIL", "BLOCKED"]
HostAdapterEventStatus = Literal["INFO", "PASS", "FAIL", "BLOCKED"]
HostAdapterEventType = Literal[
    "session.started",
    "task.launched",
    "command.completed",
    "writes.summarized",
    "usage.reported",
    "task.blocked",
    "task.completed",
]


def _reject_unknown(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value).difference(allowed))
    if unknown:
        raise LifecycleError("unknown-field", f"{label}: unknown fields: {', '.join(unknown)}")


@dataclass(frozen=True, slots=True)
class HostOperationRequest:
    operation_id: str
    capability: str
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: list[dict[str, Any]] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)
    model_route: dict[str, Any] | None = None

    schema_version = "agent-host-operation-request.v1"

    def to_json(self) -> dict[str, Any]:
        payload = {
            "schemaVersion": self.schema_version,
            "operationId": self.operation_id,
            "capability": self.capability,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "constraints": self.constraints,
        }
        if self.model_route is not None:
            payload["modelRoute"] = self.model_route
        return payload

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "HostOperationRequest":
        allowed = {"schemaVersion", "operationId", "capability", "inputs", "outputs", "constraints", "modelRoute"}
        _reject_unknown(value, allowed, "host operation request")
        if value.get("schemaVersion") != cls.schema_version:
            raise LifecycleError("unsupported-schema", "host operation request schemaVersion is unsupported")
        if not isinstance(value.get("operationId"), str) or not value["operationId"]:
            raise LifecycleError("invalid-host-operation", "operationId is required")
        if not isinstance(value.get("capability"), str) or not value["capability"]:
            raise LifecycleError("invalid-host-operation", "capability is required")
        if not isinstance(value.get("inputs"), dict):
            raise LifecycleError("invalid-host-operation", "inputs must be an object")
        if not isinstance(value.get("outputs"), list):
            raise LifecycleError("invalid-host-operation", "outputs must be an array")
        if not isinstance(value.get("constraints"), dict):
            raise LifecycleError("invalid-host-operation", "constraints must be an object")
        model_route = value.get("modelRoute")
        if model_route is not None and not isinstance(model_route, dict):
            raise LifecycleError("invalid-host-operation", "modelRoute must be an object")
        return cls(
            operation_id=value["operationId"],
            capability=value["capability"],
            inputs=value["inputs"],
            outputs=value["outputs"],
            constraints=value["constraints"],
            model_route=model_route,
        )


@dataclass(frozen=True, slots=True)
class HostOperationReceipt:
    operation_id: str
    capability: str
    status: HostOperationStatus
    outputs: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)

    schema_version = "agent-host-operation-receipt.v1"

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "operationId": self.operation_id,
            "capability": self.capability,
            "status": self.status,
            "outputs": self.outputs,
            "usage": self.usage,
        }

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "HostOperationReceipt":
        allowed = {"schemaVersion", "operationId", "capability", "status", "outputs", "usage"}
        _reject_unknown(value, allowed, "host operation receipt")
        if value.get("schemaVersion") != cls.schema_version:
            raise LifecycleError("unsupported-schema", "host operation receipt schemaVersion is unsupported")
        status = value.get("status")
        if status not in {"PASS", "FAIL", "BLOCKED"}:
            raise LifecycleError("invalid-host-operation", "status is unsupported")
        if not isinstance(value.get("operationId"), str) or not value["operationId"]:
            raise LifecycleError("invalid-host-operation", "operationId is required")
        if not isinstance(value.get("capability"), str) or not value["capability"]:
            raise LifecycleError("invalid-host-operation", "capability is required")
        if not isinstance(value.get("outputs"), list):
            raise LifecycleError("invalid-host-operation", "outputs must be an array")
        if not isinstance(value.get("usage"), dict):
            raise LifecycleError("invalid-host-operation", "usage must be an object")
        return cls(
            operation_id=value["operationId"],
            capability=value["capability"],
            status=status,
            outputs=value["outputs"],
            usage=value["usage"],
        )


@dataclass(frozen=True, slots=True)
class HostAdapterEvent:
    event_id: str
    host: str
    adapter_id: str
    run_id: str
    task_id: str
    operation_id: str
    sequence: int
    event_type: HostAdapterEventType
    status: HostAdapterEventStatus
    recorded_at: str
    payload: dict[str, Any] = field(default_factory=dict)

    schema_version = "agent-adapter-event.v1"

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "eventId": self.event_id,
            "host": self.host,
            "adapterId": self.adapter_id,
            "runId": self.run_id,
            "taskId": self.task_id,
            "operationId": self.operation_id,
            "sequence": self.sequence,
            "eventType": self.event_type,
            "status": self.status,
            "recordedAt": self.recorded_at,
            "payload": self.payload,
        }

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "HostAdapterEvent":
        allowed = {
            "schemaVersion",
            "eventId",
            "host",
            "adapterId",
            "runId",
            "taskId",
            "operationId",
            "sequence",
            "eventType",
            "status",
            "recordedAt",
            "payload",
        }
        _reject_unknown(value, allowed, "adapter event")
        if value.get("schemaVersion") != cls.schema_version:
            raise LifecycleError("unsupported-schema", "adapter event schemaVersion is unsupported")
        for key in ("eventId", "host", "adapterId", "runId", "taskId", "operationId", "recordedAt"):
            if not isinstance(value.get(key), str) or not value[key]:
                raise LifecycleError("invalid-adapter-event", f"{key} is required")
        sequence = value.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise LifecycleError("invalid-adapter-event", "sequence must be a positive integer")
        event_type = value.get("eventType")
        if event_type not in {
            "session.started",
            "task.launched",
            "command.completed",
            "writes.summarized",
            "usage.reported",
            "task.blocked",
            "task.completed",
        }:
            raise LifecycleError("invalid-adapter-event", "eventType is unsupported")
        status = value.get("status")
        if status not in {"INFO", "PASS", "FAIL", "BLOCKED"}:
            raise LifecycleError("invalid-adapter-event", "status is unsupported")
        payload = value.get("payload")
        if not isinstance(payload, dict):
            raise LifecycleError("invalid-adapter-event", "payload must be an object")
        return cls(
            event_id=value["eventId"],
            host=value["host"],
            adapter_id=value["adapterId"],
            run_id=value["runId"],
            task_id=value["taskId"],
            operation_id=value["operationId"],
            sequence=sequence,
            event_type=event_type,
            status=status,
            recorded_at=value["recordedAt"],
            payload=payload,
        )

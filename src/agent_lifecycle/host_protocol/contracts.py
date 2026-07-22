"""Closed host-operation envelopes used by adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from agent_lifecycle.contracts.errors import LifecycleError

HostOperationStatus = Literal["PASS", "FAIL", "BLOCKED"]


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

    schema_version = "agent-host-operation-request.v1"

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "operationId": self.operation_id,
            "capability": self.capability,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "constraints": self.constraints,
        }

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "HostOperationRequest":
        allowed = {"schemaVersion", "operationId", "capability", "inputs", "outputs", "constraints"}
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
        return cls(
            operation_id=value["operationId"],
            capability=value["capability"],
            inputs=value["inputs"],
            outputs=value["outputs"],
            constraints=value["constraints"],
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

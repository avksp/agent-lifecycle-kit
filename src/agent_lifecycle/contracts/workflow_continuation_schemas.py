"""Projection and one-step apply schemas for guided workflow continuation."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

from agent_lifecycle.contracts.canonical import canonical_digest
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.schema_builders import open_object_schema

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}

WORKFLOW_CONTINUATION_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-workflow-continuation-action.v1": open_object_schema(
        "agent-workflow-continuation-action.v1",
        required=[
            "schemaVersion",
            "route",
            "managedActionType",
            "stateRevision",
            "planDigest",
            "sourceRevision",
            "operationId",
            "taskId",
            "suppliedInputs",
            "managedActionDigest",
            "actionDigest",
        ],
        properties={
            "route": {"type": "string", "minLength": 1},
            "managedActionType": {"type": "string", "minLength": 1},
            "stateRevision": {"type": "integer", "minimum": 1},
            "planDigest": _DIGEST,
            "sourceRevision": {"type": "string", "minLength": 1},
            "operationId": {"type": "string", "minLength": 1},
            "taskId": {"type": ["string", "null"]},
            "suppliedInputs": {"type": "object"},
            "managedActionDigest": _DIGEST,
            "actionDigest": _DIGEST,
        },
    ),
    "agent-workflow-continuation-receipt.v1": open_object_schema(
        "agent-workflow-continuation-receipt.v1",
        required=[
            "schemaVersion",
            "status",
            "mode",
            "operationId",
            "stateBefore",
            "stateAfter",
            "plan",
            "action",
            "requiredInputs",
            "nextAction",
            "appliedEvent",
            "blockers",
            "modelCallsStarted",
            "stateWritten",
            "hostLaunchStarted",
            "productionPromotionClaimed",
            "receiptDigest",
        ],
        properties={
            "status": {"enum": ["INPUT_REQUIRED", "READY", "APPLIED", "WAITING", "BLOCKED"]},
            "mode": {"enum": ["PROJECT", "APPLY"]},
            "operationId": {"type": "string", "minLength": 1},
            "stateBefore": {"type": ["object", "null"]},
            "stateAfter": {"type": ["object", "null"]},
            "plan": {"type": ["object", "null"]},
            "action": {"type": ["object", "null"]},
            "requiredInputs": {"type": "array", "items": {"type": "object"}, "maxItems": 32},
            "nextAction": {"type": ["object", "null"]},
            "appliedEvent": {"type": ["object", "null"]},
            "blockers": {"type": "array", "items": {"type": "object"}, "maxItems": 64},
            "modelCallsStarted": {"const": False},
            "stateWritten": {"type": "boolean"},
            "hostLaunchStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": _DIGEST,
        },
    ),
    "agent-workflow-continuation-authority-projection.v1": open_object_schema(
        "agent-workflow-continuation-authority-projection.v1",
        required=["schemaVersion", "state", "events", "projectionDigest"],
        properties={
            "state": {"type": "object"},
            "events": {"type": "array", "items": {"type": "object"}},
            "projectionDigest": _DIGEST,
        },
    ),
}


def build_workflow_continuation_authority_projection(
    state: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Normalize only the four approved observation-time paths."""

    _validate_observation_times(state, events)
    normalized_state = deepcopy(state)
    normalized_events = deepcopy(events)
    if "updatedAt" in normalized_state:
        normalized_state["updatedAt"] = "<observation-time>"
    ledger = normalized_state.get("operationLedger")
    if isinstance(ledger, dict):
        for entry in ledger.values():
            if isinstance(entry, dict) and "recordedAt" in entry:
                entry["recordedAt"] = "<observation-time>"
    for event in normalized_events:
        if "recordedAt" in event:
            event["recordedAt"] = "<observation-time>"
        payload = event.get("payload")
        checkpoint = payload.get("contextCheckpoint") if isinstance(payload, dict) else None
        checkpoint_event = checkpoint.get("checkpointEvent") if isinstance(checkpoint, dict) else None
        if isinstance(checkpoint_event, dict) and "recordedAt" in checkpoint_event:
            checkpoint_event["recordedAt"] = "<observation-time>"
    body = {
        "schemaVersion": "agent-workflow-continuation-authority-projection.v1",
        "state": normalized_state,
        "events": normalized_events,
    }
    return {**body, "projectionDigest": canonical_digest(body)}


def _validate_observation_times(state: dict[str, Any], events: list[dict[str, Any]]) -> None:
    state_updated = _require_utc_timestamp(state.get("updatedAt"), "/updatedAt")
    ledger = state.get("operationLedger")
    if ledger is None:
        ledger = {}
    if not isinstance(ledger, dict):
        raise LifecycleError("continuation-authority-projection-invalid", "operationLedger must be an object")

    ledger_times: list[tuple[int, datetime, str]] = []
    for operation_id, entry in ledger.items():
        if not isinstance(entry, dict):
            raise LifecycleError(
                "continuation-authority-projection-invalid",
                "operation ledger entries must be objects",
                {"operationId": operation_id},
            )
        revision = entry.get("stateRevision")
        if not isinstance(revision, int) or isinstance(revision, bool):
            raise LifecycleError(
                "continuation-authority-projection-invalid",
                "operation ledger stateRevision must be an integer",
                {"operationId": operation_id},
            )
        timestamp = _require_utc_timestamp(
            entry.get("recordedAt"),
            f"/operationLedger/{operation_id}/recordedAt",
        )
        ledger_times.append((revision, timestamp, str(operation_id)))
    _require_monotonic(
        [
            (timestamp, f"/operationLedger/{operation_id}/recordedAt")
            for _, timestamp, operation_id in sorted(ledger_times)
        ],
    )

    event_times: list[tuple[datetime, str]] = []
    checkpoint_times: list[tuple[datetime, str]] = []
    ledger_by_operation = {str(key): value for key, value in ledger.items() if isinstance(value, dict)}
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise LifecycleError("continuation-authority-projection-invalid", "events must contain objects")
        event_path = f"/events/{index}/recordedAt"
        event_time = _require_utc_timestamp(event.get("recordedAt"), event_path)
        event_times.append((event_time, event_path))
        payload = event.get("payload")
        if not isinstance(payload, dict):
            raise LifecycleError(
                "continuation-authority-projection-invalid",
                "event payload must be an object",
                {"index": index},
            )
        checkpoint = payload.get("contextCheckpoint")
        if isinstance(checkpoint, dict) and checkpoint.get("checkpointEvent") is not None:
            checkpoint_event = checkpoint["checkpointEvent"]
            if not isinstance(checkpoint_event, dict):
                raise LifecycleError(
                    "continuation-authority-projection-invalid",
                    "checkpointEvent must be an object",
                    {"index": index},
                )
            checkpoint_path = f"/events/{index}/payload/contextCheckpoint/checkpointEvent/recordedAt"
            checkpoint_times.append(
                (_require_utc_timestamp(checkpoint_event.get("recordedAt"), checkpoint_path), checkpoint_path)
            )
        operation_id = event.get("operationId")
        ledger_entry = ledger_by_operation.get(operation_id) if isinstance(operation_id, str) else None
        if isinstance(ledger_entry, dict):
            ledger_time = _require_utc_timestamp(
                ledger_entry.get("recordedAt"),
                f"/operationLedger/{operation_id}/recordedAt",
            )
            if ledger_time > event_time:
                raise LifecycleError(
                    "continuation-observation-time-non-monotonic",
                    "operation ledger timestamp must not follow its event timestamp",
                    {"operationId": operation_id},
                )
    _require_monotonic(event_times)
    _require_monotonic(checkpoint_times)
    if ledger_times:
        latest_revision = max(item[0] for item in ledger_times)
        latest_ledger_time = min(item[1] for item in ledger_times if item[0] == latest_revision)
        if state_updated > latest_ledger_time:
            raise LifecycleError(
                "continuation-observation-time-non-monotonic",
                "state updatedAt must not follow the latest ledger observation",
            )


def _require_utc_timestamp(value: Any, path: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z") or "T" not in value:
        raise LifecycleError(
            "continuation-observation-time-invalid",
            "observation timestamp must use UTC ISO-8601 form",
            {"path": path},
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise LifecycleError(
            "continuation-observation-time-invalid",
            "observation timestamp must use UTC ISO-8601 form",
            {"path": path},
        ) from exc
    if parsed.tzinfo != UTC:
        raise LifecycleError(
            "continuation-observation-time-invalid",
            "observation timestamp must use UTC ISO-8601 form",
            {"path": path},
        )
    return parsed


def _require_monotonic(values: list[tuple[datetime, str]]) -> None:
    for previous, current in pairwise(values):
        if previous[0] > current[0]:
            raise LifecycleError(
                "continuation-observation-time-non-monotonic",
                "observation timestamps must be monotonic",
                {"previousPath": previous[1], "path": current[1]},
            )


__all__ = ["WORKFLOW_CONTINUATION_SCHEMAS", "build_workflow_continuation_authority_projection"]

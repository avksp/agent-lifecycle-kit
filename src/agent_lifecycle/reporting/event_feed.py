"""Deterministic read-only event feed over workflow state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.workflow.state import load_state, state_identity

EVENT_FEED_SCHEMA = "agent-workflow-event-feed.v1"


def build_workflow_event_feed(*, state_path: Path) -> dict[str, Any]:
    """Project workflow state into a deterministic event list without writes."""

    state = load_state(state_path)
    events = [_run_observed_event(state)]
    events.extend(_task_events(state))
    events.extend(_operation_events(state))
    blocker = state.get("blocker")
    if isinstance(blocker, dict):
        events.append(
            {
                "eventType": "blocker-observed",
                "sortKey": f"blocker:{blocker.get('code', '')}",
                "code": blocker.get("code"),
                "message": blocker.get("message") or blocker.get("reason"),
            }
        )
    events = sorted(events, key=lambda item: str(item.get("sortKey", "")))
    for item in events:
        item.pop("sortKey", None)
    body = {
        "schemaVersion": EVENT_FEED_SCHEMA,
        "status": "PASS",
        "sourceOfTruth": False,
        "readOnly": True,
        "modelCallsStarted": False,
        "stateWritten": False,
        "stateIdentity": state_identity(state_path, state),
        "eventCount": len(events),
        "events": events,
        "productionPromotionClaimed": False,
    }
    return {**body, "feedDigest": canonical_digest(body)}


def _run_observed_event(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "eventType": "run-observed",
        "sortKey": "00:run",
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "phase": state.get("phase"),
        "stateRevision": state.get("stateRevision"),
        "runStartedAt": state.get("runStartedAt"),
    }


def _task_events(state: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    tasks = state.get("tasks", [])
    for task in tasks if isinstance(tasks, list) else []:
        if not isinstance(task, dict):
            continue
        task_id = task.get("id")
        events.append(
            {
                "eventType": "task-observed",
                "sortKey": f"10:task:{task_id}",
                "taskId": task_id,
                "status": task.get("status"),
                "attempt": task.get("attempt"),
                "required": task.get("required", True),
                "dependsOn": task.get("dependsOn", []),
            }
        )
    return events


def _operation_events(state: dict[str, Any]) -> list[dict[str, Any]]:
    ledger = state.get("operationLedger")
    if not isinstance(ledger, dict):
        return []
    events: list[dict[str, Any]] = []
    for operation_id, raw in ledger.items():
        if not isinstance(raw, dict):
            continue
        recorded_at = raw.get("recordedAt") or ""
        events.append(
            {
                "eventType": "operation-recorded",
                "sortKey": f"20:operation:{recorded_at}:{operation_id}",
                "operationId": operation_id,
                "operationType": raw.get("eventType"),
                "stateRevision": raw.get("stateRevision"),
                "recordedAt": raw.get("recordedAt"),
            }
        )
    return events

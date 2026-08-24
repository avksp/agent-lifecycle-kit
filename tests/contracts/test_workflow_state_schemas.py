from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.schemas import get_schema
from agent_lifecycle.contracts.workflow_state_schemas import (
    WORKFLOW_STATE_V4,
    validate_workflow_state,
)


def _state() -> dict:
    return {
        "schemaVersion": WORKFLOW_STATE_V4,
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "stateRevision": 1,
        "phase": "RUNNING",
        "eventLog": "events.jsonl",
        "operationLedger": {},
        "tasks": [
            {
                "id": "WS-01",
                "status": "READY",
                "attempt": 0,
                "dependsOn": [],
                "attemptHistory": [],
                "required": True,
            }
        ],
    }


class WorkflowStateSchemaTests(unittest.TestCase):
    def test_v4_schema_is_registered_and_validates(self) -> None:
        self.assertEqual(get_schema(WORKFLOW_STATE_V4)["$id"], WORKFLOW_STATE_V4)
        self.assertEqual(validate_workflow_state(_state())["schemaVersion"], WORKFLOW_STATE_V4)

    def test_unknown_task_status_fails_closed(self) -> None:
        state = _state()
        state["tasks"][0]["status"] = "VALIDATING"
        with self.assertRaises(LifecycleError) as raised:
            validate_workflow_state(state)
        self.assertEqual(raised.exception.code, "invalid-workflow-state")

    def test_final_audit_requires_all_required_tasks(self) -> None:
        state = _state()
        state["phase"] = "FINAL_AUDIT"
        with self.assertRaises(LifecycleError):
            validate_workflow_state(state)


if __name__ == "__main__":
    unittest.main()

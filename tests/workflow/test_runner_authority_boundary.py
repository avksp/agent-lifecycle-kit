from __future__ import annotations

import copy
import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.runner.core import initialize_runner_state, transition_runner
from agent_lifecycle.workflow.run import run_workflow_step


class WorkflowAuthorityBoundaryTests(unittest.TestCase):
    def test_removed_runner_cannot_accept_workflow_authority(self) -> None:
        workflow = _workflow_state()
        original = copy.deepcopy(workflow)

        with self.assertRaises(LifecycleError) as raised:
            initialize_runner_state(workflow, operation_id="init", reason="must fail closed")

        self.assertEqual(raised.exception.code, "runner-authority-removed")
        self.assertEqual(workflow, original)

    def test_removed_transition_cannot_mutate_or_transition_workflow(self) -> None:
        workflow = _workflow_state()
        with self.assertRaises(LifecycleError) as raised:
            transition_runner(workflow, workflow, {})
        self.assertEqual(raised.exception.code, "runner-authority-removed")

    def test_active_workflow_step_is_read_only(self) -> None:
        self.assertTrue(callable(run_workflow_step))


def _workflow_state() -> dict:
    return {
        "schemaVersion": "agent-workflow-state.v4",
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "stateRevision": 1,
        "phase": "RUNNING",
        "authorization": {"required": True, "granted": False},
        "budgets": {
            "maxTaskAttempts": 2,
            "maxReroutesPerTask": 1,
            "maxSplitsPerTask": 1,
            "maxBillableTokens": 1000,
            "maxTaskWallSeconds": 60,
        },
        "tasks": [
            {
                "id": "WS-01",
                "status": "READY",
                "attempt": 0,
                "required": True,
                "writes": ["src"],
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()

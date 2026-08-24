from __future__ import annotations

import copy
import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.runner.core import initialize_runner_state, transition_runner


class RunnerAuthorityBoundaryTests(unittest.TestCase):
    def test_runner_requires_workflow_authorization_and_budget_caps(self) -> None:
        state = _workflow_state(granted=False)
        runner = initialize_runner_state(state, operation_id="init", reason="compatibility journal")
        with self.assertRaises(LifecycleError) as raised:
            transition_runner(runner, state, _request("attempt", 1))
        self.assertEqual(raised.exception.code, "runner-authorization-required")

        with self.assertRaises(LifecycleError) as raised_policy:
            initialize_runner_state(
                _workflow_state(granted=True),
                policy={
                    "schemaVersion": "agent-runner-policy.v1",
                    "maxAttemptsPerTask": 3,
                    "maxReroutesPerTask": 1,
                    "maxSplitsPerTask": 1,
                    "maxBillableTokens": 100,
                },
                operation_id="init-wide",
                reason="must fail closed",
            )
        self.assertEqual(raised_policy.exception.code, "runner-budget-cap-exceeded")

    def test_runner_complete_is_journal_only_and_does_not_mutate_workflow(self) -> None:
        workflow = _workflow_state(granted=True)
        original = copy.deepcopy(workflow)
        runner = initialize_runner_state(workflow, operation_id="init", reason="compatibility journal")
        runner, _ = _step(runner, workflow, "attempt", 1)
        runner, _ = _step(runner, workflow, "validate", 2)
        runner, _ = _step(runner, workflow, "review", 3)
        runner, result = _step(runner, workflow, "accept", 4)

        self.assertEqual(result["runnerStatus"], "COMPLETE")
        self.assertEqual(result["authority"]["workflowStateIsAuthoritative"], True)
        self.assertTrue(result["authority"]["journalOnly"])
        self.assertEqual(result["workflowTransitionRequired"], "task-accept")
        self.assertEqual(workflow, original)
        self.assertEqual(runner["authority"]["kind"], "compatibility-journal")


def _step(runner: dict, workflow: dict, action: str, revision: int) -> tuple[dict, dict]:
    payload = transition_runner(runner, workflow, _request(action, revision))
    return payload["state"], payload["result"]


def _request(action: str, revision: int) -> dict:
    return {
        "schemaVersion": "agent-runner-transition-request.v1",
        "operationId": f"{action}-{revision}",
        "expectedRunnerRevision": revision,
        "action": action,
        "taskId": "WS-01",
        "reason": action,
    }


def _workflow_state(*, granted: bool) -> dict:
    return {
        "schemaVersion": "agent-workflow-state.v4",
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "stateRevision": 1,
        "phase": "RUNNING",
        "authorization": {"required": True, "granted": granted},
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

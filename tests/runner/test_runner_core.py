from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError, canonical_digest  # noqa: E402
from agent_lifecycle.runner import (  # noqa: E402
    build_runner_snapshot,
    initialize_runner_state,
    request_runner_stop,
    resume_runner,
    transition_runner,
    validate_runner_state,
)
from agent_lifecycle.worktree import build_attempt_isolation_receipt  # noqa: E402


class RunnerCoreTests(unittest.TestCase):
    def test_runner_executes_controlled_acceptance_path(self) -> None:
        workflow_state = _workflow_state()
        runner = initialize_runner_state(workflow_state, policy=_policy(), operation_id="runner-init", reason="start")

        runner, attempt = _step(runner, workflow_state, "attempt", 1)
        runner, validate = _step(runner, workflow_state, "validate", 2)
        runner, review = _step(runner, workflow_state, "review", 3)
        runner, accept = _step(runner, workflow_state, "accept", 4)

        self.assertEqual(attempt["runnerStatus"], "ATTEMPTING")
        self.assertEqual(validate["runnerStatus"], "VALIDATING")
        self.assertEqual(review["runnerStatus"], "REVIEWING")
        self.assertEqual(accept["runnerStatus"], "COMPLETE")
        self.assertEqual(runner["counters"]["attemptsByTask"], {"WS-01": 1})
        self.assertEqual(validate_runner_state(runner, workflow_state=workflow_state)["runnerStatus"], "COMPLETE")

    def test_runner_rejects_transition_not_in_table(self) -> None:
        workflow_state = _workflow_state()
        runner = initialize_runner_state(workflow_state, policy=_policy(), operation_id="runner-init", reason="start")

        with self.assertRaises(LifecycleError) as raised:
            transition_runner(runner, workflow_state, _request("accept", 1))

        self.assertEqual(raised.exception.code, "runner-transition-not-allowed")

    def test_runner_enforces_attempt_and_token_budgets(self) -> None:
        workflow_state = _workflow_state()
        runner = initialize_runner_state(
            workflow_state,
            policy=_policy(max_attempts=1, max_tokens=100),
            operation_id="runner-init",
            reason="start",
        )
        runner, _ = _step(runner, workflow_state, "attempt", 1)
        runner, _ = _step(runner, workflow_state, "validate", 2)
        runner, _ = _step(runner, workflow_state, "review", 3)
        runner, _ = _step(
            runner,
            workflow_state,
            "remediate",
            4,
            patch=_patch(changed_files=["src/example.py"]),
        )

        with self.assertRaises(LifecycleError) as raised_attempt:
            transition_runner(runner, workflow_state, _request("attempt", 5))
        self.assertEqual(raised_attempt.exception.code, "runner-attempt-limit-exceeded")

        with self.assertRaises(LifecycleError) as raised_budget:
            transition_runner(runner, workflow_state, _request("block", 5, usage={"billableTokens": 101}, blocker_code="budget"))
        self.assertEqual(raised_budget.exception.code, "runner-token-budget-exceeded")

    def test_runner_enforces_reroute_and_split_limits(self) -> None:
        workflow_state = _workflow_state()
        runner = initialize_runner_state(workflow_state, policy=_policy(max_reroutes=1, max_splits=1), operation_id="runner-init", reason="start")
        runner, _ = _step(runner, workflow_state, "attempt", 1)
        runner, _ = _step(runner, workflow_state, "reroute", 2)
        runner, _ = _step(runner, workflow_state, "attempt", 3)

        with self.assertRaises(LifecycleError) as raised_reroute:
            transition_runner(runner, workflow_state, _request("reroute", 4))
        self.assertEqual(raised_reroute.exception.code, "runner-reroute-limit-exceeded")

        runner = initialize_runner_state(workflow_state, policy=_policy(max_reroutes=1, max_splits=1), operation_id="runner-init-2", reason="start")
        runner, _ = _step(runner, workflow_state, "attempt", 1)
        runner, _ = _step(runner, workflow_state, "validate", 2)
        runner, _ = _step(runner, workflow_state, "review", 3)
        runner = _with_digest(
            {
                **runner,
                "counters": {
                    **runner["counters"],
                    "splitsByTask": {"WS-01": 1},
                },
            }
        )

        with self.assertRaises(LifecycleError) as raised_split:
            transition_runner(runner, workflow_state, _request("split", 4))
        self.assertEqual(raised_split.exception.code, "runner-split-limit-exceeded")

    def test_runner_rejects_digest_mismatch_and_history_ambiguity(self) -> None:
        workflow_state = _workflow_state()
        runner = initialize_runner_state(workflow_state, policy=_policy(), operation_id="runner-init", reason="start")

        tampered = {**runner, "currentTaskId": "WS-02"}
        with self.assertRaises(LifecycleError) as raised_digest:
            validate_runner_state(tampered, workflow_state=workflow_state)
        self.assertEqual(raised_digest.exception.code, "runner-state-digest-mismatch")

        ambiguous = _with_digest(
            {
                **runner,
                "operations": {
                    **runner["operations"],
                    "extra-operation": {"action": "attempt", "runnerRevision": 2},
                },
            }
        )
        with self.assertRaises(LifecycleError) as raised_history:
            validate_runner_state(ambiguous, workflow_state=workflow_state)
        self.assertEqual(raised_history.exception.code, "invalid-runner-state")

    def test_runner_stop_and_resume_are_persistable_transitions(self) -> None:
        workflow_state = _workflow_state()
        runner = initialize_runner_state(workflow_state, policy=_policy(), operation_id="runner-init", reason="start")
        runner, _ = _step(runner, workflow_state, "attempt", 1)

        stopped = request_runner_stop(
            runner,
            workflow_state,
            operation_id="runner-stop",
            expected_runner_revision=2,
            reason="operator pause",
        )
        self.assertEqual(stopped["result"]["runnerStatus"], "STOPPED")
        self.assertEqual(stopped["state"]["stopRequest"]["resumeStatus"], "ATTEMPTING")

        resumed = resume_runner(
            stopped["state"],
            workflow_state,
            operation_id="runner-resume",
            expected_runner_revision=3,
            reason="continue",
        )
        self.assertEqual(resumed["result"]["runnerStatus"], "ATTEMPTING")
        self.assertNotIn("stopRequest", resumed["state"])

    def test_runner_patch_restore_fails_closed_on_bad_patch_or_scope(self) -> None:
        workflow_state = _workflow_state()
        runner = initialize_runner_state(workflow_state, policy=_policy(), operation_id="runner-init", reason="start")
        runner, _ = _step(runner, workflow_state, "attempt", 1)
        runner, _ = _step(runner, workflow_state, "validate", 2)
        runner, _ = _step(runner, workflow_state, "review", 3)

        with self.assertRaises(LifecycleError) as raised_status:
            transition_runner(runner, workflow_state, _request("remediate", 4, patch={**_patch(), "status": "FAIL"}))
        self.assertEqual(raised_status.exception.code, "runner-patch-restore-failed")

        with self.assertRaises(LifecycleError) as raised_scope:
            transition_runner(runner, workflow_state, _request("remediate", 4, patch=_patch(changed_files=["docs/out.md"])))
        self.assertEqual(raised_scope.exception.code, "runner-patch-write-scope-violation")

    def test_runner_snapshot_fits_4k_strict_for_small_local_models(self) -> None:
        workflow_state = _workflow_state()
        runner = initialize_runner_state(workflow_state, policy=_policy(), operation_id="runner-init", reason="start")
        runner, _ = _step(runner, workflow_state, "attempt", 1)
        profile = json.loads((ROOT / "profiles/small-context-profile.v1.json").read_text(encoding="utf-8"))

        snapshot = build_runner_snapshot(runner, workflow_state, profile=profile, window="4k-strict")

        self.assertEqual(snapshot["schemaVersion"], "agent-runner-snapshot.v1")
        self.assertEqual(snapshot["runner"]["allowedNextActions"], ["abort", "block", "reroute", "validate"])
        self.assertLessEqual(snapshot["estimatedTokens"], 450)

    def test_runner_records_worktree_isolation_receipt_digest(self) -> None:
        workflow_state = _workflow_state()
        runner = initialize_runner_state(workflow_state, policy=_policy(), operation_id="runner-init", reason="start")
        isolation_receipt = build_attempt_isolation_receipt(
            workflow_state,
            task_id="WS-01",
            attempt=1,
            policy=_worktree_policy(),
            worktree_path=".alk/worktrees/run-ws-01-1",
            baseline_ref="main",
            baseline_sha="source",
            changed_files=["src/example.py"],
            outcome="PASS",
            reason="isolated attempt",
        )

        runner, _ = _step(
            runner,
            workflow_state,
            "attempt",
            1,
            isolation_receipt=isolation_receipt,
            worktree_policy=_worktree_policy(),
        )

        self.assertEqual(runner["history"][-1]["isolationReceiptDigest"], isolation_receipt["receiptDigest"])


def _step(runner: dict, workflow_state: dict, action: str, revision: int, **overrides: object) -> tuple[dict, dict]:
    payload = transition_runner(runner, workflow_state, _request(action, revision, **overrides))
    return payload["state"], payload["result"]


def _request(
    action: str,
    revision: int,
    *,
    usage: dict | None = None,
    patch: dict | None = None,
    blocker_code: str | None = None,
    isolation_receipt: dict | None = None,
    worktree_policy: dict | None = None,
) -> dict:
    request = {
        "schemaVersion": "agent-runner-transition-request.v1",
        "operationId": f"{action}-{revision}",
        "expectedRunnerRevision": revision,
        "action": action,
        "taskId": "WS-01",
        "reason": f"{action} transition",
    }
    if usage is not None:
        request["usage"] = usage
    if patch is not None:
        request["patch"] = patch
    if blocker_code is not None:
        request["blockerCode"] = blocker_code
    if isolation_receipt is not None:
        request["isolationReceipt"] = isolation_receipt
    if worktree_policy is not None:
        request["worktreePolicy"] = worktree_policy
    return request


def _workflow_state() -> dict:
    return {
        "schemaVersion": "agent-workflow-state.v3",
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "stateRevision": 4,
        "phase": "RUNNING",
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


def _policy(*, max_attempts: int = 2, max_reroutes: int = 1, max_splits: int = 1, max_tokens: int = 120000) -> dict:
    return {
        "schemaVersion": "agent-runner-policy.v1",
        "maxAttemptsPerTask": max_attempts,
        "maxReroutesPerTask": max_reroutes,
        "maxSplitsPerTask": max_splits,
        "maxBillableTokens": max_tokens,
    }


def _patch(*, changed_files: list[str] | None = None) -> dict:
    return {
        "status": "PASS",
        "patchDigest": "a" * 64,
        "changedFiles": changed_files or ["src/example.py"],
    }


def _worktree_policy() -> dict:
    return {
        "schemaVersion": "agent-worktree-isolation-policy.v1",
        "worktreeRoot": ".alk/worktrees",
        "allowedWriteRoots": ["src"],
        "preserveFailedAttempts": True,
        "cleanupRequiresOperator": True,
    }


def _with_digest(state: dict) -> dict:
    body = {key: value for key, value in state.items() if key != "stateDigest"}
    return {**body, "stateDigest": canonical_digest(body)}


if __name__ == "__main__":
    unittest.main()

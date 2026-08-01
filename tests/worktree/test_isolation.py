from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError  # noqa: E402
from agent_lifecycle.worktree import (  # noqa: E402
    build_attempt_isolation_receipt,
    build_worktree_writeback_receipt,
    validate_attempt_isolation_receipt,
    validate_worktree_writeback_receipt,
    validate_worktree_policy,
)


class WorktreeIsolationTests(unittest.TestCase):
    def test_builds_and_validates_attempt_receipt(self) -> None:
        receipt = build_attempt_isolation_receipt(
            _state(),
            task_id="WS-01",
            attempt=1,
            policy=_policy(),
            worktree_path=".alk/worktrees/run-ws-01-1",
            baseline_ref="main",
            baseline_sha="source",
            changed_files=["src/example.py"],
            outcome="PASS",
            reason="isolated attempt completed",
        )

        validation = validate_attempt_isolation_receipt(receipt, workflow_state=_state(), policy=_policy())

        self.assertEqual(receipt["schemaVersion"], "agent-worktree-attempt-receipt.v1")
        self.assertEqual(validation["schemaVersion"], "agent-worktree-attempt-receipt-validation.v1")
        self.assertEqual(validation["cleanupDecision"], "PRESERVE")

    def test_rejects_changed_files_outside_task_scope(self) -> None:
        with self.assertRaises(LifecycleError) as raised:
            build_attempt_isolation_receipt(
                _state(),
                task_id="WS-01",
                attempt=1,
                policy=_policy(),
                worktree_path=".alk/worktrees/run-ws-01-1",
                baseline_ref="main",
                baseline_sha="source",
                changed_files=["docs/out.md"],
                outcome="PASS",
                reason="out of scope",
            )
        self.assertEqual(raised.exception.code, "worktree-write-scope-violation")

    def test_failed_attempt_cleanup_requires_explicit_authorization(self) -> None:
        with self.assertRaises(LifecycleError) as raised:
            build_attempt_isolation_receipt(
                _state(),
                task_id="WS-01",
                attempt=1,
                policy=_policy(),
                worktree_path=".alk/worktrees/run-ws-01-1",
                baseline_ref="main",
                baseline_sha="source",
                changed_files=["src/example.py"],
                outcome="FAILED",
                cleanup_decision="REMOVE",
                reason="cleanup",
            )
        self.assertEqual(raised.exception.code, "worktree-cleanup-authorization-required")

        receipt = build_attempt_isolation_receipt(
            _state(),
            task_id="WS-01",
            attempt=1,
            policy=_policy(),
            worktree_path=".alk/worktrees/run-ws-01-1",
            baseline_ref="main",
            baseline_sha="source",
            changed_files=["src/example.py"],
            outcome="FAILED",
            cleanup_decision="REMOVE",
            operator_authorization={"id": "lead", "allowFailedAttemptRemoval": True},
            reason="operator approved removal",
        )
        self.assertEqual(receipt["cleanup"]["decision"], "REMOVE")

    def test_policy_validation_is_compact_and_path_safe(self) -> None:
        validation = validate_worktree_policy(_policy())
        self.assertEqual(validation["worktreeRoot"], ".alk/worktrees")
        with self.assertRaises(LifecycleError):
            validate_worktree_policy({**_policy(), "worktreeRoot": "../outside"})

    def test_builds_and_validates_writeback_receipt(self) -> None:
        receipt = build_worktree_writeback_receipt(
            _state(),
            task_id="WS-01",
            attempt=1,
            overlay_digest="a" * 64,
            changed_files=["src/example.py", "src/extra.py"],
            decision="APPLY",
            operator_authorization={"operatorIdentityHash": "operator-hash"},
            reason="operator accepted overlay changes",
            applied_files=["src/example.py"],
            discarded_files=["src/extra.py"],
            isolation_receipt_digest="b" * 64,
        )

        validation = validate_worktree_writeback_receipt(receipt, workflow_state=_state())

        self.assertEqual(receipt["schemaVersion"], "agent-worktree-writeback-receipt.v1")
        self.assertEqual(validation["schemaVersion"], "agent-worktree-writeback-receipt-validation.v1")
        self.assertEqual(validation["decision"], "APPLY")
        self.assertEqual(validation["appliedFileCount"], 1)
        self.assertEqual(validation["discardedFileCount"], 1)

    def test_discard_writeback_does_not_apply_paths(self) -> None:
        receipt = build_worktree_writeback_receipt(
            _state(),
            task_id="WS-01",
            attempt=1,
            overlay_digest="a" * 64,
            changed_files=["src/example.py"],
            decision="DISCARD",
            operator_authorization={"operatorIdentityHash": "operator-hash"},
            reason="operator discarded overlay",
        )

        validation = validate_worktree_writeback_receipt(receipt, workflow_state=_state())

        self.assertEqual(receipt["appliedFiles"], [])
        self.assertEqual(receipt["discardedFiles"], ["src/example.py"])
        self.assertEqual(validation["discardedFileCount"], 1)

    def test_writeback_rejects_path_overlap(self) -> None:
        with self.assertRaises(LifecycleError) as raised:
            build_worktree_writeback_receipt(
                _state(),
                task_id="WS-01",
                attempt=1,
                overlay_digest="a" * 64,
                changed_files=["src/example.py"],
                decision="APPLY",
                operator_authorization={"operatorIdentityHash": "operator-hash"},
                reason="invalid overlap",
                applied_files=["src/example.py"],
                discarded_files=["src/example.py"],
            )
        self.assertEqual(raised.exception.code, "worktree-writeback-path-overlap")


def _policy() -> dict:
    return {
        "schemaVersion": "agent-worktree-isolation-policy.v1",
        "worktreeRoot": ".alk/worktrees",
        "allowedWriteRoots": ["src"],
        "preserveFailedAttempts": True,
        "cleanupRequiresOperator": True,
    }


def _state() -> dict:
    return {
        "schemaVersion": "agent-workflow-state.v3",
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "stateRevision": 2,
        "phase": "RUNNING",
        "tasks": [
            {
                "id": "WS-01",
                "status": "READY",
                "attempt": 1,
                "writes": ["src"],
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()

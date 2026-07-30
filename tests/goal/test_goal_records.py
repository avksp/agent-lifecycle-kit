from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError, canonical_digest  # noqa: E402
from agent_lifecycle.goal import build_objective_snapshot, update_goal_record, validate_goal_record  # noqa: E402


class GoalRecordTests(unittest.TestCase):
    def test_goal_record_validates_against_current_workflow_state(self) -> None:
        state = _state()
        record = _goal_record(state)

        validation = validate_goal_record(record, state=state, require_current=True)

        self.assertEqual(validation["schemaVersion"], "agent-goal-record-validation.v1")
        self.assertEqual(validation["goalId"], "release-015")
        self.assertEqual(validation["goalStatus"], "ACTIVE")
        self.assertEqual(validation["stateRevision"], 3)

    def test_goal_record_rejects_stale_state_revision(self) -> None:
        state = _state()
        record = _goal_record(state)
        record["lineage"]["stateRevision"] = 2

        with self.assertRaises(LifecycleError) as raised:
            validate_goal_record(record, state=state, require_current=True)

        self.assertEqual(raised.exception.code, "goal-state-stale")

    def test_goal_record_rejects_completion_check_mismatch(self) -> None:
        state = _state(with_completion_check=True)
        record = _goal_record(state, completion_check={"checkId": "done", "checkDigest": "1" * 64})

        with self.assertRaises(LifecycleError) as raised:
            validate_goal_record(record, state=state, require_current=True)

        self.assertEqual(raised.exception.code, "goal-completion-check-mismatch")

    def test_goal_record_snapshot_is_compact_and_traceable(self) -> None:
        state = _state(with_completion_check=True)
        record = _goal_record(state, completion_check=_completion_identity())
        profile = json.loads((ROOT / "profiles/small-context-profile.v1.json").read_text(encoding="utf-8"))

        snapshot = build_objective_snapshot(record, state, profile=profile, window="4k-strict")

        self.assertEqual(snapshot["schemaVersion"], "agent-objective-snapshot.v1")
        self.assertEqual(snapshot["goal"]["goalId"], "release-015")
        self.assertEqual(snapshot["goal"]["userIntent"], "Implement release 0.15 and ship it with validation.")
        self.assertEqual(snapshot["goal"]["ownerOutcome"], "Release is complete with evidence and no copied names.")
        self.assertIn("Keep token usage compact", snapshot["goal"]["constraints"])
        self.assertEqual(snapshot["lifecycle"]["nextAction"]["type"], "run-final-audit")
        self.assertEqual(snapshot["completionCheck"], _completion_identity())
        self.assertLessEqual(snapshot["estimatedTokens"], 450)

    def test_update_goal_record_preserves_history_and_binds_current_lineage(self) -> None:
        state = _state()
        record = _goal_record(state)
        state["stateRevision"] = 4

        updated = update_goal_record(record, state, status="READY_FOR_FINALIZATION", reason="all tasks accepted", evidence_ids=["EV-FINAL"])

        self.assertEqual(updated["status"], "READY_FOR_FINALIZATION")
        self.assertEqual(updated["evidenceIds"], ["EV-FINAL"])
        self.assertEqual(updated["lineage"]["stateRevision"], 4)
        self.assertEqual(updated["history"][0]["previousStateRevision"], 3)
        self.assertEqual(updated["history"][0]["previousGoalDigest"], canonical_digest(record))
        validate_goal_record(updated, state=state, require_current=True)


def _state(*, with_completion_check: bool = False) -> dict:
    state = {
        "schemaVersion": "agent-workflow-state.v3",
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "stateRevision": 3,
        "phase": "RUNNING",
        "tasks": [{"id": "WS-01", "status": "ACCEPTED", "attempt": 1, "required": True}],
    }
    if with_completion_check:
        state["completionCheckValidation"] = {
            "schemaVersion": "agent-completion-check-validation.v1",
            "status": "PASS",
            "checkId": "done",
            "checkKind": "verification",
            "receiptPath": "final/completion-check-receipt.json",
            "requiredEvidenceIds": ["EV-FINAL"],
            "checkDigest": "a" * 64,
        }
    return state


def _goal_record(state: dict, *, completion_check: dict | None = None) -> dict:
    record = {
        "schemaVersion": "agent-goal-record.v1",
        "goalId": "release-015",
        "userIntent": "Implement release 0.15 and ship it with validation.",
        "ownerOutcome": "Release is complete with evidence and no copied names.",
        "constraints": ["Do not commit work/", "Keep token usage compact", "Fail closed on stale state"],
        "status": "ACTIVE",
        "lineage": {
            "runId": state["runId"],
            "packageId": state["packageId"],
            "planRevision": state["planRevision"],
            "planDigest": state["planDigest"],
            "sourceRevision": state["sourceRevision"],
            "stateRevision": state["stateRevision"],
        },
        "evidenceIds": [],
        "updatedAt": "2026-07-30T08:00:00Z",
    }
    if completion_check is not None:
        record["completionCheck"] = completion_check
    return record


def _completion_identity() -> dict:
    return {"checkId": "done", "checkDigest": "a" * 64}


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402

class WorkflowPlanAdoptionTests(unittest.TestCase):
    def test_adopt_plan_resets_changed_plan_and_starts_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="BLOCKED", blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"})
            _write_plan_bundle(root, include_model_route=True)
            payload = adopt_plan(
                state_path,
                manifest_path=root / "plans/package/plan.manifest.json",
                operation_id="adopt-op",
                expected_revision=1,
                source_revision="source-2",
                reset_tasks=True,
                start_mode="auto-after-freeze",
                authorized_by="tester",
            )
            self.assertEqual(payload["phase"], "READY")
            self.assertEqual(payload["planRevision"], 2)
            self.assertEqual(payload["nextAction"]["type"], "start-execution")
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            task = next(item for item in stored["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "READY")
            self.assertEqual(task["modelRoute"]["modelClass"], "standard-code")

            payload = start_execution(
                state_path,
                operation_id="run-op",
                expected_revision=2,
                source_revision="source-2",
                reason="go",
            )
            self.assertEqual(payload["phase"], "RUNNING")
            self.assertEqual(payload["nextAction"]["taskIds"], ["WS-01"])

            payload = start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=3,
                source_revision="source-2",
                reason="launch",
            )
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            task = next(item for item in stored["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["attemptModelRoute"]["modelClass"], "standard-code")

    def test_adopt_plan_accepts_plan_lock_review_identity_without_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="BLOCKED", blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"})
            _write_plan_bundle(root, include_plan_review_report=False)

            payload = adopt_plan(
                state_path,
                manifest_path=root / "plans/package/plan.manifest.json",
                operation_id="adopt-op",
                expected_revision=1,
                source_revision="source-2",
                reset_tasks=True,
                start_mode="auto-after-freeze",
                authorized_by="tester",
            )

            self.assertEqual(payload["phase"], "READY")
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["lastPlanReview"]["surface"], "plan-lock")
            self.assertEqual(stored["lastPlanReview"]["reviewId"], "plan-review-r02")

    def test_adopt_plan_preserves_compatible_accepted_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="BLOCKED", blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"})
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["status"] = "ACCEPTED"
            state["tasks"][0]["attempt"] = 1
            state["tasks"][0]["result"] = {"path": "tasks/WS-01/attempt-1/task-result.json", "sha256": "2" * 64, "bytes": 10}
            state["tasks"][0]["review"] = {"path": "tasks/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            _write_plan_bundle(root)

            payload = adopt_plan(
                state_path,
                manifest_path=root / "plans/package/plan.manifest.json",
                operation_id="adopt-op",
                expected_revision=1,
                source_revision="source-2",
                reset_tasks=True,
                preserve_accepted_compatible=True,
                start_mode="auto-after-freeze",
                authorized_by="tester",
            )

            task = next(item for item in payload["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "ACCEPTED")
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            stored_task = next(item for item in stored["tasks"] if item["id"] == "WS-01")
            self.assertEqual(stored_task["adoptedFromPlanRevision"], 1)
            self.assertEqual(payload["phase"], "READY")

    def test_adopt_plan_preserve_unlocks_new_dependents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="BLOCKED", blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"})
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["status"] = "ACCEPTED"
            state["tasks"][0]["attempt"] = 1
            state_path.write_text(json.dumps(state), encoding="utf-8")
            _write_plan_bundle(root, include_dependent=True)

            payload = adopt_plan(
                state_path,
                manifest_path=root / "plans/package/plan.manifest.json",
                operation_id="adopt-op",
                expected_revision=1,
                source_revision="source-2",
                reset_tasks=True,
                preserve_accepted_compatible=True,
                start_mode="auto-after-freeze",
                authorized_by="tester",
            )

            task = next(item for item in payload["tasks"] if item["id"] == "WS-02")
            self.assertEqual(task["status"], "READY")


if __name__ == "__main__":
    unittest.main()

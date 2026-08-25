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

from agent_lifecycle.workflow import run_workflow_step  # noqa: E402

try:
    from tests.planning.test_completeness import _manifest as _canonical_manifest
except ImportError:
    from planning.test_completeness import _manifest as _canonical_manifest

class WorkflowPlanAdoptionTests(unittest.TestCase):
    def test_run_and_adoption_share_traceability_completeness_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(
                root,
                phase="BLOCKED",
                blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"},
            )
            manifest = _canonical_manifest()
            manifest["workstreams"][0]["acceptanceIds"] = ["AC-02"]
            manifest_path = root / "plan.manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            before_state = state_path.read_bytes()

            run_receipt = run_workflow_step(
                state_path=state_path,
                manifest_path=manifest_path,
                operation_id="run-incomplete-plan",
                expected_revision=1,
                source_revision="source",
            )
            run_failure = next(
                blocker for blocker in run_receipt["blockers"] if blocker["code"] == "plan-completeness-failed"
            )

            with self.assertRaises(LifecycleError) as raised:
                adopt_plan(
                    state_path,
                    manifest_path=manifest_path,
                    operation_id="adopt-incomplete-plan",
                    expected_revision=1,
                    source_revision="source-2",
                    reset_tasks=True,
                    start_mode="auto-after-freeze",
                    authorized_by="tester",
                )

            run_codes = {item["code"] for item in run_failure["context"]["validation"]["blockers"]}
            adoption_codes = {item["code"] for item in raised.exception.details["validation"]["blockers"]}
            self.assertEqual(raised.exception.code, "plan-completeness-failed")
            self.assertEqual(run_codes, adoption_codes)
            self.assertEqual(run_codes, {"traceability-owner-count"})
            self.assertEqual(state_path.read_bytes(), before_state)

    def test_adopt_plan_rejects_unknown_authority_before_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="BLOCKED", blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"})
            _write_plan_bundle(root)
            manifest_path = root / "plans/package/plan.manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["schemaVersion"] = "agent-plan-manifest.v1"
            manifest["integrationSeams"] = ["controller"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            before = state_path.read_bytes()

            with self.assertRaises(LifecycleError) as raised:
                adopt_plan(
                    state_path,
                    manifest_path=manifest_path,
                    operation_id="adopt-invalid-op",
                    expected_revision=1,
                    source_revision="source-2",
                    reset_tasks=True,
                    start_mode="auto-after-freeze",
                    authorized_by="tester",
                )

            self.assertEqual(raised.exception.code, "plan-manifest-contract-failed")
            self.assertEqual(state_path.read_bytes(), before)

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
            state["tasks"][0]["result"] = {"path": "work/WS-01/attempt-1/task-result.json", "sha256": "2" * 64, "bytes": 10}
            state["tasks"][0]["review"] = {"path": "work/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
            state["tasks"][0]["implementationAuditReport"] = {
                "path": "work/WS-01/attempt-1/implementation-audit.json",
                "sha256": "4" * 64,
                "bytes": 10,
                "taskId": "WS-01",
                "attempt": 1,
                "verdict": "ACCEPTED",
                "reportDigest": "5" * 64,
            }
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
            receipt = stored_task["planCompatibilityReceipt"]
            self.assertEqual(receipt["schemaVersion"], "agent-task-plan-compatibility-receipt.v1")
            self.assertEqual(receipt["previousPlan"]["planRevision"], 1)
            self.assertEqual(receipt["currentPlan"]["planRevision"], 2)
            self.assertEqual(receipt["acceptedArtifacts"]["implementationAuditReport"]["sha256"], "4" * 64)
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

    def test_adopt_plan_copies_completion_check_to_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="BLOCKED", blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"})
            _write_plan_bundle(root, include_completion_check=True)

            adopt_plan(
                state_path,
                manifest_path=root / "plans/package/plan.manifest.json",
                operation_id="adopt-op",
                expected_revision=1,
                source_revision="source-2",
                reset_tasks=True,
                start_mode="auto-after-freeze",
                authorized_by="tester",
            )

            stored = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["completionCheck"]["checkId"], "done-check")
            self.assertEqual(stored["completionCheckValidation"]["schemaVersion"], "agent-completion-check-validation.v1")
            self.assertEqual(stored["completionCheck"]["receiptPath"], "final/completion-check-receipt.json")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.workflow import continue_workflow

from .test_final_audit_outcomes import _write_v4_state
from .test_workflow_run import _write_bundle


class WorkflowContinuationTests(unittest.TestCase):
    def test_projection_is_read_only_and_ready_for_single_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            before = state_path.read_bytes()
            event_path = root / "events.jsonl"

            receipt = _continue(manifest_path, state_path, operation_id="project-start")

            self.assertEqual(receipt["status"], "READY")
            self.assertEqual(receipt["action"]["route"], "run-start")
            self.assertEqual(receipt["action"]["stateRevision"], 1)
            self.assertFalse(receipt["stateWritten"])
            self.assertFalse(receipt["modelCallsStarted"])
            self.assertEqual(state_path.read_bytes(), before)
            self.assertFalse(event_path.exists())

    def test_apply_commits_exactly_one_existing_transition_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            projection = _continue(manifest_path, state_path, operation_id="apply-start")

            receipt = _continue(
                manifest_path,
                state_path,
                operation_id="apply-start",
                apply=True,
                projected_state_revision=projection["action"]["stateRevision"],
                projected_action_digest=projection["action"]["actionDigest"],
            )

            state = json.loads(state_path.read_text(encoding="utf-8"))
            events = [json.loads(line) for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(receipt["status"], "APPLIED")
            self.assertTrue(receipt["stateWritten"])
            self.assertEqual(receipt["appliedEvent"]["eventType"], "execution-started")
            self.assertEqual(state["phase"], "RUNNING")
            self.assertEqual(state["stateRevision"], 2)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["eventType"], "execution-started")

    def test_apply_rejects_stale_action_digest_without_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            before = state_path.read_bytes()

            receipt = _continue(
                manifest_path,
                state_path,
                operation_id="stale-start",
                apply=True,
                projected_state_revision=1,
                projected_action_digest="f" * 64,
            )

            self.assertEqual(receipt["status"], "BLOCKED")
            self.assertEqual(receipt["blockers"][0]["code"], "continuation-projection-action-mismatch")
            self.assertFalse(receipt["stateWritten"])
            self.assertEqual(state_path.read_bytes(), before)
            self.assertFalse((root / "events.jsonl").exists())

    def test_parallel_ready_tasks_require_explicit_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="RUNNING", task_status="READY")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            second = dict(state["tasks"][0])
            second["id"] = "WS-02"
            state["tasks"].append(second)
            state_path.write_text(json.dumps(state), encoding="utf-8")

            receipt = _continue(manifest_path, state_path, operation_id="ambiguous-task")

            self.assertEqual(receipt["status"], "INPUT_REQUIRED")
            self.assertEqual(receipt["action"]["route"], "task-start")
            self.assertIsNone(receipt["action"]["taskId"])
            self.assertIn("taskId", {item["name"] for item in receipt["requiredInputs"]})

    def test_running_task_without_result_is_waiting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="RUNNING", task_status="RUNNING")

            receipt = _continue(manifest_path, state_path, operation_id="wait-result")

            self.assertEqual(receipt["status"], "WAITING")
            self.assertEqual(receipt["action"]["route"], "task-result")
            self.assertIn("result", {item["name"] for item in receipt["requiredInputs"]})
            self.assertFalse(receipt["stateWritten"])

    def test_absolute_artifact_input_fails_before_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="RUNNING", task_status="RUNNING")
            before = state_path.read_bytes()

            receipt = _continue(
                manifest_path,
                state_path,
                operation_id="absolute-result",
                inputs={"result": "/tmp/result.json"},
            )

            self.assertEqual(receipt["status"], "BLOCKED")
            self.assertEqual(receipt["blockers"][0]["code"], "invalid-repo-path")
            self.assertEqual(state_path.read_bytes(), before)

    def test_supported_route_projection_matrix(self) -> None:
        cases = [
            ("AWAITING_AUTHORIZATION", "READY", "authorize"),
            ("READY", "READY", "run-start"),
            ("RUNNING", "READY", "task-start"),
            ("RUNNING", "RUNNING", "task-result"),
            ("RUNNING", "VERIFYING", "task-review-apply"),
        ]
        for phase, task_status, route in cases:
            with self.subTest(route=route), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest_path, state_path = _write_bundle(root, phase=phase, task_status=task_status)
                if phase == "AWAITING_AUTHORIZATION":
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    state["authorization"] = {"required": True, "granted": False}
                    state["startMode"] = "approval-required"
                    state_path.write_text(json.dumps(state), encoding="utf-8")

                receipt = _continue(manifest_path, state_path, operation_id=f"project-{route}")

                self.assertEqual(receipt["action"]["route"], route)
                self.assertFalse(receipt["stateWritten"])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_v4_state(root)
            manifest_path = _bind_manifest(root, state_path)
            outcome = _continue(manifest_path, state_path, operation_id="project-final-outcome")
            self.assertEqual(outcome["action"]["route"], "final-audit-outcome")

            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["finalAuditOutcome"] = {"verdict": "ACCEPTED"}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            finalization = _continue(manifest_path, state_path, operation_id="project-finalize")
            self.assertEqual(finalization["action"]["route"], "finalize")

    def test_plan_only_is_explicitly_blocked_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="PLAN_ONLY", task_status="READY")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["schemaVersion"] = "agent-workflow-state.v4"
            state["startMode"] = "plan-only"
            state["authorization"] = {"required": False, "granted": False}
            state["operationLedger"] = {}
            state["blocker"] = None
            state_path.write_text(json.dumps(state), encoding="utf-8")
            before = state_path.read_bytes()

            receipt = _continue(manifest_path, state_path, operation_id="plan-only")

            self.assertEqual(receipt["status"], "BLOCKED")
            self.assertEqual(receipt["blockers"][0]["code"], "continuation-route-non-mutating")
            self.assertEqual(state_path.read_bytes(), before)


def _continue(
    manifest_path: Path,
    state_path: Path,
    *,
    operation_id: str,
    apply: bool = False,
    projected_state_revision: int | None = None,
    projected_action_digest: str | None = None,
    inputs: dict[str, object] | None = None,
) -> dict[str, object]:
    return continue_workflow(
        state_path=state_path,
        manifest_path=manifest_path,
        operation_id=operation_id,
        expected_revision=1,
        source_revision="source",
        reason="test continuation",
        apply=apply,
        projected_state_revision=projected_state_revision,
        projected_action_digest=projected_action_digest,
        inputs=inputs,
    )


def _bind_manifest(root: Path, state_path: Path) -> Path:
    manifest = {
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "package", "planArtifactRoot": "plans/package"},
        "readOnly": [],
        "forbiddenWrites": [],
        "leadOwned": [],
        "workstreams": [
            {
                "id": "WS-01",
                "title": "Task",
                "owner": "worker",
                "reviewer": "reviewer",
                "dependsOn": [],
                "writes": ["src/example.py"],
                "acceptanceIds": ["AC-01"],
                "evidenceIds": ["EV-01"],
            }
        ],
        "acceptanceCriteria": [{"id": "AC-01", "evidenceIds": ["EV-01"]}],
    }
    digest = canonical_digest(manifest)
    manifest_path = root / "plans/package/plan.manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (manifest_path.parent / "plan.lock.json").write_text(
        json.dumps({"schemaVersion": "agent-plan-lock.v1", "planRevision": 1, "manifestHash": digest}),
        encoding="utf-8",
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["planDigest"] = digest
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return manifest_path


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.audit import build_implementation_audit_report
from agent_lifecycle.contracts import canonical_digest, write_json_create
from agent_lifecycle.contracts.schemas import get_schema
from agent_lifecycle.workflow import commit_task_result, continue_workflow, start_execution, start_task

from .test_final_audit_outcomes import _write_v4_state
from .test_task_acceptance_audit_gate import (
    _write_bundle as _write_audit_bundle,
)
from .test_task_acceptance_audit_gate import (
    _write_result_review,
)
from .test_task_transitions import _strategy_start_inputs, _write_strategy_start_bundle
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
            self.assertTrue(set(get_schema(receipt["schemaVersion"])["required"]).issubset(receipt))
            self.assertTrue(set(get_schema(receipt["action"]["schemaVersion"])["required"]).issubset(receipt["action"]))
            receipt_body = {key: value for key, value in receipt.items() if key != "receiptDigest"}
            self.assertEqual(receipt["receiptDigest"], canonical_digest(receipt_body))

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

    def test_task_start_projection_and_apply_consume_exact_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, strategy_path, strategy = _write_strategy_start_bundle(root)
            manifest_path = root / "tasks/strategy/plan.manifest.json"
            inputs = _continuation_strategy_inputs(strategy_path)

            projection = _continue(
                manifest_path,
                state_path,
                operation_id="start-strategy",
                inputs=inputs,
            )
            applied = _continue(
                manifest_path,
                state_path,
                operation_id="start-strategy",
                inputs=inputs,
                apply=True,
                projected_state_revision=projection["action"]["stateRevision"],
                projected_action_digest=projection["action"]["actionDigest"],
            )

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(projection["action"]["executionStrategy"]["strategyDigest"], strategy["strategyDigest"])
            self.assertFalse(projection["action"]["executionStrategy"]["modelCallsStarted"])
            self.assertEqual(applied["status"], "APPLIED")
            self.assertEqual(
                state["tasks"][0]["attemptExecutionStrategy"]["strategyDigest"], strategy["strategyDigest"]
            )

    def test_multi_task_wait_does_not_request_an_inapplicable_task_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="RUNNING", task_status="READY")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            second_workstream = dict(manifest["workstreams"][0])
            second_workstream.update({"id": "WS-02", "dependsOn": ["WS-01"], "writes": ["src/second.py"]})
            manifest["workstreams"][0]["dependsOn"] = ["WS-02"]
            manifest["workstreams"].append(second_workstream)
            digest = canonical_digest(manifest)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (manifest_path.parent / "plan.lock.json").write_text(
                json.dumps({"schemaVersion": "agent-plan-lock.v1", "planRevision": 1, "manifestHash": digest}),
                encoding="utf-8",
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            second_task = dict(state["tasks"][0])
            second_task.update(
                {"id": "WS-02", "status": "PENDING", "dependsOn": ["WS-01"], "writes": ["src/second.py"]}
            )
            state["tasks"][0].update({"status": "PENDING", "dependsOn": ["WS-02"]})
            state["tasks"].append(second_task)
            state["planDigest"] = digest
            state_path.write_text(json.dumps(state), encoding="utf-8")

            receipt = _continue(manifest_path, state_path, operation_id="wait-multiple")

            self.assertEqual(receipt["status"], "WAITING")
            self.assertEqual(receipt["action"]["route"], "wait-for-task-outcome")
            self.assertEqual(receipt["requiredInputs"], [])
            self.assertIsNone(receipt["action"]["taskId"])

    def test_running_task_without_result_is_waiting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="RUNNING", task_status="RUNNING")

            receipt = _continue(manifest_path, state_path, operation_id="wait-result")

            self.assertEqual(receipt["status"], "WAITING")
            self.assertEqual(receipt["action"]["route"], "task-result")
            self.assertIn("result", {item["name"] for item in receipt["requiredInputs"]})
            self.assertFalse(receipt["stateWritten"])

    def test_model_backed_task_result_projects_usage_receipt_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="RUNNING", task_status="RUNNING")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["attemptModelRoute"] = {
                "modelClass": "standard",
                "operationId": "route-op",
                "decisionDigest": "d" * 64,
                "requiresUsageReceipt": True,
            }
            state_path.write_text(json.dumps(state), encoding="utf-8")

            receipt = _continue(manifest_path, state_path, operation_id="model-result")

            required = {item["name"] for item in receipt["requiredInputs"]}
            self.assertEqual(receipt["status"], "WAITING")
            self.assertIn("result", required)
            self.assertIn("modelUsageReceipt", required)

    def test_rework_review_projects_finding_ids_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="RUNNING", task_status="VERIFYING")
            review_path = "work/WS-01/attempt-1/task-review.json"
            write_json_create(root / review_path, {"verdict": "REWORK"})

            receipt = _continue(
                manifest_path,
                state_path,
                operation_id="project-rework",
                inputs={"review": review_path},
            )

            required = {item["name"] for item in receipt["requiredInputs"]}
            self.assertEqual(receipt["status"], "INPUT_REQUIRED")
            self.assertIn("findingIds", required)

    def test_audit_required_task_acceptance_matches_existing_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_audit_bundle(root, phase="RUNNING", task_status="READY", audit_required=True)
            manifest_path = Path(bundle["manifestPath"])
            state_path = Path(bundle["statePath"])
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            result_path, review_path = _write_result_review(root, bundle)
            commit_task_result(
                state_path,
                task_id="WS-01",
                operation_id="result-op",
                expected_revision=2,
                source_revision="source",
                result_path=result_path,
                reason="done",
            )
            missing_audit = _continue(
                manifest_path,
                state_path,
                operation_id="project-missing-audit",
                expected_revision=3,
                inputs={"review": review_path},
            )
            self.assertEqual(missing_audit["status"], "INPUT_REQUIRED")
            self.assertIn("implementationAudit", {item["name"] for item in missing_audit["requiredInputs"]})
            audit = build_implementation_audit_report(
                manifest_path=manifest_path,
                state_path=state_path,
                task_id="WS-01",
                result_path=result_path,
                review_path=review_path,
            )
            self.assertEqual(audit["verdict"], "ACCEPTED")
            audit_path = "work/WS-01/attempt-1/implementation-audit.json"
            write_json_create(root / audit_path, audit)
            inputs = {"review": review_path, "implementationAudit": audit_path}

            projection = _continue(
                manifest_path,
                state_path,
                operation_id="accept-op",
                expected_revision=3,
                inputs=inputs,
            )
            receipt = _continue(
                manifest_path,
                state_path,
                operation_id="accept-op",
                expected_revision=3,
                apply=True,
                projected_state_revision=projection["action"]["stateRevision"],
                projected_action_digest=projection["action"]["actionDigest"],
                inputs=inputs,
            )

            state = json.loads(state_path.read_text(encoding="utf-8"))
            events = [json.loads(line) for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(projection["status"], "READY")
            self.assertEqual(receipt["status"], "APPLIED")
            self.assertEqual(state["tasks"][0]["status"], "ACCEPTED")
            self.assertEqual(state["stateRevision"], 4)
            self.assertEqual(len(events), 3)
            self.assertEqual(events[-1]["eventType"], "task-accepted")

    def test_concurrent_state_change_blocks_apply_without_second_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            projection = _continue(manifest_path, state_path, operation_id="project-before-race")
            start_execution(
                state_path,
                operation_id="concurrent-start",
                expected_revision=1,
                source_revision="source",
                reason="concurrent transition",
            )
            before_apply = state_path.read_bytes()

            receipt = _continue(
                manifest_path,
                state_path,
                operation_id="project-before-race",
                expected_revision=1,
                apply=True,
                projected_state_revision=projection["action"]["stateRevision"],
                projected_action_digest=projection["action"]["actionDigest"],
            )

            self.assertEqual(receipt["status"], "BLOCKED")
            self.assertFalse(receipt["stateWritten"])
            self.assertEqual(state_path.read_bytes(), before_apply)

    def test_finalize_projection_lists_required_integrity_and_quorum_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_v4_state(root)
            manifest_path = _bind_manifest(root, state_path)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["finalAuditOutcome"] = {"verdict": "ACCEPTED"}
            state["proofIntegrityRequired"] = True
            state["reviewMesh"] = {"required": True, "phases": ["final-audit"]}
            state_path.write_text(json.dumps(state), encoding="utf-8")

            receipt = _continue(manifest_path, state_path, operation_id="project-final-inputs")

            required = {item["name"] for item in receipt["requiredInputs"]}
            self.assertEqual(receipt["action"]["route"], "finalize")
            self.assertTrue({"finalAudit", "proof", "proofIntegrity", "reviewMeshQuorum"}.issubset(required))

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
    expected_revision: int = 1,
    apply: bool = False,
    projected_state_revision: int | None = None,
    projected_action_digest: str | None = None,
    inputs: dict[str, object] | None = None,
) -> dict[str, object]:
    return continue_workflow(
        state_path=state_path,
        manifest_path=manifest_path,
        operation_id=operation_id,
        expected_revision=expected_revision,
        source_revision="source",
        reason="test continuation",
        apply=apply,
        projected_state_revision=projected_state_revision,
        projected_action_digest=projected_action_digest,
        inputs=inputs,
    )


def _continuation_strategy_inputs(strategy_path: str) -> dict[str, object]:
    inputs = _strategy_start_inputs()
    return {
        "executionStrategy": strategy_path,
        "strategyRequestedRisk": inputs["requestedRisk"],
        "strategyRiskPolicy": inputs["riskPolicyPath"],
        "strategyRoutingProfile": inputs["routingProfilePath"],
        "strategyBaselineProfile": inputs["baselineProfilePath"],
        "strategyHostProfile": inputs["hostProfilePath"],
        "strategyDescriptor": inputs["descriptorPath"],
        "strategyCapabilityManifest": inputs["capabilityManifestPath"],
        "strategyProjectProfile": inputs["projectProfilePath"],
    }


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

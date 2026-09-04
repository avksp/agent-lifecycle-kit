from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent_lifecycle.workflow.continuation_batch as continuation_batch_module
from agent_lifecycle.contracts import canonical_bytes, sha256_hex, write_json_create
from agent_lifecycle.workflow import continue_workflow, continue_workflow_batch
from agent_lifecycle.workflow.continuation import CONTINUATION_APPLY_ACTION_TYPES
from agent_lifecycle.workflow.continuation_batch import STOP_ACTION_REASONS
from agent_lifecycle.workflow.transition_contract import ACTION_TYPES

from .test_authorization import _receipt as _authorization_receipt
from .test_continuation import _continuation_strategy_inputs
from .test_task_acceptance_audit_gate import _write_bundle as _write_audit_bundle
from .test_task_acceptance_audit_gate import _write_result_review
from .test_task_transitions import _write_strategy_start_bundle
from .test_workflow_run import _write_bundle


class WorkflowContinuationBatchTests(unittest.TestCase):
    def test_three_transition_bundle_applies_consecutive_existing_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            bundle_path = _write_three_transition_bundle(root, state_path)

            summary = _batch(manifest_path, state_path, bundle_path=bundle_path)

            self.assertEqual(summary["stopReason"], "INPUT_REQUIRED")
            self.assertEqual(summary["appliedCount"], 3)
            self.assertEqual(_read(state_path)["stateRevision"], 4)
            self.assertEqual(len(_events(root)), 3)
            self.assertEqual({item["name"] for item in summary["requiredInputs"]}, {"result"})

    def test_applied_result_postflight_blockers_defer_to_fresh_next_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit_bundle = _write_audit_bundle(root, phase="RUNNING", task_status="RUNNING", audit_required=True)
            manifest_path = Path(audit_bundle["manifestPath"])
            state_path = Path(audit_bundle["statePath"])
            result_path, _ = _write_result_review(root, audit_bundle)
            bundle_path = _write_custom_bundle(
                root,
                [
                    {
                        "operationId": "batch-task-result",
                        "expectedActionType": "wait-for-active-tasks",
                        "inputs": {
                            "result": {
                                "path": result_path,
                                "sha256": sha256_hex((root / result_path).read_bytes()),
                            }
                        },
                    }
                ],
            )

            summary = _batch(manifest_path, state_path, bundle_path=bundle_path)

            self.assertEqual(summary["stopReason"], "INPUT_REQUIRED")
            self.assertEqual(summary["appliedCount"], 1)
            self.assertEqual(
                {item["name"] for item in summary["requiredInputs"]},
                {"review", "implementationAudit"},
            )

    def test_two_transition_bundle_applies_existing_routes_and_stops_for_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            bundle_path = _write_batch_bundle(root)

            summary = _batch(manifest_path, state_path, bundle_path=bundle_path)

            state = _read(state_path)
            receipt = _read(root / "work/batch-receipt.json")
            events = _events(root)
            self.assertEqual(summary["status"], "STOPPED")
            self.assertEqual(summary["stopReason"], "INPUT_REQUIRED")
            self.assertEqual(summary["appliedCount"], 2)
            self.assertEqual(summary["alreadyAppliedCount"], 0)
            self.assertEqual(state["stateRevision"], 3)
            self.assertEqual(state["tasks"][0]["status"], "RUNNING")
            self.assertEqual([item["operationId"] for item in events], ["batch-start", "batch-task-start"])
            self.assertEqual(len(receipt["steps"]), 2)
            self.assertFalse(receipt["modelCallsStarted"])
            self.assertFalse(receipt["hostLaunchStarted"])
            self.assertEqual(receipt["receiptDigest"], summary["receiptDigest"])
            self.assertEqual(
                summary["outputBytes"],
                len((root / "work/batch-receipt.json").read_bytes()) + len(canonical_bytes(summary)) + 1,
            )
            self.assertLessEqual(summary["inputBytes"] + summary["outputBytes"], 1_048_576)

    def test_batch_task_start_consumes_same_strategy_as_one_step_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, strategy_path, strategy = _write_strategy_start_bundle(
                root,
                project_profile={"schemaVersion": "test-project-profile.v1", "profileId": "batch"},
            )
            manifest_path = root / "tasks/strategy/plan.manifest.json"
            inputs: dict[str, object] = {}
            for name, path in _continuation_strategy_inputs(strategy_path).items():
                if name == "strategyRequestedRisk":
                    inputs[name] = path
                    continue
                input_path = str(path)
                inputs[name] = {
                    "path": input_path,
                    "sha256": sha256_hex((root / input_path).read_bytes()),
                }
            projection = continue_workflow(
                state_path=state_path,
                manifest_path=manifest_path,
                lock_path=manifest_path.parent / "plan.lock.json",
                operation_id="start-strategy",
                expected_revision=1,
                source_revision="source",
                reason="bounded continuation test",
                inputs=_continuation_strategy_inputs(strategy_path),
            )
            bundle_path = _write_custom_bundle(
                root,
                [{"operationId": "start-strategy", "expectedActionType": "launch-tasks", "inputs": inputs}],
            )

            summary = _batch(manifest_path, state_path, bundle_path=bundle_path)

            state = _read(state_path)
            receipt = _read(root / "work/batch-receipt.json")
            self.assertEqual(summary["appliedCount"], 1)
            self.assertEqual(receipt["steps"][0]["projectedActionDigest"], projection["action"]["actionDigest"])
            self.assertEqual(
                state["tasks"][0]["attemptExecutionStrategy"]["strategyDigest"], strategy["strategyDigest"]
            )

    def test_transition_cap_stops_before_second_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            bundle_path = _write_batch_bundle(root)

            summary = _batch(
                manifest_path,
                state_path,
                bundle_path=bundle_path,
                max_transitions=1,
            )

            self.assertEqual(summary["stopReason"], "CAP_TRANSITIONS")
            self.assertEqual(summary["appliedCount"], 1)
            self.assertEqual(_read(state_path)["stateRevision"], 2)
            self.assertEqual(len(_events(root)), 1)

    def test_io_cap_stops_before_first_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            bundle_path = _write_batch_bundle(root)
            before = state_path.read_bytes()

            summary = _batch(
                manifest_path,
                state_path,
                bundle_path=bundle_path,
                max_io_bytes=20_000,
            )

            self.assertEqual(summary["stopReason"], "CAP_BYTES")
            self.assertEqual(summary["appliedCount"], 0)
            self.assertEqual(state_path.read_bytes(), before)
            self.assertFalse((root / "events.jsonl").exists())
            receipt = _read(root / "work/batch-receipt.json")
            self.assertEqual(
                summary["outputBytes"],
                len(canonical_bytes(receipt)) + len(canonical_bytes(summary)) + 2,
            )

    def test_bundle_top_level_shape_is_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            bundle_path = _write_batch_bundle(root)
            bundle = _read(root / bundle_path)
            bundle["unexpected"] = True
            (root / bundle_path).write_text(json.dumps(bundle), encoding="utf-8")
            before = state_path.read_bytes()

            summary = _batch(manifest_path, state_path, bundle_path=bundle_path)

            self.assertEqual(summary["stopReason"], "BLOCKED")
            self.assertIn("continuation-bundle-invalid", {item["code"] for item in summary["blockers"]})
            self.assertEqual(state_path.read_bytes(), before)

    def test_every_closed_stop_action_maps_to_its_receipt_reason(self) -> None:
        for action_type, expected_reason in STOP_ACTION_REASONS.items():
            with self.subTest(action_type=action_type), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
                bundle_path = _write_batch_bundle(root)
                projection = {
                    "status": "READY",
                    "action": {"managedActionType": action_type},
                    "requiredInputs": [],
                    "blockers": [],
                }
                with patch.object(continuation_batch_module, "_project", return_value=projection):
                    summary = _batch(manifest_path, state_path, bundle_path=bundle_path)

                self.assertEqual(summary["stopReason"], expected_reason)
                self.assertEqual(summary["appliedCount"], 0)

    def test_changed_reference_is_revalidated_before_each_later_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            risk_path = "inputs/risk-profile.json"
            write_json_create(root / risk_path, {"schemaVersion": "test-risk-profile.v1"})
            bundle_path = _write_three_transition_bundle(root, state_path, risk_profile_path=risk_path)
            original = continuation_batch_module._revalidate_snapshots
            calls = 0

            def change_after_first_check(context: object) -> None:
                nonlocal calls
                original(context)  # type: ignore[arg-type]
                calls += 1
                if calls == 1:
                    (root / risk_path).write_text('{"tampered":true}\n', encoding="utf-8")

            with patch.object(
                continuation_batch_module,
                "_revalidate_snapshots",
                side_effect=change_after_first_check,
            ):
                summary = _batch(manifest_path, state_path, bundle_path=bundle_path)

            self.assertEqual(summary["stopReason"], "BLOCKED")
            self.assertIn("continuation-input-changed", {item["code"] for item in summary["blockers"]})
            self.assertEqual(summary["appliedCount"], 1)
            self.assertEqual(_read(state_path)["stateRevision"], 2)

    def test_initial_action_mismatch_is_blocked_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            bundle_path = _write_batch_bundle(root, first_action="launch-tasks")
            before = state_path.read_bytes()

            summary = _batch(manifest_path, state_path, bundle_path=bundle_path)

            self.assertEqual(summary["stopReason"], "BLOCKED")
            self.assertIn("continuation-bundle-action-mismatch", {item["code"] for item in summary["blockers"]})
            self.assertEqual(state_path.read_bytes(), before)

    def test_terminal_state_completes_without_consuming_bundle_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="COMPLETE", task_status="ACCEPTED")
            bundle_path = _write_batch_bundle(root)
            before = state_path.read_bytes()

            summary = _batch(manifest_path, state_path, bundle_path=bundle_path)

            self.assertEqual(summary["status"], "COMPLETE")
            self.assertEqual(summary["stopReason"], "TERMINAL")
            self.assertEqual(summary["appliedCount"], 0)
            self.assertEqual(state_path.read_bytes(), before)
            self.assertFalse((root / "events.jsonl").exists())

    def test_terminal_retry_preserves_a_proven_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            bundle_path = _write_batch_bundle(root)
            _batch(
                manifest_path,
                state_path,
                bundle_path=bundle_path,
                output_path="work/first.json",
                max_transitions=1,
            )
            state = _read(state_path)
            state["phase"] = "COMPLETE"
            state["tasks"][0]["status"] = "ACCEPTED"
            state_path.write_text(json.dumps(state), encoding="utf-8")

            summary = _batch(
                manifest_path,
                state_path,
                bundle_path=bundle_path,
                output_path="work/terminal-retry.json",
                expected_revision=2,
                resume_receipt="work/first.json",
            )

            self.assertEqual(summary["stopReason"], "TERMINAL")
            self.assertEqual(summary["alreadyAppliedCount"], 1)
            self.assertEqual(len(_read(root / "work/terminal-retry.json")["steps"]), 1)

    def test_later_action_mismatch_is_stale_after_committed_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            bundle_path = _write_custom_bundle(
                root,
                [
                    {"operationId": "batch-start", "expectedActionType": "start-execution", "inputs": {}},
                    {"operationId": "batch-task-start", "expectedActionType": "launch-tasks", "inputs": {}},
                    {"operationId": "stale-third", "expectedActionType": "finalize-run", "inputs": {}},
                ],
            )

            summary = _batch(manifest_path, state_path, bundle_path=bundle_path)

            self.assertEqual(summary["stopReason"], "STALE_BUNDLE_ENTRY")
            self.assertEqual(summary["appliedCount"], 2)
            self.assertEqual(_read(state_path)["stateRevision"], 3)
            self.assertEqual(len(_events(root)), 2)

    def test_referenced_input_digest_mismatch_fails_before_output_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="RUNNING", task_status="RUNNING")
            write_json_create(root / "inputs/result.json", {"status": "not-consumed"})
            bundle_path = _write_custom_bundle(
                root,
                [
                    {
                        "operationId": "bad-result",
                        "expectedActionType": "wait-for-active-tasks",
                        "inputs": {"result": {"path": "inputs/result.json", "sha256": "f" * 64}},
                    }
                ],
            )
            before = state_path.read_bytes()

            summary = _batch(manifest_path, state_path, bundle_path=bundle_path)

            self.assertEqual(summary["stopReason"], "BLOCKED")
            self.assertIn("continuation-input-digest-mismatch", {item["code"] for item in summary["blockers"]})
            self.assertIsNone(summary["receiptPath"])
            self.assertEqual(state_path.read_bytes(), before)

    def test_exact_receipt_and_history_prefix_resume_without_duplicate_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            bundle_path = _write_batch_bundle(root)
            first = _batch(
                manifest_path,
                state_path,
                bundle_path=bundle_path,
                output_path="work/first.json",
                max_transitions=1,
            )
            self.assertEqual(first["stopReason"], "CAP_TRANSITIONS")

            resumed = _batch(
                manifest_path,
                state_path,
                bundle_path=bundle_path,
                output_path="work/resumed.json",
                expected_revision=2,
                resume_receipt="work/first.json",
            )

            self.assertEqual(resumed["stopReason"], "INPUT_REQUIRED")
            self.assertEqual(resumed["alreadyAppliedCount"], 1)
            self.assertEqual(resumed["appliedCount"], 1)
            self.assertEqual(len(_events(root)), 2)
            self.assertEqual(_read(state_path)["stateRevision"], 3)

    def test_reused_operation_without_receipt_requires_retry_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            bundle_path = _write_batch_bundle(root)
            _batch(
                manifest_path,
                state_path,
                bundle_path=bundle_path,
                output_path="work/first.json",
                max_transitions=1,
            )
            before = state_path.read_bytes()

            summary = _batch(
                manifest_path,
                state_path,
                bundle_path=bundle_path,
                output_path="work/retry.json",
                expected_revision=2,
            )

            self.assertEqual(summary["stopReason"], "RETRY_PROOF_REQUIRED")
            self.assertEqual(state_path.read_bytes(), before)
            self.assertEqual(len(_events(root)), 1)

    def test_terminal_reused_operation_without_receipt_requires_retry_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            bundle_path = _write_batch_bundle(root)
            _batch(
                manifest_path,
                state_path,
                bundle_path=bundle_path,
                output_path="work/first.json",
                max_transitions=1,
            )
            state = _read(state_path)
            state["phase"] = "COMPLETE"
            state["tasks"][0]["status"] = "ACCEPTED"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            before = state_path.read_bytes()

            summary = _batch(
                manifest_path,
                state_path,
                bundle_path=bundle_path,
                output_path="work/retry.json",
                expected_revision=2,
            )

            self.assertEqual(summary["stopReason"], "RETRY_PROOF_REQUIRED")
            self.assertEqual(state_path.read_bytes(), before)

    def test_ledger_ahead_of_receipt_is_retry_proof_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            bundle_path = _write_batch_bundle(root)
            _batch(
                manifest_path,
                state_path,
                bundle_path=bundle_path,
                output_path="work/first.json",
                max_transitions=1,
            )
            projection = continue_workflow(
                state_path=state_path,
                manifest_path=manifest_path,
                lock_path=manifest_path.parent / "plan.lock.json",
                operation_id="batch-task-start",
                expected_revision=2,
                source_revision="source",
                reason="simulate receipt crash window",
            )
            applied = continue_workflow(
                state_path=state_path,
                manifest_path=manifest_path,
                lock_path=manifest_path.parent / "plan.lock.json",
                operation_id="batch-task-start",
                expected_revision=2,
                source_revision="source",
                reason="simulate receipt crash window",
                apply=True,
                projected_state_revision=projection["action"]["stateRevision"],
                projected_action_digest=projection["action"]["actionDigest"],
            )
            self.assertEqual(applied["status"], "APPLIED")
            state = _read(state_path)
            state["phase"] = "COMPLETE"
            state["tasks"][0]["status"] = "ACCEPTED"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            before = state_path.read_bytes()

            summary = _batch(
                manifest_path,
                state_path,
                bundle_path=bundle_path,
                output_path="work/retry.json",
                expected_revision=3,
                resume_receipt="work/first.json",
            )

            self.assertEqual(summary["stopReason"], "RETRY_PROOF_MISMATCH")
            self.assertEqual(state_path.read_bytes(), before)
            self.assertEqual(len(_events(root)), 2)

    def test_tampered_resume_receipt_is_retry_proof_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            bundle_path = _write_batch_bundle(root)
            _batch(
                manifest_path,
                state_path,
                bundle_path=bundle_path,
                output_path="work/first.json",
                max_transitions=1,
            )
            receipt = _read(root / "work/first.json")
            receipt["steps"][0]["inputStepDigest"] = "f" * 64
            (root / "work/first.json").write_text(json.dumps(receipt), encoding="utf-8")
            before = state_path.read_bytes()

            summary = _batch(
                manifest_path,
                state_path,
                bundle_path=bundle_path,
                output_path="work/retry.json",
                expected_revision=2,
                resume_receipt="work/first.json",
            )

            self.assertEqual(summary["stopReason"], "RETRY_PROOF_MISMATCH")
            self.assertEqual(state_path.read_bytes(), before)

    def test_action_catalog_is_exactly_partitioned(self) -> None:
        apply_actions = set(CONTINUATION_APPLY_ACTION_TYPES)
        stop_actions = set(STOP_ACTION_REASONS)
        self.assertFalse(apply_actions & stop_actions)
        self.assertEqual(set(ACTION_TYPES), apply_actions | stop_actions)
        self.assertEqual(len(apply_actions), 7)
        self.assertEqual(len(stop_actions), 8)


def _write_batch_bundle(root: Path, *, first_action: str = "start-execution") -> str:
    return _write_custom_bundle(
        root,
        [
            {"operationId": "batch-start", "expectedActionType": first_action, "inputs": {}},
            {"operationId": "batch-task-start", "expectedActionType": "launch-tasks", "inputs": {}},
        ],
    )


def _write_custom_bundle(root: Path, steps: list[dict[str, object]]) -> str:
    path = "inputs/continuation-bundle.json"
    bundle = {
        "schemaVersion": "agent-workflow-continuation-input-bundle.v1",
        "runId": "run",
        "packageId": "package",
        "planDigest": _read(root / "run.state.json")["planDigest"],
        "sourceRevision": "source",
        "steps": steps,
    }
    write_json_create(root / path, bundle)
    return path


def _write_three_transition_bundle(
    root: Path,
    state_path: Path,
    *,
    risk_profile_path: str | None = None,
) -> str:
    state = _read(state_path)
    state["phase"] = "AWAITING_AUTHORIZATION"
    state["authorization"] = {"required": True, "granted": False}
    state["startMode"] = "approval-required"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    authorization_path = "inputs/authorization.json"
    write_json_create(root / authorization_path, _authorization_receipt(state))
    task_inputs: dict[str, object] = {}
    if risk_profile_path is not None:
        task_inputs["riskProfile"] = {
            "path": risk_profile_path,
            "sha256": sha256_hex((root / risk_profile_path).read_bytes()),
        }
    return _write_custom_bundle(
        root,
        [
            {
                "operationId": "batch-authorize",
                "expectedActionType": "request-execution-authorization",
                "inputs": {
                    "authorizationReceipt": {
                        "path": authorization_path,
                        "sha256": sha256_hex((root / authorization_path).read_bytes()),
                    }
                },
            },
            {"operationId": "batch-start", "expectedActionType": "start-execution", "inputs": {}},
            {"operationId": "batch-task-start", "expectedActionType": "launch-tasks", "inputs": task_inputs},
        ],
    )


def _batch(
    manifest_path: Path,
    state_path: Path,
    *,
    bundle_path: str,
    output_path: str = "work/batch-receipt.json",
    max_transitions: int = 8,
    max_io_bytes: int = 1_048_576,
    expected_revision: int = 1,
    resume_receipt: str | None = None,
) -> dict[str, object]:
    return continue_workflow_batch(
        state_path=state_path,
        manifest_path=manifest_path,
        lock_path=manifest_path.parent / "plan.lock.json",
        input_bundle_path=bundle_path,
        output_path=output_path,
        max_transitions=max_transitions,
        max_io_bytes=max_io_bytes,
        expected_revision=expected_revision,
        source_revision="source",
        reason="bounded continuation test",
        resume_receipt_path=resume_receipt,
    )


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _events(root: Path) -> list[dict[str, object]]:
    path = root / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()

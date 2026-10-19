"""Reader-sized prospective writes refuse before state/event/checkpoint I/O."""

from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, canonical_bytes
from agent_lifecycle.contracts.canonical import (
    MAX_JSON_INPUT_BYTES,
    MAX_JSON_NESTING,
    load_json_object,
    prepare_json_object,
)
from agent_lifecycle.workflow.checkpoint_gate import prepare_checkpoint_gate
from agent_lifecycle.workflow.events import prepare_event
from agent_lifecycle.workflow.operation_kernel import commit_state
from agent_lifecycle.workflow.state import load_state, write_state_replace
from tests.workflow.helpers import _write_state


class StateSizeBoundaryTests(unittest.TestCase):
    def test_exact_reader_byte_limit_round_trips_and_one_more_refuses(self) -> None:
        overhead = len(canonical_bytes({"padding": ""})) + 1
        value = {"padding": "x" * (MAX_JSON_INPUT_BYTES - overhead)}
        data = prepare_json_object(value)
        self.assertEqual(len(data), MAX_JSON_INPUT_BYTES)
        self.assertEqual(load_json_object(data), value)
        value["padding"] += "x"
        with self.assertRaises(LifecycleError) as caught:
            prepare_json_object(value)
        self.assertEqual(caught.exception.code, "json-input-too-large")

    def fixture(self, root):
        path = _write_state(root, phase="RUNNING")
        state = load_state(path)
        state["contextCheckpointPolicy"] = {
            "enabled": True,
            "required": True,
            "milestoneEvents": ["size-test"],
            "checkpointRoot": ".alk/context/checkpoints",
        }
        write_state_replace(path, state)
        return path, state

    def assert_untouched(self, root, path, before):
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((root / "events.jsonl").exists())
        self.assertFalse((root / ".alk").exists())

    def test_complete_event_includes_checkpoint_metadata_before_first_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, state = self.fixture(root)
            before = path.read_bytes()
            receipt = prepare_checkpoint_gate(
                state_path=path, state=state, operation_id="oversize", event_type="size-test", payload={"padding": ""}
            ).receipt
            next_state = {**state, "stateRevision": 2}
            event = prepare_event(
                state=next_state,
                operation_id="oversize",
                event_type="size-test",
                payload={"padding": "", "contextCheckpoint": receipt},
            )
            padding = MAX_JSON_INPUT_BYTES - len(canonical_bytes(event))
            payload = {"padding": "x" * padding}
            self.assertLess(len(canonical_bytes(payload)) + 1, MAX_JSON_INPUT_BYTES)
            with self.assertRaises(LifecycleError) as caught:
                commit_state(path, state, operation_id="oversize", event_type="size-test", payload=payload)
            self.assertEqual(caught.exception.code, "json-input-too-large")
            self.assert_untouched(root, path, before)

    def test_new_ledger_record_cannot_make_a_readable_state_unreadable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, state = self.fixture(root)
            state["operationLedger"] = {
                f"prior-{index}": {"eventType": "historical", "stateRevision": 1, "recordedAt": "2026-01-01T00:00:00Z"}
                for index in range(7000)
            }
            state["lastReason"] = ""
            remainder = MAX_JSON_INPUT_BYTES - len(canonical_bytes(state)) - 1 - 20
            self.assertGreater(remainder, 0)
            state["lastReason"] = "x" * remainder
            write_state_replace(path, state)
            before = path.read_bytes()
            self.assertEqual(len(before), MAX_JSON_INPUT_BYTES - 20)
            with self.assertRaises(LifecycleError) as caught:
                commit_state(path, state, operation_id="next-record", event_type="size-test", payload={})
            self.assertEqual(caught.exception.code, "json-input-too-large")
            self.assert_untouched(root, path, before)
            self.assertEqual(len(load_state(path)["operationLedger"]), 7000)

    def test_deep_event_payload_refuses_before_checkpoint_or_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, state = self.fixture(root)
            before = path.read_bytes()
            payload = {}
            for _ in range(MAX_JSON_NESTING + 1):
                payload = {"nested": payload}
            original = deepcopy(payload)
            with self.assertRaises(LifecycleError) as caught:
                commit_state(path, state, operation_id="too-deep", event_type="size-test", payload=payload)
            self.assertEqual(caught.exception.code, "json-input-depth-exceeded")
            self.assertEqual(payload, original)
            self.assert_untouched(root, path, before)

    def near_limit(self, path):
        state = load_state(path)
        state["lastReason"] = ""
        state["lastReason"] = "x" * (MAX_JSON_INPUT_BYTES - len(canonical_bytes(state)) - 31)
        write_state_replace(path, state)
        return path.read_bytes()

    def test_extreme_nesting_has_the_same_stable_refusal_before_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, state = self.fixture(root)
            before = path.read_bytes()
            payload = {}
            for _ in range(2000):
                payload = {"nested": payload}
            with self.assertRaises(LifecycleError) as caught:
                commit_state(path, state, operation_id="extreme-depth", event_type="size-test", payload=payload)
            self.assertEqual(caught.exception.code, "json-input-depth-exceeded")
            self.assert_untouched(root, path, before)

    def test_oversized_budget_pause_does_not_create_its_decision_sidecar(self) -> None:
        from agent_lifecycle.contracts import write_json_create
        from agent_lifecycle.workflow import pause_for_budget_decision, start_task
        from tests.workflow.helpers import _budget_policy, _model_route, _model_usage_receipt, _set_task_model_route

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = _write_state(root, phase="RUNNING")
            route = _model_route()
            _set_task_model_route(path, route)
            start_task(
                path,
                task_id="WS-01",
                operation_id="start",
                expected_revision=1,
                source_revision="source",
                reason="unit",
            )
            receipt = _model_usage_receipt(route)
            receipt["usage"]["billableTokens"] = route["maxBillableTokens"] + 1
            write_json_create(root / "usage.json", receipt)
            write_json_create(root / "policy.json", _budget_policy(mode="manual"))
            before = self.near_limit(path)
            events = (root / "events.jsonl").read_bytes()
            with self.assertRaises(LifecycleError) as caught:
                pause_for_budget_decision(
                    path,
                    task_id="WS-01",
                    operation_id="over-limit",
                    expected_revision=2,
                    source_revision="source",
                    usage_receipt_path="usage.json",
                    budget_policy_path="policy.json",
                    decision_receipt_path="decision.json",
                    reason="unit overrun",
                )
            self.assertEqual(caught.exception.code, "json-input-too-large")
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual((root / "events.jsonl").read_bytes(), events)
            self.assertFalse((root / "decision.json").exists())

    def test_oversized_finalization_does_not_create_its_proof_sidecar(self) -> None:
        from agent_lifecycle.contracts import write_json_create
        from agent_lifecycle.workflow import finalize_run
        from tests.workflow.helpers import _final_audit

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = _write_state(root, phase="FINAL_AUDIT")
            state = load_state(path)
            state["tasks"][0].update(
                status="ACCEPTED",
                attempt=1,
                review={"path": "work/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10},
            )
            write_state_replace(path, state)
            write_json_create(root / "audit.json", _final_audit())
            before = self.near_limit(path)
            with self.assertRaises(LifecycleError) as caught:
                finalize_run(
                    path,
                    operation_id="over-limit",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="audit.json",
                    proof_path="proof.json",
                    reason="unit finalization",
                )
            self.assertEqual(caught.exception.code, "json-input-too-large")
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse((root / "proof.json").exists())
            self.assertFalse((root / "events.jsonl").exists())

    def test_prepared_registry_is_pure_and_refuses_a_changed_financial_frontier(self) -> None:
        from agent_lifecycle.workflow.limited_usage import aggregate_source_usage_assurance
        from tests.workflow.test_limited_usage import DeclaredFixture

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            fixture = DeclaredFixture(root)
            fixture.task["status"] = "ACCEPTED"
            fixture.append_window(398, cap=3000)
            prepared = []
            assurance = aggregate_source_usage_assurance(root, fixture.state, prepared_registries=prepared)
            self.assertEqual(len(prepared), 1)
            path = root / prepared[0].reference["path"]
            self.assertFalse(path.exists())
            self.assertIsNone(assurance["actualTokens"])
            fixture.append_window(399, cap=3000)
            with self.assertRaises(LifecycleError) as caught:
                prepared[0].persist()
            self.assertEqual(caught.exception.code, "scoped-usage-frontier-stale")
            self.assertFalse(path.exists())
            current = []
            aggregate_source_usage_assurance(root, fixture.state, prepared_registries=current)
            current[0].persist()
            self.assertEqual((root / current[0].reference["path"]).read_bytes(), current[0].snapshot["projectionBytes"])

    def test_oversized_limited_finalization_preserves_registry_history_without_new_files(self) -> None:
        from agent_lifecycle.contracts import write_json_create
        from agent_lifecycle.workflow import finalize_run
        from tests.workflow.helpers import _final_audit
        from tests.workflow.test_limited_usage import DeclaredFixture, put

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            fixture = DeclaredFixture(root)
            fixture.task["status"] = "ACCEPTED"
            fixture.state["phase"] = "FINAL_AUDIT"
            fixture.append_window(398, cap=3000)
            put(root, "run.state.json", fixture.state)
            audit = _final_audit()
            audit["planDigest"] = fixture.state["planDigest"]
            audit["completionSignal"].update(
                packageId="release-2-16", planDigest=fixture.state["planDigest"], sourceRevision=fixture.revision
            )
            write_json_create(root / "audit.json", audit)
            before = self.near_limit(fixture.state_path)
            registry_before = {
                p.relative_to(root).as_posix(): p.read_bytes()
                for p in root.glob("work/WS-01/attempt-1/source-usage-registry-*.json")
            }
            self.assertTrue(registry_before)
            with self.assertRaises(LifecycleError) as caught:
                finalize_run(
                    fixture.state_path,
                    operation_id="limited-over-limit",
                    expected_revision=1,
                    source_revision=fixture.revision,
                    final_audit_path="audit.json",
                    proof_path="proof.json",
                    reason="local accepted-state fixture; not native proof",
                )
            self.assertEqual(caught.exception.code, "json-input-too-large")
            self.assertEqual(fixture.state_path.read_bytes(), before)
            self.assertFalse((root / "proof.json").exists())
            self.assertFalse((root / "events.jsonl").exists())
            self.assertEqual(
                registry_before,
                {
                    p.relative_to(root).as_posix(): p.read_bytes()
                    for p in root.glob("work/WS-01/attempt-1/source-usage-registry-*.json")
                },
            )

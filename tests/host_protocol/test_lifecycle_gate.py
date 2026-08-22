from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import UTC, datetime

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.lifecycle_control_schemas import (
    build_default_lifecycle_control_policy,
    build_lifecycle_control_event,
)
from agent_lifecycle.host_protocol.lifecycle_gate import (
    evaluate_post_action_gate,
    evaluate_pre_action_gate,
    evaluate_stop_gate,
    require_lifecycle_gate_pass,
)


class LifecycleGateTests(unittest.TestCase):
    def test_pre_action_accepts_frozen_owned_action_only_at_enforced_level(self) -> None:
        manifest, lock, state = _bundle()
        policy = _enforced_policy("file-edit")

        gate = evaluate_pre_action_gate(
            manifest=manifest,
            lock=lock,
            state=state,
            operation="file-edit",
            action_digest="c" * 64,
            paths=["src/example.py"],
            policy=policy,
            requested_level="ENFORCED",
            next_action={"projectedAction": {"type": "launch-tasks", "taskIds": ["WS-01"]}},
            task_id="WS-01",
        )

        self.assertEqual(gate["status"], "PASS")
        self.assertTrue(gate["blocking"] is False)
        self.assertTrue(gate["decision"]["hostActionAllowed"])
        require_lifecycle_gate_pass(gate, gate_type="pre-action")

    def test_pre_action_blocks_lock_drift_and_unsafe_path(self) -> None:
        manifest, lock, state = _bundle()
        manifest["readOnly"] = ["docs"]
        lock["manifestHash"] = "f" * 64
        gate = evaluate_pre_action_gate(
            manifest=manifest,
            lock=lock,
            state=state,
            operation="file-edit",
            action_digest="c" * 64,
            paths=["docs/outside.md"],
            policy=_enforced_policy("file-edit"),
            requested_level="ENFORCED",
            next_action={"projectedAction": {"type": "launch-tasks", "taskIds": ["WS-01"]}},
            task_id="WS-01",
        )

        codes = {item["code"] for item in gate["blockers"]}
        self.assertEqual(gate["status"], "BLOCKED")
        self.assertTrue(gate["blocking"])
        self.assertIn("plan-lock-mismatch", codes)
        self.assertIn("ownership-unsafe-path", codes)
        self.assertEqual(gate["ownership"]["entries"][0]["category"], "read-only")
        manifest["readOnly"] = []
        manifest["forbiddenWrites"] = ["secrets"]
        forbidden_gate = evaluate_pre_action_gate(
            manifest=manifest,
            lock=lock,
            state=state,
            operation="file-edit",
            action_digest="c" * 64,
            paths=["secrets/token.txt"],
            policy=_enforced_policy("file-edit"),
            requested_level="ENFORCED",
            next_action={"projectedAction": {"type": "launch-tasks", "taskIds": ["WS-01"]}},
            task_id="WS-01",
        )
        self.assertEqual(forbidden_gate["ownership"]["entries"][0]["category"], "forbidden")
        with self.assertRaises(LifecycleError):
            require_lifecycle_gate_pass(gate, gate_type="pre-action")

    def test_pre_action_rejects_draft_plan_and_wrong_next_action(self) -> None:
        manifest, lock, state = _bundle()
        manifest["status"] = "DRAFT"
        draft_gate = evaluate_pre_action_gate(
            manifest=manifest,
            lock=lock,
            state=state,
            operation="file-edit",
            action_digest="c" * 64,
            paths=["src/example.py"],
            policy=_enforced_policy("file-edit"),
            requested_level="ENFORCED",
            next_action={"projectedAction": {"type": "launch-tasks", "taskIds": ["WS-01"]}},
            task_id="WS-01",
        )
        self.assertIn("plan-not-frozen", {item["code"] for item in draft_gate["blockers"]})

        manifest, lock, state = _bundle()
        wrong_action_gate = evaluate_pre_action_gate(
            manifest=manifest,
            lock=lock,
            state=state,
            operation="file-edit",
            action_digest="c" * 64,
            paths=["src/example.py"],
            policy=_enforced_policy("file-edit"),
            requested_level="ENFORCED",
            next_action={"projectedAction": {"type": "finalize-run", "taskIds": []}},
        )
        self.assertIn("next-action-mismatch", {item["code"] for item in wrong_action_gate["blockers"]})

        manifest, lock, state = _bundle()
        missing_action_gate = evaluate_pre_action_gate(
            manifest=manifest,
            lock=lock,
            state=state,
            operation="file-edit",
            action_digest="c" * 64,
            paths=["src/example.py"],
            policy=_enforced_policy("file-edit"),
            requested_level="ENFORCED",
            task_id="WS-01",
        )
        self.assertEqual(missing_action_gate["status"], "BLOCKED")
        self.assertIn("next-action-missing", {item["code"] for item in missing_action_gate["blockers"]})

    def test_invalid_selected_level_fails_closed(self) -> None:
        manifest, lock, state = _bundle()
        state["lifecycleControl"]["level"] = "ENFORCED "
        gate = evaluate_pre_action_gate(
            manifest=manifest,
            lock=lock,
            state=state,
            operation="file-edit",
            action_digest="c" * 64,
            paths=["src/example.py"],
            requested_level="ENFORCED ",
            policy=_enforced_policy("file-edit"),
            next_action={"projectedAction": {"type": "launch-tasks", "taskIds": ["WS-01"]}},
            task_id="WS-01",
        )

        self.assertEqual(gate["status"], "BLOCKED")
        self.assertTrue(gate["blocking"])
        self.assertIn("control-selection-level-invalid", {item["code"] for item in gate["blockers"]})

    def test_continue_phase_cannot_authorize_a_host_operation(self) -> None:
        manifest, lock, state = _bundle()
        gate = evaluate_pre_action_gate(
            manifest=manifest,
            lock=lock,
            state=state,
            operation="file-edit",
            action_digest="c" * 64,
            paths=["src/example.py"],
            policy=_enforced_policy("file-edit"),
            requested_level="ENFORCED",
            next_action={"projectedAction": {"type": "continue-phase", "taskIds": ["WS-01"]}},
            task_id="WS-01",
        )

        self.assertEqual(gate["status"], "BLOCKED")
        self.assertIn("next-action-mismatch", {item["code"] for item in gate["blockers"]})

    def test_observed_level_records_a_safe_decision_without_host_permission(self) -> None:
        manifest, lock, state = _bundle()
        state["lifecycleControl"]["level"] = "OBSERVED"
        gate = evaluate_pre_action_gate(
            manifest=manifest,
            lock=lock,
            state=state,
            operation="file-edit",
            action_digest="c" * 64,
            paths=["src/example.py"],
            policy=_policy_for_level("file-edit", "OBSERVED"),
            requested_level="OBSERVED",
            next_action={"projectedAction": {"type": "launch-tasks", "taskIds": ["WS-01"]}},
            task_id="WS-01",
        )

        self.assertEqual(gate["status"], "PASS")
        self.assertTrue(gate["selected"])
        self.assertFalse(gate["enforcementActive"])
        self.assertFalse(gate["decision"]["hostActionAllowed"])

    def test_post_action_rejects_changed_path_drift(self) -> None:
        manifest, lock, state = _bundle()
        pre = evaluate_pre_action_gate(
            manifest=manifest,
            lock=lock,
            state=state,
            operation="file-edit",
            action_digest="c" * 64,
            paths=["src/example.py"],
            policy=_enforced_policy("file-edit"),
            requested_level="ENFORCED",
            next_action={"projectedAction": {"type": "launch-tasks", "taskIds": ["WS-01"]}},
            task_id="WS-01",
        )
        post = evaluate_post_action_gate(
            pre_action=pre,
            manifest=manifest,
            actual_changed_paths=["src/other.py"],
            actual_status="PASS",
        )

        self.assertEqual(post["status"], "BLOCKED")
        self.assertIn("post-action-path-drift", {item["code"] for item in post["blockers"]})

    def test_post_action_rejects_replayed_event_lineage(self) -> None:
        manifest, lock, state = _bundle()
        pre = evaluate_pre_action_gate(
            manifest=manifest,
            lock=lock,
            state=state,
            operation="file-edit",
            action_digest="c" * 64,
            paths=["src/example.py"],
            policy=_enforced_policy("file-edit"),
            requested_level="ENFORCED",
            next_action={"projectedAction": {"type": "launch-tasks", "taskIds": ["WS-01"]}},
            task_id="WS-01",
        )
        event = build_lifecycle_control_event(
            pre["request"],
            event_id="event-replayed",
            event_type="post-action",
            status="PASS",
            producer_id="host-hook",
            outcome={"status": "PASS"},
        )
        event["requestDigest"] = "e" * 64
        event["eventDigest"] = canonical_digest({key: value for key, value in event.items() if key != "eventDigest"})
        post = evaluate_post_action_gate(
            pre_action=pre,
            manifest=manifest,
            actual_changed_paths=["src/example.py"],
            event=event,
        )

        self.assertEqual(post["status"], "BLOCKED")
        self.assertIn("control-event-lineage-mismatch", {item["code"] for item in post["blockers"]})

    def test_stop_requires_both_control_events_and_final_proof(self) -> None:
        manifest, lock, state = _bundle()
        policy = _enforced_policy("run-finalize")
        pre = evaluate_pre_action_gate(
            manifest=manifest,
            lock=lock,
            state=state,
            operation="run-finalize",
            action_digest="d" * 64,
            paths=[],
            policy=policy,
            requested_level="ENFORCED",
            next_action={"projectedAction": {"type": "finalize-run", "taskIds": []}},
        )
        post = evaluate_post_action_gate(
            pre_action=pre,
            manifest=manifest,
            actual_changed_paths=[],
            actual_status="PASS",
            event=build_lifecycle_control_event(
                pre["request"],
                event_id="event-finalize",
                event_type="post-action",
                status="PASS",
                producer_id="host-hook",
                outcome={"status": "PASS"},
            ),
        )
        final_audit = {"status": "PASS", "planDigest": state["planDigest"]}
        final_proof = {
            "schemaVersion": "agent-run-final-proof.v1",
            "runId": state["runId"],
            "planDigest": state["planDigest"],
        }

        stop = evaluate_stop_gate(
            state=state,
            final_audit=final_audit,
            final_proof=final_proof,
            pre_action=pre,
            post_action=post,
            requested_level="ENFORCED",
            policy=policy,
        )

        self.assertEqual(pre["status"], "PASS")
        self.assertEqual(post["status"], "PASS")
        self.assertEqual(stop["status"], "PASS")
        require_lifecycle_gate_pass(stop, gate_type="stop")

    def test_off_mode_does_not_require_plan_or_evidence(self) -> None:
        manifest, lock, state = _bundle()
        state["lifecycleControl"] = {"level": "OFF"}
        manifest["status"] = "DRAFT"
        lock["manifestHash"] = "f" * 64
        gate = evaluate_pre_action_gate(
            manifest=manifest,
            lock=lock,
            state=state,
            operation="file-edit",
            action_digest="c" * 64,
            paths=[],
            requested_level="OFF",
        )

        self.assertEqual(gate["status"], "PASS")
        self.assertFalse(gate["blocking"])

    def test_same_lineage_produces_same_gate_digest(self) -> None:
        manifest, lock, state = _bundle()
        policy = _enforced_policy("file-edit")
        arguments = {
            "manifest": manifest,
            "lock": lock,
            "state": state,
            "operation": "file-edit",
            "action_digest": "c" * 64,
            "paths": ["src/example.py"],
            "policy": policy,
            "requested_level": "ENFORCED",
            "next_action": {"projectedAction": {"type": "launch-tasks", "taskIds": ["WS-01"]}},
            "task_id": "WS-01",
            "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }

        first = evaluate_pre_action_gate(**arguments)
        second = evaluate_pre_action_gate(**arguments)

        self.assertEqual(first["gateDigest"], second["gateDigest"])

    def test_selected_level_must_be_bound_to_the_frozen_plan(self) -> None:
        manifest, lock, state = _bundle()
        state["lifecycleControl"]["planDigest"] = "f" * 64
        gate = evaluate_pre_action_gate(
            manifest=manifest,
            lock=lock,
            state=state,
            operation="file-edit",
            action_digest="c" * 64,
            paths=["src/example.py"],
            policy=_enforced_policy("file-edit"),
            requested_level="ENFORCED",
            next_action={"projectedAction": {"type": "launch-tasks", "taskIds": ["WS-01"]}},
            task_id="WS-01",
        )

        self.assertEqual(gate["status"], "BLOCKED")
        self.assertIn("control-selection-plan-mismatch", {item["code"] for item in gate["blockers"]})

    def test_enforced_selection_cannot_be_bypassed_by_requesting_off(self) -> None:
        manifest, lock, state = _bundle()
        gate = evaluate_pre_action_gate(
            manifest=manifest,
            lock=lock,
            state=state,
            operation="file-edit",
            action_digest="c" * 64,
            paths=["src/example.py"],
            policy=_enforced_policy("file-edit"),
            requested_level="OFF",
        )

        self.assertEqual(gate["status"], "BLOCKED")
        self.assertTrue(gate["blocking"])
        self.assertIn("control-selection-bypass", {item["code"] for item in gate["blockers"]})

    def test_stop_rejects_tampered_post_action_digest(self) -> None:
        manifest, lock, state = _bundle()
        policy = _enforced_policy("run-finalize")
        pre = evaluate_pre_action_gate(
            manifest=manifest,
            lock=lock,
            state=state,
            operation="run-finalize",
            action_digest="d" * 64,
            paths=[],
            policy=policy,
            requested_level="ENFORCED",
            next_action={"projectedAction": {"type": "finalize-run", "taskIds": []}},
        )
        post = evaluate_post_action_gate(
            pre_action=pre,
            manifest=manifest,
            actual_changed_paths=[],
            actual_status="PASS",
            event=build_lifecycle_control_event(
                pre["request"],
                event_id="event-finalize",
                event_type="post-action",
                status="PASS",
                producer_id="host-hook",
                outcome={"status": "PASS"},
            ),
        )
        post["actualChangedPaths"] = ["src/forged.py"]
        final_audit = {"status": "PASS", "planDigest": state["planDigest"]}
        final_proof = {
            "schemaVersion": "agent-run-final-proof.v1",
            "runId": state["runId"],
            "planDigest": state["planDigest"],
        }

        stop = evaluate_stop_gate(
            state=state,
            final_audit=final_audit,
            final_proof=final_proof,
            pre_action=pre,
            post_action=post,
            requested_level="ENFORCED",
            policy=policy,
        )

        self.assertEqual(stop["status"], "BLOCKED")
        self.assertIn("post-action-evidence-invalid", {item["code"] for item in stop["blockers"]})


def _bundle() -> tuple[dict, dict, dict]:
    manifest = {
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "package", "planArtifactRoot": "plans/package"},
        "workstreams": [{"id": "WS-01", "writes": ["src"]}],
        "readOnly": [],
        "forbiddenWrites": [],
        "leadOwned": [],
    }
    lock = {
        "schemaVersion": "agent-plan-lock.v1",
        "packageId": "package",
        "planRevision": 1,
        "manifestHash": canonical_digest(manifest),
    }
    state = {
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": canonical_digest(manifest),
        "stateRevision": 1,
        "lifecycleControl": {
            "level": "ENFORCED",
            "source": "frozen-plan",
            "planDigest": canonical_digest(manifest),
            "planRevision": 1,
        },
        "tasks": [{"id": "WS-01", "status": "ACCEPTED", "required": True}],
    }
    return manifest, lock, state


def _enforced_policy(operation: str) -> dict:
    policy = deepcopy(build_default_lifecycle_control_policy())
    policy["operations"][operation] = {
        "declaredLevel": "ENFORCED",
        "supported": True,
        "qualified": True,
        "effectiveLevel": "ENFORCED",
        "qualificationStatus": "QUALIFIED",
        "hostOwnedPreAction": True,
    }
    body = {key: value for key, value in policy.items() if key != "policyDigest"}
    return {**body, "policyDigest": canonical_digest(body)}


def _policy_for_level(operation: str, level: str) -> dict:
    policy = _enforced_policy(operation)
    policy["operations"][operation]["declaredLevel"] = level
    policy["operations"][operation]["effectiveLevel"] = level
    body = {key: value for key, value in policy.items() if key != "policyDigest"}
    return {**body, "policyDigest": canonical_digest(body)}


if __name__ == "__main__":
    unittest.main()

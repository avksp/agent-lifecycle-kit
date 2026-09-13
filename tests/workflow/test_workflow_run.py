from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.lifecycle_control_schemas import build_default_lifecycle_control_policy
from agent_lifecycle.workflow.run import run_workflow_step


class WorkflowRunTests(unittest.TestCase):
    def test_managed_runner_rejects_unknown_authority_before_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="RUNNING", task_status="READY")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["schemaVersion"] = "agent-plan-manifest.v1"
            manifest["integrationSeams"] = ["controller"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            receipt = run_workflow_step(
                state_path=state_path,
                manifest_path=manifest_path,
                operation_id="managed-invalid-op",
                expected_revision=1,
                source_revision="source",
            )

            self.assertEqual(receipt["status"], "FAIL")
            self.assertIn("plan-manifest-contract-failed", {item["code"] for item in receipt["blockers"]})
            self.assertEqual(receipt["nextAction"]["type"], "blocked")
            self.assertFalse(receipt["stateWritten"])

    def test_legacy_off_runner_guards_state_root_before_action(self) -> None:
        for policy in ("alias", "unknown", "distinct"):
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest_path, state_path = _write_bundle(root, phase="RUNNING", task_status="READY", lifecycle_level="OFF")
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["readOnly"] = ["Private"]
                manifest["workstreams"][0]["writes"] = ["private/file.py"]
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                lock_path = manifest_path.with_name("plan.lock.json")
                lock = json.loads(lock_path.read_text(encoding="utf-8"))
                lock["manifestHash"] = canonical_digest(manifest)
                lock_path.write_text(json.dumps(lock), encoding="utf-8")
                state = json.loads(state_path.read_text(encoding="utf-8"))
                state["planDigest"] = canonical_digest(manifest)
                state["lifecycleControl"]["planDigest"] = state["planDigest"]
                state_path.write_text(json.dumps(state), encoding="utf-8")
                before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                self.assertNotEqual(Path.cwd(), root)
                def compare(anchor, _parent, _left, _right, *, expected_root=root, expected_policy=policy):
                    self.assertEqual(anchor, expected_root.resolve())
                    return expected_policy == "alias"
                comparison = patch("agent_lifecycle.contracts.ownership_paths._same_filesystem_name", side_effect=compare) if policy != "unknown" else nullcontext()
                with comparison:
                    receipt = run_workflow_step(state_path=state_path, manifest_path=manifest_path,
                                                operation_id="root-guard", expected_revision=1, source_revision="source")
                self.assertEqual(receipt["status"], "PASS" if policy == "distinct" else "FAIL")
                self.assertEqual(receipt["nextAction"]["type"], "launch-tasks" if policy == "distinct" else "blocked")
                if policy != "distinct":
                    self.assertIn("ambiguous-authority-path" if policy == "alias" else "filesystem-policy-unavailable",
                                  {b["code"] for b in receipt["blockers"]})
                self.assertEqual({p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}, before)

    def test_ready_task_returns_host_owned_launch_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="RUNNING", task_status="READY")

            receipt = run_workflow_step(
                state_path=state_path,
                manifest_path=manifest_path,
                operation_id="managed-op",
                expected_revision=1,
                source_revision="source",
                reason="next step",
            )

            self.assertEqual(receipt["schemaVersion"], "agent-workflow-run-receipt.v1")
            self.assertEqual(receipt["status"], "PASS")
            self.assertEqual(receipt["nextAction"]["type"], "launch-tasks")
            self.assertEqual(receipt["nextAction"]["taskIds"], ["WS-01"])
            self.assertTrue(receipt["nextAction"]["hostActionRequired"])
            self.assertFalse(receipt["modelCallsStarted"])
            self.assertFalse(receipt["stateWritten"])
            self.assertFalse(receipt["hostLaunchStarted"])

    def test_rework_task_routes_same_task_to_next_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="REMEDIATING", task_status="REWORK")

            receipt = run_workflow_step(
                state_path=state_path,
                manifest_path=manifest_path,
                operation_id="managed-rework-op",
                expected_revision=1,
                source_revision="source",
                reason="continue remediation",
            )

            self.assertEqual(receipt["status"], "PASS")
            self.assertEqual(receipt["nextAction"]["type"], "launch-tasks")
            self.assertEqual(receipt["nextAction"]["taskIds"], ["WS-01"])
            self.assertEqual(receipt["nextAction"]["projectedAction"]["reason"], "start-remediation-attempt")

    def test_final_audit_phase_returns_finalize_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="FINAL_AUDIT", task_status="ACCEPTED")

            receipt = run_workflow_step(
                state_path=state_path,
                manifest_path=manifest_path,
                operation_id="managed-op",
                expected_revision=1,
                source_revision="source",
            )

            self.assertEqual(receipt["status"], "PASS")
            self.assertEqual(receipt["nextAction"]["type"], "finalize-run")
            self.assertTrue(receipt["nextAction"]["stateMutationRequired"])

    def test_stale_state_revision_fails_closed_without_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="RUNNING", task_status="READY")

            receipt = run_workflow_step(
                state_path=state_path,
                manifest_path=manifest_path,
                operation_id="managed-op",
                expected_revision=2,
                source_revision="source",
            )

            self.assertEqual(receipt["status"], "FAIL")
            self.assertEqual(receipt["nextAction"]["type"], "blocked")
            self.assertIn("state-revision-mismatch", {item["code"] for item in receipt["blockers"]})
            self.assertFalse(receipt["modelCallsStarted"])

    def test_non_frozen_plan_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="RUNNING", task_status="READY", plan_status="DRAFT")

            receipt = run_workflow_step(
                state_path=state_path,
                manifest_path=manifest_path,
                operation_id="managed-op",
                expected_revision=1,
                source_revision="source",
            )

            self.assertEqual(receipt["status"], "FAIL")
            self.assertIn("plan-not-frozen", {item["code"] for item in receipt["blockers"]})

    def test_source_revision_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="RUNNING", task_status="READY")

            receipt = run_workflow_step(
                state_path=state_path,
                manifest_path=manifest_path,
                operation_id="managed-op",
                expected_revision=1,
                source_revision="different-source",
            )

            self.assertEqual(receipt["status"], "FAIL")
            self.assertIn("source-revision-mismatch", {item["code"] for item in receipt["blockers"]})

    def test_enforced_control_projects_launch_tasks_as_file_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(
                root,
                phase="RUNNING",
                task_status="READY",
                lifecycle_level="ENFORCED",
            )

            receipt = run_workflow_step(
                state_path=state_path,
                manifest_path=manifest_path,
                operation_id="managed-enforced-op",
                expected_revision=1,
                source_revision="source",
            )

            self.assertEqual(receipt["status"], "PASS")
            self.assertEqual(receipt["lifecycleControl"]["operation"], "file-edit")
            self.assertTrue(receipt["lifecycleControl"]["selected"])


def _write_bundle(
    root: Path,
    *,
    phase: str,
    task_status: str,
    plan_status: str = "FROZEN",
    lifecycle_level: str | None = None,
) -> tuple[Path, Path]:
    manifest = {
        "status": plan_status,
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
    state = {
        "schemaVersion": "agent-workflow-state.v3",
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": digest,
        "sourceRevision": "source",
        "stateRevision": 1,
        "phase": phase,
        "authorization": {"required": False, "granted": True},
        "tasks": [
            {
                "id": "WS-01",
                "status": task_status,
                "attempt": 0 if task_status in {"READY", "PENDING"} else 1,
                "dependsOn": [],
                "writes": ["src/example.py"],
                "required": True,
                "artifactPaths": {
                    "result": "work/WS-01/attempt-{attempt}/task-result.json",
                    "review": "work/WS-01/attempt-{attempt}/task-review.json",
                },
                "packet": {"sha256": "1" * 64},
            }
        ],
        "eventLog": "events.jsonl",
    }
    if lifecycle_level is not None:
        state["lifecycleControl"] = {
            "level": lifecycle_level,
            "source": "frozen-plan",
            "planDigest": digest,
            "planRevision": 1,
        }
        if lifecycle_level != "OFF":
            policy = deepcopy(build_default_lifecycle_control_policy())
            policy["operations"]["file-edit"] = {
                "declaredLevel": lifecycle_level,
                "supported": True,
                "qualified": True,
                "effectiveLevel": lifecycle_level,
                "qualificationStatus": "QUALIFIED",
                "hostOwnedPreAction": True,
            }
            body = {key: value for key, value in policy.items() if key != "policyDigest"}
            state["lifecycleControl"]["policy"] = {**body, "policyDigest": canonical_digest(body)}
    state_path = root / "run.state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return manifest_path, state_path


if __name__ == "__main__":
    unittest.main()

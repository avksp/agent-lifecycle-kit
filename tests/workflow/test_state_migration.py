from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.canonical import canonical_bytes
from agent_lifecycle.contracts.workflow_storage import iter_historical_snapshots
from agent_lifecycle.workflow import adopt_plan, initialize_workflow_state, migrate_workflow_state
from agent_lifecycle.workflow.operation_kernel import load_for_update
from agent_lifecycle.workflow.state import load_state
from tests.workflow.plan_helpers import _write_plan_bundle
from tests.workflow.test_state_storage import state_fixture


def _legacy_state(path: Path, *, task_status: str = "READY") -> None:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "agent-workflow-state.v3",
                "runId": "run",
                "packageId": "package",
                "planRevision": 1,
                "planDigest": "0" * 64,
                "sourceRevision": "source",
                "stateRevision": 1,
                "phase": "STEP_REVIEW" if task_status == "VERIFYING" else "RUNNING",
                "authorization": {"required": False, "granted": True},
                "tasks": [
                    {
                        "id": "WS-01",
                        "status": task_status,
                        "attempt": 1 if task_status == "VERIFYING" else 0,
                        "dependsOn": [],
                        "attemptHistory": [],
                        "required": True,
                    }
                ],
                "eventLog": "events.jsonl",
            }
        ),
        encoding="utf-8",
    )


class WorkflowStateMigrationTests(unittest.TestCase):
    def test_native_initial_adoption_history_survives_v5_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "run.state.json"
            _write_plan_bundle(root)
            initialize_workflow_state(path, run_id="native-initial", package_id="package")
            initial = load_state(path)
            adopt_plan(
                path,
                manifest_path=root / "plans/package/plan.manifest.json",
                operation_id="first-adoption",
                expected_revision=1,
                source_revision="source-2",
                reset_tasks=False,
                start_mode="auto-after-freeze",
                authorized_by="fixture-user",
            )
            adopted = load_state(path)
            self.assertEqual(adopted["schemaVersion"], "agent-workflow-state.v4")
            self.assertEqual(len(adopted["priorSnapshots"]), 1)
            snapshot = adopted["priorSnapshots"][0]
            for field in ("runId", "packageId", "planRevision", "planDigest", "sourceRevision", "tasks"):
                self.assertEqual(snapshot[field], initial[field])
            self.assertEqual(snapshot["tasks"], [])
            self.assertEqual(snapshot["planDigest"], "")
            self.assertEqual(snapshot["sourceRevision"], "")
            before = path.read_bytes()
            result = migrate_workflow_state(
                path,
                operation_id="migrate-native-history",
                expected_revision=2,
                source_revision="source-2",
                target_schema="agent-workflow-state.v5",
            )
            migrated = load_state(path)
            self.assertEqual(migrated["schemaVersion"], "agent-workflow-state.v5")
            self.assertEqual(list(iter_historical_snapshots(root, migrated)), [snapshot])
            self.assertEqual(migrated["priorSnapshots"][0]["itemCounts"], {"tasks": 0})
            self.assertEqual((root / result["migrationReceipt"]["backupPath"]).read_bytes(), before)
            for field in ("phase", "authorization", "budgets", "runStartedAt", "runDeadlineAt"):
                self.assertEqual(migrated[field], adopted[field])

    def test_v5_preserves_blocked_expired_authority_clocks_unknown_and_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "state.json"
            state = state_fixture()
            state.update(
                stateRevision=1,
                phase="BLOCKED",
                eventLog="events.jsonl",
                blocker={"code": "test", "reason": "retain", "scope": "plan", "recoveryRoute": "adopt-plan"},
                authorization={"required": True, "granted": True, "expiresAt": "2020-01-01T00:00:00Z"},
                runStartedAt="2019-01-01T00:00:00Z",
                runDeadlineAt="2020-01-01T00:00:00Z",
                usageTotals={"actualUsd": None, "telemetryStatus": "UNAVAILABLE", "unknownHolds": ["held"]},
                migration={"retained": "v3 receipt identity"},
            )
            raw = canonical_bytes(state) + b"\n"
            path.write_bytes(raw)
            result = migrate_workflow_state(
                path,
                operation_id="v5",
                expected_revision=1,
                source_revision="source",
                target_schema="agent-workflow-state.v5",
            )
            migrated = load_state(path)
            for field in (
                "phase",
                "blocker",
                "authorization",
                "runStartedAt",
                "runDeadlineAt",
                "usageTotals",
                "migration",
            ):
                self.assertEqual(migrated[field], state[field])
            receipt = result["migrationReceipt"]
            self.assertEqual(receipt["sourceStateSha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(receipt["sourceStateBytes"], len(raw))
            self.assertEqual((root / receipt["backupPath"]).read_bytes(), raw)
            before, events = path.read_bytes(), (root / "events.jsonl").read_bytes()
            with self.assertRaises(LifecycleError) as raised:
                load_for_update(path, operation_id="expired", expected_revision=2)
            self.assertEqual(raised.exception.code, "authorization-expired")
            with self.assertRaises(LifecycleError) as raised:
                migrate_workflow_state(
                    path,
                    operation_id="again",
                    expected_revision=2,
                    source_revision="source",
                    target_schema="agent-workflow-state.v5",
                )
            self.assertEqual(raised.exception.code, "workflow-state-migration-not-required")
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual((root / "events.jsonl").read_bytes(), events)

    def test_migrates_review_phase_to_task_local_v4(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.state.json"
            _legacy_state(path, task_status="VERIFYING")
            payload = migrate_workflow_state(
                path,
                operation_id="migration-1",
                expected_revision=1,
                source_revision="source",
            )
            state = load_state(path)
            self.assertEqual(state["schemaVersion"], "agent-workflow-state.v4")
            self.assertEqual(state["phase"], "RUNNING")
            self.assertEqual(state["tasks"][0]["status"], "VERIFYING")
            self.assertEqual(payload["migrationReceipt"]["fromSchemaVersion"], "agent-workflow-state.v3")

    def test_rejects_legacy_status_without_v4_producer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.state.json"
            _legacy_state(path, task_status="VALIDATING")
            with self.assertRaises(LifecycleError) as raised:
                migrate_workflow_state(
                    path,
                    operation_id="migration-1",
                    expected_revision=1,
                    source_revision="source",
                )
            self.assertEqual(raised.exception.code, "workflow-state-migration-unsupported-status")


if __name__ == "__main__":
    unittest.main()

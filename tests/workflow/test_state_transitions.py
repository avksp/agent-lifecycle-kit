from __future__ import annotations

import json
import os
import stat
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
from agent_lifecycle.workflow.state import write_state_replace

class WorkflowStateTransitionTests(unittest.TestCase):
    @unittest.skipUnless(os.name != "nt", "POSIX mode contract only")
    def test_workflow_state_replace_uses_owner_only_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            write_state_replace(state_path, json.loads(state_path.read_text(encoding="utf-8")))
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(state_path.stat().st_mode), 0o600)

    def test_status_reports_ready_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = _write_state(Path(tmp), phase="RUNNING")
            payload = status(state_path)
            self.assertEqual(payload["phase"], "RUNNING")
            self.assertEqual(payload["nextAction"]["type"], "launch-tasks")
            self.assertEqual(payload["nextAction"]["taskIds"], ["WS-01"])

    def test_block_run_uses_expected_revision_and_appends_wal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            payload = block_run(
                state_path,
                operation_id="block-op",
                expected_revision=1,
                blocker_code="test-blocker",
                reason="blocked for test",
            )
            self.assertEqual(payload["phase"], "BLOCKED")
            self.assertEqual(payload["identity"]["stateRevision"], 2)
            events = (root / "events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(events), 1)
            self.assertEqual(json.loads(events[0])["eventType"], "run-blocked")

    def test_workflow_update_rejects_event_state_split_brain(self) -> None:
        # NEG-R03-09 Crash Split-Brain
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            event = {
                "schemaVersion": "agent-workflow-event.v1",
                "runId": "run",
                "packageId": "package",
                "stateRevision": 2,
                "operationId": "crash-op",
                "eventType": "run-blocked",
                "payload": {},
                "recordedAt": "2026-07-22T00:00:00Z",
            }
            (root / "events.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")

            with self.assertRaises(LifecycleError) as raised:
                block_run(
                    state_path,
                    operation_id="after-crash",
                    expected_revision=1,
                    blocker_code="after-crash",
                    reason="detect split brain",
                )
            self.assertEqual(raised.exception.code, "workflow-split-brain")

    def test_block_run_rejects_revision_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = _write_state(Path(tmp), phase="RUNNING")
            with self.assertRaises(LifecycleError):
                block_run(
                    state_path,
                    operation_id="block-op",
                    expected_revision=2,
                    blocker_code="drift",
                    reason="wrong revision",
                )

    def test_resolve_blocker_restores_resume_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = _write_state(Path(tmp), phase="BLOCKED", blocker={"code": "x", "reason": "x", "resumePhase": "RUNNING"})
            payload = resolve_blocker(
                state_path,
                operation_id="resolve-op",
                expected_revision=1,
                reason="fixed",
            )
            self.assertEqual(payload["phase"], "RUNNING")
            self.assertIsNone(payload["blocker"])

    def test_external_action_pause_requires_receipt_before_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            payload = pause_for_external_action(
                state_path,
                operation_id="external-pause-op",
                expected_revision=1,
                action_id="deploy-preview",
                receipt_path="external/deploy-preview.json",
                reason="operator must deploy preview",
            )
            self.assertEqual(payload["phase"], "WAITING_FOR_EXTERNAL_ACTION")
            self.assertEqual(payload["nextAction"]["type"], "record-external-action-receipt")

            with self.assertRaises(LifecycleError):
                resume_external_action(
                    state_path,
                    operation_id="external-resume-missing",
                    expected_revision=2,
                    receipt_path="external/deploy-preview.json",
                    reason="resume",
                )

            write_json_create(root / "external/deploy-preview.json", _external_action_receipt())
            payload = resume_external_action(
                state_path,
                operation_id="external-resume-op",
                expected_revision=2,
                receipt_path="external/deploy-preview.json",
                reason="external action complete",
            )
            self.assertEqual(payload["phase"], "RUNNING")

    def test_external_action_resume_rejects_lineage_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            pause_for_external_action(
                state_path,
                operation_id="external-pause-op",
                expected_revision=1,
                action_id="deploy-preview",
                receipt_path="external/deploy-preview.json",
                reason="operator must deploy preview",
            )
            receipt = _external_action_receipt()
            receipt["actionId"] = "other-action"
            write_json_create(root / "external/deploy-preview.json", receipt)

            with self.assertRaises(LifecycleError) as raised:
                resume_external_action(
                    state_path,
                    operation_id="external-resume-op",
                    expected_revision=2,
                    receipt_path="external/deploy-preview.json",
                    reason="external action complete",
                )

            self.assertEqual(raised.exception.code, "external-action-receipt-lineage-mismatch")


def _external_action_receipt() -> dict:
    return {
        "schemaVersion": "agent-external-action-receipt.v1",
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "actionId": "deploy-preview",
        "status": "PASS",
        "evidenceIds": ["EV-EXTERNAL"],
        "completedAt": "2026-07-29T08:00:00Z",
    }


if __name__ == "__main__":
    unittest.main()

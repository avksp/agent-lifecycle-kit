from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import _run_cli, _write_state, write_json_create
except ImportError:
    from helpers import _run_cli, _write_state, write_json_create


class WorkflowRecoveryCommandTests(unittest.TestCase):
    def test_external_pause_and_resume_are_public_receipt_bound_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root)
            code, payload = _run_cli(
                [
                    "workflow",
                    "external-pause",
                    "--state",
                    str(state_path),
                    "--operation-id",
                    "pause-cli",
                    "--expected-revision",
                    "1",
                    "--action-id",
                    "preview-deploy",
                    "--receipt",
                    "external/preview.json",
                    "--reason",
                    "wait for preview deployment",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(payload["nextAction"]["type"], "record-external-action-receipt")

            receipt = {
                "schemaVersion": "agent-external-action-receipt.v1",
                "runId": "run",
                "packageId": "package",
                "planRevision": 1,
                "planDigest": "0" * 64,
                "sourceRevision": "source",
                "actionId": "preview-deploy",
                "status": "PASS",
                "evidenceIds": ["EV-PREVIEW"],
                "completedAt": "2026-08-24T00:00:00Z",
            }
            write_json_create(root / "external/preview.json", receipt)
            code, payload = _run_cli(
                [
                    "workflow",
                    "external-resume",
                    "--state",
                    str(state_path),
                    "--operation-id",
                    "resume-cli",
                    "--expected-revision",
                    "2",
                    "--receipt",
                    "external/preview.json",
                    "--reason",
                    "preview deployed",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(payload["phase"], "RUNNING")

    def test_final_audit_outcome_command_routes_blocked_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["phase"] = "FINAL_AUDIT"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            audit = {
                "schemaVersion": "agent-final-candidate-audit.v1",
                "status": "FAIL",
                "semanticStatus": "BLOCKED",
                "runId": "run",
                "packageId": "package",
                "planRevision": 1,
                "planDigest": "0" * 64,
                "sourceRevision": "source",
                "productionPromotionClaimed": False,
                "verifier": {"id": "final-auditor", "independent": True},
                "findings": [],
                "blocker": {
                    "externalAction": {
                        "actionId": "release-approval",
                        "expectedReceiptPath": "external/release-approval.json",
                    }
                },
            }
            write_json_create(root / "final/final-audit.json", audit)

            code, payload = _run_cli(
                [
                    "workflow",
                    "final-audit-outcome",
                    "--state",
                    str(state_path),
                    "--operation-id",
                    "final-outcome-cli",
                    "--expected-revision",
                    "1",
                    "--source-revision",
                    "source",
                    "--final-audit",
                    "final/final-audit.json",
                    "--verdict",
                    "BLOCKED",
                    "--reason",
                    "wait for external approval",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload["phase"], "WAITING_FOR_EXTERNAL_ACTION")
            self.assertEqual(payload["nextAction"]["type"], "record-external-action-receipt")


if __name__ == "__main__":
    unittest.main()

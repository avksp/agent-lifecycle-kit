from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402

class CliSpecificationPlanCommandTests(unittest.TestCase):
    def test_specification_check_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "specification.json"
            path.write_text(
                json.dumps({
                    "tier": "S1",
                    "status": "FROZEN",
                    "requirements": [{"id": "REQ-1", "required": True}],
                }),
                encoding="utf-8",
            )
            code, payload = _run_cli(["specification", "check", "--specification", str(path)])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-specification-validation.v1")
            self.assertEqual(payload["requirementCount"], 1)

    def test_specification_completion_gate_cli_writes_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["phase"] = "FINAL_AUDIT"
            state["tasks"][0]["status"] = "ACCEPTED"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            audit_path = root / "final-audit.json"
            audit_path.write_text(json.dumps(_final_audit()), encoding="utf-8")
            input_path = root / "gate-input.json"
            input_path.write_text(
                json.dumps({
                    "requiredValidationIds": ["VAL-FULL"],
                    "validationResults": [{"id": "VAL-FULL", "status": "PASS"}],
                }),
                encoding="utf-8",
            )
            out_path = root / "completion-gate.json"

            code, payload = _run_cli(
                [
                    "specification",
                    "completion-gate",
                    "--state",
                    str(state_path),
                    "--final-audit",
                    str(audit_path),
                    "--input",
                    str(input_path),
                    "--out",
                    str(out_path),
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-completion-gate-receipt.v1")
            self.assertEqual(payload["decision"], "STOP")
            self.assertTrue(out_path.exists())

    def test_plan_check_cli_validates_manifest_and_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "plan.manifest.json"
            manifest = _manifest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            lock_path = root / "plan.lock.json"
            lock_path.write_text(
                json.dumps({
                    "schemaVersion": "agent-plan-lock.v1",
                    "planRevision": manifest["planRevision"],
                    "manifestHash": canonical_digest(manifest),
                }),
                encoding="utf-8",
            )
            code, payload = _run_cli([
                "plan",
                "check",
                "--manifest",
                str(manifest_path),
                "--lock",
                str(lock_path),
            ])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-plan-check.v1")
            self.assertEqual(payload["manifest"]["schemaVersion"], "agent-plan-validation.v1")
            self.assertEqual(payload["lock"]["schemaVersion"], "agent-plan-lock-verification.v1")

    def test_plan_acceptance_check_cli_validates_markdown_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "plan.manifest.json"
            acceptance_path = root / "acceptance-criteria.md"
            manifest = _manifest()
            manifest["acceptance"] = {
                "criteria": [
                    {"id": "AC-1", "requirementIds": ["REQ-1"], "evidenceIds": ["EV-1"]},
                ]
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            acceptance_path.write_text(
                "| ID | Requirements | Evidence | Criterion |\n"
                "|---|---|---|---|\n"
                "| `AC-1` | `REQ-1` | `EV-1` | checked |\n",
                encoding="utf-8",
            )
            code, payload = _run_cli([
                "plan",
                "acceptance-check",
                "--manifest",
                str(manifest_path),
                "--acceptance",
                str(acceptance_path),
            ])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-acceptance-checklist-validation.v1")
            self.assertEqual(payload["status"], "PASS")

    def test_plan_acceptance_check_cli_rejects_markdown_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "plan.manifest.json"
            acceptance_path = root / "acceptance-criteria.md"
            manifest = _manifest()
            manifest["acceptance"] = {
                "criteria": [
                    {"id": "AC-1", "requirementIds": ["REQ-1"], "evidenceIds": ["EV-1"]},
                ]
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            acceptance_path.write_text(
                "| ID | Requirements | Evidence | Criterion |\n"
                "|---|---|---|---|\n"
                "| `AC-1` | `REQ-1` | `EV-X` | drifted |\n",
                encoding="utf-8",
            )
            code, payload = _run_cli([
                "plan",
                "acceptance-check",
                "--manifest",
                str(manifest_path),
                "--acceptance",
                str(acceptance_path),
            ])
            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "acceptance-checklist-mismatch")
            self.assertEqual(payload["details"]["linkMismatches"][0]["id"], "AC-1")

    def test_plan_continuity_cli_snapshot_reconcile_and_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "plan.manifest.json"
            snapshot_path = root / "snapshot.json"
            handoff_path = root / "handoff.json"
            manifest = _manifest()
            manifest["repositoryReferences"] = [
                {
                    "id": "api",
                    "repoId": "api-service",
                    "owner": "api-worker",
                    "access": "write-scoped",
                    "paths": ["src/api"],
                }
            ]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            code, refs = _run_cli(["plan", "refs-check", "--manifest", str(manifest_path)])
            self.assertEqual(code, 0)
            self.assertEqual(refs["schemaVersion"], "agent-plan-reference-validation.v1")

            code, snapshot = _run_cli(["plan", "snapshot", "--manifest", str(manifest_path), "--out", str(snapshot_path)])
            self.assertEqual(code, 0)
            self.assertEqual(snapshot["schemaVersion"], "agent-plan-snapshot.v1")
            self.assertTrue(snapshot_path.exists())

            code, reconciliation = _run_cli(["plan", "reconcile", "--manifest", str(manifest_path), "--snapshot", str(snapshot_path)])
            self.assertEqual(code, 0)
            self.assertEqual(reconciliation["classification"], "MATCH")

            code, handoff = _run_cli([
                "plan",
                "handoff",
                "--manifest",
                str(manifest_path),
                "--snapshot",
                str(snapshot_path),
                "--out",
                str(handoff_path),
            ])
            self.assertEqual(code, 0)
            self.assertEqual(handoff["schemaVersion"], "agent-plan-handoff.v1")
            self.assertTrue(handoff_path.exists())

    def test_plan_reconcile_cli_fails_on_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "plan.manifest.json"
            snapshot_path = root / "snapshot.json"
            manifest = _manifest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            code, _snapshot = _run_cli(["plan", "snapshot", "--manifest", str(manifest_path), "--out", str(snapshot_path)])
            self.assertEqual(code, 0)
            manifest["planRevision"] = 2
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            code, payload = _run_cli(["plan", "reconcile", "--manifest", str(manifest_path), "--snapshot", str(snapshot_path)])

            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "plan-reconciliation-failed")

    def test_task_compile_small_cli_writes_packets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = _write_task_compile_bundle(root)
            previous_cwd = Path.cwd()
            os.chdir(root)
            try:
                code, payload = _run_cli(
                    [
                        "task",
                        "compile-small",
                        "--manifest",
                        str(manifest_path),
                        "--context-profile",
                        str(ROOT / "profiles/small-context-profile.v1.json"),
                        "--write",
                    ]
                )
            finally:
                os.chdir(previous_cwd)

            packet_path = root / "plans/p/workflow/small-model-packets/WS-01.small-model-packet.json"
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-small-model-packet-compile-result.v1")
            self.assertEqual(payload["status"], "PASS")
            self.assertTrue(packet_path.exists())


def _final_audit() -> dict:
    return {
        "schemaVersion": "agent-run-final-audit.v1",
        "status": "PASS",
        "semanticStatus": "READY_FOR_FINALIZATION",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "productionPromotionClaimed": False,
        "notAcceptedTasks": [],
        "missingReleaseEvidence": [],
        "findings": [],
    }


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ReleaseCandidateTests(unittest.TestCase):
    def test_release_inventory_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            inventory = out / "inventory.json"
            assembly = out / "release-assembly.json"
            verification = out / "release-verification.json"
            _run("tools/release/assemble_release_candidate.py", "--manifest", "plans/standalone-v1/plan.manifest.json", "--inventory", str(inventory), "--evidence", str(assembly))
            _run("tools/release/verify_release_candidate.py", "--inventory", str(inventory), "--evidence", str(verification))
            inventory_payload = json.loads(inventory.read_text(encoding="utf-8"))
            payload = json.loads(verification.read_text(encoding="utf-8"))
            self.assertIn("tools/release/validate_deferred_promotion.py", {item["path"] for item in inventory_payload["files"]})
            self.assertEqual(payload["status"], "PASS")
            self.assertFalse(payload["productionPromotionClaimed"])

    def test_support_matrix_and_deferred_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            matrix_evidence = out / "support-matrix-contract.json"
            deferred_evidence = out / "deferred-promotion-contract.json"
            _run("tools/release/validate_support_matrix.py", "--support-matrix", "docs/adapters/support-matrix.md", "--profile", "plans/standalone-v1/.agent-plan/standalone-v1/ci-matrix-profile.v2.json", "--evidence", str(matrix_evidence))
            _run("tools/release/validate_deferred_promotion.py", "--profile", "plans/standalone-v1/.agent-plan/standalone-v1/benchmark-authority-profile.v1.json", "--evidence", str(deferred_evidence))
            matrix = json.loads(matrix_evidence.read_text(encoding="utf-8"))
            deferred = json.loads(deferred_evidence.read_text(encoding="utf-8"))
            self.assertEqual(matrix["adapterMaturity"], "EXPERIMENTAL")
            self.assertTrue(deferred["deferredProductionPromotion"])
            self.assertFalse(deferred["liveModelExecutionClaimed"])

    def test_final_candidate_requires_release_evidence_and_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            evidence_dir = out / "evidence"
            evidence_dir.mkdir()
            for name in (
                "release-assembly.json",
                "release-verification.json",
                "support-matrix-contract.json",
                "deferred-promotion-contract.json",
                "release-neutrality-report.json",
            ):
                (evidence_dir / name).write_text("{}", encoding="utf-8")
            state = out / "run.state.json"
            state.write_text(json.dumps({"stateRevision": 1, "tasks": [{"id": f"WS-{index:02d}", "status": "ACCEPTED"} for index in range(1, 15)]}), encoding="utf-8")
            output = out / "final-audit.json"
            _run("tools/release/verify_final_candidate.py", "--manifest", "plans/standalone-v1/plan.manifest.json", "--state", str(state), "--release-evidence-dir", str(evidence_dir), "--output", str(output))
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["semanticStatus"], "READY_FOR_FINALIZATION")
            self.assertFalse(payload["productionPromotionClaimed"])


def _run(script: str, *args: str) -> None:
    subprocess.run([sys.executable, script, *args], cwd=ROOT, check=True)


if __name__ == "__main__":
    unittest.main()

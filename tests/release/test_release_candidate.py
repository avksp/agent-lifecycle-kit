from __future__ import annotations

import hashlib
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
            self.assertIn("tools/release/validate_live_calibration.py", {item["path"] for item in inventory_payload["files"]})
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

    def test_live_calibration_validator_accepts_live_receipt_with_4k_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            receipt = out / "live-calibration-receipt.json"
            evidence = out / "live-calibration-evidence.json"
            _write_live_calibration_receipt(receipt, synthetic=False)

            _run(
                "tools/release/validate_live_calibration.py",
                "--profile",
                "conformance/core/live-calibration-profile.v1.json",
                "--budget-targets",
                "conformance/core/budget-targets.v1.json",
                "--receipt",
                str(receipt),
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            scenarios = {item["scenarioId"] for item in payload["aggregates"]}
            self.assertEqual(payload["status"], "PASS")
            self.assertIn("S1-SMALL-CONTEXT-4K-STRICT-01", scenarios)
            self.assertFalse(payload["productionPromotionClaimed"])

    def test_live_calibration_validator_rejects_synthetic_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            receipt = out / "live-calibration-receipt.json"
            evidence = out / "live-calibration-evidence.json"
            _write_live_calibration_receipt(receipt, synthetic=True)

            result = _run_no_check(
                "tools/release/validate_live_calibration.py",
                "--profile",
                "conformance/core/live-calibration-profile.v1.json",
                "--budget-targets",
                "conformance/core/budget-targets.v1.json",
                "--receipt",
                str(receipt),
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("synthetic-live-calibration-receipt", {item["code"] for item in payload["blockers"]})

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


def _run_no_check(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, script, *args], cwd=ROOT, check=False, text=True, capture_output=True)


def _write_live_calibration_receipt(path: Path, *, synthetic: bool) -> None:
    profile = _load_json(ROOT / "conformance/core/live-calibration-profile.v1.json")
    targets = _load_json(ROOT / "conformance/core/budget-targets.v1.json")
    runs = []
    for scenario in profile["requiredScenarios"]:
        for cohort in profile["requiredCohorts"]:
            runs.append(
                {
                    "runId": f"{scenario}-{cohort}-run-01",
                    "scenarioId": scenario,
                    "cohort": cohort,
                    "usageAttested": True,
                    "qualityStatus": "PASS",
                    "usage": {
                        "billableTokens": 1000,
                        "inputTokens": 700,
                        "outputTokens": 300,
                        "cumulativeContextBytes": 4096,
                        "toolCalls": 2,
                        "wallSeconds": 10,
                    },
                }
            )
    receipt = {
        "schemaVersion": "agent-lifecycle-live-calibration-receipt.v1",
        "status": "PASS",
        "receiptId": "test-live-calibration-receipt",
        "host": "codex",
        "profileId": profile["profileId"],
        "profileDigest": _digest(profile),
        "budgetTargetsDigest": _digest(targets),
        "sourceRevision": "test-source",
        "liveModelInvocations": len(runs),
        "syntheticReplayUsed": synthetic,
        "qualityRegressionCount": 0,
        "usageAttestationPolicy": {"missingOrUnattestedUsage": "FAIL"},
        "runs": runs,
    }
    path.write_text(json.dumps(receipt), encoding="utf-8")


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected JSON object: {path}")
    return value


def _digest(value: dict) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


if __name__ == "__main__":
    unittest.main()

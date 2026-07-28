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

class FinalCandidateValidatorTests(unittest.TestCase):
    def test_final_candidate_requires_release_evidence_and_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest, state, evidence_dir = _write_final_candidate_fixture(out)
            output = out / "final-audit.json"
            _run("tools/release/verify_final_candidate.py", "--manifest", str(manifest), "--state", str(state), "--release-evidence-dir", str(evidence_dir), "--output", str(output))
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["semanticStatus"], "READY_FOR_FINALIZATION")
            self.assertEqual(payload["status"], "PASS")
            self.assertFalse(payload["productionPromotionClaimed"])
            self.assertTrue(all(item["status"] == "PASS" for item in payload["lineageChecks"]))

    def test_final_candidate_rejects_failed_release_evidence(self) -> None:
        # NEG-R03-01 Failed Release Verification
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest, state, evidence_dir = _write_final_candidate_fixture(out)
            verification = json.loads((evidence_dir / "release-verification.json").read_text(encoding="utf-8"))
            verification["status"] = "FAIL"
            (evidence_dir / "release-verification.json").write_text(json.dumps(verification), encoding="utf-8")
            output = out / "final-audit.json"

            result = _run_no_check(
                "tools/release/verify_final_candidate.py",
                "--manifest",
                str(manifest),
                "--state",
                str(state),
                "--release-evidence-dir",
                str(evidence_dir),
                "--output",
                str(output),
            )

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("evidence-status-not-pass", {item["code"] for item in payload["blockers"]})

    def test_final_candidate_rejects_malformed_release_evidence(self) -> None:
        # NEG-R03-02 Malformed Evidence
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest, state, evidence_dir = _write_final_candidate_fixture(out)
            (evidence_dir / "release-verification.json").write_text("[]", encoding="utf-8")
            output = out / "final-audit.json"

            result = _run_no_check(
                "tools/release/verify_final_candidate.py",
                "--manifest",
                str(manifest),
                "--state",
                str(state),
                "--release-evidence-dir",
                str(evidence_dir),
                "--output",
                str(output),
            )

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("malformed-release-evidence", {item["code"] for item in payload["blockers"]})

    def test_final_candidate_rejects_malformed_neutrality_counters(self) -> None:
        # NEG-R03-02 Malformed Evidence
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest, state, evidence_dir = _write_final_candidate_fixture(out)
            report = json.loads((evidence_dir / "release-neutrality-report.json").read_text(encoding="utf-8"))
            report["counters"]["findings"] = "zero"
            (evidence_dir / "release-neutrality-report.json").write_text(json.dumps(report), encoding="utf-8")
            output = out / "final-audit.json"

            result = _run_no_check(
                "tools/release/verify_final_candidate.py",
                "--manifest",
                str(manifest),
                "--state",
                str(state),
                "--release-evidence-dir",
                str(evidence_dir),
                "--output",
                str(output),
            )

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("evidence-counters-non-zero", {item["code"] for item in payload["blockers"]})

    def test_final_candidate_rejects_manifest_state_mismatch(self) -> None:
        # NEG-R03-03 Manifest/State Mismatch
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest, state, evidence_dir = _write_final_candidate_fixture(out)
            state_payload = json.loads(state.read_text(encoding="utf-8"))
            state_payload["planRevision"] = 14
            state.write_text(json.dumps(state_payload), encoding="utf-8")
            output = out / "final-audit.json"

            result = _run_no_check(
                "tools/release/verify_final_candidate.py",
                "--manifest",
                str(manifest),
                "--state",
                str(state),
                "--release-evidence-dir",
                str(evidence_dir),
                "--output",
                str(output),
            )

            payload = json.loads(output.read_text(encoding="utf-8"))
            failed = {item["id"] for item in payload["lineageChecks"] if item["status"] == "FAIL"}
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("state.planRevision", failed)

    def test_final_candidate_rejects_packet_index_mismatch(self) -> None:
        # NEG-R03-04 Packet Index Mismatch
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest, state, evidence_dir = _write_final_candidate_fixture(out)
            manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
            index = Path(manifest_payload["package"]["artifactRoot"]) / "workflow/task-packets/index.json"
            index_payload = json.loads(index.read_text(encoding="utf-8"))
            index_payload["manifestDigest"] = "9" * 64
            index.write_text(json.dumps(index_payload), encoding="utf-8")
            output = out / "final-audit.json"

            result = _run_no_check(
                "tools/release/verify_final_candidate.py",
                "--manifest",
                str(manifest),
                "--state",
                str(state),
                "--release-evidence-dir",
                str(evidence_dir),
                "--output",
                str(output),
            )

            payload = json.loads(output.read_text(encoding="utf-8"))
            failed = {item["id"] for item in payload["lineageChecks"] if item["status"] == "FAIL"}
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("taskPacketIndex.manifestDigest", failed)

    def test_release_verification_rejects_stale_inventory_identity(self) -> None:
        # NEG-R03-05 Inventory Stale
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            payload = out / "payload.txt"
            payload.write_text("before\n", encoding="utf-8")
            inventory_body = {
                "schemaVersion": "agent-release-candidate-inventory.v1",
                "packageId": "package",
                "planRevision": 1,
                "planDigest": "0" * 64,
                "payloadRoots": [],
                "files": [_identity(payload)],
            }
            inventory = out / "inventory.json"
            _write_json(inventory, {**inventory_body, "candidatePayloadInventoryDigest": _digest(inventory_body)})
            payload.write_text("after\n", encoding="utf-8")
            evidence = out / "release-verification.json"

            result = _run_no_check(
                "tools/release/verify_release_candidate.py",
                "--inventory",
                str(inventory),
                "--evidence",
                str(evidence),
            )

            verification = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(verification["status"], "FAIL")
            self.assertEqual(verification["mismatches"][0]["reason"], "identity-mismatch")

    def test_final_candidate_derives_required_tasks_from_manifest(self) -> None:
        # NEG-R03-15 Required Task Set Hole
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest, state, evidence_dir = _write_final_candidate_fixture(out, accepted_tasks=["WS-01"])
            output = out / "final-audit.json"

            result = _run_no_check(
                "tools/release/verify_final_candidate.py",
                "--manifest",
                str(manifest),
                "--state",
                str(state),
                "--release-evidence-dir",
                str(evidence_dir),
                "--output",
                str(output),
            )

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("WS-02", payload["notAcceptedTasks"])

    def test_final_candidate_rejects_unknown_evidence_schema(self) -> None:
        # NEG-R03-16 Release Evidence Schema Drift
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest, state, evidence_dir = _write_final_candidate_fixture(out)
            evidence = json.loads((evidence_dir / "support-matrix-contract.json").read_text(encoding="utf-8"))
            evidence["schemaVersion"] = "agent-release-unknown.v1"
            (evidence_dir / "support-matrix-contract.json").write_text(json.dumps(evidence), encoding="utf-8")
            output = out / "final-audit.json"

            result = _run_no_check(
                "tools/release/verify_final_candidate.py",
                "--manifest",
                str(manifest),
                "--state",
                str(state),
                "--release-evidence-dir",
                str(evidence_dir),
                "--output",
                str(output),
            )

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unknown-evidence-schema", {item["code"] for item in payload["blockers"]})

    def test_final_candidate_rejects_production_promotion_claim(self) -> None:
        # NEG-R03-06 Production Promotion Claim In Offline Mode
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest, state, evidence_dir = _write_final_candidate_fixture(out)
            evidence = json.loads((evidence_dir / "deferred-promotion-contract.json").read_text(encoding="utf-8"))
            evidence["productionPromotionClaimed"] = True
            (evidence_dir / "deferred-promotion-contract.json").write_text(json.dumps(evidence), encoding="utf-8")
            output = out / "final-audit.json"

            result = _run_no_check(
                "tools/release/verify_final_candidate.py",
                "--manifest",
                str(manifest),
                "--state",
                str(state),
                "--release-evidence-dir",
                str(evidence_dir),
                "--output",
                str(output),
            )

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("production-promotion-claim", {item["code"] for item in payload["blockers"]})


if __name__ == "__main__":
    unittest.main()

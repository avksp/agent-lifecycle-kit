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


class Release04CandidateValidatorTests(unittest.TestCase):
    def test_release_0_4_candidate_validator_accepts_required_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            evidence_dir = out / "evidence"
            evidence_dir.mkdir()
            _write_r04_required_evidence(evidence_dir)
            final_proof = out / "final-proof.json"
            _write_r04_final_proof(final_proof, ROOT / "tasks/release-0-4/plan.manifest.json")
            evidence = out / "validation.json"

            _run(
                "tools/release/verify_release_0_4_candidate.py",
                "--manifest",
                "tasks/release-0-4/plan.manifest.json",
                "--evidence-dir",
                str(evidence_dir),
                "--final-proof",
                str(final_proof),
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["schemaVersion"], "agent-release-0-4-validation.v1")
            self.assertEqual(payload["status"], "PASS")
            self.assertFalse(payload["productionPromotionClaimed"])

    def test_release_0_4_candidate_validator_rejects_missing_host_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            evidence_dir = out / "evidence"
            evidence_dir.mkdir()
            _write_r04_required_evidence(evidence_dir)
            final_proof = out / "final-proof.json"
            _write_r04_final_proof(final_proof, ROOT / "tasks/release-0-4/plan.manifest.json")
            evidence = out / "validation.json"

            result = _run_no_check(
                "tools/release/verify_release_0_4_candidate.py",
                "--manifest",
                "tasks/release-0-4/plan.manifest.json",
                "--evidence-dir",
                str(evidence_dir),
                "--final-proof",
                str(final_proof),
                "--evidence",
                str(evidence),
                "--required-hosts",
                "codex,missing-host",
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("release-0-4-host-profile-invalid", {item["code"] for item in payload["blockers"]})

    def test_release_0_4_candidate_validator_rejects_missing_declared_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            evidence_dir = out / "evidence"
            evidence_dir.mkdir()
            _write_r04_required_evidence(evidence_dir)
            final_proof = out / "final-proof.json"
            _write_r04_final_proof(final_proof, ROOT / "tasks/release-0-4/plan.manifest.json")
            (evidence_dir / "workflow-budget.json").unlink()
            evidence = out / "validation.json"

            result = _run_no_check(
                "tools/release/verify_release_0_4_candidate.py",
                "--manifest",
                "tasks/release-0-4/plan.manifest.json",
                "--evidence-dir",
                str(evidence_dir),
                "--final-proof",
                str(final_proof),
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("release-0-4-evidence-missing-or-failed", {item["code"] for item in payload["blockers"]})

    def test_release_0_4_candidate_validator_rejects_missing_final_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            evidence_dir = out / "evidence"
            evidence_dir.mkdir()
            _write_r04_required_evidence(evidence_dir)
            evidence = out / "validation.json"

            result = _run_no_check(
                "tools/release/verify_release_0_4_candidate.py",
                "--manifest",
                "tasks/release-0-4/plan.manifest.json",
                "--evidence-dir",
                str(evidence_dir),
                "--final-proof",
                str(out / "missing-final-proof.json"),
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("release-0-4-final-proof-missing", {item["code"] for item in payload["blockers"]})


if __name__ == "__main__":
    unittest.main()

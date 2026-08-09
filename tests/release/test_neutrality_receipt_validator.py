from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class NeutralityReceiptValidatorTests(unittest.TestCase):
    def test_current_neutrality_sources_pass_validator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "neutrality-receipt.json"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_neutrality_receipt.py"),
                    "--path",
                    "src/agent_lifecycle/neutrality",
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                check=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertEqual(payload["schemaVersion"], "agent-neutrality-receipt-validation.v1")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(len(payload["requiredCounters"]), 9)

    def test_validator_rejects_missing_existing_receipt_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "receipt.py").write_text(
                "REQUIRED_COMPLETENESS_COUNTERS = ('findings',)\n"
                "def build_claims():\n    require_zero_completeness_counters()\n"
                "def verify_existing_receipt():\n    return True\n",
                encoding="utf-8",
            )
            (root / "cli.py").write_text("def _bootstrap():\n    require_zero_completeness_counters()\n", encoding="utf-8")
            evidence = root / "evidence.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_neutrality_receipt.py"),
                    "--path",
                    str(root),
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                text=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("neutrality-completeness-gate-missing", {item["code"] for item in payload["blockers"]})

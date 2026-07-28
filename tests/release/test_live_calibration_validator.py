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

class LiveCalibrationValidatorTests(unittest.TestCase):
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

    def test_live_calibration_validator_accepts_promoted_host_receipt_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            receipts = out / "receipts"
            receipts.mkdir()
            evidence = out / "live-calibration-evidence.json"
            _write_live_calibration_receipt(receipts / "codex.json", synthetic=False)

            _run(
                "tools/release/validate_live_calibration.py",
                "--profile",
                "conformance/core/live-calibration-profile.v1.json",
                "--budget-targets",
                "conformance/core/budget-targets.v1.json",
                "--receipt-dir",
                str(receipts),
                "--promoted-hosts",
                "codex",
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["promotedHosts"], ["codex"])
            self.assertEqual(payload["hosts"], ["codex"])

    def test_live_calibration_validator_requires_receipt_per_promoted_host(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            receipts = out / "receipts"
            receipts.mkdir()
            evidence = out / "live-calibration-evidence.json"
            _write_live_calibration_receipt(receipts / "codex.json", synthetic=False)

            result = _run_no_check(
                "tools/release/validate_live_calibration.py",
                "--profile",
                "conformance/core/live-calibration-profile.v1.json",
                "--budget-targets",
                "conformance/core/budget-targets.v1.json",
                "--receipt-dir",
                str(receipts),
                "--promoted-hosts",
                "codex,claude-code",
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("missing-live-calibration-receipt", {item["code"] for item in payload["blockers"]})


if __name__ == "__main__":
    unittest.main()

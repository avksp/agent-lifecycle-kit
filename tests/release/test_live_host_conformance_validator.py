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

class LiveHostConformanceValidatorTests(unittest.TestCase):
    def test_live_host_conformance_validator_accepts_contract_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            receipts = out / "live-host"
            receipts.mkdir()
            evidence = out / "live-host-conformance.json"
            _write_live_host_conformance_receipt(receipts / "codex.json", host="codex", synthetic=False)

            _run(
                "tools/release/validate_live_host_conformance.py",
                "--profile",
                "conformance/core/live-calibration-profile.v1.json",
                "--baseline",
                "conformance/core/adapter-baseline.v1.json",
                "--receipt-dir",
                str(receipts),
                "--promoted-hosts",
                "codex",
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["checks"][0]["passedOperationCount"], payload["checks"][0]["requiredOperationCount"])
            self.assertFalse(payload["productionPromotionClaimed"])

    def test_live_host_conformance_validator_accepts_probe_plan_integration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            receipts = out / "live-host"
            receipts.mkdir()
            probe_plan = out / "adapter-probe-plan.json"
            evidence = out / "live-host-conformance.json"
            _write_live_host_conformance_receipt(receipts / "codex.json", host="codex", synthetic=False)
            _run(
                "tools/release/generate_adapter_probe_plan.py",
                "--profile",
                "conformance/core/adapter-probe-profile.v1.json",
                "--manifest",
                "adapters/codex/capabilities.manifest.json",
                "--out",
                str(probe_plan),
            )

            _run(
                "tools/release/validate_live_host_conformance.py",
                "--profile",
                "conformance/core/live-calibration-profile.v1.json",
                "--baseline",
                "conformance/core/adapter-baseline.v1.json",
                "--receipt-dir",
                str(receipts),
                "--promoted-hosts",
                "codex",
                "--probe-plan",
                str(probe_plan),
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["adapterProbePlan"]["path"], str(probe_plan))

    def test_live_host_conformance_validator_rejects_synthetic_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            receipts = out / "live-host"
            receipts.mkdir()
            evidence = out / "live-host-conformance.json"
            _write_live_host_conformance_receipt(receipts / "codex.json", host="codex", synthetic=True)

            result = _run_no_check(
                "tools/release/validate_live_host_conformance.py",
                "--profile",
                "conformance/core/live-calibration-profile.v1.json",
                "--baseline",
                "conformance/core/adapter-baseline.v1.json",
                "--receipt-dir",
                str(receipts),
                "--promoted-hosts",
                "codex",
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("synthetic-live-host-receipt", {item["code"] for item in payload["blockers"]})

    def test_live_host_conformance_validator_rejects_host_protocol_bypass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            receipts = out / "live-host"
            receipts.mkdir()
            evidence = out / "live-host-conformance.json"
            _write_live_host_conformance_receipt(receipts / "codex.json", host="codex", synthetic=False, bypass=True)

            result = _run_no_check(
                "tools/release/validate_live_host_conformance.py",
                "--profile",
                "conformance/core/live-calibration-profile.v1.json",
                "--baseline",
                "conformance/core/adapter-baseline.v1.json",
                "--receipt-dir",
                str(receipts),
                "--promoted-hosts",
                "codex",
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("host-protocol-envelope-invalid", {item["code"] for item in payload["blockers"]})


if __name__ == "__main__":
    unittest.main()

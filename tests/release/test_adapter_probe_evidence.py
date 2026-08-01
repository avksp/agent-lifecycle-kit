from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402


class AdapterProbeEvidenceTests(unittest.TestCase):
    def test_validates_probe_receipts_against_plan_without_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            plan = out / "adapter-probe-plan.json"
            receipts = out / "receipts"
            receipts.mkdir()
            validation = out / "adapter-probe-validation.json"
            _write_plan(plan)
            _write_live_host_conformance_receipt(receipts / "goose.json", host="goose", synthetic=False)
            _write_live_host_conformance_receipt(receipts / "openinterpreter.json", host="openinterpreter", synthetic=False)

            _run(
                "tools/release/validate_adapter_probe_evidence.py",
                "--plan",
                str(plan),
                "--receipt-dir",
                str(receipts),
                "--out",
                str(validation),
            )

            payload = json.loads(validation.read_text(encoding="utf-8"))
            self.assertEqual(payload["schemaVersion"], "agent-adapter-probe-evidence-validation.v1")
            self.assertEqual(payload["status"], "PASS")
            self.assertFalse(payload["driftDetected"])
            self.assertFalse(payload["productionPromotionClaimed"])
            self.assertFalse(payload["maturityChangeClaimed"])

    def test_detects_missing_planned_operation_as_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            plan = out / "adapter-probe-plan.json"
            receipts = out / "receipts"
            receipts.mkdir()
            validation = out / "adapter-probe-validation.json"
            _write_plan(plan)
            _write_drifted_receipt(receipts / "goose.json")
            _write_live_host_conformance_receipt(receipts / "openinterpreter.json", host="openinterpreter", synthetic=False)

            result = _run_no_check(
                "tools/release/validate_adapter_probe_evidence.py",
                "--plan",
                str(plan),
                "--receipt-dir",
                str(receipts),
                "--out",
                str(validation),
            )

            payload = json.loads(validation.read_text(encoding="utf-8"))
            codes = {item["code"] for item in payload["blockers"]}
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertTrue(payload["driftDetected"])
            self.assertIn("adapter-probe-operation-missing", codes)


def _write_plan(path: Path) -> None:
    _run(
        "tools/release/generate_adapter_probe_plan.py",
        "--profile",
        "conformance/core/adapter-probe-profile.v1.json",
        "--manifest",
        "adapters/goose/capabilities.manifest.json",
        "--manifest",
        "adapters/openinterpreter/capabilities.manifest.json",
        "--out",
        str(path),
    )


def _write_drifted_receipt(path: Path) -> None:
    _write_live_host_conformance_receipt(path, host="goose", synthetic=False)
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["operations"] = [item for item in receipt["operations"] if item["name"] != "launch"]
    path.write_text(json.dumps(receipt), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

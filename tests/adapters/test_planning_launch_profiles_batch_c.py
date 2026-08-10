from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.adapter_sessions.local_launch_profile import validate_local_launch_profile
from agent_lifecycle.adapter_sessions.qualification import load_shipped_launch_profile
from agent_lifecycle.contracts import canonical_digest
from tools.live_hosts.planning_launch_harness import run_planning_preflight

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "kimi-code": "0.30.0",
    "openinterpreter": "0.0.34",
    "pi": "0.83.0",
}


class PlanningLaunchProfilesBatchCTests(unittest.TestCase):
    def test_profiles_and_public_facts_are_exact_and_fail_closed(self) -> None:
        for adapter_id, version in EXPECTED.items():
            with self.subTest(adapter=adapter_id):
                profile = load_shipped_launch_profile(adapter_id, repository_root=ROOT)
                descriptor = self._json(f"adapters/{adapter_id}/adapter.descriptor.json")
                capabilities = self._json(f"adapters/{adapter_id}/capabilities.manifest.json")
                receipt = self._json(f"conformance/adapters/{adapter_id}/event-stream-receipt.json")
                self.assertEqual(validate_local_launch_profile(profile)["status"], "PASS")
                self.assertEqual(profile["qualification"]["expectedVersion"], version)
                self.assertEqual(profile["planningOnly"]["status"], "UNSUPPORTED")
                self.assertEqual(profile["planningOnly"]["planningSupportStatus"], "PLANNING_ONLY_UNSUPPORTED")
                self.assertEqual(profile["planningOnly"]["qualificationEvidence"], [])
                self.assertEqual(descriptor["managedLaunch"]["status"], "WRAPPER_ONLY")
                self.assertEqual(capabilities["planningLaunch"]["profileStatus"], "UNSUPPORTED")
                self.assertEqual(capabilities["descriptorDigest"], canonical_digest(descriptor))
                self.assertEqual(receipt["descriptorDigest"], canonical_digest(descriptor))
                self.assertEqual(receipt["receiptDigest"], canonical_digest({k: v for k, v in receipt.items() if k != "receiptDigest"}))

    def test_unsupported_profile_starts_no_host_with_approval(self) -> None:
        approval_payload = {
            "schemaVersion": "agent-planning-launch-qualification-approval.v1",
            "approved": True,
            "adapterId": "pi",
            "maxProcesses": 2,
            "maxWallSeconds": 330,
            "modelTokenBudget": 20000,
        }
        with tempfile.TemporaryDirectory() as tmp:
            approval = Path(tmp) / "approval.json"
            approval.write_text(json.dumps(approval_payload), encoding="utf-8")
            report = run_planning_preflight("pi", approval)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["processCalls"], 0)
        self.assertFalse(report["modelCallsStarted"])

    def test_wrappers_are_thin_bindings(self) -> None:
        for name in ("kimi_code", "openinterpreter", "pi"):
            text = (ROOT / f"tools/live_hosts/{name}_launch_harness.py").read_text(encoding="utf-8")
            self.assertIn("planning_launch_harness import main", text)
            self.assertNotIn("subprocess", text)

    @staticmethod
    def _json(relative: str) -> dict:
        return json.loads((ROOT / relative).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

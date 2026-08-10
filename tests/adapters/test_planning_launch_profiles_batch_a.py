from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_lifecycle.adapter_sessions.local_launch_profile import validate_local_launch_profile
from agent_lifecycle.adapter_sessions.qualification import load_shipped_launch_profile
from agent_lifecycle.contracts import canonical_digest
from tools.live_hosts.planning_launch_harness import run_planning_preflight

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "cursor": ("2026.07.23", "UNSUPPORTED"),
    "gemini-cli": ("0.46.0", "CANDIDATE"),
    "qwen-code": ("0.21.8", "UNSUPPORTED"),
}


class PlanningLaunchProfilesBatchATests(unittest.TestCase):
    def test_profiles_and_public_facts_are_exact_and_fail_closed(self) -> None:
        for adapter_id, (version, profile_status) in EXPECTED.items():
            with self.subTest(adapter=adapter_id):
                profile = load_shipped_launch_profile(adapter_id, repository_root=ROOT)
                descriptor = self._json(f"adapters/{adapter_id}/adapter.descriptor.json")
                capabilities = self._json(f"adapters/{adapter_id}/capabilities.manifest.json")
                receipt = self._json(f"conformance/adapters/{adapter_id}/event-stream-receipt.json")
                self.assertEqual(validate_local_launch_profile(profile)["status"], "PASS")
                self.assertEqual(profile["qualification"]["expectedVersion"], version)
                self.assertEqual(profile["planningOnly"]["status"], profile_status)
                self.assertEqual(profile["planningOnly"]["planningSupportStatus"], "PLANNING_ONLY_UNSUPPORTED")
                self.assertEqual(profile["planningOnly"]["qualificationEvidence"], [])
                if adapter_id == "gemini-cli":
                    planning_argv = profile["planningOnly"]["argvTemplate"]
                    self.assertEqual(planning_argv[planning_argv.index("--output-format") + 1], "json")
                self.assertEqual(descriptor["managedLaunch"]["status"], "WRAPPER_ONLY")
                self.assertEqual(descriptor["qualifiedLaunch"]["expectedHostVersion"], version)
                self.assertFalse(descriptor["qualifiedLaunch"]["publicSupportClaimed"])
                self.assertEqual(capabilities["planningLaunch"]["profileStatus"], profile_status)
                self.assertEqual(capabilities["descriptorDigest"], canonical_digest(descriptor))
                self.assertEqual(receipt["descriptorDigest"], canonical_digest(descriptor))
                self.assertEqual(receipt["receiptDigest"], canonical_digest({k: v for k, v in receipt.items() if k != "receiptDigest"}))

    def test_missing_approval_starts_no_host(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            approval = Path(tmp) / "approval.json"
            approval.write_text("{}\n", encoding="utf-8")
            report = run_planning_preflight("gemini-cli", approval)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["processCalls"], 0)
        self.assertFalse(report["modelCallsStarted"])

    def test_approved_limits_reach_the_shared_candidate_runner(self) -> None:
        approval_payload = {
            "schemaVersion": "agent-planning-launch-qualification-approval.v1",
            "approved": True,
            "adapterId": "gemini-cli",
            "maxProcesses": 2,
            "maxWallSeconds": 30,
            "modelTokenBudget": 100,
        }
        version_receipt = {"status": "PASS", "processCalls": 1, "blockers": []}
        planning_evidence = {
            "status": "PASS",
            "processCalls": 1,
            "modelCallsStarted": True,
            "blockers": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            approval = Path(tmp) / "approval.json"
            approval.write_text(json.dumps(approval_payload), encoding="utf-8")
            with (
                mock.patch(
                    "tools.live_hosts.planning_launch_harness._init_disposable_repository"
                ),
                mock.patch(
                    "tools.live_hosts.planning_launch_harness.launch_from_local_profile",
                    return_value=version_receipt,
                ),
                mock.patch(
                    "tools.live_hosts.planning_launch_harness.run_planning_qualification_candidate",
                    return_value=planning_evidence,
                ) as candidate,
            ):
                report = run_planning_preflight("gemini-cli", approval)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["processCalls"], 2)
        self.assertEqual(candidate.call_args.kwargs["max_wall_seconds"], 20)
        self.assertEqual(candidate.call_args.kwargs["model_token_budget"], 100)

    def test_wrappers_are_thin_bindings(self) -> None:
        for name in ("cursor", "gemini_cli", "qwen_code"):
            text = (ROOT / f"tools/live_hosts/{name}_launch_harness.py").read_text(encoding="utf-8")
            self.assertIn("planning_launch_harness import main", text)
            self.assertNotIn("subprocess", text)

    @staticmethod
    def _json(relative: str) -> dict:
        return json.loads((ROOT / relative).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

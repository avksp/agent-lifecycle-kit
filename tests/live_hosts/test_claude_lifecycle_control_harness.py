from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.live_hosts import claude_lifecycle_control_harness

ROOT = Path(__file__).resolve().parents[2]


class ClaudeLifecycleControlHarnessTests(unittest.TestCase):
    def test_fixture_check_is_non_promoting_and_does_not_start_host(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = root / "receipt.json"
            report = claude_lifecycle_control_harness.run_fixture_check(
                ROOT / "adapters/claude/lifecycle-control.template.json",
                ROOT / "policy/adapter-lifecycle-control.json",
                receipt,
            )

            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["qualificationStatus"], "NO_RECOMMENDATION")
            self.assertTrue(report["syntheticReplayUsed"])
            self.assertFalse(report["liveCallsStarted"])
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertFalse(payload["productionPromotionClaimed"])

    def test_live_mode_requires_explicit_authorization_before_runner(self) -> None:
        calls: list[list[str]] = []

        def runner(command: list[str], _cwd: Path | None) -> tuple[int, str, str, float]:
            calls.append(command)
            return 0, "claude 2.1.226\n", "", 0.01

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = root / "receipt.json"
            report = claude_lifecycle_control_harness.run_live_qualification(
                template_path=ROOT / "adapters/claude/lifecycle-control.template.json",
                policy_path=ROOT / "policy/adapter-lifecycle-control.json",
                claude_bin="claude",
                expected_host_version="2.1.226",
                matrix_path=None,
                allow_live=False,
                worktree=root,
                receipt_path=receipt,
                runner=runner,
                clean_checker=lambda _path: True,
            )

            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["qualificationStatus"], "NO_RECOMMENDATION")
            self.assertFalse(report["liveCallsStarted"])
            self.assertEqual(calls, [])

    def test_live_preflight_without_matrix_stays_no_recommendation(self) -> None:
        def runner(_command: list[str], _cwd: Path | None) -> tuple[int, str, str, float]:
            return 0, "claude 2.1.226\n", "", 0.01

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = claude_lifecycle_control_harness.run_live_qualification(
                template_path=ROOT / "adapters/claude/lifecycle-control.template.json",
                policy_path=ROOT / "policy/adapter-lifecycle-control.json",
                claude_bin="claude",
                expected_host_version="2.1.226",
                matrix_path=None,
                allow_live=True,
                worktree=root,
                receipt_path=root / "receipt.json",
                runner=runner,
                clean_checker=lambda _path: True,
            )

            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["qualificationStatus"], "NO_RECOMMENDATION")
            self.assertTrue(report["liveCallsStarted"])
            self.assertTrue(report["syntheticReplayUsed"])

    def test_malformed_matrix_returns_bounded_failure_and_receipt(self) -> None:
        def runner(_command: list[str], _cwd: Path | None) -> tuple[int, str, str, float]:
            return 0, "claude 2.1.226\n", "", 0.01

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            matrix = root / "matrix.json"
            matrix.write_text(json.dumps({"positiveEvidence": "invalid", "negativeEvidence": []}), encoding="utf-8")
            receipt = root / "receipt.json"
            report = claude_lifecycle_control_harness.run_live_qualification(
                template_path=ROOT / "adapters/claude/lifecycle-control.template.json",
                policy_path=ROOT / "policy/adapter-lifecycle-control.json",
                claude_bin="claude",
                expected_host_version="2.1.226",
                matrix_path=matrix,
                allow_live=True,
                worktree=root,
                receipt_path=receipt,
                runner=runner,
                clean_checker=lambda _path: True,
            )

            self.assertEqual(report["status"], "FAIL")
            self.assertTrue(receipt.is_file())
            self.assertEqual(report["qualificationStatus"], "NO_RECOMMENDATION")
            self.assertIn("control-qualification-matrix-shape", {item["code"] for item in report["blockers"]})

    def test_oversized_matrix_returns_bounded_failure_and_receipt(self) -> None:
        def runner(_command: list[str], _cwd: Path | None) -> tuple[int, str, str, float]:
            return 0, "claude 2.1.226\n", "", 0.01

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            matrix = root / "matrix.json"
            matrix.write_text(
                json.dumps(
                    {
                        "positiveEvidence": [
                            {
                                "scenarioId": f"extra-{index}",
                                "source": "live",
                                "syntheticReplayUsed": False,
                                "padding": "x" * 300,
                            }
                            for index in range(64)
                        ],
                        "negativeEvidence": [],
                    }
                ),
                encoding="utf-8",
            )
            receipt = root / "receipt.json"
            report = claude_lifecycle_control_harness.run_live_qualification(
                template_path=ROOT / "adapters/claude/lifecycle-control.template.json",
                policy_path=ROOT / "policy/adapter-lifecycle-control.json",
                claude_bin="claude",
                expected_host_version="2.1.226",
                matrix_path=matrix,
                allow_live=True,
                worktree=root,
                receipt_path=receipt,
                runner=runner,
                clean_checker=lambda _path: True,
            )

            self.assertEqual(report["status"], "FAIL")
            self.assertTrue(receipt.is_file())
            self.assertIn("control-qualification-matrix-invalid", {item["code"] for item in report["blockers"]})

    def test_missing_policy_returns_bounded_fixture_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = root / "receipt.json"
            report = claude_lifecycle_control_harness.run_fixture_check(
                ROOT / "adapters/claude/lifecycle-control.template.json",
                root / "missing-policy.json",
                receipt,
            )

            self.assertEqual(report["status"], "FAIL")
            self.assertTrue(receipt.is_file())
            self.assertIn(
                "control-qualification-control-policy-read-failed", {item["code"] for item in report["blockers"]}
            )

    def test_default_host_probe_has_timeout(self) -> None:
        completed = type("Completed", (), {"returncode": 0, "stdout": "claude 2.1.226\n", "stderr": ""})()
        with patch.object(claude_lifecycle_control_harness.subprocess, "run", return_value=completed) as run:
            result = claude_lifecycle_control_harness._run_command(["claude", "--version"], None)

        self.assertEqual(result[0], 0)
        self.assertEqual(run.call_args.kwargs["timeout"], 10.0)


if __name__ == "__main__":
    unittest.main()

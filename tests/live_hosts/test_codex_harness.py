from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.host_protocol import HostOperationReceipt, HostOperationRequest  # noqa: E402
from tools.live_hosts import codex_harness  # noqa: E402


class CodexHarnessTests(unittest.TestCase):
    def test_fixture_operations_cover_adapter_baseline_with_valid_envelopes(self) -> None:
        baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")

        operations = codex_harness.build_fixture_operations("codex", baseline)

        self.assertEqual(
            {operation["name"] for operation in operations},
            set(baseline["requiredOperations"]),
        )
        self.assertTrue(all(operation["syntheticReplayUsed"] is True for operation in operations))
        for operation in operations:
            request = HostOperationRequest.from_json(operation["hostOperationRequest"])
            receipt = HostOperationReceipt.from_json(operation["hostOperationReceipt"])
            self.assertEqual(request.operation_id, receipt.operation_id)
            self.assertEqual(request.capability, operation["name"])
            self.assertEqual(receipt.capability, operation["name"])

    def test_jsonl_usage_parser_extracts_nested_usage_cost_and_session(self) -> None:
        payload = "\n".join(
            [
                json.dumps({"type": "session", "session_id": "codex-session-1"}),
                json.dumps(
                    {
                        "type": "turn",
                        "usage": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20, "cumulativeContextBytes": 1200},
                        "cost_usd": 0.015,
                        "tool_calls": [{"name": "shell"}],
                    }
                ),
                "not-json",
            ]
        )

        usage = codex_harness.parse_codex_jsonl(payload, wall_seconds=1.25)

        self.assertEqual(usage.session_id, "codex-session-1")
        self.assertEqual(usage.input_tokens, 12)
        self.assertEqual(usage.output_tokens, 8)
        self.assertEqual(usage.billable_tokens, 20)
        self.assertEqual(usage.cumulative_context_bytes, 1200)
        self.assertEqual(usage.tool_calls, 1)
        self.assertEqual(usage.cost_usd, 0.015)
        self.assertEqual(usage.wall_seconds, 1.25)

    def test_live_authorization_supports_budget_modes(self) -> None:
        with self.assertRaises(codex_harness.HarnessError) as caught:
            codex_harness.require_live_authorization(codex_harness.BudgetPolicy(mode="metered"))
        self.assertEqual(caught.exception.code, "BLOCKED_BUDGET_EXHAUSTED")

        with self.assertRaises(codex_harness.HarnessError):
            codex_harness.require_live_authorization(codex_harness.BudgetPolicy(mode="metered", budget_cap_usd=0))

        codex_harness.require_live_authorization(codex_harness.BudgetPolicy(mode="metered", budget_cap_usd=0.01))

        with self.assertRaises(codex_harness.HarnessError):
            codex_harness.require_live_authorization(codex_harness.BudgetPolicy(mode="subscription", max_invocations=1), required_invocations=2)

        codex_harness.require_live_authorization(
            codex_harness.BudgetPolicy(mode="subscription", max_invocations=2, max_wall_seconds=30),
            required_invocations=2,
        )
        codex_harness.require_live_authorization(
            codex_harness.BudgetPolicy(mode="local", max_invocations=2, max_billable_tokens=1000),
            required_invocations=2,
        )

    def test_live_host_receipt_mode_blocks_before_live_without_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report = tmp_path / "blocked-report.json"
            receipt = tmp_path / "codex.json"

            exit_code = codex_harness.main(
                [
                    "--mode",
                    "live-host-receipt",
                    "--baseline",
                    "conformance/core/adapter-baseline.v1.json",
                    "--receipt",
                    str(receipt),
                    "--report",
                    str(report),
                ]
            )

            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertNotEqual(exit_code, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertFalse(payload["liveCallsStarted"])
            self.assertFalse(receipt.exists())
            self.assertIn("BLOCKED_BUDGET_EXHAUSTED", {item["code"] for item in payload["blockers"]})

    def test_live_host_receipt_with_fake_runner_writes_valid_receipt(self) -> None:
        baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")
        calls: list[list[str]] = []

        def fake_runner(command: list[str]) -> codex_harness.CommandResult:
            calls.append(command)
            operation = command[-1].split("Operation: ", 1)[1].split(".", 1)[0]
            stdout = "\n".join(
                [
                    json.dumps({"type": "session", "session_id": f"session-{operation}"}),
                    json.dumps(
                        {
                            "type": "turn",
                            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                            "cost_usd": 0.001,
                        }
                    ),
                ]
            )
            return codex_harness.CommandResult(returncode=0, stdout=stdout, stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt = tmp_path / "receipts/codex.json"
            report = codex_harness.run_live_host_receipt(
                codex_bin="codex",
                baseline_path=ROOT / "conformance/core/adapter-baseline.v1.json",
                worktree=tmp_path / "clean-worktree",
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=codex_harness.BudgetPolicy(mode="metered", budget_cap_usd=1.0),
                runner=fake_runner,
                clean_worktree_checker=lambda _: {"clean": True, "dirtyEntryCount": 0},
            )

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(payload["schemaVersion"], codex_harness.LIVE_HOST_RECEIPT_SCHEMA)
            self.assertEqual(payload["host"], "codex")
            self.assertFalse(payload["syntheticReplayUsed"])
            self.assertTrue(payload["usageAttested"])
            self.assertEqual({item["name"] for item in payload["operations"]}, set(baseline["requiredOperations"]))
            self.assertEqual(len(calls), len(baseline["requiredOperations"]))

    def test_live_host_receipt_blocks_when_invocation_exceeds_budget_cap(self) -> None:
        def expensive_runner(command: list[str]) -> codex_harness.CommandResult:
            stdout = "\n".join(
                [
                    json.dumps({"type": "session", "session_id": "session-expensive"}),
                    json.dumps(
                        {
                            "type": "turn",
                            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                            "cost_usd": 2.0,
                        }
                    ),
                ]
            )
            return codex_harness.CommandResult(returncode=0, stdout=stdout, stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt = tmp_path / "receipts/codex.json"
            report = codex_harness.run_live_host_receipt(
                codex_bin="codex",
                baseline_path=ROOT / "conformance/core/adapter-baseline.v1.json",
                worktree=tmp_path / "clean-worktree",
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=codex_harness.BudgetPolicy(mode="metered", budget_cap_usd=1.0),
                runner=expensive_runner,
                clean_worktree_checker=lambda _: {"clean": True, "dirtyEntryCount": 0},
            )

            self.assertEqual(report["status"], "FAIL")
            self.assertFalse(receipt.exists())
            self.assertIn("BLOCKED_BUDGET_EXHAUSTED", {item["code"] for item in report["blockers"]})

    def test_live_host_receipt_subscription_mode_does_not_require_cost_usd(self) -> None:
        baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")

        def subscription_runner(command: list[str]) -> codex_harness.CommandResult:
            stdout = "\n".join(
                [
                    json.dumps({"type": "session", "session_id": "session-subscription"}),
                    json.dumps({"type": "turn", "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}),
                ]
            )
            return codex_harness.CommandResult(returncode=0, stdout=stdout, stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt = tmp_path / "receipts/codex.json"
            report = codex_harness.run_live_host_receipt(
                codex_bin="codex",
                baseline_path=ROOT / "conformance/core/adapter-baseline.v1.json",
                worktree=tmp_path / "clean-worktree",
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=codex_harness.BudgetPolicy(
                    mode="subscription",
                    max_invocations=len(baseline["requiredOperations"]),
                    max_billable_tokens=1000,
                ),
                runner=subscription_runner,
                clean_worktree_checker=lambda _: {"clean": True, "dirtyEntryCount": 0},
            )

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(payload["budgetMode"], "subscription")
            self.assertEqual(payload["budgetUsage"]["costUsd"], 0.0)

    def test_live_calibration_mode_blocks_before_live_without_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report = tmp_path / "blocked-calibration-report.json"
            receipt = tmp_path / "codex-calibration.json"

            exit_code = codex_harness.main(
                [
                    "--mode",
                    "live-calibration",
                    "--profile",
                    "conformance/core/live-calibration-profile.v1.json",
                    "--budget-targets",
                    "conformance/core/budget-targets.v1.json",
                    "--receipt",
                    str(receipt),
                    "--report",
                    str(report),
                ]
            )

            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertNotEqual(exit_code, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertFalse(payload["liveCallsStarted"])
            self.assertFalse(receipt.exists())
            self.assertIn("BLOCKED_BUDGET_EXHAUSTED", {item["code"] for item in payload["blockers"]})

    def test_live_calibration_with_fake_runner_writes_validator_compatible_receipt(self) -> None:
        profile = _load_json(ROOT / "conformance/core/live-calibration-profile.v1.json")
        calls: list[list[str]] = []

        def fake_runner(command: list[str]) -> codex_harness.CommandResult:
            calls.append(command)
            stdout = "\n".join(
                [
                    json.dumps({"type": "session", "session_id": f"session-{len(calls)}"}),
                    json.dumps(
                        {
                            "type": "turn",
                            "usage": {
                                "input_tokens": 10,
                                "output_tokens": 5,
                                "total_tokens": 15,
                                "cumulativeContextBytes": 1000,
                            },
                            "cost_usd": 0.001,
                        }
                    ),
                ]
            )
            return codex_harness.CommandResult(returncode=0, stdout=stdout, stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt = tmp_path / "calibration/codex.json"
            report = codex_harness.run_live_calibration(
                codex_bin="codex",
                profile_path=ROOT / "conformance/core/live-calibration-profile.v1.json",
                budget_targets_path=ROOT / "conformance/core/budget-targets.v1.json",
                worktree=tmp_path / "clean-worktree",
                runs_per_scenario_cohort=1,
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=codex_harness.BudgetPolicy(mode="metered", budget_cap_usd=1.0),
                runner=fake_runner,
                clean_worktree_checker=lambda _: {"clean": True, "dirtyEntryCount": 0},
            )

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            expected_runs = len(profile["requiredScenarios"]) * len(profile["requiredCohorts"])
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(payload["schemaVersion"], codex_harness.LIVE_CALIBRATION_RECEIPT_SCHEMA)
            self.assertEqual(payload["host"], "codex")
            self.assertFalse(payload["syntheticReplayUsed"])
            self.assertEqual(payload["qualityRegressionCount"], 0)
            self.assertEqual(payload["liveModelInvocations"], expected_runs)
            self.assertEqual(len(payload["runs"]), expected_runs)
            self.assertEqual(len(calls), expected_runs)
            self.assertEqual(payload["runs"][0]["usage"]["sessionId"], "session-1")
            validation_evidence = tmp_path / "calibration-validation.json"
            validation = subprocess.run(
                [
                    sys.executable,
                    "tools/release/validate_live_calibration.py",
                    "--profile",
                    "conformance/core/live-calibration-profile.v1.json",
                    "--budget-targets",
                    "conformance/core/budget-targets.v1.json",
                    "--receipt",
                    str(receipt),
                    "--evidence",
                    str(validation_evidence),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(validation.returncode, 0, validation.stderr)
            validation_payload = json.loads(validation_evidence.read_text(encoding="utf-8"))
            self.assertEqual(validation_payload["status"], "PASS")

    def test_live_calibration_local_mode_uses_resource_caps_without_cost(self) -> None:
        profile = _load_json(ROOT / "conformance/core/live-calibration-profile.v1.json")
        expected_runs = len(profile["requiredScenarios"]) * len(profile["requiredCohorts"])

        def local_runner(command: list[str]) -> codex_harness.CommandResult:
            stdout = "\n".join(
                [
                    json.dumps({"type": "session", "session_id": "session-local"}),
                    json.dumps(
                        {
                            "type": "turn",
                            "usage": {
                                "input_tokens": 10,
                                "output_tokens": 5,
                                "total_tokens": 15,
                                "cumulativeContextBytes": 1000,
                            },
                        }
                    ),
                ]
            )
            return codex_harness.CommandResult(returncode=0, stdout=stdout, stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt = tmp_path / "calibration/codex.json"
            report = codex_harness.run_live_calibration(
                codex_bin="codex",
                profile_path=ROOT / "conformance/core/live-calibration-profile.v1.json",
                budget_targets_path=ROOT / "conformance/core/budget-targets.v1.json",
                worktree=tmp_path / "clean-worktree",
                runs_per_scenario_cohort=1,
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=codex_harness.BudgetPolicy(
                    mode="local",
                    max_invocations=expected_runs,
                    max_billable_tokens=expected_runs * 20,
                    max_wall_seconds=expected_runs,
                ),
                runner=local_runner,
                clean_worktree_checker=lambda _: {"clean": True, "dirtyEntryCount": 0},
            )

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(payload["budgetMode"], "local")
            self.assertEqual(payload["budgetUsage"]["costUsd"], 0.0)
            self.assertEqual(payload["liveModelInvocations"], expected_runs)

    def test_live_calibration_uses_context_byte_proxy_when_codex_usage_omits_it(self) -> None:
        profile = _load_json(ROOT / "conformance/core/live-calibration-profile.v1.json")
        expected_runs = len(profile["requiredScenarios"]) * len(profile["requiredCohorts"])

        def runner_without_context_bytes(command: list[str]) -> codex_harness.CommandResult:
            stdout = "\n".join(
                [
                    json.dumps({"type": "session", "session_id": "session-proxy"}),
                    json.dumps({"type": "turn", "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}),
                ]
            )
            return codex_harness.CommandResult(returncode=0, stdout=stdout, stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt = tmp_path / "calibration/codex.json"
            report = codex_harness.run_live_calibration(
                codex_bin="codex",
                profile_path=ROOT / "conformance/core/live-calibration-profile.v1.json",
                budget_targets_path=ROOT / "conformance/core/budget-targets.v1.json",
                worktree=tmp_path / "clean-worktree",
                runs_per_scenario_cohort=1,
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=codex_harness.BudgetPolicy(
                    mode="subscription",
                    max_invocations=expected_runs,
                    max_billable_tokens=expected_runs * 20,
                ),
                runner=runner_without_context_bytes,
                clean_worktree_checker=lambda _: {"clean": True, "dirtyEntryCount": 0},
            )

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(payload["contextByteAccounting"], "host-jsonl-or-harness-observed-prompt-and-jsonl-bytes")
            first_usage = payload["runs"][0]["usage"]
            self.assertGreater(first_usage["cumulativeContextBytes"], 0)
            self.assertEqual(first_usage["cumulativeContextBytesSource"], "harness-observed-prompt-and-jsonl-bytes")

    def test_fixture_check_report_is_not_live_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "fixture-report.json"

            exit_code = codex_harness.main(
                [
                    "--mode",
                    "fixture-check",
                    "--baseline",
                    "conformance/core/adapter-baseline.v1.json",
                    "--report",
                    str(report),
                ]
            )

            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "PASS")
            self.assertTrue(payload["syntheticFixtureOnly"])
            self.assertFalse(payload["productionPromotionClaimed"])


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected object: {path}")
    return value


if __name__ == "__main__":
    unittest.main()

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
from tools.live_hosts import hermes_harness  # noqa: E402


class HermesHarnessTests(unittest.TestCase):
    def test_fixture_operations_cover_adapter_baseline_with_valid_envelopes(self) -> None:
        baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")

        operations = hermes_harness.build_fixture_operations("hermes", baseline)

        self.assertEqual({operation["name"] for operation in operations}, set(baseline["requiredOperations"]))
        self.assertTrue(all(operation["syntheticReplayUsed"] is True for operation in operations))
        for operation in operations:
            request = HostOperationRequest.from_json(operation["hostOperationRequest"])
            receipt = HostOperationReceipt.from_json(operation["hostOperationReceipt"])
            self.assertEqual(request.operation_id, receipt.operation_id)
            self.assertEqual(request.capability, operation["name"])
            self.assertEqual(receipt.capability, operation["name"])

    def test_usage_file_parser_extracts_tokens_cost_and_session(self) -> None:
        usage = hermes_harness.parse_hermes_usage_file(
            {
                "session_id": "hermes-session-1",
                "tokens": {
                    "input": 11,
                    "output": 9,
                    "total": 20,
                    "cache_read_tokens": 3,
                    "cache_write_tokens": 2,
                    "reasoning_tokens": 4,
                    "cumulativeContextBytes": 1200,
                },
                "estimated_cost_usd": 0.03,
                "api_calls": 1,
            },
            wall_seconds=1.2,
        )

        self.assertEqual(usage.session_id, "hermes-session-1")
        self.assertEqual(usage.input_tokens, 11)
        self.assertEqual(usage.output_tokens, 9)
        self.assertEqual(usage.billable_tokens, 20)
        self.assertEqual(usage.raw_total_tokens, 20)
        self.assertEqual(usage.cache_read_tokens, 3)
        self.assertEqual(usage.cache_write_tokens, 2)
        self.assertEqual(usage.reasoning_tokens, 4)
        self.assertEqual(usage.cumulative_context_bytes, 1200)
        self.assertEqual(usage.cost_usd, 0.03)
        self.assertEqual(usage.tool_calls, 1)
        self.assertEqual(usage.wall_seconds, 1.2)

    def test_minimal_direct_command_uses_explicit_provider_model_and_ignores_rules(self) -> None:
        options = hermes_harness.HermesInvocationOptions(
            minimal_direct=True,
            provider="test-provider",
            model="test-model",
        ).normalized()

        command = hermes_harness._hermes_command("hermes", "probe", Path("usage.json"), options)

        self.assertIn("--ignore-rules", command)
        self.assertEqual(command[command.index("--provider") + 1], "test-provider")
        self.assertEqual(command[command.index("--model") + 1], "test-model")
        self.assertEqual(command[command.index("--oneshot") + 1], "probe")
        self.assertEqual(command[command.index("--usage-file") + 1], "usage.json")

    def test_minimal_direct_command_has_no_provider_model_default(self) -> None:
        options = hermes_harness.HermesInvocationOptions(minimal_direct=True).normalized()

        command = hermes_harness._hermes_command("hermes", "probe", Path("usage.json"), options)

        self.assertIn("--ignore-rules", command)
        self.assertNotIn("--provider", command)
        self.assertNotIn("--model", command)

    def test_live_host_receipt_blocks_when_hermes_has_no_auth_provider(self) -> None:
        baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt = tmp_path / "hermes.json"
            report = hermes_harness.run_live_host_receipt(
                hermes_bin="hermes",
                baseline_path=ROOT / "conformance/core/adapter-baseline.v1.json",
                worktree=tmp_path / "clean-worktree",
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=hermes_harness.BudgetPolicy(
                    mode="subscription",
                    max_invocations=len(baseline["requiredOperations"]),
                    max_billable_tokens=1000,
                ),
                runner=lambda command, cwd: hermes_harness.CommandResult(returncode=0, stdout="", stderr="", wall_seconds=0.1),
                clean_worktree_checker=lambda _: {"clean": True, "dirtyEntryCount": 0},
                auth_checker=lambda _: {"authenticated": False, "statusReturncode": 0},
            )

            self.assertEqual(report["status"], "FAIL")
            self.assertFalse(report["liveCallsStarted"])
            self.assertFalse(receipt.exists())
            self.assertIn("BLOCKED_HOST_AUTH", {item["code"] for item in report["blockers"]})

    def test_auth_status_parser_accepts_only_usable_pooled_credentials(self) -> None:
        self.assertTrue(hermes_harness._auth_status_logged_in("test-provider: logged in", ""))
        self.assertFalse(hermes_harness._auth_status_logged_in("test-provider: logged out", ""))
        self.assertFalse(hermes_harness._auth_status_logged_in("test-provider: logged in rate-limited 1113 (429)", ""))

    def test_live_host_receipt_with_fake_runner_writes_validator_compatible_receipt(self) -> None:
        baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")
        calls: list[list[str]] = []

        def fake_runner(command: list[str], cwd: Path | None) -> hermes_harness.CommandResult:
            calls.append(command)
            usage_file = Path(command[command.index("--usage-file") + 1])
            usage_file.parent.mkdir(parents=True, exist_ok=True)
            operation = command[command.index("--oneshot") + 1].split("Operation: ", 1)[1].split(".", 1)[0]
            usage_file.write_text(
                json.dumps({"session_id": f"session-{operation}", "tokens": {"input": 10, "output": 5, "total": 15}}),
                encoding="utf-8",
            )
            return hermes_harness.CommandResult(returncode=0, stdout='{\"status\":\"PASS\"}', stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt_dir = tmp_path / "receipts"
            receipt = receipt_dir / "hermes.json"
            model_selection = hermes_harness.load_host_model_selection(
                ROOT / "profiles/hosts/hermes-live-profile.v1.json",
                model_class="standard-code",
            )
            selection_receipt = receipt_dir / "hermes-model-selection.json"
            report = hermes_harness.run_live_host_receipt(
                hermes_bin="hermes",
                baseline_path=ROOT / "conformance/core/adapter-baseline.v1.json",
                worktree=tmp_path / "clean-worktree",
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=hermes_harness.BudgetPolicy(
                    mode="subscription",
                    max_invocations=len(baseline["requiredOperations"]),
                    max_billable_tokens=1000,
                ),
                runner=fake_runner,
                clean_worktree_checker=lambda _: {"clean": True, "dirtyEntryCount": 0},
                auth_checker=lambda _: {"authenticated": True},
                invocation_options=hermes_harness.HermesInvocationOptions(minimal_direct=True),
                model_selection=model_selection,
                model_selection_receipt_path=selection_receipt,
            )

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            selection_payload = json.loads(selection_receipt.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(payload["schemaVersion"], hermes_harness.LIVE_HOST_RECEIPT_SCHEMA)
            self.assertEqual(payload["host"], "hermes")
            self.assertFalse(payload["syntheticReplayUsed"])
            self.assertTrue(payload["usageAttested"])
            self.assertEqual({item["name"] for item in payload["operations"]}, set(baseline["requiredOperations"]))
            self.assertEqual(len(calls), len(baseline["requiredOperations"]))
            self.assertIn("--ignore-rules", calls[0])
            self.assertEqual(calls[0][calls[0].index("--model") + 1], "<hermes-host-local-standard-code-model>")
            self.assertTrue(payload["hermesInvocationOptions"]["minimalDirect"])
            self.assertEqual(selection_payload["schemaVersion"], "agent-host-model-selection-receipt.v1")
            self.assertNotIn("<hermes-host-local-standard-code-model>", json.dumps(payload["modelSelection"]))

            validation_evidence = tmp_path / "host-conformance-validation.json"
            validation = subprocess.run(
                [
                    sys.executable,
                    "tools/release/validate_live_host_conformance.py",
                    "--profile",
                    "conformance/core/live-calibration-profile.v1.json",
                    "--baseline",
                    "conformance/core/adapter-baseline.v1.json",
                    "--receipt-dir",
                    str(receipt_dir),
                    "--promoted-hosts",
                    "hermes",
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

    def test_live_calibration_uses_context_byte_proxy_when_usage_file_omits_it(self) -> None:
        profile = _load_json(ROOT / "conformance/core/live-calibration-profile.v1.json")
        expected_runs = len(profile["requiredScenarios"]) * len(profile["requiredCohorts"])

        def fake_runner(command: list[str], cwd: Path | None) -> hermes_harness.CommandResult:
            usage_file = Path(command[command.index("--usage-file") + 1])
            usage_file.parent.mkdir(parents=True, exist_ok=True)
            usage_file.write_text(
                json.dumps({"session_id": "session-proxy", "tokens": {"input": 10, "output": 5, "total": 15}}),
                encoding="utf-8",
            )
            return hermes_harness.CommandResult(returncode=0, stdout='{\"status\":\"PASS\"}', stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt = tmp_path / "calibration/hermes.json"
            report = hermes_harness.run_live_calibration(
                hermes_bin="hermes",
                profile_path=ROOT / "conformance/core/live-calibration-profile.v1.json",
                budget_targets_path=ROOT / "conformance/core/budget-targets.v1.json",
                worktree=tmp_path / "clean-worktree",
                runs_per_scenario_cohort=1,
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=hermes_harness.BudgetPolicy(
                    mode="subscription",
                    max_invocations=expected_runs,
                    max_billable_tokens=expected_runs * 20,
                ),
                runner=fake_runner,
                clean_worktree_checker=lambda _: {"clean": True, "dirtyEntryCount": 0},
                auth_checker=lambda _: {"authenticated": True},
            )

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(payload["host"], "hermes")
            self.assertEqual(payload["liveModelInvocations"], expected_runs)
            first_usage = payload["runs"][0]["usage"]
            self.assertGreater(first_usage["cumulativeContextBytes"], 0)
            self.assertEqual(first_usage["cumulativeContextBytesSource"], "harness-observed-prompt-stdout-stderr-and-usage-file-bytes")


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected object: {path}")
    return value


if __name__ == "__main__":
    unittest.main()

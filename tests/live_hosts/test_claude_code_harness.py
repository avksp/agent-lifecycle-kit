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
from tools.live_hosts import claude_code_harness  # noqa: E402


class ClaudeCodeHarnessTests(unittest.TestCase):
    def test_fixture_operations_cover_adapter_baseline_with_valid_envelopes(self) -> None:
        baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")

        operations = claude_code_harness.build_fixture_operations("claude-code", baseline)

        self.assertEqual({operation["name"] for operation in operations}, set(baseline["requiredOperations"]))
        self.assertTrue(all(operation["syntheticReplayUsed"] is True for operation in operations))
        for operation in operations:
            request = HostOperationRequest.from_json(operation["hostOperationRequest"])
            receipt = HostOperationReceipt.from_json(operation["hostOperationReceipt"])
            self.assertEqual(request.operation_id, receipt.operation_id)
            self.assertEqual(request.capability, operation["name"])
            self.assertEqual(receipt.capability, operation["name"])

    def test_stream_json_usage_parser_extracts_usage_cost_and_session(self) -> None:
        payload = "\n".join(
            [
                json.dumps({"type": "system", "subtype": "init", "session_id": "claude-session-1"}),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "usage": {
                                "input_tokens": 12,
                                "output_tokens": 8,
                                "cache_creation_input_tokens": 3,
                                "cumulativeContextBytes": 1200,
                            }
                        },
                    }
                ),
                json.dumps({"type": "result", "total_cost_usd": 0.015}),
            ]
        )

        usage = claude_code_harness.parse_claude_jsonl(payload, wall_seconds=1.25)

        self.assertEqual(usage.session_id, "claude-session-1")
        self.assertEqual(usage.input_tokens, 12)
        self.assertEqual(usage.output_tokens, 8)
        self.assertEqual(usage.billable_tokens, 23)
        self.assertEqual(usage.cumulative_context_bytes, 1200)
        self.assertEqual(usage.cost_usd, 0.015)
        self.assertEqual(usage.wall_seconds, 1.25)

    def test_live_host_receipt_mode_blocks_before_live_without_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report = tmp_path / "blocked-report.json"
            receipt = tmp_path / "claude-code.json"

            exit_code = claude_code_harness.main(
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

    def test_live_host_receipt_with_fake_runner_writes_validator_compatible_receipt(self) -> None:
        baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")
        calls: list[list[str]] = []

        def fake_runner(command: list[str], cwd: Path | None) -> claude_code_harness.CommandResult:
            calls.append(command)
            operation = command[-1].split("Operation: ", 1)[1].split(".", 1)[0]
            stdout = "\n".join(
                [
                    json.dumps({"type": "system", "session_id": f"session-{operation}"}),
                    json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 10, "output_tokens": 5}}}),
                ]
            )
            return claude_code_harness.CommandResult(returncode=0, stdout=stdout, stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt_dir = tmp_path / "receipts"
            receipt = receipt_dir / "claude-code.json"
            model_selection = claude_code_harness.load_host_model_selection(
                ROOT / "profiles/hosts/claude-code-live-profile.v1.json",
                model_class="standard-code",
            )
            selection_receipt = receipt_dir / "claude-code-model-selection.json"
            report = claude_code_harness.run_live_host_receipt(
                claude_bin="claude",
                baseline_path=ROOT / "conformance/core/adapter-baseline.v1.json",
                worktree=tmp_path / "clean-worktree",
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=claude_code_harness.BudgetPolicy(mode="subscription", max_invocations=len(baseline["requiredOperations"]), max_billable_tokens=1000),
                model_selection=model_selection,
                model_selection_receipt_path=selection_receipt,
                runner=fake_runner,
                clean_worktree_checker=lambda _: {"clean": True, "dirtyEntryCount": 0},
            )

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            selection_payload = json.loads(selection_receipt.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(payload["schemaVersion"], claude_code_harness.LIVE_HOST_RECEIPT_SCHEMA)
            self.assertEqual(payload["host"], "claude-code")
            self.assertFalse(payload["syntheticReplayUsed"])
            self.assertTrue(payload["usageAttested"])
            self.assertEqual({item["name"] for item in payload["operations"]}, set(baseline["requiredOperations"]))
            self.assertEqual(len(calls), len(baseline["requiredOperations"]))
            self.assertEqual(calls[0][calls[0].index("--model") + 1], "<claude-code-host-local-standard-code-model>")
            self.assertEqual(selection_payload["schemaVersion"], "agent-host-model-selection-receipt.v1")
            self.assertNotIn("<claude-code-host-local-standard-code-model>", json.dumps(payload["modelSelection"]))

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
                    "claude-code",
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

    def test_live_calibration_with_fake_runner_writes_validator_compatible_receipt(self) -> None:
        profile = _load_json(ROOT / "conformance/core/live-calibration-profile.v1.json")
        expected_runs = len(profile["requiredScenarios"]) * len(profile["requiredCohorts"])
        calls: list[list[str]] = []

        def fake_runner(command: list[str], cwd: Path | None) -> claude_code_harness.CommandResult:
            calls.append(command)
            stdout = "\n".join(
                [
                    json.dumps({"type": "system", "session_id": f"session-{len(calls)}"}),
                    json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 10, "output_tokens": 5}}}),
                ]
            )
            return claude_code_harness.CommandResult(returncode=0, stdout=stdout, stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt = tmp_path / "calibration/claude-code.json"
            report = claude_code_harness.run_live_calibration(
                claude_bin="claude",
                profile_path=ROOT / "conformance/core/live-calibration-profile.v1.json",
                budget_targets_path=ROOT / "conformance/core/budget-targets.v1.json",
                worktree=tmp_path / "clean-worktree",
                runs_per_scenario_cohort=1,
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=claude_code_harness.BudgetPolicy(mode="subscription", max_invocations=expected_runs, max_billable_tokens=expected_runs * 20),
                runner=fake_runner,
                clean_worktree_checker=lambda _: {"clean": True, "dirtyEntryCount": 0},
            )

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(payload["schemaVersion"], claude_code_harness.LIVE_CALIBRATION_RECEIPT_SCHEMA)
            self.assertEqual(payload["host"], "claude-code")
            self.assertEqual(payload["liveModelInvocations"], expected_runs)
            self.assertEqual(len(payload["runs"]), expected_runs)
            self.assertEqual(payload["runs"][0]["usage"]["sessionId"], "session-1")
            self.assertEqual(payload["runs"][0]["usage"]["cumulativeContextBytesSource"], "harness-observed-prompt-and-jsonl-bytes")

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


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected object: {path}")
    return value


if __name__ == "__main__":
    unittest.main()

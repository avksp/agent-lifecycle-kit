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
from tools.live_hosts import cursor_harness  # noqa: E402


class CursorHarnessTests(unittest.TestCase):
    def test_fixture_operations_cover_adapter_baseline_with_valid_envelopes(self) -> None:
        baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")

        operations = cursor_harness.build_fixture_operations("cursor", baseline)

        self.assertEqual({operation["name"] for operation in operations}, set(baseline["requiredOperations"]))
        self.assertTrue(all(operation["syntheticReplayUsed"] is True for operation in operations))
        for operation in operations:
            request = HostOperationRequest.from_json(operation["hostOperationRequest"])
            receipt = HostOperationReceipt.from_json(operation["hostOperationReceipt"])
            self.assertEqual(request.operation_id, receipt.operation_id)
            self.assertEqual(request.capability, operation["name"])
            self.assertEqual(receipt.capability, operation["name"])

    def test_stream_json_usage_parser_extracts_usage_cost_and_chat_id(self) -> None:
        payload = "\n".join(
            [
                json.dumps({"type": "system", "chat_id": "cursor-chat-1"}),
                json.dumps(
                    {
                        "type": "assistant",
                        "usage": {
                            "input_tokens": 14,
                            "output_tokens": 7,
                            "cache_read_input_tokens": 2,
                            "cumulativeContextBytes": 1600,
                        },
                        "toolCalls": [{"name": "read"}],
                    }
                ),
                json.dumps({"type": "result", "total_cost_usd": 0.02}),
            ]
        )

        usage = cursor_harness.parse_cursor_jsonl(payload, wall_seconds=1.4)

        self.assertEqual(usage.session_id, "cursor-chat-1")
        self.assertEqual(usage.input_tokens, 14)
        self.assertEqual(usage.output_tokens, 7)
        self.assertEqual(usage.billable_tokens, 23)
        self.assertEqual(usage.cumulative_context_bytes, 1600)
        self.assertEqual(usage.tool_calls, 1)
        self.assertEqual(usage.cost_usd, 0.02)
        self.assertEqual(usage.wall_seconds, 1.4)

    def test_live_host_receipt_blocks_when_cursor_agent_is_not_authenticated(self) -> None:
        baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt = tmp_path / "cursor.json"
            report = cursor_harness.run_live_host_receipt(
                cursor_bin="cursor",
                cursor_model="test-strong-model",
                baseline_path=ROOT / "conformance/core/adapter-baseline.v1.json",
                worktree=tmp_path / "clean-worktree",
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=cursor_harness.BudgetPolicy(
                    mode="subscription",
                    max_invocations=len(baseline["requiredOperations"]),
                    max_billable_tokens=1000,
                ),
                runner=lambda command, cwd: cursor_harness.CommandResult(returncode=0, stdout="", stderr="", wall_seconds=0.1),
                clean_worktree_checker=lambda _: {"clean": True, "dirtyEntryCount": 0},
                auth_checker=lambda _: {"authenticated": False, "statusReturncode": 1},
            )

            self.assertEqual(report["status"], "FAIL")
            self.assertFalse(report["liveCallsStarted"])
            self.assertFalse(receipt.exists())
            self.assertIn("BLOCKED_HOST_AUTH", {item["code"] for item in report["blockers"]})

    def test_live_host_receipt_with_fake_runner_writes_validator_compatible_receipt(self) -> None:
        baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")
        calls: list[list[str]] = []

        def fake_runner(command: list[str], cwd: Path | None) -> cursor_harness.CommandResult:
            calls.append(command)
            operation = command[-1].split("Operation: ", 1)[1].split(".", 1)[0]
            stdout = "\n".join(
                [
                    json.dumps({"type": "system", "chat_id": f"chat-{operation}"}),
                    json.dumps({"type": "assistant", "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}),
                ]
            )
            return cursor_harness.CommandResult(returncode=0, stdout=stdout, stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt_dir = tmp_path / "receipts"
            receipt = receipt_dir / "cursor.json"
            report = cursor_harness.run_live_host_receipt(
                cursor_bin="cursor",
                cursor_model="test-strong-model",
                baseline_path=ROOT / "conformance/core/adapter-baseline.v1.json",
                worktree=tmp_path / "clean-worktree",
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=cursor_harness.BudgetPolicy(
                    mode="subscription",
                    max_invocations=len(baseline["requiredOperations"]),
                    max_billable_tokens=1000,
                ),
                runner=fake_runner,
                clean_worktree_checker=lambda _: {"clean": True, "dirtyEntryCount": 0},
                auth_checker=lambda _: {"authenticated": True},
            )

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(payload["schemaVersion"], cursor_harness.LIVE_HOST_RECEIPT_SCHEMA)
            self.assertEqual(payload["host"], "cursor")
            self.assertEqual(payload["cursorModel"], "test-strong-model")
            self.assertFalse(payload["syntheticReplayUsed"])
            self.assertTrue(payload["usageAttested"])
            self.assertEqual({item["name"] for item in payload["operations"]}, set(baseline["requiredOperations"]))
            self.assertEqual(len(calls), len(baseline["requiredOperations"]))
            self.assertTrue(all("--model" in command for command in calls))
            self.assertTrue(all(command[command.index("--model") + 1] == "test-strong-model" for command in calls))

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
                    "cursor",
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

    def test_live_calibration_uses_context_byte_proxy_when_cursor_usage_omits_it(self) -> None:
        profile = _load_json(ROOT / "conformance/core/live-calibration-profile.v1.json")
        expected_runs = len(profile["requiredScenarios"]) * len(profile["requiredCohorts"])

        def fake_runner(command: list[str], cwd: Path | None) -> cursor_harness.CommandResult:
            stdout = "\n".join(
                [
                    json.dumps({"type": "system", "chat_id": "chat-proxy"}),
                    json.dumps({"type": "assistant", "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}),
                ]
            )
            return cursor_harness.CommandResult(returncode=0, stdout=stdout, stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt = tmp_path / "calibration/cursor.json"
            report = cursor_harness.run_live_calibration(
                cursor_bin="cursor",
                cursor_model="test-standard-model",
                profile_path=ROOT / "conformance/core/live-calibration-profile.v1.json",
                budget_targets_path=ROOT / "conformance/core/budget-targets.v1.json",
                worktree=tmp_path / "clean-worktree",
                runs_per_scenario_cohort=1,
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=cursor_harness.BudgetPolicy(
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
            self.assertEqual(payload["host"], "cursor")
            self.assertEqual(payload["cursorModel"], "test-standard-model")
            self.assertEqual(payload["liveModelInvocations"], expected_runs)
            first_usage = payload["runs"][0]["usage"]
            self.assertGreater(first_usage["cumulativeContextBytes"], 0)
            self.assertEqual(first_usage["cumulativeContextBytesSource"], "harness-observed-prompt-and-jsonl-bytes")


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected object: {path}")
    return value


if __name__ == "__main__":
    unittest.main()

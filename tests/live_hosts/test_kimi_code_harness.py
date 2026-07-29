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
from tools.live_hosts import kimi_code_harness  # noqa: E402


class KimiCodeHarnessTests(unittest.TestCase):
    def test_fixture_operations_cover_adapter_baseline_with_valid_envelopes(self) -> None:
        baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")

        operations = kimi_code_harness.build_fixture_operations("kimi-code", baseline)

        self.assertEqual({operation["name"] for operation in operations}, set(baseline["requiredOperations"]))
        self.assertTrue(all(operation["syntheticReplayUsed"] is True for operation in operations))
        for operation in operations:
            request = HostOperationRequest.from_json(operation["hostOperationRequest"])
            receipt = HostOperationReceipt.from_json(operation["hostOperationReceipt"])
            self.assertEqual(request.operation_id, receipt.operation_id)
            self.assertEqual(request.capability, operation["name"])
            self.assertEqual(receipt.capability, operation["name"])

    def test_stream_json_parser_uses_result_usage_without_double_counting(self) -> None:
        payload = "\n".join(
            [
                json.dumps({"type": "system", "session_id": "kimi-session-1", "model": "GLM-5.2"}),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "usage": {
                                "input_tokens": 11,
                                "output_tokens": 9,
                                "cache_read_input_tokens": 5,
                                "total_tokens": 20,
                            }
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "result",
                        "session_id": "kimi-session-1",
                        "duration_ms": 1234,
                        "usage": {
                            "input_tokens": 11,
                            "output_tokens": 9,
                            "cache_read_input_tokens": 5,
                            "total_tokens": 20,
                        },
                    }
                ),
            ]
        )

        usage = kimi_code_harness.parse_kimi_code_stream_json(payload, wall_seconds=9.9)

        self.assertEqual(usage.session_id, "kimi-session-1")
        self.assertEqual(usage.input_tokens, 11)
        self.assertEqual(usage.output_tokens, 9)
        self.assertEqual(usage.billable_tokens, 20)
        self.assertEqual(usage.wall_seconds, 1.234)
        self.assertEqual(usage.event_count, 3)

    def test_stream_json_parser_accepts_kimi_usage_metadata(self) -> None:
        payload = "\n".join(
            [
                json.dumps({"type": "system", "sessionId": "kimi-session-2"}),
                json.dumps(
                    {
                        "type": "response.completed",
                        "usageMetadata": {
                            "promptTokenCount": 13,
                            "candidatesTokenCount": 7,
                            "totalTokenCount": 20,
                        },
                    }
                ),
            ]
        )

        usage = kimi_code_harness.parse_kimi_code_stream_json(payload, wall_seconds=0.5)

        self.assertEqual(usage.session_id, "kimi-session-2")
        self.assertEqual(usage.input_tokens, 13)
        self.assertEqual(usage.output_tokens, 7)
        self.assertEqual(usage.billable_tokens, 20)

    def test_live_host_receipt_with_fake_runner_writes_validator_compatible_receipt(self) -> None:
        baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")
        calls: list[list[str]] = []

        def fake_runner(command: list[str]) -> kimi_code_harness.CommandResult:
            calls.append(command)
            prompt = command[command.index("--prompt") + 1]
            operation = prompt.split("Operation: ", 1)[1].split(".", 1)[0]
            stdout = "\n".join(
                [
                    json.dumps({"type": "system", "session_id": f"session-{operation}", "model": "GLM-5.2"}),
                    json.dumps(
                        {
                            "type": "result",
                            "duration_ms": 100,
                            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                        }
                    ),
                ]
            )
            return kimi_code_harness.CommandResult(returncode=0, stdout=stdout, stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt_dir = tmp_path / "receipts"
            receipt = receipt_dir / "kimi-code.json"
            report = kimi_code_harness.run_live_host_receipt(
                kimi_bin="kimi",
                baseline_path=ROOT / "conformance/core/adapter-baseline.v1.json",
                worktree=tmp_path / "clean-worktree",
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=kimi_code_harness.BudgetPolicy(
                    mode="subscription",
                    max_invocations=len(baseline["requiredOperations"]),
                    max_billable_tokens=1000,
                ),
                kimi_model="glm-5.2",
                runner=fake_runner,
                clean_worktree_checker=lambda _: {"clean": True, "dirtyEntryCount": 0},
            )

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(payload["schemaVersion"], kimi_code_harness.LIVE_HOST_RECEIPT_SCHEMA)
            self.assertEqual(payload["host"], "kimi-code")
            self.assertFalse(payload["syntheticReplayUsed"])
            self.assertTrue(payload["usageAttested"])
            self.assertEqual({item["name"] for item in payload["operations"]}, set(baseline["requiredOperations"]))
            self.assertEqual(len(calls), len(baseline["requiredOperations"]))
            self.assertEqual(calls[0][calls[0].index("--model") + 1], "glm-5.2")
            self.assertNotIn("--plan", calls[0])
            self.assertNotIn("--approval-mode", calls[0])
            self.assertNotIn("--safe-mode", calls[0])

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
                    "kimi-code",
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

    def test_live_calibration_uses_context_byte_proxy_when_kimi_usage_omits_it(self) -> None:
        profile = _load_json(ROOT / "conformance/core/live-calibration-profile.v1.json")
        expected_runs = len(profile["requiredScenarios"]) * len(profile["requiredCohorts"])
        calls: list[list[str]] = []

        def fake_runner(command: list[str]) -> kimi_code_harness.CommandResult:
            calls.append(command)
            stdout = "\n".join(
                [
                    json.dumps({"type": "system", "session_id": "session-proxy", "model": "GLM-5.2"}),
                    json.dumps(
                        {
                            "type": "result",
                            "duration_ms": 100,
                            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                        }
                    ),
                ]
            )
            return kimi_code_harness.CommandResult(returncode=0, stdout=stdout, stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt = tmp_path / "calibration/kimi-code.json"
            report = kimi_code_harness.run_live_calibration(
                kimi_bin="kimi",
                profile_path=ROOT / "conformance/core/live-calibration-profile.v1.json",
                budget_targets_path=ROOT / "conformance/core/budget-targets.v1.json",
                worktree=tmp_path / "clean-worktree",
                runs_per_scenario_cohort=1,
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=kimi_code_harness.BudgetPolicy(
                    mode="subscription",
                    max_invocations=expected_runs,
                    max_billable_tokens=expected_runs * 20,
                ),
                runner=fake_runner,
                clean_worktree_checker=lambda _: {"clean": True, "dirtyEntryCount": 0},
            )

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(payload["host"], "kimi-code")
            self.assertEqual(payload["liveModelInvocations"], expected_runs)
            first_usage = payload["runs"][0]["usage"]
            self.assertGreater(first_usage["cumulativeContextBytes"], 0)
            self.assertEqual(first_usage["cumulativeContextBytesSource"], "harness-observed-prompt-and-jsonl-bytes")
            self.assertNotIn("--plan", calls[0])
            self.assertNotIn("--approval-mode", calls[0])
            self.assertNotIn("--safe-mode", calls[0])

    def test_live_host_receipt_blocks_when_kimi_mutates_worktree(self) -> None:
        checks = iter(
            [
                {"clean": True, "dirtyEntryCount": 0},
                {"clean": False, "dirtyEntryCount": 1},
            ]
        )

        def fake_runner(command: list[str]) -> kimi_code_harness.CommandResult:
            stdout = "\n".join(
                [
                    json.dumps({"type": "system", "session_id": "session-mutated", "model": "GLM-5.2"}),
                    json.dumps(
                        {
                            "type": "result",
                            "duration_ms": 100,
                            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                        }
                    ),
                ]
            )
            return kimi_code_harness.CommandResult(returncode=0, stdout=stdout, stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report = kimi_code_harness.run_live_host_receipt(
                kimi_bin="kimi",
                baseline_path=ROOT / "conformance/core/adapter-baseline.v1.json",
                worktree=tmp_path / "clean-worktree",
                allow_live=True,
                receipt_path=tmp_path / "receipts/kimi-code.json",
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=kimi_code_harness.BudgetPolicy(
                    mode="subscription",
                    max_invocations=13,
                    max_billable_tokens=1000,
                ),
                runner=fake_runner,
                clean_worktree_checker=lambda _: next(checks),
            )

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("BLOCKED_WORKTREE_MUTATED", {item["code"] for item in report["blockers"]})


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected object: {path}")
    return value


if __name__ == "__main__":
    unittest.main()

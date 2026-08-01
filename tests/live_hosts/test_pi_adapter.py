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
from tools.live_hosts import pi_harness  # noqa: E402


class PiHarnessTests(unittest.TestCase):
    def test_fixture_operations_cover_adapter_baseline_with_valid_envelopes(self) -> None:
        baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")

        operations = pi_harness.build_fixture_operations("pi", baseline)

        self.assertEqual({operation["name"] for operation in operations}, set(baseline["requiredOperations"]))
        for operation in operations:
            request = HostOperationRequest.from_json(operation["hostOperationRequest"])
            receipt = HostOperationReceipt.from_json(operation["hostOperationReceipt"])
            self.assertEqual(request.operation_id, receipt.operation_id)
            self.assertEqual(request.capability, operation["name"])

    def test_parser_uses_last_nonzero_nested_pi_usage(self) -> None:
        payload = "\n".join(
            [
                json.dumps({"type": "session", "id": "session-1"}),
                json.dumps({"type": "message_update", "message": {"usage": {"input": 0, "output": 0, "totalTokens": 0}}}),
                json.dumps(
                    {
                        "type": "message_end",
                        "message": {
                            "usage": {
                                "input": 12,
                                "output": 37,
                                "cacheRead": 384,
                                "cacheWrite": 0,
                                "reasoning": 30,
                                "totalTokens": 433,
                                "cost": {"total": 0},
                            }
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "agent_end",
                        "messages": [
                            {},
                            {
                                "usage": {
                                    "input": 14,
                                    "output": 39,
                                    "cacheRead": 390,
                                    "cacheWrite": 0,
                                    "totalTokens": 443,
                                    "cost": {"total": 0},
                                }
                            },
                        ],
                    }
                ),
            ]
        )

        usage = pi_harness.parse_pi_jsonl(payload, wall_seconds=1.234)

        self.assertEqual(usage.session_id, "session-1")
        self.assertEqual(usage.input_tokens, 14)
        self.assertEqual(usage.output_tokens, 39)
        self.assertEqual(usage.billable_tokens, 443)
        self.assertEqual(usage.cost_usd, None)
        self.assertEqual(usage.wall_seconds, 1.234)

    def test_containment_blocks_missing_explicit_provider_and_model(self) -> None:
        blockers = pi_harness._containment_blockers(
            pi_provider=None,
            pi_model=None,
            pi_thinking=None,
            model_selection=None,
        )

        self.assertIn("BLOCKED_MODEL_BINDING_UNDECLARED", {item["code"] for item in blockers})

    def test_operation_command_is_bounded_json_print(self) -> None:
        command = pi_harness._operation_command(
            "pi",
            "discover",
            pi_provider="provider",
            pi_model="model-id",
            pi_thinking="off",
            model_selection=None,
        )

        self.assertEqual(command[:3], ["pi", "--mode", "json"])
        self.assertIn("--no-session", command)
        self.assertIn("--no-tools", command)
        self.assertIn("--no-extensions", command)
        self.assertIn("--no-skills", command)
        self.assertIn("--no-context-files", command)
        self.assertIn("--no-approve", command)
        self.assertIn("--offline", command)
        self.assertEqual(command[command.index("--provider") + 1], "provider")
        self.assertEqual(command[command.index("--model") + 1], "model-id")
        self.assertEqual(command[command.index("--thinking") + 1], "off")
        self.assertIn("--print", command)

    def test_live_host_receipt_with_fake_runner_writes_validator_compatible_receipt(self) -> None:
        baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")
        calls: list[list[str]] = []

        def fake_runner(command: list[str]) -> pi_harness.CommandResult:
            calls.append(command)
            operation = command[-1].split("Operation: ", 1)[1].split(".", 1)[0]
            stdout = "\n".join(
                [
                    json.dumps({"type": "session", "id": f"session-{operation}"}),
                    json.dumps({"type": "message_end", "message": {"usage": {"input": 10, "output": 5, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 15}}}),
                ]
            )
            return pi_harness.CommandResult(returncode=0, stdout=stdout, stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt_dir = tmp_path / "receipts"
            receipt = receipt_dir / "pi.json"
            report = pi_harness.run_live_host_receipt(
                pi_bin="pi",
                baseline_path=ROOT / "conformance/core/adapter-baseline.v1.json",
                worktree=tmp_path / "clean-worktree",
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=pi_harness.BudgetPolicy(
                    mode="subscription",
                    max_invocations=len(baseline["requiredOperations"]),
                    max_billable_tokens=1000,
                ),
                pi_provider="provider",
                pi_model="model-id",
                runner=fake_runner,
                clean_worktree_checker=lambda _: {"clean": True, "dirtyEntryCount": 0},
            )

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(payload["schemaVersion"], pi_harness.LIVE_HOST_RECEIPT_SCHEMA)
            self.assertEqual(payload["host"], "pi")
            self.assertFalse(payload["syntheticReplayUsed"])
            self.assertTrue(payload["usageAttested"])
            self.assertEqual({item["name"] for item in payload["operations"]}, set(baseline["requiredOperations"]))
            self.assertEqual(len(calls), len(baseline["requiredOperations"]))

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
                    "pi",
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

    def test_live_calibration_uses_context_byte_proxy_when_usage_omits_it(self) -> None:
        profile = _load_json(ROOT / "conformance/core/live-calibration-profile.v1.json")
        expected_runs = len(profile["requiredScenarios"]) * len(profile["requiredCohorts"])

        def fake_runner(command: list[str]) -> pi_harness.CommandResult:
            stdout = "\n".join(
                [
                    json.dumps({"type": "session", "id": "session-proxy"}),
                    json.dumps({"type": "message_end", "message": {"usage": {"input": 10, "output": 5, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 15}}}),
                ]
            )
            return pi_harness.CommandResult(returncode=0, stdout=stdout, stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt = tmp_path / "calibration/pi.json"
            report = pi_harness.run_live_calibration(
                pi_bin="pi",
                profile_path=ROOT / "conformance/core/live-calibration-profile.v1.json",
                budget_targets_path=ROOT / "conformance/core/budget-targets.v1.json",
                worktree=tmp_path / "clean-worktree",
                runs_per_scenario_cohort=1,
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=pi_harness.BudgetPolicy(
                    mode="subscription",
                    max_invocations=expected_runs,
                    max_billable_tokens=expected_runs * 20,
                ),
                pi_provider="provider",
                pi_model="model-id",
                runner=fake_runner,
                clean_worktree_checker=lambda _: {"clean": True, "dirtyEntryCount": 0},
            )

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(payload["host"], "pi")
            self.assertEqual(payload["liveModelInvocations"], expected_runs)
            first_usage = payload["runs"][0]["usage"]
            self.assertGreater(first_usage["cumulativeContextBytes"], 0)
            self.assertEqual(first_usage["cumulativeContextBytesSource"], "harness-observed-prompt-and-json-output-bytes")


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected object: {path}")
    return value

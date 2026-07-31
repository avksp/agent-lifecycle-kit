from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.host_protocol import HostOperationReceipt, HostOperationRequest, build_acp_probe_receipt
from tools.live_hosts import grok_build_harness


ROOT = Path(__file__).resolve().parents[2]


class GrokBuildHarnessTests(unittest.TestCase):
    def test_fixture_operations_cover_adapter_baseline_with_valid_envelopes(self) -> None:
        baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")

        operations = grok_build_harness.build_fixture_operations("grok-build", baseline)

        self.assertEqual({operation["name"] for operation in operations}, set(baseline["requiredOperations"]))
        for operation in operations:
            request = HostOperationRequest.from_json(operation["hostOperationRequest"])
            receipt = HostOperationReceipt.from_json(operation["hostOperationReceipt"])
            self.assertEqual(request.operation_id, receipt.operation_id)
            self.assertEqual(request.capability, operation["name"])

    def test_parser_uses_grok_usage_json_without_double_counting_cost(self) -> None:
        payload = json.dumps(
            {
                "text": "{\"ok\":true}",
                "sessionId": "session-1",
                "usage": {
                    "input_tokens": 11637,
                    "cache_read_input_tokens": 128,
                    "output_tokens": 29,
                    "reasoning_tokens": 24,
                    "total_tokens": 11794,
                },
                "total_cost_usd": 0.0234864,
                "modelUsage": {
                    "grok-4.5": {
                        "inputTokens": 11637,
                        "outputTokens": 29,
                        "costUSD": 0.0234864,
                    }
                },
            },
            indent=2,
        )

        usage = grok_build_harness.parse_grok_build_json(payload, wall_seconds=6.068)

        self.assertEqual(usage.input_tokens, 11637)
        self.assertEqual(usage.output_tokens, 29)
        self.assertEqual(usage.billable_tokens, 11794)
        self.assertEqual(usage.cost_usd, 0.0234864)
        self.assertEqual(usage.session_id, "session-1")
        self.assertEqual(usage.event_count, 1)

    def test_containment_blocks_missing_explicit_model(self) -> None:
        blockers = grok_build_harness._containment_blockers(grok_model=None, model_selection=None)

        self.assertIn("BLOCKED_MODEL_BINDING_UNDECLARED", {item["code"] for item in blockers})

    def test_live_host_receipt_with_fake_runner_writes_validator_compatible_receipt(self) -> None:
        baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")
        calls: list[list[str]] = []

        def fake_runner(command: list[str]) -> grok_build_harness.CommandResult:
            calls.append(command)
            prompt = command[command.index("--single") + 1]
            operation = prompt.split("Operation: ", 1)[1].split(".", 1)[0]
            stdout = json.dumps(
                {
                    "text": json.dumps({"operation": operation, "status": "PASS"}),
                    "sessionId": f"session-{operation}",
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "total_tokens": 15,
                    },
                }
            )
            return grok_build_harness.CommandResult(returncode=0, stdout=stdout, stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt_dir = tmp_path / "receipts"
            receipt = receipt_dir / "grok-build.json"
            report = grok_build_harness.run_live_host_receipt(
                grok_bin="grok",
                baseline_path=ROOT / "conformance/core/adapter-baseline.v1.json",
                worktree=tmp_path / "clean-worktree",
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=grok_build_harness.BudgetPolicy(
                    mode="subscription",
                    max_invocations=len(baseline["requiredOperations"]),
                    max_billable_tokens=1000,
                ),
                grok_model="grok-4.5",
                runner=fake_runner,
                clean_worktree_checker=lambda _: {"clean": True, "dirtyEntryCount": 0},
            )

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(payload["schemaVersion"], grok_build_harness.LIVE_HOST_RECEIPT_SCHEMA)
            self.assertEqual(payload["host"], "grok-build")
            self.assertEqual({item["name"] for item in payload["operations"]}, set(baseline["requiredOperations"]))
            self.assertEqual(len(calls), len(baseline["requiredOperations"]))
            self.assertEqual(calls[0][0], "grok")
            self.assertIn("--single", calls[0])
            self.assertIn("--no-subagents", calls[0])
            self.assertIn("--no-memory", calls[0])
            self.assertIn("--disable-web-search", calls[0])
            self.assertEqual(calls[0][calls[0].index("--permission-mode") + 1], "plan")
            self.assertEqual(calls[0][calls[0].index("--tools") + 1], "")
            self.assertEqual(calls[0][calls[0].index("--model") + 1], "grok-4.5")

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
                    "grok-build",
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

    def test_live_calibration_uses_context_byte_proxy_when_grok_omits_it(self) -> None:
        profile = _load_json(ROOT / "conformance/core/live-calibration-profile.v1.json")
        expected_runs = len(profile["requiredScenarios"]) * len(profile["requiredCohorts"])

        def fake_runner(command: list[str]) -> grok_build_harness.CommandResult:
            stdout = json.dumps(
                {
                    "text": "{\"status\":\"PASS\"}",
                    "sessionId": "session-proxy",
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "total_tokens": 15,
                    },
                }
            )
            return grok_build_harness.CommandResult(returncode=0, stdout=stdout, stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt = tmp_path / "calibration/grok-build.json"
            report = grok_build_harness.run_live_calibration(
                grok_bin="grok",
                profile_path=ROOT / "conformance/core/live-calibration-profile.v1.json",
                budget_targets_path=ROOT / "conformance/core/budget-targets.v1.json",
                worktree=tmp_path / "clean-worktree",
                runs_per_scenario_cohort=1,
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=grok_build_harness.BudgetPolicy(
                    mode="subscription",
                    max_invocations=expected_runs,
                    max_billable_tokens=expected_runs * 20,
                ),
                grok_model="grok-4.5",
                runner=fake_runner,
                clean_worktree_checker=lambda _: {"clean": True, "dirtyEntryCount": 0},
            )

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(payload["host"], "grok-build")
            self.assertEqual(payload["liveModelInvocations"], expected_runs)
            first_usage = payload["runs"][0]["usage"]
            self.assertGreater(first_usage["cumulativeContextBytes"], 0)
            self.assertEqual(first_usage["cumulativeContextBytesSource"], "harness-observed-prompt-and-json-output-bytes")


def test_grok_build_probe_receipt_passes_without_live_model_call_when_probe_is_valid() -> None:
    descriptor = _load_json(ROOT / "adapters/grok-build/adapter.descriptor.json")
    receipt = build_acp_probe_receipt(
        descriptor["hostCapabilities"][0],
        executable_found=True,
        probe_passed=True,
        invocation_contract_valid=True,
    )

    assert receipt["schemaVersion"] == "agent-acp-probe-receipt.v1"
    assert receipt["status"] == "PASS"
    assert receipt["host"] == "grok-build"
    assert receipt["liveCallsStarted"] is False


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected object: {path}")
    return value

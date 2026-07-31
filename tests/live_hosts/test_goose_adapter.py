from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.host_protocol import build_acp_probe_receipt
from agent_lifecycle.host_protocol import HostOperationReceipt, HostOperationRequest
from tools.live_hosts import goose_harness


ROOT = Path(__file__).resolve().parents[2]


class GooseHarnessTests(unittest.TestCase):
    def test_fixture_operations_cover_adapter_baseline_with_valid_envelopes(self) -> None:
        baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")

        operations = goose_harness.build_fixture_operations("goose", baseline)

        self.assertEqual({operation["name"] for operation in operations}, set(baseline["requiredOperations"]))
        self.assertTrue(all(operation["syntheticReplayUsed"] is True for operation in operations))
        for operation in operations:
            request = HostOperationRequest.from_json(operation["hostOperationRequest"])
            receipt = HostOperationReceipt.from_json(operation["hostOperationReceipt"])
            self.assertEqual(request.operation_id, receipt.operation_id)
            self.assertEqual(request.capability, operation["name"])
            self.assertEqual(receipt.capability, operation["name"])

    def test_pretty_json_parser_uses_goose_metadata(self) -> None:
        payload = """
    __( O)>  new session
{
  "messages": [
    {"id": null, "role": "user", "content": []},
    {"id": "msg_1", "role": "assistant", "content": [{"type": "text", "text": "{\\"status\\":\\"PASS\\"}"}]}
  ],
  "metadata": {
    "total_tokens": 336,
    "input_tokens": 312,
    "output_tokens": 24,
    "cost_usd": 0.0005424,
    "status": "completed"
  }
}
"""

        usage = goose_harness.parse_goose_stream_json(payload, wall_seconds=3.207)

        self.assertEqual(usage.input_tokens, 312)
        self.assertEqual(usage.output_tokens, 24)
        self.assertEqual(usage.billable_tokens, 336)
        self.assertEqual(usage.cost_usd, 0.0005424)
        self.assertEqual(usage.wall_seconds, 3.207)
        self.assertEqual(usage.event_count, 1)

    def test_containment_blocks_default_profile_for_live_promotion(self) -> None:
        blockers = goose_harness._containment_blockers(
            goose_provider="zai",
            goose_model="glm-5.2",
            goose_no_profile=False,
            model_selection=None,
        )

        self.assertIn("BLOCKED_UNBOUNDED_HOST_PROFILE", {item["code"] for item in blockers})

    def test_live_host_receipt_with_fake_runner_writes_validator_compatible_receipt(self) -> None:
        baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")
        calls: list[list[str]] = []

        def fake_runner(command: list[str]) -> goose_harness.CommandResult:
            calls.append(command)
            prompt = command[command.index("--text") + 1]
            operation = prompt.split("Operation: ", 1)[1].split(".", 1)[0]
            stdout = json.dumps(
                {
                    "messages": [
                        {"id": None, "role": "user", "content": []},
                        {"id": f"msg-{operation}", "role": "assistant", "content": [{"type": "text", "text": "{\"status\":\"PASS\"}"}]},
                    ],
                    "metadata": {
                        "total_tokens": 15,
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "status": "completed",
                    },
                },
                indent=2,
            )
            return goose_harness.CommandResult(returncode=0, stdout=stdout, stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt_dir = tmp_path / "receipts"
            receipt = receipt_dir / "goose.json"
            report = goose_harness.run_live_host_receipt(
                goose_bin="goose",
                baseline_path=ROOT / "conformance/core/adapter-baseline.v1.json",
                worktree=tmp_path / "clean-worktree",
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=goose_harness.BudgetPolicy(
                    mode="subscription",
                    max_invocations=len(baseline["requiredOperations"]),
                    max_billable_tokens=1000,
                ),
                goose_provider="zai",
                goose_model="glm-5.2",
                goose_no_profile=True,
                runner=fake_runner,
                clean_worktree_checker=lambda _: {"clean": True, "dirtyEntryCount": 0},
            )

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(payload["schemaVersion"], goose_harness.LIVE_HOST_RECEIPT_SCHEMA)
            self.assertEqual(payload["host"], "goose")
            self.assertFalse(payload["syntheticReplayUsed"])
            self.assertTrue(payload["usageAttested"])
            self.assertEqual({item["name"] for item in payload["operations"]}, set(baseline["requiredOperations"]))
            self.assertEqual(len(calls), len(baseline["requiredOperations"]))
            self.assertEqual(calls[0][:2], ["goose", "run"])
            self.assertIn("--no-session", calls[0])
            self.assertIn("--no-profile", calls[0])
            self.assertEqual(calls[0][calls[0].index("--provider") + 1], "zai")
            self.assertEqual(calls[0][calls[0].index("--model") + 1], "glm-5.2")

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
                    "goose",
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

    def test_live_calibration_uses_context_byte_proxy_when_goose_usage_omits_it(self) -> None:
        profile = _load_json(ROOT / "conformance/core/live-calibration-profile.v1.json")
        expected_runs = len(profile["requiredScenarios"]) * len(profile["requiredCohorts"])

        def fake_runner(command: list[str]) -> goose_harness.CommandResult:
            stdout = json.dumps(
                {
                    "messages": [
                        {"id": None, "role": "user", "content": []},
                        {"id": "msg-proxy", "role": "assistant", "content": [{"type": "text", "text": "{\"status\":\"PASS\"}"}]},
                    ],
                    "metadata": {
                        "total_tokens": 15,
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "status": "completed",
                    },
                },
                indent=2,
            )
            return goose_harness.CommandResult(returncode=0, stdout=stdout, stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt = tmp_path / "calibration/goose.json"
            report = goose_harness.run_live_calibration(
                goose_bin="goose",
                profile_path=ROOT / "conformance/core/live-calibration-profile.v1.json",
                budget_targets_path=ROOT / "conformance/core/budget-targets.v1.json",
                worktree=tmp_path / "clean-worktree",
                runs_per_scenario_cohort=1,
                allow_live=True,
                receipt_path=receipt,
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=goose_harness.BudgetPolicy(
                    mode="subscription",
                    max_invocations=expected_runs,
                    max_billable_tokens=expected_runs * 20,
                ),
                goose_provider="zai",
                goose_model="glm-5.2",
                goose_no_profile=True,
                runner=fake_runner,
                clean_worktree_checker=lambda _: {"clean": True, "dirtyEntryCount": 0},
            )

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(payload["host"], "goose")
            self.assertEqual(payload["liveModelInvocations"], expected_runs)
            first_usage = payload["runs"][0]["usage"]
            self.assertGreater(first_usage["cumulativeContextBytes"], 0)
            self.assertEqual(first_usage["cumulativeContextBytesSource"], "harness-observed-prompt-and-json-output-bytes")

    def test_live_host_receipt_blocks_when_goose_mutates_worktree(self) -> None:
        baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")
        checks = iter(
            [
                {"clean": True, "dirtyEntryCount": 0},
                {"clean": False, "dirtyEntryCount": 1},
            ]
        )

        def fake_runner(command: list[str]) -> goose_harness.CommandResult:
            stdout = json.dumps(
                {
                    "messages": [{"id": "msg-mutated", "role": "assistant", "content": []}],
                    "metadata": {
                        "total_tokens": 15,
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "status": "completed",
                    },
                }
            )
            return goose_harness.CommandResult(returncode=0, stdout=stdout, stderr="", wall_seconds=0.1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report = goose_harness.run_live_host_receipt(
                goose_bin="goose",
                baseline_path=ROOT / "conformance/core/adapter-baseline.v1.json",
                worktree=tmp_path / "clean-worktree",
                allow_live=True,
                receipt_path=tmp_path / "receipts/goose.json",
                diagnostic_dir=tmp_path / "diagnostics",
                budget_policy=goose_harness.BudgetPolicy(
                    mode="subscription",
                    max_invocations=len(baseline["requiredOperations"]),
                    max_billable_tokens=1000,
                ),
                goose_provider="zai",
                goose_model="glm-5.2",
                goose_no_profile=True,
                runner=fake_runner,
                clean_worktree_checker=lambda _: next(checks),
            )

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("BLOCKED_WORKTREE_MUTATED", {item["code"] for item in report["blockers"]})


def test_goose_probe_receipt_passes_without_live_model_call_when_probe_is_valid() -> None:
    descriptor = _load_json(ROOT / "adapters/goose/adapter.descriptor.json")
    receipt = build_acp_probe_receipt(
        descriptor["hostCapabilities"][0],
        executable_found=True,
        probe_passed=True,
        invocation_contract_valid=True,
    )

    assert receipt["schemaVersion"] == "agent-acp-probe-receipt.v1"
    assert receipt["status"] == "PASS"
    assert receipt["host"] == "goose"
    assert receipt["liveCallsStarted"] is False


def test_goose_probe_receipt_fails_closed_on_missing_executable() -> None:
    descriptor = _load_json(ROOT / "adapters/goose/adapter.descriptor.json")
    receipt = build_acp_probe_receipt(
        descriptor["hostCapabilities"][0],
        executable_found=False,
        probe_passed=True,
        invocation_contract_valid=True,
    )

    assert receipt["status"] == "FAIL"
    assert "acp-executable-missing" in {item["code"] for item in receipt["blockers"]}


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected object: {path}")
    return value

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.live_hosts import (  # noqa: E402
    claude_code_harness,
    codex_harness,
    cursor_harness,
    gemini_cli_harness,
    goose_harness,
    grok_build_harness,
    hermes_harness,
    kimi_code_harness,
    opencode_harness,
    openinterpreter_harness,
    qwen_code_harness,
)
from tools.live_hosts.common import (  # noqa: E402
    BudgetPolicy,
    BudgetTracker,
    HarnessError,
    dispatch_with_host_env,
    load_host_env_file_from_args,
)


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Usage:
    billable_tokens: int
    wall_seconds: float
    cost_usd: float | None = None


class BudgetPolicyTests(unittest.TestCase):
    def test_metered_mode_requires_usd_cap(self) -> None:
        with self.assertRaises(HarnessError) as caught:
            BudgetPolicy(mode="metered").require_authorized(allow_live=True, required_invocations=1)

        self.assertEqual(caught.exception.code, "BLOCKED_BUDGET_EXHAUSTED")
        BudgetPolicy(mode="metered", budget_cap_usd=0.01).require_authorized(allow_live=True, required_invocations=1)

    def test_subscription_and_local_modes_require_resource_caps(self) -> None:
        with self.assertRaises(HarnessError):
            BudgetPolicy(mode="subscription", max_invocations=2).require_authorized(allow_live=True, required_invocations=2)

        BudgetPolicy(mode="subscription", max_invocations=2, max_billable_tokens=100).require_authorized(
            allow_live=True,
            required_invocations=2,
        )
        BudgetPolicy(mode="local", max_invocations=2, max_wall_seconds=10).require_authorized(
            allow_live=True,
            required_invocations=2,
        )

    def test_budget_tracker_enforces_cost_token_and_time_caps_after_recording(self) -> None:
        with self.assertRaises(HarnessError):
            BudgetTracker().record(Usage(billable_tokens=10, wall_seconds=1, cost_usd=2), BudgetPolicy(mode="metered", budget_cap_usd=1))

        with self.assertRaises(HarnessError):
            BudgetTracker().record(
                Usage(billable_tokens=101, wall_seconds=1),
                BudgetPolicy(mode="subscription", max_invocations=1, max_billable_tokens=100),
            )

        with self.assertRaises(HarnessError):
            BudgetTracker().record(
                Usage(billable_tokens=1, wall_seconds=11),
                BudgetPolicy(mode="local", max_invocations=1, max_wall_seconds=10),
            )

    def test_usage_attestation_policy_distinguishes_cost_required_modes(self) -> None:
        self.assertEqual(
            BudgetPolicy(mode="metered", budget_cap_usd=1).usage_attestation_policy("host"),
            "host-usage-and-cost-required-per-invocation",
        )
        self.assertEqual(
            BudgetPolicy(mode="local", max_invocations=1, max_wall_seconds=1).usage_attestation_policy("host"),
            "host-usage-required-per-invocation-local-resource-budget",
        )


class HostEnvFileTests(unittest.TestCase):
    def test_host_env_file_requires_explicit_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "host.env"
            env_file.write_text("ALK_PROVIDER_KEY=secret-value\n", encoding="utf-8")

            with self.assertRaises(HarnessError) as caught:
                load_host_env_file_from_args(str(env_file), [])

            self.assertEqual(caught.exception.code, "missing-host-env-allow")

    def test_host_env_file_redacts_values_and_ignores_unallowed_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "host.env"
            env_file.write_text(
                "export ALK_PROVIDER_KEY='secret-value'\n"
                "ALK_OTHER_PROVIDER_KEY=other-secret\n",
                encoding="utf-8",
            )

            host_env = load_host_env_file_from_args(str(env_file), ["ALK_PROVIDER_KEY"])
            redacted = host_env.redacted_json()

            self.assertEqual(host_env.values, {"ALK_PROVIDER_KEY": "secret-value"})
            self.assertEqual(redacted["loadedVariables"], ["ALK_PROVIDER_KEY"])
            self.assertEqual(redacted["ignoredVariableCount"], 1)
            self.assertTrue(redacted["valuesRedacted"])
            self.assertNotIn("secret-value", str(redacted))
            self.assertNotIn("ALK_OTHER_PROVIDER_KEY", str(redacted))
            self.assertNotIn(env_file.as_posix(), str(redacted))

    def test_dispatch_with_host_env_restores_process_environment(self) -> None:
        original = os.environ.get("ALK_TEST_HOST_KEY")
        os.environ.pop("ALK_TEST_HOST_KEY", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                env_file = Path(tmp) / "host.env"
                env_file.write_text("ALK_TEST_HOST_KEY=secret-value\n", encoding="utf-8")
                args = argparse.Namespace(host_env_file=str(env_file), host_env_allow=["ALK_TEST_HOST_KEY"])

                report = dispatch_with_host_env(
                    args,
                    lambda _: {
                        "schemaVersion": "test-report.v1",
                        "status": "PASS",
                        "seen": os.environ.get("ALK_TEST_HOST_KEY"),
                    },
                )

                self.assertEqual(report["seen"], "secret-value")
                self.assertIsNone(os.environ.get("ALK_TEST_HOST_KEY"))
                self.assertEqual(report["hostEnv"]["loadedVariables"], ["ALK_TEST_HOST_KEY"])
                self.assertNotIn("secret-value", str(report["hostEnv"]))
        finally:
            if original is not None:
                os.environ["ALK_TEST_HOST_KEY"] = original

    def test_all_live_harness_fixture_modes_accept_redacted_host_env_file(self) -> None:
        modules = [
            claude_code_harness,
            codex_harness,
            cursor_harness,
            gemini_cli_harness,
            goose_harness,
            grok_build_harness,
            hermes_harness,
            kimi_code_harness,
            opencode_harness,
            openinterpreter_harness,
            qwen_code_harness,
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / "host.env"
            env_value = "alk-fixture-" + "redaction-marker"
            env_file.write_text(f"ALK_TEST_HOST_KEY={env_value}\n", encoding="utf-8")
            reports: list[Path] = []
            for module in modules:
                with self.subTest(module=module.__name__):
                    report = tmp_path / f"{module.HOST}.json"
                    exit_code = module.main(
                        [
                            "--mode",
                            "fixture-check",
                            "--baseline",
                            "conformance/core/adapter-baseline.v1.json",
                            "--host-env-file",
                            str(env_file),
                            "--host-env-allow",
                            "ALK_TEST_HOST_KEY",
                            "--report",
                            str(report),
                        ]
                    )
                    reports.append(report)
                    payload = report.read_text(encoding="utf-8")
                    parsed = json.loads(payload)
                    self.assertEqual(exit_code, 0)
                    self.assertEqual(parsed["status"], "PASS")
                    self.assertEqual(parsed["hostEnv"]["loadedVariables"], ["ALK_TEST_HOST_KEY"])

            evidence = tmp_path / "host-env-hygiene.json"
            command = [
                sys.executable,
                "tools/release/validate_host_env_hygiene.py",
                "--host-env-file",
                str(env_file),
                "--host-env-allow",
                "ALK_TEST_HOST_KEY",
                "--require-host-env-report",
                "--evidence",
                str(evidence),
            ]
            for report in reports:
                command.extend(["--report", str(report)])
            validation = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(validation.returncode, 0, validation.stderr)
            self.assertNotIn(env_value, evidence.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

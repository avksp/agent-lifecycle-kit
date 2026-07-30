from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402


class CliDiagnosticsCommandTests(unittest.TestCase):
    def test_diagnose_cli_outputs_redacted_readiness_report(self) -> None:
        code, payload = _run_cli(
            [
                "diagnose",
                "--adapter",
                str(ROOT / "adapters/codex/adapter.descriptor.json"),
                "--no-install-plans",
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-readiness-report.v1")
        self.assertIn(payload["status"], {"PASS", "WARN"})
        self.assertFalse(payload["productionPromotionClaimed"])
        self.assertFalse(payload["maturityChangesClaimed"])
        self.assertEqual(payload["installPlans"], [])
        self.assertNotIn(str(ROOT), json.dumps(payload, sort_keys=True))

    def test_adapter_install_plan_is_dry_run_for_plugin_and_host_local_adapters(self) -> None:
        cases = [
            ("adapters/codex/adapter.descriptor.json", "codex", "VERIFIED", "codex"),
            ("adapters/claude/adapter.descriptor.json", "claude-code", "VERIFIED", "adapters/claude/adapter.descriptor.json"),
            ("adapters/gemini-cli/adapter.descriptor.json", "gemini-cli", "EXPERIMENTAL", "gemini"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            sentinel = Path(tmp) / "sentinel"
            sentinel.write_text("unchanged", encoding="utf-8")
            for descriptor, host, maturity, expected_command_fragment in cases:
                with self.subTest(host=host):
                    code, payload = _run_cli(["adapter", "install-plan", "--descriptor", str(ROOT / descriptor)])

                    self.assertEqual(code, 0)
                    self.assertEqual(payload["schemaVersion"], "agent-adapter-install-plan.v1")
                    self.assertEqual(payload["status"], "DRY_RUN")
                    self.assertEqual(payload["host"], host)
                    self.assertEqual(payload["maturity"], maturity)
                    self.assertFalse(payload["writesStarted"])
                    self.assertFalse(payload["productionPromotionClaimed"])
                    self.assertFalse(payload["maturityChangeClaimed"])
                    rendered_commands = json.dumps(payload["commands"], sort_keys=True)
                    self.assertIn(expected_command_fragment, rendered_commands)
                    self.assertNotIn(str(ROOT), json.dumps(payload, sort_keys=True))
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")


if __name__ == "__main__":
    unittest.main()

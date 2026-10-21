from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.cli.adapter import dispatch_adapter
from agent_lifecycle.cli.parsers import build_parser


class AgentPluginQualificationCommandTests(unittest.TestCase):
    def test_provider_preflight_cli_error_is_bounded_and_private(self):
        from tests.cli.helpers import _run_cli

        code, payload = _run_cli([
            "adapter", "provider-preflight", "--profile",
            "/private/nonexistent/sk-fixture-secret.json",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "UNAVAILABLE")
        self.assertEqual(payload["modelCalls"], 0)
        self.assertNotIn("sk-fixture", str(payload))
        self.assertNotIn("/private", str(payload))

    def test_plugin_qualify_command_is_registered(self) -> None:
        args = build_parser().parse_args(
            [
                "adapter",
                "plugin-qualify",
                "--adapter",
                "codex",
                "--profile",
                "profile.json",
                "--package",
                "package",
            ]
        )
        self.assertEqual(args.adapter_command, "plugin-qualify")
        self.assertEqual(args.adapter, "codex")

    def test_command_delegates_to_explicit_probe(self) -> None:
        args = build_parser().parse_args(
            [
                "adapter",
                "plugin-qualify",
                "--adapter",
                "codex",
                "--profile",
                str(Path("adapters/codex/agent_plugin_profile.json")),
                "--package",
                "package",
            ]
        )
        receipt = {"schemaVersion": "agent-plugin-qualification-receipt.v1", "status": "UNAVAILABLE"}
        with patch("agent_lifecycle.cli.adapter.read_json_object", return_value={"adapterId": "codex"}), patch(
            "agent_lifecycle.cli.adapter.run_agent_plugin_qualification_probe", return_value=receipt
        ) as probe:
            payload = dispatch_adapter(args)
        self.assertEqual(payload, receipt)
        probe.assert_called_once()


if __name__ == "__main__":
    unittest.main()

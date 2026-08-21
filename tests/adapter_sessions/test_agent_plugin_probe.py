from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from agent_lifecycle.adapter_sessions.agent_plugin_probe import build_agent_plugin_probe_runner


class AgentPluginProbeCompositionTests(unittest.TestCase):
    def test_probe_runner_uses_bounded_process_adapter(self) -> None:
        profile = {
            "adapterId": "codex",
            "environment": {"allow": ["PATH"], "allowPatterns": []},
            "qualification": {"timeoutSeconds": 4, "maxOutputBytes": 2048},
        }
        with mock.patch("agent_lifecycle.adapter_sessions.agent_plugin_probe.run_process", return_value={"status": "PASS"}) as run:
            runner = build_agent_plugin_probe_runner(profile, Path("/tmp/project"))
            result = runner(["codex", "--version"], 1)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(run.call_args.args[0], ["codex", "--version"])
        self.assertEqual(run.call_args.kwargs["timeout_seconds"], 4.0)
        self.assertEqual(run.call_args.kwargs["max_output_bytes"], 2048)


if __name__ == "__main__":
    unittest.main()

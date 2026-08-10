from __future__ import annotations

import contextlib
import json
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.cli import main


class StartPlanningLaunchCliTests(unittest.TestCase):
    def test_launch_and_profile_are_forwarded_without_changing_stdout_contract(self) -> None:
        expected = {
            "schemaVersion": "agent-lifecycle-start-receipt.v1",
            "status": "REVIEW_REQUIRED",
            "receiptDigest": "a" * 64,
        }
        with patch("agent_lifecycle.cli.start.start_lifecycle", return_value=expected) as start:
            stdout = StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "start",
                        "--adapter",
                        "codex",
                        "--text",
                        "prepare a plan",
                        "--mode",
                        "plan",
                        "--launch",
                        "--host-launch-profile",
                        ".alk/host-launch/codex.json",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), expected)
        self.assertTrue(start.call_args.kwargs["launch"])
        self.assertEqual(start.call_args.kwargs["host_launch_profile_path"], Path(".alk/host-launch/codex.json"))

    def test_launch_without_explicit_profile_uses_domain_default(self) -> None:
        expected = {"schemaVersion": "agent-lifecycle-start-receipt.v1", "status": "BLOCKED"}
        with patch("agent_lifecycle.cli.start.start_lifecycle", return_value=expected) as start:
            with contextlib.redirect_stdout(StringIO()):
                code = main(["start", "--adapter", "codex", "--file", "task.md", "--launch"])

        self.assertEqual(code, 0)
        self.assertTrue(start.call_args.kwargs["launch"])
        self.assertIsNone(start.call_args.kwargs["host_launch_profile_path"])


if __name__ == "__main__":
    unittest.main()

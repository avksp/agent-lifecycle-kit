from __future__ import annotations

import contextlib
from io import StringIO
import unittest

from agent_lifecycle.cli.parsers import build_parser


class RemovedRunnerParserTests(unittest.TestCase):
    def test_runner_group_is_not_registered(self) -> None:
        parser = build_parser()
        with contextlib.redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
            parser.parse_args(["runner", "start"])
        self.assertEqual(raised.exception.code, 2)

    def test_workflow_run_remains_registered(self) -> None:
        parser = build_parser()
        parsed = parser.parse_args(
            [
                "workflow",
                "run",
                "--state",
                "state.json",
                "--manifest",
                "plan.manifest.json",
                "--operation-id",
                "run-1",
                "--expected-revision",
                "1",
                "--source-revision",
                "source",
            ]
        )
        self.assertEqual(parsed.command, "workflow")
        self.assertEqual(parsed.workflow_command, "run")


if __name__ == "__main__":
    unittest.main()

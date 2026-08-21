from __future__ import annotations

import unittest

from agent_lifecycle.cli.parsers import build_parser


class ParserCompatibilityTests(unittest.TestCase):
    def test_split_parser_modules_preserve_public_command_shapes(self) -> None:
        parser = build_parser()
        for argv, command in (
            (["version"], "version"),
            (["report", "status-view"], "report"),
            (["workflow", "status", "--state", "state.json"], "workflow"),
            (["plan", "check", "--manifest", "plan.json"], "plan"),
            (["task", "compile", "--manifest", "plan.json"], "task"),
        ):
            parsed = parser.parse_args(argv)
            self.assertEqual(parsed.command, command)


if __name__ == "__main__":
    unittest.main()

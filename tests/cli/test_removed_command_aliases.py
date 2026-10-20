from __future__ import annotations

import unittest

from agent_lifecycle.cli import lifecycle_parsers
from agent_lifecycle.cli.command_registry import COMMAND_DISPATCH
from agent_lifecycle.cli.parsers import build_parser


class RemovedDuplicateParserTests(unittest.TestCase):
    def test_only_uncalled_private_duplicates_are_removed(self) -> None:
        removed = (
            "diagnose",
            "diagnostics",
            "contract",
            "evidence",
            "import",
            "quality",
            "audit",
            "context",
            "thread",
            "goal",
            "model",
            "tier",
            "specification",
            "plan",
            "task",
        )
        for name in removed:
            with self.subTest(name=name):
                self.assertFalse(hasattr(lifecycle_parsers, f"_add_{name}_parser"))
        for live in ("start", "host_launch", "workflow", "schema", "review_mesh"):
            self.assertTrue(callable(getattr(lifecycle_parsers, f"_add_{live}_parser")))

    def test_live_public_command_routes_still_parse_and_dispatch(self) -> None:
        parser = build_parser()
        for argv in (
            ["diagnose"],
            ["diagnostics", "bundle"],
            ["schema", "list"],
            ["plan", "check", "--manifest", "plan.json"],
            ["task", "compile", "--manifest", "plan.json"],
        ):
            with self.subTest(argv=argv):
                parsed = parser.parse_args(argv)
                self.assertIn(parsed.command, COMMAND_DISPATCH)

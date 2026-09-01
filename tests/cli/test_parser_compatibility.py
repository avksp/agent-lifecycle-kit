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
            (
                [
                    "audit",
                    "delta",
                    "--manifest",
                    "plan.json",
                    "--lock",
                    "lock.json",
                    "--state",
                    "state.json",
                    "--task",
                    "WS-01",
                    "--dependency-report",
                    "dependencies.json",
                    "--validation-selection",
                    "selection.json",
                ],
                "audit",
            ),
        ):
            parsed = parser.parse_args(argv)
            self.assertEqual(parsed.command, command)

    def test_delta_parser_preserves_repeated_finding_inputs(self) -> None:
        parsed = build_parser().parse_args(
            [
                "audit",
                "delta",
                "--manifest",
                "plan.json",
                "--lock",
                "lock.json",
                "--state",
                "state.json",
                "--task",
                "WS-01",
                "--dependency-report",
                "dependencies.json",
                "--validation-selection",
                "selection.json",
                "--finding-check-binding",
                "binding-1.json",
                "--finding-check-binding",
                "binding-2.json",
                "--finding-check-evidence",
                "evidence.json",
            ]
        )
        self.assertEqual(parsed.audit_command, "delta")
        self.assertEqual(parsed.finding_check_binding, ["binding-1.json", "binding-2.json"])
        self.assertEqual(parsed.finding_check_evidence, ["evidence.json"])


if __name__ == "__main__":
    unittest.main()

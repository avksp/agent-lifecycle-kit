"""New remedy flags extend existing commands without adding an execution route."""

from __future__ import annotations

import unittest

from agent_lifecycle.cli.parsers import build_parser


class ReviewMeshRemedyCliTests(unittest.TestCase):
    def test_existing_commands_expose_exact_opt_in_arguments(self):
        parser = build_parser(["review-mesh"])
        for command, arguments in [
            (
                "import-result",
                ["--profile", "profile.json", "--assignment", "assignment.json", "--reviewer-output", "raw.json"],
            ),
            (
                "synthesize",
                ["--profile", "profile.json", "--result", "result.json", "--remedy-decisions", "decisions.json"],
            ),
            ("quorum", ["--profile", "profile.json", "--synthesis", "synthesis.json", "--min-reviewers", "1"]),
        ]:
            parsed = parser.parse_args(["review-mesh", command, *arguments, "--remedy-evidence", "evidence.json"])
            self.assertEqual(parsed.remedy_evidence, "evidence.json")

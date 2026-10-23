"""The repository's existing gates and published examples share one contract."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import shlex
import unittest
from pathlib import Path

from agent_lifecycle.cli.parsers import build_parser
from agent_lifecycle.quality.architecture_policy import load_architecture_limits

ROOT = Path(__file__).resolve().parents[2]


class ArchitecturePolicyIntegrationTests(unittest.TestCase):
    def test_canonical_limits_and_ci_selection_cannot_drift(self) -> None:
        policy = load_architecture_limits(ROOT / "policy/architecture-limits.json")
        self.assertEqual({
            "targetFileLines": 800, "hardFileLines": 1200,
            "targetFunctionLines": 80, "hardFunctionLines": 150,
            "hardSymbols": 80, "cliTargetFunctionLines": 80, "cliHardFunctionLines": 150,
        }, policy["limits"])
        ci = (ROOT / ".github/workflows/ci.yml").read_text()
        complexity = ci.split("- name: Validate architecture complexity\n", 1)[1].split("\n      - name:", 1)[0]
        self.assertIn("--policy policy/architecture-limits.json", complexity)
        self.assertIn("validate_architecture_complexity.py", complexity)
        for flag in ("--target-file-lines", "--hard-file-lines", "--target-function-lines", "--hard-function-lines", "--hard-symbols"):
            self.assertNotIn(flag, complexity)
        self.assertIn("--policy policy/architecture-dependencies.json", ci)
        self.assertIn("--require-acyclic-modules", ci)
        self.assertIn("--require-acyclic-packages", ci)
        self.assertIn('python: ["3.11", "3.12", "3.13", "3.14"]', ci)
        self.assertIn("os: [ubuntu-latest, macos-latest, windows-latest]", ci)

    def test_empty_mypy_baseline_keeps_normal_source_wide_configuration(self) -> None:
        import tomllib

        policy = json.loads((ROOT / "policy/python-quality.json").read_text())
        self.assertEqual([], policy["mypy"]["baseline"])
        self.assertFalse((ROOT / "src/agent_lifecycle/runner/attempt_snapshots.py").exists())
        config = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["mypy"]
        self.assertEqual(["src/agent_lifecycle"], config["files"])
        self.assertNotIn("exclude", config)
        self.assertNotIn("follow_imports", config)
        self.assertNotIn("ignore_errors", config)
        self.assertGreaterEqual(policy["coverage"]["minimumStatementLinePercent"], 76.0)

    def test_cookbook_review_apply_examples_parse_and_invalid_result_refuses(self) -> None:
        parser = build_parser()
        for path in ("docs/guides/lifecycle-cookbook.md", "docs/ru/guides/lifecycle-cookbook.md"):
            document = (ROOT / path).read_text()
            blocks = [block for block in re.findall(r"```bash\n(.*?)```", document, re.S)
                      if block.startswith("agent-lifecycle workflow task-review-apply")]
            self.assertEqual(1, len(blocks))
            argv = shlex.split(blocks[0].replace("\\\n", " "))[1:]
            with self.subTest(path=path):
                parsed = parser.parse_args(argv)
                self.assertEqual("apply independent review", parsed.reason)
                self.assertNotIn("--result", argv)
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                    parser.parse_args([*argv, "--result", "unattached-result.json"])
                self.assertEqual(2, caught.exception.code)
        with contextlib.redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit) as caught:
            parser.parse_args(["workflow", "task-review-apply", "--help"])
        self.assertEqual(0, caught.exception.code)
        self.assertNotIn("--result", output.getvalue())
        self.assertIn("--reason", output.getvalue())

    def test_changed_skill_references_keep_exact_sha_and_bounded_feasibility(self) -> None:
        for name in ("agent-first-planning", "audit-agent-plan", "audit-plan-implementation"):
            root = ROOT / "skills" / name
            contract = (root / "references/lifecycle-contract.md").read_bytes()
            entry = (root / "SKILL.md").read_text()
            with self.subTest(skill=name):
                self.assertIn(f"Full contract SHA256: `{hashlib.sha256(contract).hexdigest()}`", entry)
                text = contract.decode()
                for required in ("1\u20133 actual entrypoints", "lower capability/authority boundary", "negative case",
                                 "exact write owners", "UNIT_ONLY", "before freeze", "no extra audit stage",
                                 "declared-ledger-route-unsupported", "test_unsupported_package_and_rebound_opening_refuse"):
                    self.assertIn(required, text)
                self.assertIn("user's scope decision", text)


if __name__ == "__main__":
    unittest.main()

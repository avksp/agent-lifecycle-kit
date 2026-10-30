"""The repository's existing gates and published examples share one contract."""

from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import re
import shlex
import unittest
from pathlib import Path

from agent_lifecycle.cli.parsers import build_parser
from agent_lifecycle.quality.architecture_policy import (
    branch_findings,
    function_branch_records,
    load_architecture_limits,
    private_import_findings,
)

ROOT = Path(__file__).resolve().parents[2]


class ArchitecturePolicyIntegrationTests(unittest.TestCase):
    def test_named_private_edges_cannot_return(self) -> None:
        forbidden = {
            "workflow/closing_policy.py": {
                ("agent_lifecycle.contracts.workflow_state_schemas", "_closing_instant"),
            },
            "adapter_sessions/limited_native_evidence.py": {
                ("agent_lifecycle.accounting.host_bridge", "_json"),
            },
            "adapter_sessions/attempt_authority.py": {
                ("agent_lifecycle.accounting.declared_ledger", "_sync_directory"),
                ("agent_lifecycle.accounting.declared_ledger_records", "_require"),
            },
            "accounting/closing_resource_recovery.py": {
                ("agent_lifecycle.contracts.workflow_state_schemas", "_closing_instant"),
            },
        }
        for name, edges in forbidden.items():
            tree = ast.parse((ROOT / "src/agent_lifecycle" / name).read_text())
            imports = {
                (node.module, alias.name)
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names
            }
            with self.subTest(path=name):
                self.assertFalse(imports & edges)

    def test_removed_private_debt_cannot_authorize_reintroduction(self) -> None:
        policy = json.loads((ROOT / "policy/architecture-dependencies.json").read_text())
        for module, symbol, consumer in (
            (
                "agent_lifecycle.contracts.workflow_state_schemas",
                "_closing_instant",
                "agent_lifecycle.workflow.closing_policy",
            ),
            (
                "agent_lifecycle.accounting.host_bridge",
                "_json",
                "agent_lifecycle.adapter_sessions.limited_native_evidence",
            ),
            (
                "agent_lifecycle.contracts.workflow_state_schemas",
                "_closing_instant",
                "agent_lifecycle.accounting.closing_resource_recovery",
            ),
            (
                "agent_lifecycle.accounting.declared_ledger",
                "_sync_directory",
                "agent_lifecycle.adapter_sessions.attempt_authority",
            ),
            (
                "agent_lifecycle.accounting.declared_ledger_records",
                "_require",
                "agent_lifecycle.adapter_sessions.attempt_authority",
            ),
        ):
            record = {
                "module": module,
                "symbol": symbol,
                "alias": symbol,
                "consumer": consumer,
                "explicitReexport": False,
            }
            with self.subTest(module=module, symbol=symbol):
                findings = private_import_findings([record], policy)["blockers"]
                self.assertEqual(len(findings), 1)
                self.assertEqual(findings[0]["code"], "architecture-private-import-unapproved")

    def test_reduced_functions_and_helpers_cannot_restore_branch_debt(self) -> None:
        policy = load_architecture_limits(ROOT / "policy/architecture-limits.json")
        for path, entrypoint in (
            ("contracts/preparation_policy.py", "evaluate_preparation_policy"),
            ("contracts/agent_plugin_qualification_schemas.py", "validate_qualification_profile"),
        ):
            tree = ast.parse((ROOT / "src/agent_lifecycle" / path).read_text())
            records = function_branch_records(tree, path)
            with self.subTest(path=path):
                self.assertTrue(records)
                self.assertTrue(all(row["score"] <= 20 for row in records), records)
                self.assertFalse(any(row["path"] == path for row in policy["branchBaseline"]))
                self.assertFalse(any(row["path"] == path for row in policy["branchExceptions"]))
                excess = {"path": path, "name": entrypoint, "score": 21, "fingerprint": "0" * 64}
                self.assertEqual(len(branch_findings([excess], policy)), 1)

    def test_final_typed_flow_reduces_existing_branch_debt(self) -> None:
        path = "workflow/implementation_audit_gate.py"
        records = function_branch_records(ast.parse((ROOT / "src/agent_lifecycle" / path).read_text()), path)
        selected = [row for row in records if row["name"] == "validate_final_task_evidence_reports"]
        helpers = [row for row in records if row["name"] == "_accepted_final_typed_tasks"]
        self.assertEqual(len(selected), 1)
        self.assertLessEqual(selected[0]["score"], 48)
        self.assertEqual(len(helpers), 1)
        self.assertLessEqual(helpers[0]["score"], 20)
        policy = load_architecture_limits(ROOT / "policy/architecture-limits.json")
        self.assertEqual(branch_findings(selected + helpers, policy), [])

    def test_canonical_limits_and_ci_selection_cannot_drift(self) -> None:
        policy = load_architecture_limits(ROOT / "policy/architecture-limits.json")
        self.assertEqual(
            {
                "targetFileLines": 800,
                "hardFileLines": 1200,
                "targetFunctionLines": 80,
                "hardFunctionLines": 150,
                "hardSymbols": 80,
                "cliTargetFunctionLines": 80,
                "cliHardFunctionLines": 150,
            },
            policy["limits"],
        )
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        complexity = ci.split("- name: Validate architecture complexity\n", 1)[1].split("\n      - name:", 1)[0]
        self.assertIn("--policy policy/architecture-limits.json", complexity)
        self.assertIn("validate_architecture_complexity.py", complexity)
        for flag in (
            "--target-file-lines",
            "--hard-file-lines",
            "--target-function-lines",
            "--hard-function-lines",
            "--hard-symbols",
        ):
            self.assertNotIn(flag, complexity)
        self.assertIn("--policy policy/architecture-dependencies.json", ci)
        self.assertIn("--require-acyclic-modules", ci)
        self.assertIn("--require-acyclic-packages", ci)
        versions = re.search(r"python: \[(.*?)\]", ci)
        self.assertIsNotNone(versions)
        supported = json.loads("[" + versions.group(1) + "]")
        for version in ("3.11", "3.12", "3.13", "3.14"):
            self.assertIn(version, supported)
        self.assertIn("os: [ubuntu-latest, macos-latest, windows-latest]", ci)

    def test_empty_mypy_baseline_keeps_normal_source_wide_configuration(self) -> None:
        import tomllib

        policy = json.loads((ROOT / "policy/python-quality.json").read_text(encoding="utf-8"))
        self.assertEqual([], policy["mypy"]["baseline"])
        self.assertFalse((ROOT / "src/agent_lifecycle/runner/attempt_snapshots.py").exists())
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["mypy"]
        self.assertEqual(["src/agent_lifecycle"], config["files"])
        self.assertNotIn("exclude", config)
        self.assertNotIn("follow_imports", config)
        self.assertNotIn("ignore_errors", config)
        self.assertIs(config["check_untyped_defs"], True)
        self.assertGreaterEqual(policy["coverage"]["minimumCombinedPercent"], 76.0)
        self.assertGreaterEqual(policy["coverage"]["minimumStatementLinePercent"], 76.0)
        for name in ("docs/architecture/system-architecture.md", "docs/ru/architecture/system-architecture.md"):
            document = (ROOT / name).read_text(encoding="utf-8")
            for term in (
                "check_untyped_defs = true",
                "minimumCombinedPercent = 76",
                "minimumStatementLinePercent = 76",
            ):
                self.assertIn(term, document)

    def test_cookbook_review_apply_examples_parse_and_invalid_result_refuses(self) -> None:
        parser = build_parser()
        for path in ("docs/guides/lifecycle-cookbook.md", "docs/ru/guides/lifecycle-cookbook.md"):
            document = (ROOT / path).read_text(encoding="utf-8")
            blocks = [
                block
                for block in re.findall(r"```bash\n(.*?)```", document, re.S)
                if block.startswith("agent-lifecycle workflow task-review-apply")
            ]
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
            entry = (root / "SKILL.md").read_text(encoding="utf-8")
            with self.subTest(skill=name):
                self.assertIn(f"Full contract SHA256: `{hashlib.sha256(contract).hexdigest()}`", entry)
                text = contract.decode()
                for required in (
                    "1\u20133 actual entrypoints",
                    "lower capability/authority boundary",
                    "negative case",
                    "exact write owners",
                    "UNIT_ONLY",
                    "before freeze",
                    "no extra audit stage",
                    "declared-ledger-route-unsupported",
                    "test_unsupported_package_and_rebound_opening_refuse",
                ):
                    self.assertIn(required, text)
                self.assertIn("user's scope decision", text)


if __name__ == "__main__":
    unittest.main()

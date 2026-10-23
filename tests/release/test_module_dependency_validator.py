from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ModuleDependencyValidatorTests(unittest.TestCase):
    def test_unresolved_dynamic_import_writes_failure_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sample"
            root.mkdir()
            (root / "__init__.py").write_text("", encoding="utf-8")
            (root / "a.py").write_text("import importlib\nimportlib.import_module(input())\n", encoding="utf-8")
            evidence = Path(tmp) / "failure.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_module_dependencies.py"),
                    "--package-root",
                    str(root),
                    "--repository-root",
                    tmp,
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "FAIL")
            self.assertFalse(payload["graphComplete"])
            self.assertFalse(payload["productionPromotionClaimed"])
            self.assertEqual(payload["blockers"][0]["code"], "dependency-dynamic-import-unresolved")

    def test_current_audit_workflow_cycle_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "dependencies.json"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_module_dependencies.py"),
                    "--package-root",
                    "src/agent_lifecycle",
                    "--forbid-cycle",
                    "agent_lifecycle.audit,agent_lifecycle.audit.implementation,agent_lifecycle.workflow.reviews",
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                check=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["forbiddenCycles"][0][0], "agent_lifecycle.audit")
        self.assertTrue(all(not Path(item["path"]).is_absolute() for item in payload["sourceFiles"]))

    def test_validator_rejects_declared_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "agent_lifecycle"
            root.mkdir()
            (root / "__init__.py").write_text("", encoding="utf-8")
            (root / "first.py").write_text("from agent_lifecycle import second\n", encoding="utf-8")
            (root / "second.py").write_text("from agent_lifecycle import third\n", encoding="utf-8")
            (root / "third.py").write_text("from agent_lifecycle import first\n", encoding="utf-8")
            evidence = Path(tmp) / "evidence.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_module_dependencies.py"),
                    "--package-root",
                    str(root),
                    "--forbid-cycle",
                    "agent_lifecycle.first,agent_lifecycle.second,agent_lifecycle.third",
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                text=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("module-import-cycle", {item["code"] for item in payload["blockers"]})

    def test_validator_includes_function_local_imports_and_ignores_self_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "agent_lifecycle"
            root.mkdir()
            (root / "__init__.py").write_text("", encoding="utf-8")
            (root / "first.py").write_text(
                "def load():\n    from agent_lifecycle.second import value\n    return value\n",
                encoding="utf-8",
            )
            (root / "second.py").write_text("value = 1\n", encoding="utf-8")
            evidence = Path(tmp) / "evidence.json"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_module_dependencies.py"),
                    "--package-root",
                    str(root),
                    "--require-acyclic-modules",
                    "--require-acyclic-packages",
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                check=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["moduleSccs"], [])
        self.assertTrue(payload["dependencyReportDigest"])
        self.assertEqual(payload["dependencyReport"]["reportDigest"], payload["dependencyReportDigest"])
        self.assertTrue(any(edge["to"] == "agent_lifecycle.second" for edge in payload["moduleEdges"]))
        self.assertTrue(any(edge["to"] == "second" for edge in payload["packageEdges"]))

    def test_validator_rejects_package_only_cycle_and_layer_violation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "agent_lifecycle"
            (root / "one").mkdir(parents=True)
            (root / "two").mkdir()
            for package in (root, root / "one", root / "two"):
                (package / "__init__.py").write_text("", encoding="utf-8")
            (root / "one" / "first.py").write_text("from agent_lifecycle.two import second\n", encoding="utf-8")
            (root / "two" / "second.py").write_text("from agent_lifecycle.one import first\n", encoding="utf-8")
            policy = Path(tmp) / "policy.json"
            policy.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-architecture-dependencies.v1",
                        "packageLevels": {"one": 1, "two": 0},
                        "moduleLevels": {},
                    }
                ),
                encoding="utf-8",
            )
            evidence = Path(tmp) / "evidence.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_module_dependencies.py"),
                    "--package-root",
                    str(root),
                    "--policy",
                    str(policy),
                    "--require-acyclic-packages",
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                text=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertNotEqual(result.returncode, 0)
        codes = {item["code"] for item in payload["blockers"]}
        self.assertIn("package-import-cycle", codes)
        self.assertIn("architecture-layer-violation", codes)


class PrivateImportRatchetTests(unittest.TestCase):
    def records(self, source):
        import ast

        from agent_lifecycle.quality.architecture_policy import private_import_records

        return private_import_records(ast.parse(source), "agent_lifecycle.workflow.consumer", "agent_lifecycle")

    def policy(self, records=()):
        from agent_lifecycle.contracts import canonical_digest

        groups = {"ordinary": [], "reexports": []}
        for row in records:
            entry = {key: row[key] for key in ("module", "symbol", "alias", "consumer")}
            entry["reason"] = "Existing exact reviewed debt"
            groups["reexports" if row["explicitReexport"] else "ordinary"].append(entry)
        return {
            "privateImportBaseline": groups["ordinary"],
            "privateImportReexports": groups["reexports"],
            "privateImportBaselineDigest": canonical_digest(groups),
        }

    def test_new_private_import_and_changed_alias_refuse(self):
        from agent_lifecycle.quality.architecture_policy import private_import_findings

        original = self.records("from agent_lifecycle.accounting.ledger import _read as checked\n")
        policy = self.policy(original)
        self.assertEqual([], private_import_findings(original, policy)["blockers"])
        for source in (
            "from agent_lifecycle.accounting.ledger import _read as public\n",
            "from agent_lifecycle.accounting.ledger import _other as checked\n",
        ):
            self.assertTrue(private_import_findings(self.records(source), policy)["blockers"])
        self.assertTrue(private_import_findings(original, self.policy())["blockers"])

    def test_explicit_reexport_is_distinct_and_alias_module_access_cannot_bypass(self):
        from agent_lifecycle.quality.architecture_policy import private_import_findings

        rows = self.records("from agent_lifecycle.accounting.ledger import _read as _read\n")
        self.assertTrue(rows[0]["explicitReexport"])
        self.assertEqual(1, private_import_findings(rows, self.policy(rows))["explicitReexportCount"])
        rows = self.records("import agent_lifecycle.accounting.ledger as ledger\nother = ledger\nvalue = other._read\n")
        self.assertEqual("_read", rows[0]["symbol"])
        self.assertTrue(private_import_findings(rows, self.policy())["blockers"])

    def test_missing_reason_or_baseline_growth_cannot_be_accepted(self):
        from agent_lifecycle.contracts import canonical_digest
        from agent_lifecycle.quality.architecture_policy import private_import_findings

        rows = self.records("from agent_lifecycle.accounting.ledger import _read\n")
        policy = self.policy(rows)
        policy["privateImportBaseline"][0].pop("reason")
        policy["privateImportBaselineDigest"] = canonical_digest(
            {"ordinary": policy["privateImportBaseline"], "reexports": []}
        )
        with self.assertRaises(ValueError):
            private_import_findings(rows, policy)
        policy = self.policy(rows)
        policy["privateImportBaseline"].append(dict(policy["privateImportBaseline"][0], alias="hidden"))
        with self.assertRaises(ValueError):
            private_import_findings(rows, policy)

    def test_relative_import_consumer_and_module_alias_rebinding_cannot_hide_private_edge(self):
        from agent_lifecycle.quality.architecture_policy import private_import_findings

        original = self.records("from ..accounting.ledger import _read as read\n")
        self.assertEqual("agent_lifecycle.accounting.ledger", original[0]["module"])
        changed = [{**original[0], "consumer": "agent_lifecycle.audit.new_consumer"}]
        self.assertTrue(private_import_findings(changed, self.policy(original))["blockers"])
        rows = self.records(
            "import agent_lifecycle.workflow.local as module\nimport agent_lifecycle.accounting.ledger as module\nother = module\nother = other\nother._read()\n"
        )
        self.assertEqual(1, len(rows))
        self.assertTrue(private_import_findings(rows, self.policy())["blockers"])

    def test_cli_rejects_exact_new_private_edge_with_existing_dependency_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "agent_lifecycle"
            (root / "accounting").mkdir(parents=True)
            (root / "workflow").mkdir()
            for directory in (root, root / "accounting", root / "workflow"):
                (directory / "__init__.py").write_text("")
            (root / "accounting/ledger.py").write_text("def _read(): return 1\n")
            (root / "workflow/consumer.py").write_text("from ..accounting.ledger import _read as read\n")
            policy = Path(tmp) / "policy.json"
            policy.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-architecture-dependencies.v1",
                        "packageLevels": {"accounting": 0, "workflow": 1, "__root__": 0},
                        **self.policy(),
                    }
                )
            )
            evidence = Path(tmp) / "dependencies.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_module_dependencies.py"),
                    "--package-root",
                    str(root),
                    "--repository-root",
                    tmp,
                    "--policy",
                    str(policy),
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(1, result.returncode)
            payload = json.loads(evidence.read_text())
            self.assertEqual(1, payload["privateImports"]["ordinaryCount"])
            self.assertEqual("architecture-private-import-unapproved", payload["privateImports"]["blockers"][0]["code"])
            self.assertTrue(payload["dependencyReport"]["graphComplete"])

    def test_annotated_dotted_and_chained_module_aliases_keep_exact_identity(self):
        import ast

        from agent_lifecycle.quality.architecture_policy import private_import_findings, private_import_records

        sources = (
            "import agent_lifecycle.accounting.ledger as ledger\nother: object = ledger\nother._read()\n",
            "import agent_lifecycle.accounting.ledger\nother = agent_lifecycle.accounting.ledger\nother._read()\n",
            "import agent_lifecycle.accounting.ledger\npkg = agent_lifecycle.accounting\nfirst: object = pkg.ledger\nother = first\nother._read()\n",
            "import agent_lifecycle.accounting.ledger as ledger\nother = later\nlater: object = ledger\nother._read()\n",
            "import agent_lifecycle.accounting.ledger as ledger\nother = ledger\nother = other.child\nother._read()\n",
        )
        for source in sources:
            for modules in (None, {"agent_lifecycle.accounting.ledger", "agent_lifecycle.workflow.consumer"}):
                with self.subTest(source=source, known_modules=modules):
                    rows = private_import_records(
                        ast.parse(source), "agent_lifecycle.workflow.consumer", "agent_lifecycle", known_modules=modules
                    )
                    self.assertEqual(
                        [
                            {
                                "module": "agent_lifecycle.accounting.ledger",
                                "symbol": "_read",
                                "alias": "other._read",
                                "consumer": "agent_lifecycle.workflow.consumer",
                                "explicitReexport": False,
                            }
                        ],
                        rows,
                    )
                    self.assertEqual(1, len(private_import_findings(rows, self.policy())["blockers"]))

    def test_cli_rejects_annotated_and_attribute_alias_chains(self):
        sources = (
            "import agent_lifecycle.accounting.ledger as ledger\nother: object = ledger\nother._read()\n",
            "import agent_lifecycle.accounting.ledger\nother = agent_lifecycle.accounting.ledger\nother._read()\n",
            "import agent_lifecycle.accounting.ledger\npkg = agent_lifecycle.accounting\nfirst: object = pkg.ledger\nother = first\nother._read()\n",
        )
        for source in sources:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "agent_lifecycle"
                (root / "accounting").mkdir(parents=True)
                (root / "workflow").mkdir()
                for directory in (root, root / "accounting", root / "workflow"):
                    (directory / "__init__.py").write_text("")
                (root / "accounting/ledger.py").write_text("def _read(): return 1\n")
                (root / "workflow/consumer.py").write_text(source)
                policy = Path(tmp) / "policy.json"
                policy.write_text(
                    json.dumps(
                        {
                            "schemaVersion": "agent-architecture-dependencies.v1",
                            "packageLevels": {"accounting": 0, "workflow": 1, "__root__": 0},
                            **self.policy(),
                        }
                    )
                )
                evidence = Path(tmp) / "dependencies.json"
                result = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "tools/release/validate_module_dependencies.py"),
                        "--package-root",
                        str(root),
                        "--repository-root",
                        tmp,
                        "--policy",
                        str(policy),
                        "--evidence",
                        str(evidence),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(1, result.returncode, result.stderr)
                payload = json.loads(evidence.read_text())
                self.assertTrue(payload["dependencyReport"]["graphComplete"])
                self.assertEqual(1, payload["privateImports"]["ordinaryCount"])
                self.assertEqual(
                    ["architecture-private-import-unapproved"],
                    [row["code"] for row in payload["privateImports"]["blockers"]],
                )

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ModuleDependencyValidatorTests(unittest.TestCase):
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

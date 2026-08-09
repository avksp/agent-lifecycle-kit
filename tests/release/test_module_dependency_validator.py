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

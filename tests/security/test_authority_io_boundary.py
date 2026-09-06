"""Keep known direct and aliased I/O bypasses out of workflow and freeze."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


def _authority_bypasses(source: str) -> list[int]:
    tree = ast.parse(source)
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases.update({entry.asname or entry.name: entry.name for entry in node.names})
        elif isinstance(node, ast.ImportFrom):
            aliases.update({entry.asname or entry.name: f"{node.module}.{entry.name}" for entry in node.names})
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        name = ""
        if isinstance(function, ast.Name):
            name = aliases.get(function.id, function.id)
        elif isinstance(function, ast.Attribute):
            if function.attr in {"read_text", "read_bytes", "write_text", "write_bytes", "open"}:
                violations.append(node.lineno)
                continue
            if isinstance(function.value, ast.Name):
                name = f"{aliases.get(function.value.id, function.value.id)}.{function.attr}"
        if name in {"json.loads", "json.load", "open", "builtins.open", "io.open", "os.open", "os.fdopen"}:
            violations.append(node.lineno)
    return sorted(set(violations))


class AuthorityIoBoundaryTests(unittest.TestCase):
    def test_workflow_and_freeze_delegate_to_shared_io(self) -> None:
        root = Path(__file__).resolve().parents[2] / "src" / "agent_lifecycle"
        violations = {}
        for package in ("workflow", "freeze"):
            for path in sorted((root / package).rglob("*.py")):
                lines = _authority_bypasses(path.read_text(encoding="utf-8"))
                if lines:
                    violations[path.relative_to(root).as_posix()] = lines
        self.assertEqual(violations, {})

    def test_direct_and_import_aliased_mutations_are_rejected(self) -> None:
        for source in (
            "import json; json.loads(data)",
            "import json as decoder; decoder.loads(data)",
            "from json import loads as decode; decode(data)",
            "open(path)",
            "from builtins import open as read_file; read_file(path)",
            "path.read_text(encoding='utf-8')",
            "import os as system; system.open(path, 0)",
        ):
            with self.subTest(source=source):
                self.assertEqual(_authority_bypasses(source), [1])

    def test_shared_helper_delegation_is_not_a_bypass(self) -> None:
        source = "from agent_lifecycle.contracts import read_json_object; read_json_object(path)"
        self.assertEqual(_authority_bypasses(source), [])


if __name__ == "__main__":
    unittest.main()

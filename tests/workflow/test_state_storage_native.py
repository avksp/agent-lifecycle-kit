"""Portable native fixture contract; historical RED runs only explicitly."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


class PortableStorageFixtureContractTests(unittest.TestCase):
    def test_baseline_is_explicit_does_not_import_storage_implementation(self):
        helper = Path(__file__).with_name("storage_helpers.py")
        tree = ast.parse(helper.read_text(encoding="utf-8"))
        imports = [
            node.module
            for node in ast.walk(tree)
            if isinstance(
                node,
                ast.ImportFrom,
            )
        ]
        prefix = "agent_lifecycle.workflow.storage"
        matched = any(name and name.startswith(prefix) for name in imports)
        self.assertFalse(matched)
        source = helper.read_text(encoding="utf-8")
        for required in (
            '"git", "archive"',
            '"task-accept"',
            '"json-input-too-large"',
            '"fixtureOnly": True',
            '"--timeout-seconds"',
        ):
            self.assertIn(required, source)


if __name__ == "__main__":
    unittest.main()

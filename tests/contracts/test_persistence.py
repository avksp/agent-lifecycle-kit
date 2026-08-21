"""Regression tests for shared private persistence primitives."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts.persistence import create_private_json, require_private_json, replace_private_json


class PersistenceTests(unittest.TestCase):
    def test_create_replace_and_require_preserve_private_atomic_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".alk" / "state.json"
            first = {"schemaVersion": "test.v1", "value": 1}
            second = {"schemaVersion": "test.v1", "value": 2}

            create_private_json(path, first)
            self.assertEqual(require_private_json(path), path)
            self.assertEqual(path.read_text(encoding="utf-8").strip(), '{"schemaVersion":"test.v1","value":1}')
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

            replace_private_json(path, second)
            self.assertEqual(path.read_text(encoding="utf-8").strip(), '{"schemaVersion":"test.v1","value":2}')

    def test_create_does_not_replace_existing_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".alk" / "state.json"
            create_private_json(path, {"value": 1})
            with self.assertRaises(FileExistsError):
                create_private_json(path, {"value": 2})


if __name__ == "__main__":
    unittest.main()

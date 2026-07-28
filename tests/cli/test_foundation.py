from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402

class CliFoundationTests(unittest.TestCase):
    def test_version_outputs_compact_json(self) -> None:
        code, payload = _run_cli(["version"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-version.v1")
        self.assertEqual(payload["version"], __version__)

    def test_schema_list_outputs_index(self) -> None:
        code, payload = _run_cli(["schema", "list"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-schema-index.v1")
        self.assertTrue(payload["schemas"])

    def test_schema_show_outputs_schema(self) -> None:
        code, payload = _run_cli(["schema", "show", "agent-host-operation-request.v1"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["$id"], "agent-host-operation-request.v1")

    def test_reserved_group_fails_with_stable_error(self) -> None:
        code, payload = _run_cli(["adapter"])
        self.assertEqual(code, 2)
        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-error.v1")
        self.assertEqual(payload["code"], "command-not-implemented")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path

try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402

class CliFoundationTests(unittest.TestCase):
    def test_root_dispatch_delegates_are_importable(self) -> None:
        for module_name in (
            "agent_lifecycle.cli.dispatch_adapters",
            "agent_lifecycle.cli.dispatch_contracts",
            "agent_lifecycle.cli.dispatch_lifecycle",
            "agent_lifecycle.cli.dispatch_observability",
            "agent_lifecycle.cli.dispatch_planning",
        ):
            with self.subTest(module=module_name):
                self.assertIsNotNone(import_module(module_name))

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

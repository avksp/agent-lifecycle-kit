from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from agent_lifecycle.cli import main
from tests.cli.helpers import _run_cli


class TierResolveRequestTests(unittest.TestCase):
    def test_help_example_resolves_and_schema_is_registered(self) -> None:
        output = StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as exit_result:
            main(["tier", "resolve", "--help"])
        self.assertEqual(exit_result.exception.code, 0)
        schema_id = "agent-sdd-tier-resolution-request.v1"
        help_text = output.getvalue()
        self.assertIn(schema_id, help_text)
        example = help_text.split("Minimal request:", 1)[1]
        request = json.loads(example)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "request.json"
            path.write_text(example, encoding="utf-8")
            code, result = _run_cli(["tier", "resolve", "--request", str(path)])
        self.assertEqual(code, 0, result)
        self.assertEqual(result["tier"], "S1")
        code, output_obj = _run_cli(["schema", "show", schema_id])
        self.assertEqual(code, 0, output_obj)
        schema = output_obj.get("schema", output_obj)
        self.assertEqual(schema["$id"], schema_id)
        self.assertEqual(set(schema["required"]), set(request))

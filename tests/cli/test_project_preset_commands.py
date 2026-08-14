from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.cli import main


def _run(argv: list[str]) -> tuple[int, dict[str, object]]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = main(argv)
    return code, json.loads(output.getvalue())


class ProjectPresetCommandTests(unittest.TestCase):
    def test_list_inspect_and_validate_are_read_only(self) -> None:
        code, listed = _run(["project", "preset", "list"])
        self.assertEqual(code, 0)
        self.assertEqual(listed["status"], "PASS")

        code, inspected = _run(["project", "preset", "inspect", "--preset", "quick-change"])
        self.assertEqual(code, 0)
        self.assertEqual(inspected["operation"], "inspect")

        code, validated = _run(["project", "preset", "validate", "--preset", "feature-implementation"])
        self.assertEqual(code, 0)
        self.assertEqual(validated["status"], "PASS")

    def test_render_writes_only_to_explicit_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, receipt = _run(
                [
                    "project",
                    "preset",
                    "render",
                    "--preset",
                    "quick-change",
                    "--project-root",
                    str(root),
                    "--adapter",
                    "codex",
                    "--out",
                    ".alk/profile.json",
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue((root / ".alk/profile.json").is_file())
            self.assertTrue(receipt["explicitOutputPath"])


if __name__ == "__main__":
    unittest.main()

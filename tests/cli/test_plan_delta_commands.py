from __future__ import annotations

import contextlib
import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path

from agent_lifecycle.cli import main


def _run(args: list[str]) -> tuple[int, dict]:
    output = StringIO()
    with contextlib.redirect_stdout(output):
        code = main(args)
    return code, json.loads(output.getvalue())


def _manifest(path: Path, revision: int, description: str) -> None:
    path.write_text(json.dumps({
        "package": {"id": "sample"},
        "planRevision": revision,
        "status": "FROZEN",
        "baseRevision": {"ref": "main", "sha": "a" * 40},
        "specification": {"requirements": [{"id": "R1", "description": description}]},
        "workstreams": [],
        "acceptance": {"criteria": []},
        "validation": {},
    }), encoding="utf-8")


class PlanDeltaCliTests(unittest.TestCase):
    def test_delta_and_delta_check_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = root / "before.json"
            after = root / "after.json"
            delta = root / "delta.json"
            _manifest(before, 1, "before")
            _manifest(after, 2, "after")
            code, payload = _run(["plan", "delta", "--before", str(before), "--after", str(after), "--out", str(delta)])
            self.assertEqual(code, 0)
            self.assertTrue(payload["reviewRequired"])
            code, checked = _run(["plan", "delta-check", "--delta", str(delta)])
            self.assertEqual(code, 0)
            self.assertEqual(checked["status"], "PASS")


if __name__ == "__main__":
    unittest.main()

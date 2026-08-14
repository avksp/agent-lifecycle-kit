from __future__ import annotations

import contextlib
import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path

from agent_lifecycle.cli import main
from agent_lifecycle.contracts import canonical_digest


def _principles() -> dict:
    body = {
        "schemaVersion": "agent-project-principles.v1",
        "principlesId": "sample",
        "revision": 1,
        "entries": [{"id": "small", "category": "delivery", "statement": "Prefer small changes."}],
        "authority": {"principlesRole": "defaults-and-constraints", "sourceOfTruth": "frozen-plan-and-lock", "semanticReview": "independent-review"},
        "source": {"kind": "project-local", "path": "docs/project-principles.json"},
        "productionPromotionClaimed": False,
    }
    return {**body, "principlesDigest": canonical_digest(body)}


class ProjectPrinciplesCliTests(unittest.TestCase):
    def test_principles_check_writes_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "docs/project-principles.json"
            source.parent.mkdir()
            source.write_text(json.dumps(_principles()), encoding="utf-8")
            output = StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["project", "principles", "check", "--project-root", str(root), "--file", str(source)])
            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], "PASS")


if __name__ == "__main__":
    unittest.main()

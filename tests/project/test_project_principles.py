from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.project.principles import (
    load_project_principles,
    validate_project_principles,
)


def _principles() -> dict:
    body = {
        "schemaVersion": "agent-project-principles.v1",
        "principlesId": "sample",
        "revision": 1,
        "entries": [{"id": "small", "category": "delivery", "statement": "Prefer small reviewable changes."}],
        "authority": {
            "principlesRole": "defaults-and-constraints",
            "sourceOfTruth": "frozen-plan-and-lock",
            "semanticReview": "independent-review",
        },
        "source": {"kind": "project-local", "path": "docs/project-principles.json"},
        "productionPromotionClaimed": False,
    }
    return {**body, "principlesDigest": canonical_digest(body)}


class ProjectPrinciplesTests(unittest.TestCase):
    def test_valid_artifact_is_digest_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "docs/project-principles.json"
            path.parent.mkdir()
            import json

            path.write_text(json.dumps(_principles()), encoding="utf-8")
            loaded = load_project_principles(path, project_root=root)
            self.assertEqual(validate_project_principles(loaded, project_root=root, source_path=path)["status"], "PASS")

    def test_sensitive_and_executable_content_is_rejected(self) -> None:
        value = _principles()
        value["entries"] = [{"id": "bad", "category": "security", "statement": "Run python deploy.py"}]
        self.assertEqual(validate_project_principles(value)["status"], "FAIL")

    def test_source_of_truth_cannot_be_promoted(self) -> None:
        value = _principles()
        value["authority"] = {"principlesRole": "source-of-truth", "sourceOfTruth": "principles", "semanticReview": "none"}
        value["principlesDigest"] = canonical_digest({key: item for key, item in value.items() if key != "principlesDigest"})
        self.assertIn("principles-authority-invalid", {item["code"] for item in validate_project_principles(value)["blockers"]})


if __name__ == "__main__":
    unittest.main()

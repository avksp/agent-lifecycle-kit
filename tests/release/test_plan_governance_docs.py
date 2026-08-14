from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class PlanGovernanceDocumentationTests(unittest.TestCase):
    def test_bilingual_governance_pages_exist_and_link_to_contracts(self) -> None:
        for relative in (
            "docs/reference/project-principles-and-plan-deltas.md",
            "docs/ru/reference/project-principles-and-plan-deltas.md",
            "docs/guides/long-term-project-governance.md",
            "docs/ru/guides/long-term-project-governance.md",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)
        english = (ROOT / "docs/reference/project-principles-and-plan-deltas.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/reference/project-principles-and-plan-deltas.md").read_text(encoding="utf-8")
        for marker in ("agent-project-principles.v1", "agent-plan-delta.v1", "plan delta", "sourceOfTruth"):
            self.assertIn(marker, english)
        for marker in ("agent-project-principles.v1", "agent-plan-delta.v1", "plan delta", "sourceOfTruth"):
            self.assertIn(marker, russian)

    def test_profile_docs_use_supported_review_mesh_ids(self) -> None:
        for relative in (
            "docs/reference/project-workflow-profile.md",
            "docs/ru/reference/project-workflow-profile.md",
        ):
            content = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn('"reviewMesh": "advisory"', content)
            self.assertNotIn('"reviewMesh": "blocking"', content)
            self.assertIn('"reviewMesh": "parallel-research-synthesis"', content)


if __name__ == "__main__":
    unittest.main()

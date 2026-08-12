from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.project.guidance import build_stage_guidance_projection


class ProjectGuidanceTests(unittest.TestCase):
    def test_guidance_is_a_bounded_host_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "guidance").mkdir()
            (root / "guidance/planning.md").write_text("Use the project review checklist.", encoding="utf-8")
            effective = {
                "effectiveProfileDigest": "a" * 64,
                "stages": {"planning": {"guidanceRef": "guidance/planning.md", "mode": "plan"}},
            }

            projection = build_stage_guidance_projection(effective, stage="planning", project_root=root)

        self.assertEqual(projection["guidance"]["guidanceRef"], "guidance/planning.md")
        self.assertTrue(projection["guidance"]["guidancePresent"])
        self.assertFalse(projection["guidance"]["guidanceExecutable"])
        self.assertFalse(projection["guidance"]["systemPromptAuthority"])

    def test_unknown_stage_is_rejected(self) -> None:
        with self.assertRaises(LifecycleError):
            build_stage_guidance_projection({"stages": {}}, stage="custom", project_root=Path.cwd())


if __name__ == "__main__":
    unittest.main()

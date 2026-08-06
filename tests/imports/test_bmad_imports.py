from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.imports import bmad_profile, import_bmad_planning, validate_dialect_profile, validate_import_result


class BmadImportTests(unittest.TestCase):
    def test_bmad_profile_is_draft_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "story.md"
            source.write_text(
                "# Story 12\n\n"
                "- Acceptance criteria must be reviewed.\n"
                "- Testing notes must become explicit evidence.\n",
                encoding="utf-8",
            )

            result = import_bmad_planning(source, target_tokens=4096)

            self.assertEqual(validate_dialect_profile(bmad_profile())["status"], "PASS")
            self.assertEqual(validate_import_result(result)["status"], "PASS")
            self.assertEqual(result["dialectProfile"]["dialectId"], "bmad-method-planning")
            self.assertEqual(result["candidatePlan"]["status"], "DRAFT")
            self.assertTrue(result["auditRequired"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.imports import import_openspec_planning, openspec_profile, validate_dialect_profile, validate_import_result


class OpenSpecImportTests(unittest.TestCase):
    def test_openspec_profile_imports_to_review_required_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "openspec.md"
            source.write_text(
                "# Checkout capability\n\n"
                "- Capture acceptance criteria before implementation.\n"
                "- Validate migration risks before freeze.\n",
                encoding="utf-8",
            )

            first = import_openspec_planning(source, target_tokens=4096)
            second = import_openspec_planning(source, target_tokens=4096)

            self.assertEqual(validate_dialect_profile(openspec_profile())["status"], "PASS")
            self.assertEqual(validate_import_result(first)["status"], "PASS")
            self.assertEqual(first["importDigest"], second["importDigest"])
            self.assertEqual(first["dialectProfile"]["dialectId"], "openspec-planning")
            self.assertEqual(first["candidatePlan"]["status"], "DRAFT")
            self.assertTrue(first["candidatePlan"]["importState"]["requiresReview"])


if __name__ == "__main__":
    unittest.main()

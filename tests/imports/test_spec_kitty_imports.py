from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.imports import import_spec_kitty_planning, spec_kitty_profile, validate_dialect_profile, validate_import_result


class SpecKittyImportTests(unittest.TestCase):
    def test_spec_kitty_profile_keeps_external_plan_untrusted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "design.md"
            source.write_text(
                "# Search feature\n\n"
                "- Review requirements before work starts.\n"
                "- Verify checks before final proof.\n",
                encoding="utf-8",
            )

            result = import_spec_kitty_planning(source, target_tokens=4096)

            self.assertEqual(validate_dialect_profile(spec_kitty_profile())["status"], "PASS")
            self.assertEqual(validate_import_result(result)["status"], "PASS")
            self.assertEqual(result["dialectProfile"]["dialectKind"], "spec-kitty")
            self.assertFalse(result["sourceTrusted"])
            self.assertTrue(result["freezeBlocked"])


if __name__ == "__main__":
    unittest.main()

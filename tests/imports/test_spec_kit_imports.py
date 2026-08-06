from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.imports import import_spec_kit_planning, spec_kit_profile, validate_dialect_profile, validate_import_result


class SpecKitImportTests(unittest.TestCase):
    def test_spec_kit_profile_records_untrusted_dialect_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "spec.md"
            source.write_text(
                "# Account export\n\n"
                "- Define functional requirements.\n"
                "- Keep test plan evidence explicit.\n",
                encoding="utf-8",
            )

            result = import_spec_kit_planning(source, target_tokens=4096)
            profile = spec_kit_profile()

            self.assertEqual(validate_dialect_profile(profile)["status"], "PASS")
            self.assertEqual(validate_import_result(result)["status"], "PASS")
            self.assertEqual(result["nativeDialectProfileDigest"], profile["profileDigest"])
            self.assertEqual(result["dialectProfile"]["dialectKind"], "spec-kit")
            self.assertTrue(result["freezeBlocked"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
TOOLS_RELEASE = ROOT / "tools" / "release"
sys.path.insert(0, str(TOOLS_RELEASE))

from validate_release_ref import validate_release_ref  # noqa: E402


class ReleaseRefValidatorTests(unittest.TestCase):
    def test_current_release_tag_is_an_ancestor_of_main(self) -> None:
        result = validate_release_ref(repository_root=ROOT, tag="v1.74.0", main_ref="HEAD")

        self.assertEqual(result["status"], "PASS", result["blockers"])
        self.assertTrue(result["privilegedPublicationAllowed"])

    def test_non_semver_tag_is_blocked_before_git_resolution(self) -> None:
        result = validate_release_ref(repository_root=ROOT, tag="release/latest", main_ref="HEAD")

        self.assertEqual(result["status"], "FAIL")
        self.assertIn("release-tag-not-immutable-semver", {item["code"] for item in result["blockers"]})
        self.assertFalse(result["privilegedPublicationAllowed"])


if __name__ == "__main__":
    unittest.main()

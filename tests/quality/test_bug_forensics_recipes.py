from __future__ import annotations

import unittest

from agent_lifecycle.quality import (
    build_bug_forensics_recipe_library,
    validate_bug_forensics_recipe_library,
)


class BugForensicsRecipeTests(unittest.TestCase):
    def test_recipes_reuse_existing_receipts_and_stay_optional(self) -> None:
        library = build_bug_forensics_recipe_library()

        validation = validate_bug_forensics_recipe_library(library)

        self.assertEqual(validation["status"], "PASS")
        self.assertFalse(library["enabledByDefault"])
        self.assertTrue(library["reusesExistingReceiptSchemas"])
        self.assertEqual(library["competingReceiptSchemas"], [])
        self.assertEqual(library["budgetUnits"], "tokens-and-resources")
        self.assertEqual(
            {item["recipeId"] for item in library["recipes"]},
            {"issue-classification", "reproduction", "investigation", "validation", "review"},
        )

    def test_recipe_check_can_target_one_recipe(self) -> None:
        validation = validate_bug_forensics_recipe_library(recipe_id="reproduction")

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(validation["recipeIds"], ["reproduction"])

    def test_competing_receipt_schema_fails_closed(self) -> None:
        library = build_bug_forensics_recipe_library()
        library["competingReceiptSchemas"] = ["agent-new-bug-fix-receipt.v1"]
        library["libraryDigest"] = "0" * 64

        validation = validate_bug_forensics_recipe_library(library)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("bug-forensics-recipe-competing-schema", {item["code"] for item in validation["blockers"]})


if __name__ == "__main__":
    unittest.main()

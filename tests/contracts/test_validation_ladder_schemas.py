from __future__ import annotations

import unittest

from agent_lifecycle.contracts.validation_ladder_schemas import VALIDATION_LADDER_SCHEMAS


class ValidationLadderSchemaTests(unittest.TestCase):
    def test_all_schemas_are_closed(self) -> None:
        self.assertEqual(len(VALIDATION_LADDER_SCHEMAS), 4)
        for schema in VALIDATION_LADDER_SCHEMAS.values():
            self.assertFalse(schema["additionalProperties"])

    def test_catalog_and_profile_records_are_closed(self) -> None:
        catalog = VALIDATION_LADDER_SCHEMAS["agent-validation-check-catalog.v1"]
        profile = VALIDATION_LADDER_SCHEMAS["agent-validation-ladder-profile.v1"]

        self.assertFalse(catalog["properties"]["checks"]["items"]["additionalProperties"])
        self.assertFalse(profile["properties"]["mappings"]["items"]["additionalProperties"])

    def test_selection_has_read_only_constants(self) -> None:
        selection = VALIDATION_LADDER_SCHEMAS["agent-validation-selection.v1"]

        self.assertEqual(selection["properties"]["commandsExecuted"], {"const": False})
        self.assertEqual(selection["properties"]["stateWritten"], {"const": False})

    def test_release_full_receipt_cannot_claim_promotion(self) -> None:
        receipt = VALIDATION_LADDER_SCHEMAS["agent-release-full-validation-receipt.v1"]

        self.assertEqual(receipt["properties"]["status"], {"const": "PASS"})
        self.assertEqual(receipt["properties"]["productionPromotionClaimed"], {"const": False})


if __name__ == "__main__":
    unittest.main()

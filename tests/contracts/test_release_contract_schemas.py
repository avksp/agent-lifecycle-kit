from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema


class ReleaseContractSchemaTests(unittest.TestCase):
    def test_publication_adoption_schema_is_registered(self) -> None:
        schema = get_schema("agent-publication-adoption-validation.v1")

        self.assertEqual(schema["properties"]["schemaVersion"], {"const": "agent-publication-adoption-validation.v1"})
        self.assertIn("checks", schema["required"])
        self.assertIn("blockers", schema["required"])
        self.assertEqual(schema["properties"]["productionPromotionClaimed"], {"const": False})


if __name__ == "__main__":
    unittest.main()

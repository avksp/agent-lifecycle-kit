from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class PlanManifestSchemaTests(unittest.TestCase):
    def test_manifest_contract_is_registered_and_closed(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}
        self.assertIn("agent-plan-manifest.v1", ids)
        schema = get_schema("agent-plan-manifest.v1")
        self.assertFalse(schema["additionalProperties"])
        self.assertFalse(schema["$defs"]["packageIntegrity"]["additionalProperties"])
        self.assertEqual(
            schema["$defs"]["extensions"]["properties"]["securityAnalysis"]["properties"]["profileId"]["const"],
            "security-analysis.v1",
        )

    def test_validation_schema_is_registered(self) -> None:
        schema = get_schema("agent-plan-manifest-validation.v1")
        self.assertFalse(schema["additionalProperties"])
        self.assertIn("validationDigest", schema["required"])


if __name__ == "__main__":
    unittest.main()

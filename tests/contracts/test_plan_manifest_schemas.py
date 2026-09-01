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
        self.assertEqual(schema["properties"]["implementationAudit"]["$ref"], "#/$defs/implementationAudit")
        self.assertFalse(schema["$defs"]["implementationAudit"]["additionalProperties"])
        self.assertEqual(
            schema["$defs"]["implementationAudit"]["required"],
            ["required", "finalRequired"],
        )
        self.assertEqual(
            schema["$defs"]["extensions"]["properties"]["securityAnalysis"]["properties"]["profileId"]["const"],
            "security-analysis.v1",
        )

    def test_validation_schema_is_registered(self) -> None:
        schema = get_schema("agent-plan-manifest-validation.v1")
        self.assertFalse(schema["additionalProperties"])
        self.assertIn("validationDigest", schema["required"])

    def test_plan_schema_required_arrays_are_valid_draft_2020_12_structure(self) -> None:
        for schema_id in ("agent-plan-manifest.v1", "agent-plan-manifest-validation.v1"):
            with self.subTest(schema_id=schema_id):
                schema = get_schema(schema_id)
                self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertEqual(schema["type"], "object")
                self.assertEqual(len(schema["required"]), len(set(schema["required"])))
                self.assertEqual(schema["required"].count("schemaVersion"), 1)
                self.assertTrue(set(schema["required"]).issubset(schema["properties"]))

    def test_implementation_audit_policy_has_exact_boolean_fields(self) -> None:
        policy = get_schema("agent-plan-manifest.v1")["$defs"]["implementationAudit"]
        self.assertEqual(set(policy["properties"]), {"required", "finalRequired"})
        self.assertEqual(policy["properties"]["required"], {"type": "boolean"})
        self.assertEqual(policy["properties"]["finalRequired"], {"type": "boolean"})


if __name__ == "__main__":
    unittest.main()

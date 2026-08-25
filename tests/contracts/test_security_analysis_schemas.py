from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas
from agent_lifecycle.contracts.security_analysis_schemas import SECURITY_FINDING_SCHEMA


class SecurityAnalysisSchemaTests(unittest.TestCase):
    def test_security_schemas_are_registered(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}
        self.assertIn(SECURITY_FINDING_SCHEMA, ids)
        self.assertIn("agent-security-analysis-profile.v1", ids)
        self.assertIn("agent-security-verification-assignment.v1", ids)

    def test_finding_schema_keeps_authority_false(self) -> None:
        schema = get_schema(SECURITY_FINDING_SCHEMA)
        self.assertEqual(schema["properties"]["trusted"], {"const": False})
        self.assertEqual(schema["properties"]["authorityClaimed"], {"const": False})


if __name__ == "__main__":
    unittest.main()

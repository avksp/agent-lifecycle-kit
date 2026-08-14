from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts.audit_optimization_schemas import (  # noqa: E402
    AUDIT_OPTIMIZATION_APPLIED_PROFILE_SCHEMA,
    AUDIT_OPTIMIZATION_APPLY_RESULT_SCHEMA,
    AUDIT_OPTIMIZATION_RECOMMENDATION_SCHEMA,
    AUDIT_OPTIMIZATION_SAMPLE_SCHEMA,
    AUDIT_OPTIMIZATION_SCHEMAS,
)
from agent_lifecycle.contracts.schemas import get_schema, list_schemas  # noqa: E402


class AuditOptimizationSchemaTests(unittest.TestCase):
    def test_public_contract_ids_are_versioned_and_registered_in_module(self) -> None:
        self.assertEqual(AUDIT_OPTIMIZATION_SAMPLE_SCHEMA, "agent-audit-optimization-sample.v1")
        self.assertEqual(AUDIT_OPTIMIZATION_RECOMMENDATION_SCHEMA, "agent-audit-optimization-recommendation.v1")
        self.assertIn(AUDIT_OPTIMIZATION_SAMPLE_SCHEMA, AUDIT_OPTIMIZATION_SCHEMAS)
        self.assertIn(AUDIT_OPTIMIZATION_RECOMMENDATION_SCHEMA, AUDIT_OPTIMIZATION_SCHEMAS)

    def test_sample_schema_is_closed_on_sensitive_storage_flags(self) -> None:
        schema = AUDIT_OPTIMIZATION_SCHEMAS[AUDIT_OPTIMIZATION_SAMPLE_SCHEMA]
        for field in ("rawPromptStored", "rawOutputStored", "secretsStored", "providerModelNamesStored", "localPathsStored"):
            self.assertEqual(schema["properties"][field]["const"], False)

    def test_public_registry_exposes_optimizer_contracts(self) -> None:
        listed_ids = {item["id"] for item in list_schemas()["schemas"]}
        self.assertIn(AUDIT_OPTIMIZATION_SAMPLE_SCHEMA, listed_ids)
        self.assertIn(AUDIT_OPTIMIZATION_APPLIED_PROFILE_SCHEMA, listed_ids)
        self.assertIn(AUDIT_OPTIMIZATION_APPLY_RESULT_SCHEMA, listed_ids)
        self.assertEqual(get_schema(AUDIT_OPTIMIZATION_SAMPLE_SCHEMA)["$id"], AUDIT_OPTIMIZATION_SAMPLE_SCHEMA)


if __name__ == "__main__":
    unittest.main()

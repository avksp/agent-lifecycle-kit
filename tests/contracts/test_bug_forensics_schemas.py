from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class BugForensicsSchemaTests(unittest.TestCase):
    def test_bug_forensics_schema_ids_are_registered(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}

        for schema_id in {
            "agent-bug-forensics-profile.v1",
            "agent-bug-forensics-profile-validation.v1",
            "agent-bug-reproduction-receipt.v1",
            "agent-bug-reproduction-receipt-validation.v1",
            "agent-failure-fingerprint.v1",
            "agent-failure-fingerprint-validation.v1",
            "agent-bug-hypothesis-ledger.v1",
            "agent-bug-hypothesis-ledger-validation.v1",
            "agent-regression-proof-receipt.v1",
            "agent-regression-proof-receipt-validation.v1",
            "agent-bug-forensics-gate-receipt.v1",
            "agent-bug-forensics-gate-validation.v1",
            "agent-bug-forensics-audit.v1",
            "agent-bug-forensics-audit-validation.v1",
        }:
            with self.subTest(schema_id=schema_id):
                self.assertIn(schema_id, ids)
                self.assertEqual(get_schema(schema_id)["properties"]["schemaVersion"]["const"], schema_id)

    def test_fix_impact_schema_remains_r19_authority(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}

        self.assertIn("agent-fix-impact-receipt.v1", ids)
        self.assertNotIn("agent-bug-fix-impact-receipt.v1", ids)


if __name__ == "__main__":
    unittest.main()

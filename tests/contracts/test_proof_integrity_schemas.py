from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts.schemas import get_schema, list_schemas  # noqa: E402


class ProofIntegritySchemaTests(unittest.TestCase):
    def test_proof_integrity_schemas_are_registered(self) -> None:
        schema_ids = {item["id"] for item in list_schemas()["schemas"]}

        for schema_id in (
            "agent-proof-finding.v1",
            "agent-proof-finding-validation.v1",
            "agent-root-cause-evidence.v1",
            "agent-root-cause-evidence-validation.v1",
            "agent-fix-impact-receipt.v1",
            "agent-fix-impact-receipt-validation.v1",
            "agent-receipt-hash-chain.v1",
            "agent-receipt-hash-chain-validation.v1",
            "agent-hash-chain-migration-policy.v1",
            "agent-hash-chain-migration-validation.v1",
            "agent-proof-integrity-receipt.v1",
            "agent-proof-integrity-validation.v1",
        ):
            with self.subTest(schema_id=schema_id):
                self.assertIn(schema_id, schema_ids)

    def test_fix_impact_receipt_schema_is_canonical_owner(self) -> None:
        schema = get_schema("agent-fix-impact-receipt.v1")

        self.assertIn("rootCauseDigests", schema["required"])
        self.assertIn("collateralDamage", schema["required"])
        self.assertIn("impactDigest", schema["required"])
        self.assertFalse(schema["properties"]["productionPromotionClaimed"]["const"])


if __name__ == "__main__":
    unittest.main()

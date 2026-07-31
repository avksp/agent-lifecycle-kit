from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts.schemas import get_schema, list_schemas  # noqa: E402


class ImportDialectSchemaTests(unittest.TestCase):
    def test_import_dialect_and_episode_schemas_are_registered(self) -> None:
        schema_ids = {item["id"] for item in list_schemas()["schemas"]}

        for schema_id in (
            "agent-import-dialect-profile.v1",
            "agent-import-dialect-profile-validation.v1",
            "agent-episode-index.v1",
            "agent-episode-index-validation.v1",
            "agent-episode-retrieval.v1",
        ):
            with self.subTest(schema_id=schema_id):
                self.assertIn(schema_id, schema_ids)

    def test_import_dialect_profile_schema_preserves_untrusted_gate(self) -> None:
        schema = get_schema("agent-import-dialect-profile.v1")

        self.assertFalse(schema["properties"]["sourceTrusted"]["const"])
        self.assertTrue(schema["properties"]["requiresReview"]["const"])
        self.assertTrue(schema["properties"]["freezeBlocked"]["const"])

    def test_planning_import_schema_exposes_native_dialect_profile_digest(self) -> None:
        schema = get_schema("agent-planning-import-result.v1")

        self.assertIn("nativeDialectProfileDigest", schema["properties"])
        self.assertEqual(schema["properties"]["dialectProfile"]["type"], ["object", "null"])


if __name__ == "__main__":
    unittest.main()

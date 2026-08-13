from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class ContextCheckpointSchemaTests(unittest.TestCase):
    def test_checkpoint_contracts_are_registered(self) -> None:
        schema_ids = {item["id"] for item in list_schemas()["schemas"]}
        self.assertTrue(
            {
                "agent-context-checkpoint.v1",
                "agent-context-checkpoint-validation.v1",
                "agent-context-checkpoint-event.v1",
            }.issubset(schema_ids)
        )

    def test_checkpoint_is_advisory_and_bounded(self) -> None:
        schema = get_schema("agent-context-checkpoint.v1")
        self.assertEqual(schema["properties"]["implementationAuthorized"], {"const": False})
        self.assertEqual(schema["properties"]["proofAuthority"], {"const": "none"})
        self.assertEqual(schema["properties"]["referencedArtifacts"]["maxItems"], 32)
        self.assertEqual(schema["properties"]["captureEvidence"], {"type": ["object", "null"]})


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema


class ProjectPrinciplesSchemaTests(unittest.TestCase):
    def test_profile_schema_keeps_principles_non_authoritative(self) -> None:
        schema = get_schema("agent-project-workflow-profile.v1")
        reference = schema["properties"]["principles"]
        self.assertEqual(reference["properties"]["sourceOfTruth"], {"const": False})


if __name__ == "__main__":
    unittest.main()

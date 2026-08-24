from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class DomainLanguageSchemaTests(unittest.TestCase):
    def test_domain_language_contracts_are_registered(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}
        self.assertIn("agent-project-domain-language.v1", ids)
        self.assertIn("agent-project-domain-language-validation.v1", ids)
        self.assertIn("agent-project-domain-language-delta.v1", ids)
        self.assertIn("agent-project-domain-language-audit.v1", ids)

    def test_artifact_schema_requires_bilingual_terms_and_authority_boundary(self) -> None:
        schema = get_schema("agent-project-domain-language.v1")
        self.assertEqual(schema["properties"]["languageDigest"]["minLength"], 64)
        self.assertEqual(schema["properties"]["productionPromotionClaimed"], {"const": False})
        term = schema["properties"]["terms"]["items"]
        self.assertEqual(term["properties"]["labels"]["required"], ["en", "ru"])
        self.assertEqual(term["properties"]["definitions"]["required"], ["en", "ru"])


if __name__ == "__main__":
    unittest.main()

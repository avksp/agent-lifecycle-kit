from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas
from agent_lifecycle.contracts.research_evidence_schemas import (
    RESEARCH_CITATION_MATCH_STATUSES,
    RESEARCH_EVIDENCE_SCHEMAS,
    RESEARCH_EVIDENCE_STATUSES,
    RESEARCH_PROVENANCE_RELATIONSHIPS,
)


class ResearchEvidenceSchemaTests(unittest.TestCase):
    def test_research_contracts_are_registered(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}
        self.assertTrue(set(RESEARCH_EVIDENCE_SCHEMAS).issubset(ids))
        for schema_id in RESEARCH_EVIDENCE_SCHEMAS:
            self.assertEqual(get_schema(schema_id)["$id"], schema_id)

    def test_contracts_keep_authority_and_raw_content_outside_portable_evidence(self) -> None:
        source = get_schema("agent-research-source.v1")
        claim = get_schema("agent-research-claim.v1")
        package = get_schema("agent-research-evidence-package.v1")
        summary = get_schema("agent-research-evidence-summary.v1")

        self.assertEqual(source["properties"]["rawContentStored"], {"const": False})
        self.assertEqual(source["properties"]["sourceOfTruth"], {"const": False})
        self.assertEqual(claim["properties"]["lifecycleAuthority"], {"const": "none"})
        self.assertEqual(package["properties"]["sourceOfTruth"], {"const": False})
        self.assertEqual(summary["properties"]["productionPromotionClaimed"], {"const": False})

    def test_bounded_enums_and_resource_shapes_are_explicit(self) -> None:
        source = get_schema("agent-research-source.v1")
        citation = get_schema("agent-research-citation.v1")
        provenance = get_schema("agent-research-provenance-edge.v1")
        package = get_schema("agent-research-evidence-package.v1")

        self.assertEqual(source["properties"]["status"]["enum"], list(RESEARCH_EVIDENCE_STATUSES))
        self.assertEqual(citation["properties"]["matchStatus"]["enum"], list(RESEARCH_CITATION_MATCH_STATUSES))
        self.assertEqual(provenance["properties"]["relationship"]["enum"], list(RESEARCH_PROVENANCE_RELATIONSHIPS))
        self.assertEqual(package["properties"]["sources"]["maxItems"], 128)
        self.assertEqual(package["properties"]["provenance"]["maxItems"], 512)


if __name__ == "__main__":
    unittest.main()

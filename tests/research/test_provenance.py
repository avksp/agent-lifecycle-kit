from __future__ import annotations

import unittest

from agent_lifecycle.research.provenance import analyze_provenance


def _source(source_id: str) -> dict:
    return {"sourceId": source_id}


class ResearchProvenanceTests(unittest.TestCase):
    def test_duplicate_sources_are_grouped_and_not_independent(self) -> None:
        result = analyze_provenance(
            [_source("a"), _source("b"), _source("c")],
            [
                {"sourceId": "b", "relatedSourceId": "a", "relationship": "duplicate-of"},
                {"sourceId": "c", "relatedSourceId": "a", "relationship": "derived-from"},
            ],
        )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["duplicateGroups"], [["a", "b"]])
        self.assertNotIn("b", result["independentSourceIds"])
        self.assertEqual(result["independenceBySource"]["c"], "derivative")

    def test_cycles_are_reported_as_blockers(self) -> None:
        result = analyze_provenance(
            [_source("a"), _source("b")],
            [
                {"sourceId": "a", "relatedSourceId": "b", "relationship": "suggested-by"},
                {"sourceId": "b", "relatedSourceId": "a", "relationship": "suggested-by"},
            ],
        )

        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["cycles"])
        self.assertEqual(result["blockers"][0]["code"], "provenance-cycle")

    def test_missing_source_is_reported_without_crashing(self) -> None:
        result = analyze_provenance(
            [_source("a")],
            [{"sourceId": "a", "relatedSourceId": "missing", "relationship": "derived-from"}],
        )

        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["blockers"][0]["code"], "provenance-source-missing")


if __name__ == "__main__":
    unittest.main()

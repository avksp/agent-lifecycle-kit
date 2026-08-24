from __future__ import annotations

import unittest

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.planning.deltas import build_plan_delta, validate_plan_delta
from tests.project.test_domain_language import _language


def _manifest(revision: int, description: str) -> dict:
    return {
        "package": {"id": "sample"},
        "planRevision": revision,
        "status": "FROZEN",
        "baseRevision": {"ref": "main", "sha": "a" * 40},
        "specification": {"requirements": [{"id": "R1", "description": description}]},
        "workstreams": [],
        "acceptance": {"criteria": []},
        "validation": {},
    }


class DomainLanguageDeltaTests(unittest.TestCase):
    def test_term_delta_is_read_only_and_digest_bound(self) -> None:
        before = _language()
        after = _language(revision=2, old_alias_status="DEPRECATED")
        after["terms"][0]["labels"]["en"] = "Capability qualification"
        after["languageDigest"] = canonical_digest(
            {key: value for key, value in after.items() if key != "languageDigest"}
        )

        delta = build_plan_delta(
            _manifest(1, "before"),
            _manifest(2, "after"),
            language_before=before,
            language_after=after,
        )

        self.assertEqual(validate_plan_delta(delta)["status"], "PASS")
        delta["termChanges"]["renamedTerms"][0]["afterLabels"]["en"] = "Tampered"
        self.assertEqual(validate_plan_delta(delta)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()

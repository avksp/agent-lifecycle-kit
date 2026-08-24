from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.planning.continuity import (
    build_domain_language_continuity,
    reconcile_domain_language_continuity,
)
from agent_lifecycle.project.domain_language import (
    build_domain_language_delta,
    domain_language_digest,
    load_domain_language,
    validate_domain_language,
)


def _language(*, revision: int = 1, old_alias_status: str = "ACTIVE") -> dict:
    body = {
        "schemaVersion": "agent-project-domain-language.v1",
        "languageId": "alk-terms",
        "revision": revision,
        "defaultLocale": "en",
        "terms": [
            {
                "termId": "qualification",
                "labels": {"en": "Qualification", "ru": "Квалификация"},
                "definitions": {
                    "en": "A bounded validation of a named capability.",
                    "ru": "Ограниченная проверка названной возможности.",
                },
                "aliases": [
                    {"value": "qualification receipt", "locale": "en", "status": old_alias_status},
                    {"value": "квалификационное подтверждение", "locale": "ru", "status": "ACTIVE"},
                ],
                "contexts": ["agent-plugin", "benchmark", "structured-result"],
                "references": [
                    {"kind": "documentation", "path": "docs/terms.md", "locator": "qualification"},
                    {
                        "kind": "symbol",
                        "path": "src/agent_lifecycle/project/domain_language.py",
                        "locator": "validate_domain_language",
                    },
                ],
            }
        ],
        "authority": {
            "role": "terminology-reference",
            "sourceOfTruth": "specification-and-frozen-plan",
            "semanticReview": "independent-review",
        },
        "source": {"kind": "project-local", "path": "docs/domain-language.json"},
        "productionPromotionClaimed": False,
    }
    return {**body, "languageDigest": canonical_digest(body)}


class DomainLanguageTests(unittest.TestCase):
    def test_valid_bilingual_artifact_is_digest_bound_and_loadable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "docs/domain-language.json"
            source.parent.mkdir()
            source.write_text(json.dumps(_language(), ensure_ascii=False), encoding="utf-8")
            loaded = load_domain_language(source, project_root=root)

        self.assertEqual(validate_domain_language(loaded, project_root=root, source_path=source)["status"], "PASS")
        self.assertEqual(loaded["languageDigest"], domain_language_digest(loaded))

    def test_ambiguous_labels_and_unsafe_content_fail_closed(self) -> None:
        value = _language()
        value["terms"].append(
            {
                "termId": "other",
                "labels": {"en": "Qualification", "ru": "Другое"},
                "definitions": {"en": "Other.", "ru": "Другое."},
                "aliases": [],
                "contexts": ["other"],
                "references": [{"kind": "documentation", "path": "../outside.md"}],
            }
        )
        value["terms"][0]["definitions"]["en"] = "Run python deploy.py"
        value["languageDigest"] = canonical_digest(
            {key: item for key, item in value.items() if key != "languageDigest"}
        )

        blockers = {item["code"] for item in validate_domain_language(value)["blockers"]}
        self.assertIn("domain-language-label-ambiguous", blockers)
        self.assertIn("domain-language-reference-path-invalid", blockers)
        self.assertIn("domain-language-executable-guidance", blockers)

    def test_delta_reports_rename_deprecation_and_sorted_impact(self) -> None:
        before = _language()
        after = _language(revision=2, old_alias_status="DEPRECATED")
        after["terms"][0]["labels"]["en"] = "Capability qualification"
        after["languageDigest"] = canonical_digest(
            {key: item for key, item in after.items() if key != "languageDigest"}
        )

        delta = build_domain_language_delta(before, after)

        self.assertEqual(delta["status"], "PASS")
        self.assertEqual(delta["renamedTerms"][0]["kind"], "RENAME")
        self.assertEqual(delta["deprecatedAliases"][0]["value"], "qualification receipt")
        self.assertEqual(
            [item["path"] for item in delta["impactedReferences"]],
            sorted(item["path"] for item in delta["impactedReferences"]),
        )

    def test_continuity_detects_plan_lineage_drift(self) -> None:
        language = _language()
        snapshot = build_domain_language_continuity(language, plan_digest="a" * 64, source_revision="b" * 40)
        self.assertEqual(
            reconcile_domain_language_continuity(snapshot, language, plan_digest="a" * 64, source_revision="b" * 40)[
                "status"
            ],
            "PASS",
        )
        self.assertEqual(
            reconcile_domain_language_continuity(snapshot, language, plan_digest="c" * 64, source_revision="b" * 40)[
                "status"
            ],
            "FAIL",
        )


if __name__ == "__main__":
    unittest.main()

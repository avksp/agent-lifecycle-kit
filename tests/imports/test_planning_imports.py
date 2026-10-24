from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.ownership_paths import require_declared_output_footprint
from agent_lifecycle.imports import (
    import_planning_input,
    require_import_validation_pass,
    require_skill_proposal_pass,
    validate_import_result,
    validate_skill_improvement_proposal,
)
from agent_lifecycle.imports.planning import import_planning_text
from agent_lifecycle.planning import validate_plan_manifest


class PlanningImportTests(unittest.TestCase):
    def test_markdown_import_produces_draft_that_requires_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "incoming.md"
            source.write_text(
                "# Payment workflow\n\n- Keep confirmation after review.\n- Record validation evidence.\n",
                encoding="utf-8",
            )

            result = import_planning_input(source, package_id="payment-workflow", target_tokens=4096)
            validation = validate_import_result(result)
            candidate = result["candidatePlan"]

            self.assertEqual(result["schemaVersion"], "agent-planning-import-result.v1")
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(require_import_validation_pass(validation)["status"], "PASS")
            self.assertEqual(candidate["status"], "DRAFT")
            self.assertTrue(candidate["importState"]["freezeBlocked"])
            self.assertTrue(candidate["importState"]["auditRequired"])
            self.assertEqual(validate_plan_manifest(candidate)["status"], "DRAFT")
            require_declared_output_footprint(candidate)
            self.assertEqual(candidate["package"]["planArtifactRoot"], "imported/plan")
            self.assertEqual(len(candidate["specification"]["requirements"]), 2)

    def test_import_blocks_sensitive_source_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "incoming.md"
            source.write_text("Use " + "/" + "Users/local/private in an untrusted note.", encoding="utf-8")

            result = import_planning_input(source)
            validation = validate_import_result(result)

            self.assertEqual(result["status"], "FAIL")
            self.assertIsNone(result["candidatePlan"])
            self.assertIn("planning-import-local-path", {item["code"] for item in result["blockers"]})
            self.assertEqual(validation["status"], "FAIL")

    def test_json_import_keeps_source_untrusted_and_compact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "incoming.json"
            source.write_text(
                json.dumps(
                    {
                        "title": "Review package",
                        "requirements": [
                            {"description": "Validate before implementation."},
                            {"description": "Keep output compact."},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = import_planning_input(source, target_tokens=4096)

            self.assertFalse(result["sourceTrusted"])
            self.assertLessEqual(result["estimatedTokens"], 4096)
            self.assertEqual(result["candidateLifecycleStatus"], "DRAFT_REQUIRES_REVIEW")

    def test_import_fails_closed_without_requirements_or_over_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "incoming.md"
            source.write_text("# Title only\n", encoding="utf-8")
            large = Path(tmp) / "large.md"
            large.write_text("x" * 128, encoding="utf-8")

            missing = import_planning_input(source)
            capped = import_planning_input(large, max_input_bytes=64)

            self.assertEqual(missing["status"], "FAIL")
            self.assertIn("planning-import-requirements-missing", {item["code"] for item in missing["blockers"]})
            self.assertEqual(capped["status"], "FAIL")
            self.assertIn("planning-import-input-cap-exceeded", {item["code"] for item in capped["blockers"]})

    def test_shared_secret_categories_are_refused_without_echo(self) -> None:
        secrets = [
            "sk-" + "a" * 24,
            "gh" + "p_" + "b" * 24,
            "Bearer " + "synthetic-credential",
            "password=" + "synthetic-credential",
            "https://example.com/download?token=" + "synthetic-credential",
            "-----BEGIN " + "PRIVATE KEY-----\nsynthetic\n-----END PRIVATE KEY-----",
        ]
        for secret in secrets:
            with self.subTest(category=secrets.index(secret)):
                with self.assertRaises(LifecycleError) as caught:
                    import_planning_text("- Review " + secret)
                self.assertEqual(caught.exception.code, "import-sensitive-content")
                self.assertTrue(secret not in str(caught.exception))

    def test_labels_package_ids_and_nested_decoded_text_are_refused(self) -> None:
        secret = "gh" + "p_" + "c" * 24
        encoded = "".join(f"\\u{ord(char):04x}" for char in secret)
        inputs = [
            ("- Review", {"source_label": secret}),
            ("- Review", {"package_id": secret}),
            ('{"requirements":[{"description":"' + encoded + '"}]}', {}),
            (json.dumps({"requirements": ["Review"], "metadata": {"password": ["opaque"]}}), {}),
        ]
        for text, options in inputs:
            with self.assertRaises(LifecycleError) as caught:
                import_planning_text(text, **options)
            self.assertEqual(caught.exception.code, "import-sensitive-content")
            self.assertTrue(secret not in str(caught.exception))

    def test_path_redaction_categories_do_not_reject_benign_requirements(self) -> None:
        text = "- Preserve /api/v1/status and https://example.com/docs?q=public."
        result = import_planning_text(text, source_label="requirements.md")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["source"]["label"], "requirements.md")
        self.assertEqual(result["candidatePlan"]["specification"]["requirements"][0]["description"], text[2:])

    def test_skill_proposal_is_never_auto_applied(self) -> None:
        proposal = {
            "schemaVersion": "agent-skill-improvement-proposal.v1",
            "proposalId": "proposal-1",
            "affectedSkill": "agent-workflow-orchestrator",
            "status": "PROPOSED",
            "rationale": "Reduce repeated context.",
            "expectedBehavior": "Ask for less duplicate evidence.",
            "requiredTests": ["skills behavior fixture"],
            "requiresReview": True,
            "autoApply": False,
            "applied": False,
        }

        validation = validate_skill_improvement_proposal(proposal)
        self.assertEqual(require_skill_proposal_pass(validation)["status"], "PASS")

        unsafe = dict(proposal)
        unsafe["autoApply"] = True
        unsafe_validation = validate_skill_improvement_proposal(unsafe)
        self.assertEqual(unsafe_validation["status"], "FAIL")
        self.assertIn("skill-proposal-auto-apply", {item["code"] for item in unsafe_validation["blockers"]})


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import unittest

from agent_lifecycle.imports import import_planning_text, validate_import_result


class PlanningImportTests(unittest.TestCase):
    def test_inline_text_produces_reviewable_draft(self) -> None:
        result = import_planning_text("## Plan\n- Preserve the source of truth\n- Run focused checks", package_id="draft")
        validation = validate_import_result(result)

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(result["candidatePlan"]["schemaVersion"], "agent-plan-manifest.v1")
        self.assertEqual(result["candidatePlan"]["status"], "DRAFT")
        self.assertTrue(result["freezeBlocked"])

    def test_candidate_authority_mutation_is_rejected(self) -> None:
        result = import_planning_text("# Plan\n- Review the imported requirements", package_id="draft")
        mutated = copy.deepcopy(result)
        mutated["candidatePlan"]["integrationSeams"] = ["controller"]

        validation = validate_import_result(mutated)

        self.assertEqual(validation["status"], "FAIL")
        codes = {item["code"] for item in validation["blockers"]}
        self.assertIn("planning-import-candidate-invalid", codes)


if __name__ == "__main__":
    unittest.main()

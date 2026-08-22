from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.imports import import_external_dialect, validate_external_import_result


class ExternalDialectTests(unittest.TestCase):
    def test_workflow_dialect_is_imported_as_a_reviewable_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "workflow.json"
            source.write_text(
                json.dumps(
                    {
                        "title": "Review workflow",
                        "steps": ["inspect changes", "run tests"],
                        "validation": ["all checks pass"],
                    }
                ),
                encoding="utf-8",
            )

            result = import_external_dialect(source, family="workflow", package_id="external-draft")
            validation = validate_external_import_result(result)

            self.assertEqual(result["status"], "PASS")
            self.assertEqual(validation["status"], "PASS")
            self.assertEqual(result["candidatePlan"]["schemaVersion"], "agent-plan-manifest.v1")
            self.assertEqual(result["candidatePlan"]["status"], "DRAFT")
            self.assertFalse(result["candidatePlan"]["externalImport"]["executesInput"])
            self.assertTrue(result["requiresReview"])


if __name__ == "__main__":
    unittest.main()

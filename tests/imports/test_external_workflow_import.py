from __future__ import annotations

import unittest
from pathlib import Path

from agent_lifecycle.imports import import_external_workflow, validate_external_import_result
from agent_lifecycle.planning import validate_plan_manifest

ROOT = Path(__file__).resolve().parents[2]


class ExternalWorkflowImportTests(unittest.TestCase):
    def test_workflow_yaml_maps_to_draft_without_execution_semantics(self) -> None:
        source = ROOT / "conformance/fixtures/imports/external-workflow-basic.yaml"

        result = import_external_workflow(source, package_id="workflow-draft", target_tokens=4096)
        validation = validate_external_import_result(result)
        candidate = result["candidatePlan"]

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(result["externalDialect"]["family"], "workflow")
        self.assertFalse(result["externalDialect"]["executesInput"])
        self.assertFalse(result["externalDialect"]["portableProviderDefaults"])
        self.assertEqual(candidate["status"], "DRAFT")
        self.assertFalse(candidate["externalImport"]["executesInput"])
        self.assertGreaterEqual(len(candidate["specification"]["requirements"]), 3)
        self.assertEqual(validate_plan_manifest(candidate)["status"], "DRAFT")

    def test_workflow_validation_hints_are_context_not_commands(self) -> None:
        source = ROOT / "conformance/fixtures/imports/external-workflow-basic.yaml"

        result = import_external_workflow(source, target_tokens=4096)
        candidate = result["candidatePlan"]

        self.assertEqual(len(candidate["externalImport"]["validationHints"]), 2)
        self.assertEqual(candidate["acceptance"]["releaseGate"], "External dialect imports require ALK plan review and explicit freeze before implementation.")


if __name__ == "__main__":
    unittest.main()

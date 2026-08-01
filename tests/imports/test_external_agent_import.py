from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.imports import import_external_agent, validate_external_import_result

ROOT = Path(__file__).resolve().parents[2]


class ExternalAgentImportTests(unittest.TestCase):
    def test_agent_yaml_redacts_host_local_provider_model_and_environment(self) -> None:
        source = ROOT / "conformance/fixtures/imports/external-agent-basic.yaml"

        result = import_external_agent(source, package_id="agent-draft", target_tokens=4096)
        validation = validate_external_import_result(result)
        rendered = json.dumps(result, sort_keys=True)

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(result["externalDialect"]["family"], "agent")
        self.assertIn("provider", result["externalDialect"]["hostLocalHintKeys"])
        self.assertIn("model", result["externalDialect"]["hostLocalHintKeys"])
        self.assertIn("environmentKeys", result["externalDialect"]["hostLocalHintKeys"])
        self.assertEqual(result["candidatePlan"]["externalImport"]["hostLocalHints"]["environmentKeys"], ["HOST_LOCAL_SETTING"])
        self.assertNotIn("runtime-provider-placeholder", rendered)
        self.assertNotIn("runtime-model-placeholder", rendered)
        self.assertNotIn("runtime-local-placeholder", rendered)
        self.assertFalse(result["candidatePlan"]["externalImport"]["portableProviderDefaults"])
        self.assertTrue(result["candidatePlan"]["importState"]["requiresReview"])

    def test_agent_json_uses_policy_hints_as_review_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "agent.json"
            source.write_text(
                json.dumps(
                    {
                        "name": "Policy review agent",
                        "role": "Check small patch",
                        "policies": ["run focused tests", "record evidence"],
                        "tools": ["shell"],
                    }
                ),
                encoding="utf-8",
            )

            result = import_external_agent(source, target_tokens=4096)

            requirements = result["candidatePlan"]["specification"]["requirements"]
            self.assertGreaterEqual(len(requirements), 3)
            self.assertTrue(any("policy hint" in item["description"] for item in requirements))


if __name__ == "__main__":
    unittest.main()

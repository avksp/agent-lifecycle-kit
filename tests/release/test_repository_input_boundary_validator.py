from __future__ import annotations

import unittest
from pathlib import Path

from tools.release.validate_repository_input_boundaries import validate_sources


ROOT = Path(__file__).resolve().parents[2]


class RepositoryInputBoundaryValidatorTests(unittest.TestCase):
    def test_current_sources_pass_boundary_validator(self) -> None:
        payload = validate_sources(ROOT / "src/agent_lifecycle")

        self.assertEqual(payload["status"], "PASS", payload["blockers"])
        self.assertEqual(payload["schemaVersion"], "agent-repository-input-boundary-validation.v1")
        self.assertTrue(payload["requiredProperties"]["gitRevisionOptionBoundary"])
        self.assertTrue(payload["requiredProperties"]["stableRegularFileContainment"])
        self.assertTrue(payload["requiredProperties"]["symlinksRejected"])
        self.assertTrue(payload["requiredProperties"]["artifactRecognitionSeparateFromValidation"])

    def test_validator_requires_each_boundary_source_and_regression_test(self) -> None:
        payload = validate_sources(ROOT / "src/agent_lifecycle")

        checked = {item["id"] for item in payload["checks"]}
        self.assertEqual(
            checked,
            {"source-paths", "source-git", "source-changeSummary", "source-evidenceIndex", "security-regression-tests"},
        )


if __name__ == "__main__":
    unittest.main()

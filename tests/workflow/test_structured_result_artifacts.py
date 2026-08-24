from __future__ import annotations

import unittest

from agent_lifecycle.workflow.artifacts import (
    build_structured_result_artifact,
    validate_structured_result_artifact,
)


class StructuredResultArtifactTests(unittest.TestCase):
    def test_artifact_validates_without_claiming_workflow_authority(self) -> None:
        artifact = _artifact()

        validation = validate_structured_result_artifact(
            artifact,
            expected={"runId": "run-1", "taskId": "WS-01", "planDigest": "a" * 64},
        )

        self.assertEqual(validation["status"], "PASS")
        self.assertFalse(artifact["authorityClaimed"])

    def test_artifact_lineage_mutation_fails_closed(self) -> None:
        artifact = _artifact()
        artifact["sourceRevision"] = "other"

        validation = validate_structured_result_artifact(
            artifact,
            expected={"sourceRevision": "source"},
        )

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("structured-result-artifact-lineage-mismatch", {item["code"] for item in validation["blockers"]})


def _artifact() -> dict:
    return build_structured_result_artifact(
        run_id="run-1",
        package_id="package-1",
        task_id="WS-01",
        attempt=1,
        plan_digest="a" * 64,
        source_revision="source",
        lock_digest="b" * 64,
        operation_id="reference-evaluation",
        selection={"status": "PASS", "selectionDigest": "c" * 64},
        validation={"status": "PASS", "validationDigest": "d" * 64},
        output={"schemaVersion": "result.v1", "status": "PASS"},
    )


if __name__ == "__main__":
    unittest.main()

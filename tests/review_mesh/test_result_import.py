from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.review_mesh import build_review_mesh_assignment, build_review_mesh_profile, import_review_mesh_result


class ReviewMeshResultImportTests(unittest.TestCase):
    def test_import_result_redacts_secret_like_markers_without_raw_output(self) -> None:
        profile, assignment = _profile_and_assignment()

        result = import_review_mesh_result(
            profile=profile,
            assignment=assignment,
            reviewer_output={
                "schemaVersion": "reviewer-output.test",
                "status": "FAIL",
                "budgetUsage": {"invocations": 1, "inputTokens": 100, "outputTokens": 20, "wallSeconds": 3},
                "findings": [{"id": "F1", "severity": "MEDIUM", "status": "open", "message": "token " + "sk-" + "abcdefghijklmnopqrstuv"}],
            },
        )

        self.assertEqual(result["schemaVersion"], "agent-review-mesh-result.v1")
        self.assertEqual(result["redaction"]["status"], "REDACTED")
        self.assertEqual(result["redaction"]["secretLikeMarkersRedacted"], 1)
        self.assertFalse(result["import"]["rawOutputStored"])
        self.assertIn("[REDACTED]", result["findings"][0]["message"])

    def test_import_result_rejects_local_absolute_paths_by_default(self) -> None:
        profile, assignment = _profile_and_assignment()

        with self.assertRaises(LifecycleError) as raised:
            import_review_mesh_result(
                profile=profile,
                assignment=assignment,
                reviewer_output={
                    "budgetUsage": {"invocations": 0, "inputTokens": 0, "outputTokens": 0, "wallSeconds": 0},
                    "findings": [{"id": "F1", "severity": "LOW", "status": "open", "message": "/Us" + "ers/example/private.txt"}],
                },
            )

        self.assertEqual(raised.exception.code, "review-mesh-local-path-leakage")

    def test_import_result_can_redact_explicit_local_evidence_refs(self) -> None:
        profile, assignment = _profile_and_assignment()

        result = import_review_mesh_result(
            profile=profile,
            assignment=assignment,
            reviewer_output={
                "budgetUsage": {"invocations": 0, "inputTokens": 0, "outputTokens": 0, "wallSeconds": 0},
                "findings": [{"id": "F1", "severity": "LOW", "status": "open", "message": "/Vo" + "lumes/Work/evidence.json"}],
            },
            allow_local_evidence_refs=True,
        )

        self.assertEqual(result["redaction"]["localPathsRedacted"], 1)
        self.assertIn("[LOCAL_PATH]", result["findings"][0]["message"])


def _profile_and_assignment() -> tuple[dict, dict]:
    profile = build_review_mesh_profile(independence_required=False)
    assignment = build_review_mesh_assignment(
        profile=profile,
        assignment_id="RM-1",
        subject={"taskId": "TASK-1", "reviewMeshBlockingOptIn": True},
        reviewer={"role": "reviewer", "modelClass": "strong-reasoning"},
        blocking=True,
    )
    return profile, assignment


if __name__ == "__main__":
    unittest.main()

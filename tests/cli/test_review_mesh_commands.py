from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import write_json_create
from agent_lifecycle.review_mesh import build_review_mesh_profile

try:
    from .helpers import _run_cli
except ImportError:
    from helpers import _run_cli


class ReviewMeshCliTests(unittest.TestCase):
    def test_assign_import_synthesize_and_quorum_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = build_review_mesh_profile(independence_required=False)
            profile_path = root / "profile.json"
            intake_path = root / "intake.json"
            assignment_path = root / "assignment.json"
            reviewer_output_path = root / "reviewer-output.json"
            result_path = root / "result.json"
            synthesis_path = root / "synthesis.json"
            quorum_path = root / "quorum.json"
            write_json_create(profile_path, profile)
            write_json_create(
                intake_path,
                {
                    "schemaVersion": "agent-adapter-task-start-receipt.v1",
                    "status": "REVIEW_REQUIRED",
                    "adapterId": "codex",
                    "input": {"label": "task.md"},
                    "receiptDigest": "a" * 64,
                },
            )

            code, assignment = _run_cli(
                [
                    "review-mesh",
                    "assign",
                    "--intake",
                    intake_path.as_posix(),
                    "--profile",
                    profile_path.as_posix(),
                    "--mode",
                    "parallel-research-synthesis",
                    "--phase",
                    "plan-review",
                    "--assignment-id",
                    "RM-1",
                    "--reviewer-id",
                    "reviewer-a",
                    "--reviewer-role",
                    "plan-reviewer",
                    "--out",
                    assignment_path.as_posix(),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(assignment["schemaVersion"], "agent-review-mesh-reviewer-packet.v1")

            write_json_create(
                reviewer_output_path,
                {
                    "status": "FAIL",
                    "budgetUsage": {"invocations": 1, "inputTokens": 100, "outputTokens": 20, "wallSeconds": 3},
                    "findings": [{"id": "F1", "severity": "LOW", "status": "open"}],
                },
            )
            code, result = _run_cli(
                [
                    "review-mesh",
                    "import-result",
                    "--profile",
                    profile_path.as_posix(),
                    "--assignment",
                    assignment_path.as_posix(),
                    "--reviewer-output",
                    reviewer_output_path.as_posix(),
                    "--out",
                    result_path.as_posix(),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(result["schemaVersion"], "agent-review-mesh-result.v1")

            code, synthesis = _run_cli(
                [
                    "review-mesh",
                    "synthesize",
                    "--profile",
                    profile_path.as_posix(),
                    "--result",
                    result_path.as_posix(),
                    "--accepted-finding-id",
                    "F1",
                    "--out",
                    synthesis_path.as_posix(),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(synthesis["schemaVersion"], "agent-review-mesh-synthesis.v1")

            code, quorum = _run_cli(
                [
                    "review-mesh",
                    "quorum",
                    "--profile",
                    profile_path.as_posix(),
                    "--synthesis",
                    synthesis_path.as_posix(),
                    "--min-reviewers",
                    "1",
                    "--reviewer-role",
                    "plan-reviewer",
                    "--out",
                    quorum_path.as_posix(),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(quorum["schemaVersion"], "agent-review-mesh-quorum-receipt.v1")
            self.assertTrue(quorum_path.is_file())


if __name__ == "__main__":
    unittest.main()

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
    def test_template_list_and_prepare_commands_build_local_packets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            intake_path = root / "intake.json"
            out_dir = root / "prepared"
            receipt_path = root / "prepare-receipt.json"
            write_json_create(
                intake_path,
                {
                    "schemaVersion": "agent-adapter-task-start-receipt.v1",
                    "status": "REVIEW_REQUIRED",
                    "adapterId": "codex",
                    "input": {"label": "task.md"},
                    "receiptDigest": "b" * 64,
                },
            )

            code, library = _run_cli(["review-mesh", "template-list"])
            self.assertEqual(code, 0)
            self.assertIn("parallel-research-synthesis", library["templateIds"])
            self.assertFalse(library["hostExecutionStarted"])

            code, receipt = _run_cli(
                [
                    "review-mesh",
                    "prepare",
                    "--intake",
                    intake_path.as_posix(),
                    "--template",
                    "parallel-research-synthesis",
                    "--reviewer",
                    "codex-example:architecture-reviewer:strong-reasoning",
                    "--reviewer",
                    "claude-example:risk-reviewer:strong-reasoning",
                    "--reviewer",
                    "opencode-glm-example:local-reviewer:local-strong-review",
                    "--evidence-id",
                    "EV-PLAN",
                    "--out-dir",
                    out_dir.as_posix(),
                    "--out",
                    receipt_path.as_posix(),
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(receipt["schemaVersion"], "agent-review-mesh-prepare-receipt.v1")
            self.assertEqual(receipt["reviewerCount"], 3)
            self.assertFalse(receipt["hostExecutionStarted"])
            self.assertFalse(receipt["modelCallsStarted"])
            self.assertTrue((out_dir / "profile.json").is_file())
            self.assertEqual(len(list((out_dir / "assignments").glob("*.json"))), 3)
            self.assertTrue(receipt_path.is_file())

    def test_profile_command_writes_provider_neutral_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_path = root / "profile.json"

            code, profile = _run_cli(
                [
                    "review-mesh",
                    "profile",
                    "--profile-id",
                    "rm-plan-review",
                    "--default-mode",
                    "parallel-research-synthesis",
                    "--reviewer-model-class",
                    "strong-reasoning",
                    "--reviewer-model-class",
                    "local-strong-review",
                    "--max-invocations",
                    "3",
                    "--max-input-tokens",
                    "12000",
                    "--max-output-tokens",
                    "3000",
                    "--out",
                    profile_path.as_posix(),
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(profile["schemaVersion"], "agent-review-mesh-profile.v1")
            self.assertEqual(profile["profileId"], "rm-plan-review")
            self.assertEqual(profile["defaultMode"], "parallel-research-synthesis")
            self.assertEqual(profile["reviewerModelClasses"], ["strong-reasoning", "local-strong-review"])
            self.assertEqual(profile["budgetCap"]["maxInvocations"], 3)
            self.assertFalse(profile["independencePolicy"]["required"])
            self.assertTrue(profile_path.is_file())

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

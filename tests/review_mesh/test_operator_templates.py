from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.review_mesh.operator_templates import (
    REVIEW_MESH_OPERATOR_TEMPLATE_IDS,
    get_review_mesh_operator_template,
    list_review_mesh_operator_templates,
    parse_reviewer_spec,
    prepare_review_mesh_operator_packets,
    validate_review_mesh_operator_template,
)


class ReviewMeshOperatorTemplateTests(unittest.TestCase):
    def test_built_in_templates_are_valid_and_provider_neutral(self) -> None:
        library = list_review_mesh_operator_templates()

        self.assertEqual(library["schemaVersion"], "agent-review-mesh-operator-template-library.v1")
        self.assertEqual(tuple(library["templateIds"]), REVIEW_MESH_OPERATOR_TEMPLATE_IDS)
        for template in library["templates"]:
            self.assertEqual(validate_review_mesh_operator_template(template)["status"], "PASS")
            self.assertFalse(template["hostExecutionStarted"])
            self.assertFalse(template["modelCallsStarted"])
            self.assertFalse(template["providerBrokerStarted"])
            reviewer_ids = {reviewer["id"] for reviewer in template["defaultReviewers"]}
            self.assertNotIn("codex", " ".join(sorted(reviewer_ids)))
            self.assertNotIn("claude", " ".join(sorted(reviewer_ids)))

    def test_prepare_writes_local_packets_without_host_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = prepare_review_mesh_operator_packets(
                source=_source(review_mesh_required=True),
                template_id="parallel-research-synthesis",
                reviewers=[
                    parse_reviewer_spec("codex-example:architecture-reviewer:strong-reasoning"),
                    parse_reviewer_spec("claude-example:risk-reviewer:strong-reasoning"),
                    parse_reviewer_spec("opencode-glm-example:local-reviewer:local-strong-review"),
                ],
                out_dir=root / "mesh",
                evidence_ids=["EV-PLAN"],
            )

            self.assertEqual(receipt["schemaVersion"], "agent-review-mesh-prepare-receipt.v1")
            self.assertEqual(receipt["status"], "PASS")
            self.assertEqual(receipt["mode"], "parallel-research-synthesis")
            self.assertEqual(receipt["reviewerCount"], 3)
            self.assertFalse(receipt["hostExecutionStarted"])
            self.assertFalse(receipt["modelCallsStarted"])
            self.assertFalse(receipt["providerBrokerStarted"])
            self.assertTrue((root / "mesh" / "profile.json").is_file())
            self.assertEqual(len(list((root / "mesh" / "assignments").glob("*.json"))), 3)
            self.assertEqual({artifact["role"] for artifact in receipt["artifacts"]}, {"profile", "assignment-packet"})

    def test_prepare_rejects_blocking_without_frozen_plan_opt_in(self) -> None:
        with self.assertRaises(LifecycleError) as raised:
            prepare_review_mesh_operator_packets(
                source=_source(review_mesh_required=False),
                template_id="leader-draft-review",
                blocking=True,
            )

        self.assertEqual(raised.exception.code, "review-mesh-prepare-blocking-without-plan-opt-in")

    def test_template_files_match_built_in_template_ids(self) -> None:
        root = Path(__file__).resolve().parents[2]
        template_dir = root / "templates" / "review-mesh"
        file_ids = {
            json.loads(path.read_text(encoding="utf-8"))["templateId"]
            for path in template_dir.glob("*.json")
        }

        self.assertEqual(file_ids, set(REVIEW_MESH_OPERATOR_TEMPLATE_IDS))
        for template_id in file_ids:
            self.assertEqual(get_review_mesh_operator_template(template_id)["templateId"], template_id)


def _source(*, review_mesh_required: bool) -> dict[str, object]:
    return {
        "kind": "PLAN_MANIFEST",
        "label": "release-x",
        "digest": "a" * 64,
        "status": "FROZEN",
        "reviewMesh": {"required": review_mesh_required},
    }


if __name__ == "__main__":
    unittest.main()

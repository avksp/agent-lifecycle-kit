from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import jsonschema

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.schemas import get_schema
from agent_lifecycle.review_mesh.results import import_review_mesh_result
from tests.review_mesh.test_operator_templates import _handoff_fixture, _prepare_handoff

ROOT = Path(__file__).resolve().parents[2]


class ReviewMeshContractExampleTests(unittest.TestCase):
    def test_public_docs_and_generated_example_share_the_real_raw_contract(self):
        for name in ("docs/reference/review-mesh.md", "docs/ru/reference/review-mesh.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for marker in ("reviewer-output.v1", "agent-review-mesh-result.v1", "--review-input", "SKIPPED"):
                self.assertIn(marker, text)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, inventory = _handoff_fixture(root)
            receipt = _prepare_handoff(root, manifest, inventory)
            packet = receipt["assignmentPackets"][0]
            format_ = packet["reviewerTask"]["responseFormat"]
            jsonschema.validate(format_["example"], get_schema("reviewer-output.v1"))
            jsonschema.validate(format_["example"], format_["contract"]["schema"])
            self.assertFalse(format_["exampleIsCompletion"])
            index = json.loads((root / "prepared/reading-index.json").read_bytes())
            for field in ("reviewChain", "authorityRefs", "budgetRefs", "previousFindings"):
                self.assertEqual(index["subject"][field], inventory[field])
            self.assertFalse(receipt["modelCallsStarted"])
            self.assertFalse(receipt["promptAuthorityGranted"])

    def test_normalized_result_cannot_be_presented_as_a_prepared_raw_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, inventory = _handoff_fixture(root)
            receipt = _prepare_handoff(root, manifest, inventory)
            packet = receipt["assignmentPackets"][0]
            kwargs = {"profile": receipt["profile"], "assignment": packet["assignment"]}
            normalized = import_review_mesh_result(
                **kwargs,
                reviewer_output=packet["reviewerTask"]["responseFormat"]["example"],
            )
            before = canonical_digest(normalized)
            with self.assertRaises(LifecycleError):
                import_review_mesh_result(**kwargs, reviewer_output=normalized)
            self.assertEqual(canonical_digest(normalized), before)

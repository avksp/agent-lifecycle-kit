from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import jsonschema

from agent_lifecycle.audit.delta_review import build_delta_review_packet
from agent_lifecycle.contracts.schemas import get_schema, list_schemas
from agent_lifecycle.review.validation import build_review_impact_graph, derive_delta_selection
from tests.review import synthetic_case


class PlanDeltaSchemaTests(unittest.TestCase):
    def test_public_plan_delta_schemas_are_registered(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}
        self.assertIn("agent-project-principles.v1", ids)
        self.assertIn("agent-plan-delta.v1", ids)
        self.assertIn("agent-plan-delta-validation.v1", ids)

    def test_generated_scope_selection_and_composite_match_public_schemas(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = synthetic_case(Path(tmp))
            subject = case["delta"]["subject"]
            values = [
                case["baseline"],
                case["delta"],
                case["composite"],
                case["delta"]["reviewScope"],
                build_review_impact_graph(case["manifest"]),
                derive_delta_selection(case["baseline"]["subject"], subject),
                build_delta_review_packet(subject, baseline=case["baseline"]),
            ]
            for value in values:
                with self.subTest(schema=value["schemaVersion"]):
                    jsonschema.validate(value, get_schema(value["schemaVersion"]))


if __name__ == "__main__":
    unittest.main()

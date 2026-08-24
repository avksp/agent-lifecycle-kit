from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from agent_lifecycle.contracts.independent_evidence_schemas import build_independence_requirement
from agent_lifecycle.planning.completeness import validate_plan_completeness

ROOT = Path(__file__).resolve().parents[2]


class PlanIndependenceRequirementCompletenessTests(unittest.TestCase):
    def _manifest(self) -> dict:
        manifest = json.loads((ROOT / "tests/planning/fixtures/canonical-plan-manifest.v1.json").read_text())
        manifest["releaseImpact"] = "bounded contract validation"
        requirement = build_independence_requirement()
        manifest["acceptance"]["criteria"][0]["independence"] = requirement
        manifest["acceptance"]["criteria"][0]["independentEvidenceIds"] = ["EV-INDEPENDENT"]
        manifest["acceptance"]["evidence"].append(
            {"id": "EV-INDEPENDENT", "description": "bounded independent evidence"}
        )
        manifest["workstreams"][0]["evidenceIds"].append("EV-INDEPENDENT")
        return manifest

    def test_required_independence_must_have_an_explicit_evidence_route(self) -> None:
        manifest = self._manifest()
        manifest["acceptance"]["criteria"][0].pop("independentEvidenceIds")

        validation = validate_plan_completeness(manifest)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("missing-independent-evidence-route", {item["code"] for item in validation["blockers"]})

    def test_optional_independence_does_not_add_a_blocker(self) -> None:
        manifest = self._manifest()
        manifest["acceptance"]["criteria"][0]["independence"] = build_independence_requirement(required=False)
        manifest["acceptance"]["criteria"][0].pop("independentEvidenceIds")

        validation = validate_plan_completeness(copy.deepcopy(manifest))

        self.assertEqual(validation["status"], "PASS")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import unittest
from pathlib import Path

from agent_lifecycle.contracts.independent_evidence_schemas import build_independence_requirement
from agent_lifecycle.planning.manifest_contract import validate_plan_manifest_contract

ROOT = Path(__file__).resolve().parents[2]


class PlanIndependenceRequirementContractTests(unittest.TestCase):
    def test_acceptance_criterion_can_declare_independence(self) -> None:
        manifest = json.loads((ROOT / "tests/planning/fixtures/canonical-plan-manifest.v1.json").read_text())
        criterion = manifest["acceptance"]["criteria"][0]
        requirement = build_independence_requirement()
        criterion["independence"] = requirement
        criterion["independentEvidenceIds"] = ["EV-INDEPENDENT"]

        validation = validate_plan_manifest_contract(manifest)

        self.assertEqual(validation["status"], "PASS")

    def test_independence_requirement_extension_keeps_manifest_contract_open(self) -> None:
        manifest = json.loads((ROOT / "tests/planning/fixtures/canonical-plan-manifest.v1.json").read_text())
        criterion = manifest["acceptance"]["criteria"][0]
        requirement = build_independence_requirement()
        requirement["unexpected"] = True
        criterion["independence"] = requirement
        criterion["independentEvidenceIds"] = ["EV-INDEPENDENT"]

        validation = validate_plan_manifest_contract(manifest)

        self.assertEqual(validation["status"], "PASS")


if __name__ == "__main__":
    unittest.main()

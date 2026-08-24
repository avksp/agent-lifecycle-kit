from __future__ import annotations

import unittest

from agent_lifecycle.contracts.finding_check_schemas import build_finding_check_binding
from agent_lifecycle.contracts.proof_validation import build_finding_identity
from agent_lifecycle.planning.deltas import build_plan_delta, finding_check_plan_lineage
from agent_lifecycle.workflow.artifacts import (
    build_finding_check_evidence_artifact,
    validate_finding_check_evidence_artifact,
)


class FindingCheckEvidenceTests(unittest.TestCase):
    def test_evidence_is_read_only_and_lineage_bound(self) -> None:
        finding = build_finding_identity({"path": "src/fix.py", "ruleId": "M1", "message": "issue"})
        delta = build_plan_delta(_manifest(1), _manifest(2))
        binding = build_finding_check_binding(
            finding_id=finding["findingId"],
            finding_digest=finding["findingDigest"],
            plan_delta_digest=delta["deltaDigest"],
            plan_lineage=finding_check_plan_lineage(delta),
            check_identity={"id": "check", "route": "release/86"},
            owner="WS86-02",
            scope={"paths": ["src/fix.py"]},
            source_revision="a" * 40,
        )
        evidence = build_finding_check_evidence_artifact(
            binding,
            result="PASS",
            source_revision="a" * 40,
            evidence_ids=["EV86-NEGATIVE"],
        )
        self.assertTrue(evidence["readOnly"])
        self.assertEqual(validate_finding_check_evidence_artifact(evidence, binding=binding)["status"], "PASS")
        evidence["sourceRevision"] = "b" * 40
        self.assertEqual(validate_finding_check_evidence_artifact(evidence, binding=binding)["status"], "FAIL")


def _manifest(revision: int) -> dict:
    return {
        "package": {"id": "release-1-86"},
        "planRevision": revision,
        "status": "FROZEN",
        "baseRevision": {"ref": "main", "sha": "a" * 40},
        "specification": {"requirements": [{"id": "R1", "description": "issue"}]},
        "workstreams": [{"id": "WS1", "writes": ["src/fix.py"], "evidenceIds": ["EV1"]}],
        "acceptance": {"criteria": [{"id": "AC1", "requirementIds": ["R1"], "evidenceIds": ["EV1"]}]},
        "validation": {"extraEvidence": ["EV1"]},
        "securityGates": ["offline"],
        "finalAuditGates": ["[AC1|EV1] evidence"],
    }


if __name__ == "__main__":
    unittest.main()

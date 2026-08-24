from __future__ import annotations

import unittest

from agent_lifecycle.audit import build_finding_check_adoption_audit
from agent_lifecycle.audit.proof_findings import build_finding_check_binding
from agent_lifecycle.contracts.finding_check_schemas import validate_finding_check_binding
from agent_lifecycle.contracts.proof_validation import build_finding_identity
from agent_lifecycle.planning.deltas import build_plan_delta, finding_check_plan_lineage


class FindingCheckBindingAuditTests(unittest.TestCase):
    def test_audit_facing_export_builds_stable_binding(self) -> None:
        finding = build_finding_identity({"path": "src/fix.py", "ruleId": "M1", "message": "issue"})
        delta = build_plan_delta(_manifest(1), _manifest(2))
        binding = build_finding_check_binding(
            finding_id=finding["findingId"],
            finding_digest=finding["findingDigest"],
            plan_delta_digest=delta["deltaDigest"],
            plan_lineage=finding_check_plan_lineage(delta),
            check_identity={"id": "check", "route": "release/86"},
            owner="WS86-01",
            scope={"paths": ["src/fix.py"]},
            source_revision="a" * 40,
        )
        self.assertEqual(binding["bindingId"].split("-")[0:2], ["finding", "check"])
        self.assertEqual(validate_finding_check_binding(binding)["status"], "PASS")
        audit = build_finding_check_adoption_audit(
            findings=[finding],
            bindings=[binding],
            plan_deltas=[delta],
        )
        self.assertEqual(audit["status"], "PASS")


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

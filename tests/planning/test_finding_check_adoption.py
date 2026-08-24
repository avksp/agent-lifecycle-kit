from __future__ import annotations

import unittest

from agent_lifecycle.contracts.finding_check_schemas import validate_finding_check_proposal
from agent_lifecycle.contracts.proof_validation import build_finding_identity
from agent_lifecycle.planning.deltas import build_plan_delta
from agent_lifecycle.planning.traceability import validate_finding_check_traceability
from agent_lifecycle.policy import build_finding_check_proposal


class FindingCheckAdoptionTests(unittest.TestCase):
    def test_proposal_is_advisory_until_explicit_approval(self) -> None:
        proposal = build_finding_check_proposal(
            finding={"path": "src/fix.py", "ruleId": "H1", "severity": "HIGH", "message": "issue"},
            plan_delta=build_plan_delta(_manifest(1), _manifest(2)),
            check_identity={"id": "check", "route": "release/86"},
            owner="WS86-01",
            scope={"paths": ["src/fix.py"]},
            source_revision="a" * 40,
        )
        self.assertEqual(proposal["status"], "PASS")
        self.assertFalse(proposal["applyAllowed"])
        self.assertTrue(proposal["approvalRequired"])
        self.assertEqual(validate_finding_check_proposal(proposal)["status"], "PASS")
        traceability = validate_finding_check_traceability(
            findings=[build_finding_identity({"path": "src/fix.py", "ruleId": "H1", "severity": "HIGH", "message": "issue"})],
            bindings=[proposal["binding"]],
            plan_deltas=[build_plan_delta(_manifest(1), _manifest(2))],
        )
        self.assertEqual(traceability["status"], "PASS")

    def test_blocked_plan_delta_cannot_be_adopted(self) -> None:
        before = _manifest(1)
        after = _manifest(1)
        proposal = build_finding_check_proposal(
            finding=build_finding_identity({"path": "src/fix.py", "ruleId": "H1", "message": "issue"}),
            plan_delta=build_plan_delta(before, after),
            check_identity={"id": "check", "route": "release/86"},
            owner="WS86-01",
            scope={"paths": ["src/fix.py"]},
            source_revision="a" * 40,
        )
        self.assertEqual(proposal["status"], "FAIL")
        self.assertFalse(proposal["authorityClaimed"])

    def test_traceability_rejects_tampered_evidence_digest(self) -> None:
        finding = {"path": "src/fix.py", "ruleId": "H1", "severity": "HIGH", "message": "issue"}
        identity = build_finding_identity(finding)
        delta = build_plan_delta(_manifest(1), _manifest(2))
        proposal = build_finding_check_proposal(
            finding=finding,
            plan_delta=delta,
            check_identity={"id": "check", "route": "release/86"},
            owner="WS86-01",
            scope={"paths": ["src/fix.py"]},
            source_revision="a" * 40,
        )
        binding = proposal["binding"]
        evidence = {
            "schemaVersion": "agent-finding-check-evidence.v1",
            "status": "PASS",
            "bindingId": binding["bindingId"],
            "findingId": identity["findingId"],
            "checkIdentity": dict(binding["checkIdentity"]),
            "sourceRevision": binding["sourceRevision"],
            "result": "PASS",
            "evidenceIds": ["EV-86"],
            "readOnly": True,
            "modelCallsStarted": False,
            "hostLaunchStarted": False,
            "productionPromotionClaimed": False,
            "evidenceDigest": "0" * 64,
        }
        traceability = validate_finding_check_traceability(
            findings=[identity],
            bindings=[binding],
            plan_deltas=[delta],
            evidence=[evidence],
        )
        self.assertEqual(traceability["status"], "FAIL")
        self.assertIn("finding-check-evidence-invalid", {item["code"] for item in traceability["blockers"]})


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

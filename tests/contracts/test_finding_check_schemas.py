from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.finding_check_schemas import (
    build_finding_check_binding,
    build_finding_check_evidence,
    transition_finding_check_binding,
    validate_finding_check_binding,
    validate_finding_check_evidence,
)
from agent_lifecycle.contracts.proof_validation import build_finding_identity
from agent_lifecycle.planning.deltas import build_plan_delta, finding_check_plan_lineage


class FindingCheckSchemaTests(unittest.TestCase):
    def test_binding_lifecycle_is_authorized_and_idempotent(self) -> None:
        binding = _binding()
        authorization = _authorization("accept")
        accepted = transition_finding_check_binding(binding, "ACCEPTED", authorization=authorization)
        self.assertEqual(accepted["status"], "PASS")
        self.assertEqual(accepted["binding"]["status"], "ACCEPTED")

        repeated = transition_finding_check_binding(accepted["binding"], "ACCEPTED", authorization=authorization)
        self.assertTrue(repeated["idempotent"])

        evidence = build_finding_check_evidence(
            accepted["binding"],
            result="PASS",
            source_revision="a" * 40,
            evidence_ids=["EV-86"],
        )
        implemented = transition_finding_check_binding(
            accepted["binding"],
            "IMPLEMENTED",
            authorization=_authorization("implemented"),
            evidence=evidence,
        )
        verified = transition_finding_check_binding(
            implemented["binding"],
            "VERIFIED",
            authorization=_authorization("verified"),
            evidence=evidence,
        )
        retired = transition_finding_check_binding(
            verified["binding"],
            "RETIRED",
            authorization=_authorization("retired"),
        )
        self.assertEqual(retired["binding"]["status"], "RETIRED")
        self.assertEqual(validate_finding_check_binding(retired["binding"])["status"], "PASS")

    def test_check_identity_cannot_contain_executable_text(self) -> None:
        with self.assertRaisesRegex(LifecycleError, "executable"):
            _binding(check_identity={"id": "check", "route": "tests", "command": "rm -rf /"})

    def test_tampered_evidence_and_stale_source_fail_closed(self) -> None:
        binding = _binding()
        evidence = build_finding_check_evidence(
            binding,
            result="PASS",
            source_revision="a" * 40,
            evidence_ids=["EV-86"],
        )
        evidence["checkIdentity"]["route"] = "changed"
        self.assertEqual(validate_finding_check_evidence(evidence, binding)["status"], "FAIL")
        stale = build_finding_check_evidence(
            binding,
            result="PASS",
            source_revision="b" * 40,
            evidence_ids=["EV-86"],
        )
        with self.assertRaises(LifecycleError):
            transition_finding_check_binding(
                binding,
                "IMPLEMENTED",
                authorization=_authorization("stale"),
                evidence=stale,
            )

    def test_binding_identity_tampering_fails_closed(self) -> None:
        binding = _binding()
        binding["bindingId"] = "finding-check-tampered"
        binding["bindingDigest"] = canonical_digest(
            {key: value for key, value in binding.items() if key != "bindingDigest"}
        )
        validation = validate_finding_check_binding(binding)
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("finding-check-binding-id-mismatch", {item["code"] for item in validation["blockers"]})


def _binding(*, check_identity: dict[str, str] | None = None) -> dict:
    finding = build_finding_identity({"path": "src/example.py", "ruleId": "H1", "severity": "HIGH", "message": "defect"})
    delta = build_plan_delta(_manifest(1, "before"), _manifest(2, "after"))
    return build_finding_check_binding(
        finding_id=finding["findingId"],
        finding_digest=finding["findingDigest"],
        plan_delta_digest=delta["deltaDigest"],
        plan_lineage=finding_check_plan_lineage(delta),
        check_identity=check_identity or {"id": "check-86", "route": "validation/finding-check"},
        owner="WS86-01",
        scope={"paths": ["src/example.py"]},
        source_revision="a" * 40,
    )


def _authorization(operation_id: str) -> dict[str, object]:
    return {"status": "APPROVED", "actor": "operator", "operationId": operation_id, "authorityClaimed": False}


def _manifest(revision: int, description: str) -> dict:
    return {
        "package": {"id": "release-1-86"},
        "planRevision": revision,
        "status": "FROZEN",
        "baseRevision": {"ref": "main", "sha": "a" * 40},
        "specification": {"requirements": [{"id": "R1", "description": description}]},
        "workstreams": [{"id": "WS1", "writes": ["src/example.py"], "evidenceIds": ["EV-86"]}],
        "acceptance": {"criteria": [{"id": "AC1", "requirementIds": ["R1"], "evidenceIds": ["EV-86"]}]},
        "validation": {"extraEvidence": ["EV-86"]},
        "budgetPolicy": {"modelTokenBudget": 0},
        "securityGates": ["offline"],
        "finalAuditGates": ["[AC1|EV-86] evidence"],
    }


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.finding_check_schemas import (
    build_finding_check_binding,
    build_finding_check_evidence,
    build_finding_check_proposal,
    build_finding_impact_scope,
    transition_finding_check_binding,
    validate_finding_check_binding,
    validate_finding_check_evidence,
    validate_finding_check_proposal,
    validate_finding_impact_scope,
)
from agent_lifecycle.contracts.proof_validation import build_finding_identity
from agent_lifecycle.planning.deltas import build_plan_delta, finding_check_plan_lineage


class FindingCheckSchemaTests(unittest.TestCase):
    def test_frozen_impact_scope_is_exact_and_source_bound(self) -> None:
        scope = build_finding_impact_scope(
            finding_id="F-1",
            finding_digest="a" * 64,
            plan_revision=2,
            plan_digest="b" * 64,
            source_revision="c" * 40,
            paths=["src/agent_lifecycle/example.py"],
            modules=["agent_lifecycle.example"],
            ownership_paths=["src/agent_lifecycle/example.py"],
            acceptance_ids=["AC-1"],
            gate_ids=["gate-1"],
        )

        self.assertEqual(validate_finding_impact_scope(scope)["status"], "PASS")
        scope["sourceRevision"] = "d" * 40
        self.assertEqual(validate_finding_impact_scope(scope)["status"], "FAIL")

    def test_impact_scope_rejects_unknown_fields_even_with_recomputed_digest(self) -> None:
        scope = build_finding_impact_scope(
            finding_id="F-1",
            finding_digest="a" * 64,
            plan_revision=2,
            plan_digest="b" * 64,
            source_revision="c" * 40,
            paths=["src/agent_lifecycle/example.py"],
            modules=["agent_lifecycle.example"],
        )
        scope["reviewerText"] = "not authority"
        scope["scopeDigest"] = canonical_digest({key: value for key, value in scope.items() if key != "scopeDigest"})

        validation = validate_finding_impact_scope(scope)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("finding-impact-scope-shape", {item["code"] for item in validation["blockers"]})

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

    def test_reviewer_reproduction_is_advisory_and_never_parsed_as_command(self) -> None:
        for reproduction in (
            'python -c \'open("owned", "w")\'',
            "--output=../../owned",
            "TOKEN=value command",
            "check; rm -rf /",
        ):
            with self.subTest(reproduction=reproduction):
                proposal = build_finding_check_proposal(_binding(), reproduction=reproduction)
                self.assertEqual(validate_finding_check_proposal(proposal)["status"], "PASS")
                self.assertEqual(proposal["reviewerReproduction"]["text"], reproduction)
                self.assertFalse(proposal["reviewerReproduction"]["parsedAsCommand"])
                self.assertFalse(proposal["applyAllowed"])

    def test_check_route_rejects_traversal_identity(self) -> None:
        with self.assertRaises(LifecycleError):
            _binding(check_identity={"id": "check", "route": "../../etc/passwd"})

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
    finding = build_finding_identity(
        {"path": "src/example.py", "ruleId": "H1", "severity": "HIGH", "message": "defect"}
    )
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

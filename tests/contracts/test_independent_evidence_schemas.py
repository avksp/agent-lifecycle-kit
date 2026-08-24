from __future__ import annotations

import unittest
from copy import deepcopy

from agent_lifecycle.contracts.independent_evidence_schemas import (
    build_independence_requirement,
    build_independent_evidence,
    validate_independent_evidence,
)
from agent_lifecycle.contracts.schemas import get_schema


class IndependentEvidenceSchemaTests(unittest.TestCase):
    def test_registry_contains_requirement_and_evidence_contracts(self) -> None:
        self.assertEqual(get_schema("agent-independence-requirement.v1")["$id"], "agent-independence-requirement.v1")
        self.assertEqual(get_schema("agent-independent-evidence.v1")["$id"], "agent-independent-evidence.v1")

    def test_bounded_evidence_validates_for_required_criterion(self) -> None:
        requirement = build_independence_requirement(
            prohibited_producer_classes=["implementation-worker"],
            allowed_methods=["deterministic-check"],
        )
        evidence = build_independent_evidence(
            evidence_id="EV-IND-1",
            criterion_id="AC-IND-1",
            requirement=requirement,
            source_revision="source-revision-1",
            source_lineage_digest="1" * 64,
            method="deterministic-check",
            producer_class="independent-reviewer",
            producer_identity_hash="2" * 64,
            implementation_digest="3" * 64,
        )

        validation = validate_independent_evidence(evidence, requirement=requirement)

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(validation["independenceStatus"], "REQUIRED_PASS")

    def test_shared_producer_and_stale_source_fail_closed(self) -> None:
        requirement = build_independence_requirement(prohibited_producer_classes=["implementation-worker"])
        evidence = build_independent_evidence(
            evidence_id="EV-IND-2",
            criterion_id="AC-IND-2",
            requirement=requirement,
            source_revision="source-revision-1",
            source_lineage_digest="4" * 64,
            method="human-review",
            producer_class="independent-reviewer",
            producer_identity_hash="5" * 64,
            implementation_digest="6" * 64,
        )
        evidence = deepcopy(evidence)
        evidence["producerClass"] = "implementation-worker"
        evidence["sourceRevision"] = "source-revision-1"
        from agent_lifecycle.contracts import canonical_digest

        evidence.pop("evidenceDigest")
        evidence["evidenceDigest"] = canonical_digest(evidence)

        validation = validate_independent_evidence(
            evidence,
            requirement=requirement,
            expected_source_revision="source-revision-2",
        )

        codes = {item["code"] for item in validation["blockers"]}
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("independent-evidence-producer-not-independent", codes)
        self.assertIn("independent-evidence-source-stale", codes)

    def test_unavailable_required_evidence_is_not_a_pass(self) -> None:
        requirement = build_independence_requirement()
        evidence = {
            "schemaVersion": "agent-independent-evidence.v1",
            "status": "UNAVAILABLE",
            "evidenceId": "EV-IND-3",
            "criterionId": "AC-IND-3",
            "requirementDigest": requirement["requirementDigest"],
            "sourceRevision": "source-revision-1",
            "sourceLineageDigest": "7" * 64,
            "method": "human-review",
            "producerClass": "independent-reviewer",
            "producerIdentityHash": "8" * 64,
            "implementationDigest": "9" * 64,
            "findings": [],
            "unavailableReason": "reviewer unavailable",
            "rawReasoningStored": False,
            "rawTranscriptStored": False,
            "productionPromotionClaimed": False,
        }
        from agent_lifecycle.contracts import canonical_digest

        evidence["evidenceDigest"] = canonical_digest(evidence)

        validation = validate_independent_evidence(evidence, requirement=requirement)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("independent-evidence-required", {item["code"] for item in validation["blockers"]})

    def test_malformed_requirement_lists_fail_closed_without_type_error(self) -> None:
        requirement = build_independence_requirement()
        requirement["requiredDimensions"] = [{"unexpected": True}]

        validation = validate_independent_evidence({}, requirement=requirement)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("independent-evidence-requirement-invalid", {item["code"] for item in validation["blockers"]})


if __name__ == "__main__":
    unittest.main()

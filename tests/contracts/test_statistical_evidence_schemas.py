from __future__ import annotations

import unittest
from copy import deepcopy

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.schemas import get_schema
from agent_lifecycle.contracts.statistical_evidence_schemas import (
    MAX_STATISTICAL_SAMPLES,
    build_statistical_evidence_requirement,
    build_statistical_evidence_set,
    required_rule_of_three_sample_count,
    validate_statistical_evidence_set,
)


class StatisticalEvidenceSchemaTests(unittest.TestCase):
    source_revision = "source-revision-1"
    lineage_digest = "a" * 64
    implementation_producer = "b" * 64
    independent_producer = "c" * 64

    def test_registry_contains_statistical_evidence_contracts(self) -> None:
        self.assertEqual(
            get_schema("agent-statistical-evidence-requirement.v1")["$id"],
            "agent-statistical-evidence-requirement.v1",
        )
        self.assertEqual(
            get_schema("agent-statistical-evidence-set.v1")["$id"],
            "agent-statistical-evidence-set.v1",
        )

    def test_rule_of_three_exact_boundaries(self) -> None:
        self.assertEqual(required_rule_of_three_sample_count(0.02), 150)
        self.assertEqual(required_rule_of_three_sample_count(0.01), 300)
        for threshold, below, enough in ((0.02, 149, 150), (0.01, 299, 300)):
            requirement = build_statistical_evidence_requirement(threshold=threshold)
            failing = self._evidence(requirement, below)
            passing = self._evidence(requirement, enough)

            self.assertEqual(failing["status"], "FAIL")
            self.assertIn(
                "statistical-effective-sample-insufficient",
                {item["code"] for item in failing["blockers"]},
            )
            self.assertEqual(passing["status"], "PASS")
            self.assertEqual(passing["effectiveIndependentCount"], enough)

    def test_duplicate_stale_and_shared_producer_fail_closed(self) -> None:
        requirement = build_statistical_evidence_requirement(threshold=0.02)
        samples = self._samples(150)
        samples[1]["sampleIdentity"] = samples[0]["sampleIdentity"]
        samples[2]["sourceRevision"] = "stale-revision"
        samples[3]["producerIdentityHash"] = self.implementation_producer

        evidence = build_statistical_evidence_set(
            criterion_id="AC-STAT",
            requirement=requirement,
            samples=samples,
            source_revision=self.source_revision,
            source_lineage_digest=self.lineage_digest,
            implementation_producer_identity_hashes=[self.implementation_producer],
        )

        codes = {item["code"] for item in evidence["blockers"]}
        self.assertEqual(evidence["status"], "FAIL")
        self.assertEqual(evidence["effectiveIndependentCount"], 147)
        self.assertIn("statistical-sample-identity-duplicate", codes)
        self.assertIn("statistical-sample-source-stale", codes)
        self.assertIn("statistical-shared-producer-undisclosed", codes)
        self.assertIn("statistical-sample-producer-not-independent", codes)

    def test_claim_mutations_are_rebuilt_during_validation(self) -> None:
        requirement = build_statistical_evidence_requirement(threshold=0.02)
        evidence = self._evidence(requirement, 150)
        mutated = deepcopy(evidence)
        mutated["effectiveIndependentCount"] = 151
        mutated["adequate"] = True
        mutated["evidenceDigest"] = canonical_digest(
            {key: value for key, value in mutated.items() if key != "evidenceDigest"}
        )

        validation = validate_statistical_evidence_set(
            mutated,
            requirement=requirement,
            expected_source_revision=self.source_revision,
            expected_source_lineage_digest=self.lineage_digest,
            implementation_producer_identity_hashes=[self.implementation_producer],
        )

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn(
            "statistical-evidence-derived-field-mismatch",
            {item["code"] for item in validation["blockers"]},
        )

    def test_source_lineage_mutation_fails_with_stable_blocker(self) -> None:
        requirement = build_statistical_evidence_requirement(threshold=0.02)
        evidence = self._evidence(requirement, 150)

        validation = validate_statistical_evidence_set(
            evidence,
            requirement=requirement,
            expected_source_revision=self.source_revision,
            expected_source_lineage_digest="d" * 64,
            implementation_producer_identity_hashes=[self.implementation_producer],
        )

        codes = {item["code"] for item in validation["blockers"]}
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("statistical-evidence-lineage-mismatch", codes)
        self.assertIn("statistical-sample-lineage-mismatch", codes)

    def test_observed_error_invalidates_zero_error_method(self) -> None:
        requirement = build_statistical_evidence_requirement(threshold=0.02)
        samples = self._samples(150)
        samples[0]["observedError"] = True

        evidence = build_statistical_evidence_set(
            criterion_id="AC-STAT",
            requirement=requirement,
            samples=samples,
            source_revision=self.source_revision,
            source_lineage_digest=self.lineage_digest,
            implementation_producer_identity_hashes=[self.implementation_producer],
        )

        self.assertEqual(evidence["status"], "FAIL")
        self.assertIn(
            "statistical-rule-of-three-observed-errors",
            {item["code"] for item in evidence["blockers"]},
        )

    def test_raw_sample_fields_are_not_stored_in_portable_evidence(self) -> None:
        requirement = build_statistical_evidence_requirement(threshold=0.02)
        samples = self._samples(150)
        samples[0]["rawPayload"] = {"prompt": "must not be copied"}

        evidence = build_statistical_evidence_set(
            criterion_id="AC-STAT",
            requirement=requirement,
            samples=samples,
            source_revision=self.source_revision,
            source_lineage_digest=self.lineage_digest,
            implementation_producer_identity_hashes=[self.implementation_producer],
        )
        validation = validate_statistical_evidence_set(
            evidence,
            requirement=requirement,
            expected_source_revision=self.source_revision,
            expected_source_lineage_digest=self.lineage_digest,
            implementation_producer_identity_hashes=[self.implementation_producer],
        )

        self.assertNotIn("rawPayload", evidence["samples"][0])
        self.assertNotIn("must not be copied", str(evidence))
        self.assertEqual(validation["status"], "PASS")

    def test_malformed_requirement_fails_closed_without_exception(self) -> None:
        evidence = {
            "schemaVersion": "agent-statistical-evidence-set.v1",
            "criterionId": "AC-STAT",
            "samples": [],
        }
        invalid_requirements = [None, {}, {"threshold": 0}, {"confidenceMethod": "unknown"}]

        for requirement in invalid_requirements:
            with self.subTest(requirement=requirement):
                validation = validate_statistical_evidence_set(
                    evidence,
                    requirement=requirement,  # type: ignore[arg-type]
                    expected_source_revision=self.source_revision,
                    expected_source_lineage_digest=self.lineage_digest,
                )
                self.assertEqual(validation["status"], "FAIL")
                self.assertIn(
                    "statistical-evidence-requirement-invalid",
                    {item["code"] for item in validation["blockers"]},
                )

    def test_statistical_evidence_has_a_bounded_sample_cap(self) -> None:
        schema = get_schema("agent-statistical-evidence-set.v1")

        self.assertEqual(schema["properties"]["samples"]["maxItems"], MAX_STATISTICAL_SAMPLES)

    def _evidence(self, requirement: dict, count: int) -> dict:
        return build_statistical_evidence_set(
            criterion_id="AC-STAT",
            requirement=requirement,
            samples=self._samples(count),
            source_revision=self.source_revision,
            source_lineage_digest=self.lineage_digest,
            implementation_producer_identity_hashes=[self.implementation_producer],
        )

    def _samples(self, count: int) -> list[dict]:
        return [
            {
                "sampleIdentity": canonical_digest({"sample": index}),
                "sourceClass": "INDEPENDENT_HOLDOUT",
                "derivation": "tracked-holdout-fixture",
                "sourceRevision": self.source_revision,
                "sourceLineageDigest": self.lineage_digest,
                "producerClass": "independent-reviewer",
                "producerIdentityHash": self.independent_producer,
                "sharedProducerDisclosed": False,
                "observedError": False,
            }
            for index in range(count)
        ]


if __name__ == "__main__":
    unittest.main()

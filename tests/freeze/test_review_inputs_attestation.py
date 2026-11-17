"""Strict lock construction consumes the ordinary reviewed-lock entry point."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest, sha256_hex
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.reviewer_identity_schemas import REVIEWER_REQUIRED_LOCK, reviewer_attestation_authority
from agent_lifecycle.freeze.package_integrity import (
    build_reviewed_plan_lock_v2,
    verify_plan_lock_envelope,
    verify_plan_package_integrity,
)
from tests.review.test_reviewer_attestation_strict import OBSERVED, REVIEWER, WORKER, attest, policy_for

REVIEW_PATH = "packet/plan-review.json"
MANIFEST_PATH = "packet/plan.manifest.json"


class StrictPlanLockTests(TestCase):
    def setUp(self) -> None:
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve(strict=True)
        (self.root / "packet").mkdir()
        policy = policy_for("freeze")
        self.manifest = {
            "schemaVersion": "agent-plan-manifest.v1",
            "status": "FROZEN",
            "package": {"id": "strict", "planArtifactRoot": "packet"},
            "planRevision": 1,
            "baseRevision": {"sha": "a" * 40},
            "author": {"id": WORKER[0], "runId": WORKER[1]},
            "planFiles": sorted([MANIFEST_PATH, REVIEW_PATH]),
            "packageIntegrity": {"required": True, "inventorySource": "planFiles", "lockSchemaVersion": "agent-plan-lock.v2"},
            "planReview": {"report": REVIEW_PATH, "required": True, "reviewedRevision": 1, "verdict": "READY_TO_FREEZE"},
            "reviewerAttestationPolicy": policy,
            "reviewerAttestationAuthority": reviewer_attestation_authority(policy),
        }
        digest = canonical_digest(self.manifest)
        self.review = attest(
            policy,
            {
                "schemaVersion": "agent-plan-review.v1",
                "packageId": "strict",
                "planRevision": 1,
                "reviewedPlanHash": digest,
                "reviewId": "full",
                "verdict": "READY_TO_FREEZE",
                "fullReview": True,
                "findings": [],
                "reviewer": REVIEWER,
            },
            phase="freeze",
            lineage={"packageId": "strict", "planRevision": 1, "planDigest": digest, "sourceRevision": "a" * 40},
        )

    def build(self, manifest: dict, review: dict) -> dict:
        raw = canonical_bytes(review) + b"\n"
        (self.root / MANIFEST_PATH).write_bytes(canonical_bytes(manifest) + b"\n")
        (self.root / REVIEW_PATH).write_bytes(raw)
        with patch("agent_lifecycle.freeze.package_integrity.reviewer_observed_at", return_value=OBSERVED):
            return build_reviewed_plan_lock_v2(
                manifest, review, review_path=REVIEW_PATH, review_sha256=sha256_hex(raw), repository_root=self.root,
            )

    def test_required_lock_reverifies_exact_report_at_archived_time(self) -> None:
        lock = self.build(self.manifest, self.review)
        self.assertEqual(lock["schemaVersion"], REVIEWER_REQUIRED_LOCK)
        self.assertEqual(lock["reviewerAdmission"]["observedAt"], OBSERVED)
        self.assertTrue(verify_plan_package_integrity(self.manifest, lock, repository_root=self.root)["filesystemVerified"])

    def test_downgraded_lock_and_replayed_report_refuse(self) -> None:
        lock = self.build(self.manifest, self.review)
        with self.assertRaisesRegex(LifecycleError, "authority does not match"):
            verify_plan_lock_envelope(self.manifest, {**lock, "schemaVersion": "agent-plan-lock.v2"})
        revised = deepcopy(self.manifest)
        revised["planRevision"] = revised["planReview"]["reviewedRevision"] = 2
        with self.assertRaisesRegex(LifecycleError, "did not verify"):
            self.build(revised, self.review)
        self.assertFalse((self.root / "packet/plan.lock.json").exists())

    def test_required_proof_missing_or_report_mutated_does_not_build_lock(self) -> None:
        unsigned = {key: val for key, val in self.review.items() if key != "reviewerProvenance"}
        with self.assertRaisesRegex(LifecycleError, "requires an exact signed review"):
            self.build(self.manifest, unsigned)
        with self.assertRaisesRegex(LifecycleError, "did not verify"):
            self.build(self.manifest, {**self.review, "verdict": "CHANGES_REQUIRED"})
        self.assertFalse((self.root / "packet/plan.lock.json").exists())

    def test_advisory_reports_declared_without_changing_lock_format(self) -> None:
        advisory = deepcopy(self.manifest)
        advisory.pop("reviewerAttestationAuthority")
        advisory["reviewerAttestationPolicy"]["mode"] = "advisory"
        review = {key: val for key, val in self.review.items() if key != "reviewerProvenance"}
        review["reviewedPlanHash"] = canonical_digest(advisory)
        lock = self.build(advisory, review)
        self.assertEqual(lock["schemaVersion"], "agent-plan-lock.v2")
        verified = verify_plan_package_integrity(advisory, lock, repository_root=self.root)
        self.assertEqual(verified["reviewerAttestation"]["guarantee"], "DECLARED")

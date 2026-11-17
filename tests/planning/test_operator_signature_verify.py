"""Actual canonical freeze and plan verification with public synthetic signatures."""

from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.cli.plan_lock_commands import create_reviewed_plan_lock
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.operator_signature_schemas import operator_authority_marker
from agent_lifecycle.freeze import verify_plan_package_integrity
from agent_lifecycle.planning.verification import build_plan_verification
from agent_lifecycle.review.validation import make_review_scope
from tests.cli.test_plan_lock_commands import _write_reviewed_package
from tests.contracts.test_operator_signature import (
    NEGATIVE_CASES,
    envelope,
    inventory,
    negative_case,
    policy,
)
from tests.review import review_for, subject_for, synthetic_full_case, write_json


def write(path, value):
    path.write_bytes(canonical_bytes(value) + b"\n")


def prepare_package(root, mode="required", case=None):
    manifest_name, review_name = _write_reviewed_package(root)
    m = json.loads((root / manifest_name).read_bytes())
    m["baseRevision"] = {"ref": "test", "sha": "source"}
    m["operatorSignaturePolicy"] = policy(mode)
    if mode == "required":
        m["operatorSignatureAuthority"] = operator_authority_marker(m["operatorSignaturePolicy"])
    m["packageIntegrity"]["allowedUnlistedFiles"].append("operator-freeze-signature.json")
    signed = envelope(m)
    if case is not None:
        m, signed = negative_case(m, "freeze", case)
    write(root / manifest_name, m)
    review = json.loads((root / review_name).read_bytes())
    review["reviewedPlanHash"] = canonical_digest(m)
    write(root / review_name, review)
    signature = root / m["package"]["planArtifactRoot"] / "operator-freeze-signature.json"
    if signed is not None:
        write(signature, signed)
    return m, manifest_name, review_name


class OperatorSignaturePlanTests(unittest.TestCase):
    def test_scoped_v3_lock_also_requires_exact_signature_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = synthetic_full_case(root)
            m = case["manifest"]
            m["operatorSignaturePolicy"] = policy()
            m["operatorSignatureAuthority"] = operator_authority_marker(m["operatorSignaturePolicy"])
            m["packageIntegrity"].setdefault("allowedUnlistedFiles", ["plan.lock.json"]).append(
                "operator-freeze-signature.json"
            )
            write_json(root, "plans/r1/plan.manifest.json", m)
            report = review_for(root, subject_for(root, m), "single-full")
            report["currentApplicability"] = {
                "baselineDigest": None,
                "candidateHash": canonical_digest(m),
                "completeCoverage": True,
                "unchangedBaselineApplicable": True,
                "allChangesReviewed": True,
                "allBlockingFindingsResolved": True,
            }
            digest = write_json(root, "plans/r1/review.json", report)
            composite = {
                **case["composite"],
                "reviewedPlanHash": canonical_digest(m),
                "reviewScope": {**make_review_scope(report["subject"]), "kind": "COMPOSITE"},
                "reportBindings": {"plans/r1/review.json": digest},
            }
            write_json(root, "plans/r1/composite.json", composite)
            write_json(root, "plans/r1/operator-freeze-signature.json", envelope(m))
            receipt = create_reviewed_plan_lock(
                manifest_path="plans/r1/plan.manifest.json", review_path="plans/r1/composite.json", repository_root=root
            )
            lock = json.loads((root / receipt["lockPath"]).read_bytes())
            self.assertEqual(lock["schemaVersion"], "agent-plan-lock.v3")
            self.assertEqual(verify_plan_package_integrity(m, lock, repository_root=root)["status"], "PASS")
            lock.pop("operatorSignature")
            with self.assertRaises(LifecycleError):
                verify_plan_package_integrity(m, lock, repository_root=root)

    def test_actual_freeze_signature_bound_lock_and_repeatable_readonly_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            m, name, review = prepare_package(root)
            created = create_reviewed_plan_lock(manifest_path=name, review_path=review, repository_root=root)
            lock = json.loads((root / created["lockPath"]).read_bytes())
            self.assertTrue(lock["operatorSignature"]["signatureVerified"])
            before = inventory(root)
            for _ in range(2):
                result = build_plan_verification(m, manifest_path=root / name, lock=lock, repository_root=root)
                self.assertEqual(result["status"], "PASS", result)
            self.assertEqual(before, inventory(root))
            with self.assertRaises(LifecycleError) as caught:
                create_reviewed_plan_lock(manifest_path=name, review_path=review, repository_root=root)
            self.assertEqual(caught.exception.code, "plan-lock-exists")

    def test_seven_required_freeze_refusals_leave_package_byte_identical(self):
        for case in NEGATIVE_CASES:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _m, name, review = prepare_package(root, case=case)
                before = inventory(root)
                with self.assertRaises(LifecycleError):
                    create_reviewed_plan_lock(manifest_path=name, review_path=review, repository_root=root)
                self.assertEqual(inventory(root), before)
                self.assertFalse((root / "plans/release-test/plan.lock.json").exists())

    def test_unsigned_older_writer_lock_is_refused_and_advisory_can_continue(self):
        for mode in ("required", "advisory"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                m, name, review = prepare_package(root, mode)
                created = create_reviewed_plan_lock(manifest_path=name, review_path=review, repository_root=root)
                lock = json.loads((root / created["lockPath"]).read_bytes())
                lock.pop("operatorSignature")
                if mode == "required":
                    with self.assertRaises(LifecycleError):
                        verify_plan_package_integrity(m, lock, repository_root=root)
                else:
                    result = verify_plan_package_integrity(m, lock, repository_root=root)
                    self.assertEqual(result["status"], "PASS")
                    self.assertTrue(result["operatorSignature"]["signatureVerified"])

    def test_expired_frozen_signature_requires_revision_instead_of_in_place_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            m, name, review = prepare_package(root)
            created = create_reviewed_plan_lock(manifest_path=name, review_path=review, repository_root=root)
            lock = json.loads((root / created["lockPath"]).read_bytes())
            before = inventory(root)
            with (
                patch(
                    "agent_lifecycle.freeze.package_integrity.operator_observed_at",
                    return_value="2095-01-01T00:00:00.000000Z",
                ),
                self.assertRaises(LifecycleError),
            ):
                verify_plan_package_integrity(m, lock, repository_root=root)
            self.assertEqual(before, inventory(root))
            signed = envelope(m, expiresAt="2091-01-01T00:00:00.000000Z")
            write(root / m["package"]["planArtifactRoot"] / "operator-freeze-signature.json", signed)
            with self.assertRaises(LifecycleError) as caught:
                verify_plan_package_integrity(m, lock, repository_root=root)
            self.assertEqual(caught.exception.code, "operator-signature-lock-mismatch")

    def test_competing_canonical_freeze_has_one_winner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _m, name, review = prepare_package(root)

            def attempt():
                try:
                    create_reviewed_plan_lock(manifest_path=name, review_path=review, repository_root=root)
                    return "created"
                except LifecycleError as exc:
                    return exc.code

            with ThreadPoolExecutor(max_workers=2) as workers:
                outcomes = list(workers.map(lambda _: attempt(), range(2)))
            self.assertEqual(outcomes.count("created"), 1)
            self.assertEqual(outcomes.count("plan-lock-exists"), 1)

    def test_off_never_reads_or_adds_signature_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            name, review = _write_reviewed_package(root)
            with patch(
                "agent_lifecycle.contracts.operator_signature.read_stable_repository_file",
                side_effect=AssertionError("off must not read signatures"),
            ):
                created = create_reviewed_plan_lock(manifest_path=name, review_path=review, repository_root=root)
            lock = json.loads((root / created["lockPath"]).read_bytes())
            self.assertNotIn("operatorSignature", lock)


if __name__ == "__main__":
    unittest.main()

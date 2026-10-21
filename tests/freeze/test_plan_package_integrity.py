from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.cli.plan_lock_commands import create_reviewed_plan_lock
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.freeze import build_plan_lock_v2, verify_plan_package_integrity
from agent_lifecycle.freeze.package_integrity import build_reviewed_plan_lock_v2
from tests.review import synthetic_case, synthetic_full_case, write_json

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/freeze/fixtures/canonical-v2-plan-package"


class ScopedPlanPackageIntegrityTests(unittest.TestCase):
    def test_blocked_full_baseline_cannot_produce_composite_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = synthetic_case(root, negative=False, git_repository=True)
            case["baseline"]["verdict"] = "BLOCKED"
            digest = canonical_digest(case["baseline"])
            case["delta"]["dependsOn"] = [digest]
            case["delta"]["currentApplicability"]["baselineDigest"] = digest
            for path, report in case["reports"].items():
                case["composite"]["reportBindings"][path] = write_json(root, path, report)
            write_json(root, "plans/r2/review.json", case["composite"])
            before = self.snapshot(root)
            with self.assertRaises(LifecycleError) as raised:
                self.create(root)
            self.assertEqual(raised.exception.code, "review-baseline-verdict-unavailable")
            self.assertEqual(before, self.snapshot(root))

    def test_omitted_source_file_refuses_even_when_all_supplied_hashes_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            synthetic_case(root, git_repository=True)
            (root / "unreviewed.py").write_text("changed runtime", encoding="utf-8")
            before = self.snapshot(root)
            with self.assertRaises(LifecycleError) as raised:
                self.create(root)
            self.assertEqual(raised.exception.code, "review-runtime-incomplete")
            self.assertEqual(before, self.snapshot(root))

    def test_one_full_seat_uses_composite_v3_with_existing_v2_manifest_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = synthetic_full_case(root)
            receipt = create_reviewed_plan_lock(
                manifest_path="plans/r1/plan.manifest.json", review_path="plans/r1/composite.json", repository_root=root
            )
            lock = json.loads((root / receipt["lockPath"]).read_bytes())
            self.assertEqual(lock["schemaVersion"], "agent-plan-lock.v3")
            self.assertEqual(lock["reviewScopeKind"], "COMPOSITE")
            self.assertEqual(case["manifest"]["packageIntegrity"]["lockSchemaVersion"], "agent-plan-lock.v2")
            self.assertTrue(case["report"]["fullReview"])
            self.assertFalse(case["composite"]["fullReview"])
            lock["schemaVersion"] = "agent-plan-lock.v2"
            with self.assertRaises(LifecycleError) as raised:
                verify_plan_package_integrity(case["manifest"], lock, repository_root=root)
            self.assertEqual(raised.exception.code, "plan-lock-scope-required")

    def test_full_author_cannot_fill_an_independent_seat_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            synthetic_full_case(root, author="reviewer")
            before = self.snapshot(root)
            with self.assertRaises(LifecycleError) as raised:
                create_reviewed_plan_lock(
                    manifest_path="plans/r1/plan.manifest.json",
                    review_path="plans/r1/composite.json",
                    repository_root=root,
                )
            self.assertEqual(raised.exception.code, "review-not-independent")
            self.assertEqual(before, self.snapshot(root))

    def test_frozen_source_proof_survives_later_implementation_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = synthetic_case(root, git_repository=True)
            receipt = self.create(root)
            lock = json.loads((root / receipt["lockPath"]).read_bytes())
            original_lock = (root / receipt["lockPath"]).read_bytes()
            (root / "runtime.py").write_text("authorized later implementation", encoding="utf-8")
            (root / "added.py").write_text("new task output", encoding="utf-8")
            result = verify_plan_package_integrity(case["manifest"], lock, repository_root=root)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual((root / receipt["lockPath"]).read_bytes(), original_lock)
            # The exact same state is unsuitable for creating a new reviewed
            # lock: only the historical immutable proof remains applicable.
            with self.assertRaises(LifecycleError):
                verify_plan_package_integrity(
                    case["manifest"], lock, repository_root=root, require_current_review_source=True
                )

    def test_actual_lock_command_binds_full_negative_baseline_and_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = synthetic_case(root, git_repository=True)
            before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
            receipt = self.create(root)
            lock = json.loads((root / receipt["lockPath"]).read_bytes())
            result = verify_plan_package_integrity(case["manifest"], lock, repository_root=root)
            self.assertTrue(result["filesystemVerified"])
            self.assertEqual(lock["schemaVersion"], "agent-plan-lock.v3")
            self.assertEqual(lock["reviewScopeKind"], "COMPOSITE")
            self.assertIn("fix.txt", {entry["path"] for entry in lock["reviewEvidence"]})
            self.assertTrue(all(p.read_bytes() == data for p, data in before.items()))
            self.assertEqual(len([p for p in root.rglob("*") if p.is_file()]), len(before) + 1)

    def test_tampered_nested_inputs_refuse_before_any_authority_write(self):
        for target in ("plans/r1/review.json", "plans/r1/plan.md", "runtime.py", "fix.txt", "authority.txt"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                synthetic_case(root, git_repository=True)
                (root / target).write_bytes(b"altered")
                before = self.snapshot(root)
                with self.assertRaises(LifecycleError):
                    self.create(root)
                self.assertEqual(before, self.snapshot(root))
                self.assertFalse((root / "plans/r2/plan.lock.json").exists())

    def test_missing_and_symlinked_evidence_refuse_without_writes(self):
        for mode in ("missing", "symlink"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                synthetic_case(root, git_repository=True)
                (root / "fix.txt").unlink()
                if mode == "symlink":
                    (root / "fix.txt").symlink_to(root / "authority.txt")
                with self.assertRaises(LifecycleError):
                    self.create(root)
                self.assertFalse((root / "plans/r2/plan.lock.json").exists())

    def test_declared_expired_authority_is_not_a_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = synthetic_case(root, git_repository=True)
            case["delta"]["reviewAuthority"]["expiresAt"] = "2026-09-01T00:00:00Z"
            digest = write_json(root, "plans/r2/delta.json", case["delta"])
            case["composite"]["reportBindings"]["plans/r2/delta.json"] = digest
            write_json(root, "plans/r2/review.json", case["composite"])
            before = self.snapshot(root)
            with self.assertRaises(LifecycleError) as raised:
                self.create(root)
            self.assertEqual(raised.exception.code, "review-authority-expired")
            self.assertEqual(before, self.snapshot(root))

    def test_post_lock_changed_evidence_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = synthetic_case(root, git_repository=True)
            receipt = self.create(root)
            lock = json.loads((root / receipt["lockPath"]).read_bytes())
            (root / "fix.txt").write_text("changed", encoding="utf-8")
            with self.assertRaises(LifecycleError):
                verify_plan_package_integrity(case["manifest"], lock, repository_root=root)

    @staticmethod
    def create(root):
        return create_reviewed_plan_lock(
            manifest_path="plans/r2/plan.manifest.json", review_path="plans/r2/review.json", repository_root=root
        )

    @staticmethod
    def snapshot(root):
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class PlanPackageIntegrityTests(unittest.TestCase):
    def test_native_freeze_consumer_keeps_ordinary_and_refuses_stronger_claims_without_writes(self) -> None:
        claims = [
            ({}, True),
            ({"reviewerProvenance": {"guarantee": "DECLARED", "attestation": None}}, True),
            ({"reviewerProvenance": {"guarantee": "ATTESTED", "attestation": None}}, False),
            ({"reviewerProvenance": {}}, False),
            ({"provenanceValidation": {"status": "PASS", "guarantee": "ATTESTED"}}, False),
        ]
        with _temporary_fixture() as (root, package):
            manifest, _ = _fixture_payload(root=root, package=package)
            review_rel = (package / "review.json").relative_to(root).as_posix()
            manifest["planFiles"].append(review_rel)
            manifest["planReview"] = {
                "required": True,
                "report": review_rel,
                "reviewedRevision": manifest["planRevision"],
                "verdict": "READY_TO_FREEZE",
            }
            (package / "plan.manifest.json").write_bytes(canonical_bytes(manifest) + b"\n")
            for claim, allowed in claims:
                review = {
                    "schemaVersion": "agent-plan-review.v1",
                    "reviewId": "review",
                    "reviewer": {"id": "reviewer", "runId": "review-run", "surface": "unit", "independent": True},
                    "packageId": manifest["package"]["id"],
                    "planRevision": manifest["planRevision"],
                    "reviewedPlanHash": canonical_digest(manifest),
                    "fullReview": True,
                    "verdict": "READY_TO_FREEZE",
                    "findings": [],
                    **claim,
                }
                data = canonical_bytes(review) + b"\n"
                (root / review_rel).write_bytes(data)
                before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                with self.subTest(claim=claim):
                    if allowed:
                        lock = build_reviewed_plan_lock_v2(
                            manifest,
                            review,
                            review_path=review_rel,
                            review_sha256=hashlib.sha256(data).hexdigest(),
                            repository_root=root,
                        )
                        self.assertEqual(lock["schemaVersion"], "agent-plan-lock.v2")
                    else:
                        with self.assertRaises(LifecycleError) as caught:
                            build_reviewed_plan_lock_v2(
                                manifest,
                                review,
                                review_path=review_rel,
                                review_sha256=hashlib.sha256(data).hexdigest(),
                                repository_root=root,
                            )
                        self.assertEqual(caught.exception.code, "review-provenance-invalid")
                    self.assertEqual(
                        before, {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                    )

    def test_intact_fixture_passes_and_exposes_every_entry(self) -> None:
        manifest, lock = _fixture_payload()

        result = verify_plan_package_integrity(manifest, lock, repository_root=ROOT)

        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["filesystemVerified"])
        self.assertEqual(len(result["entries"]), 2)

    def test_same_size_mutation_is_rejected(self) -> None:
        with _temporary_fixture() as (root, package):
            manifest, lock = _fixture_payload(root=root, package=package)
            path = package / "plan.md"
            original = path.read_text(encoding="utf-8")
            path.write_text("X" + original[1:], encoding="utf-8")

            with self.assertRaises(LifecycleError) as raised:
                verify_plan_package_integrity(manifest, lock, repository_root=root)

        self.assertEqual(raised.exception.code, "plan-package-files-mismatch")

    def test_missing_file_is_rejected(self) -> None:
        with _temporary_fixture() as (root, package):
            manifest, lock = _fixture_payload(root=root, package=package)
            (package / "plan.md").unlink()

            with self.assertRaises(LifecycleError) as raised:
                verify_plan_package_integrity(manifest, lock, repository_root=root)

        self.assertIn(raised.exception.code, {"repository-file-missing", "plan-package-files-mismatch"})

    def test_undeclared_top_level_file_is_rejected(self) -> None:
        with _temporary_fixture() as (root, package):
            manifest, lock = _fixture_payload(root=root, package=package)
            (package / "extra.md").write_text("undeclared", encoding="utf-8")

            with self.assertRaises(LifecycleError) as raised:
                verify_plan_package_integrity(manifest, lock, repository_root=root)

        self.assertEqual(raised.exception.code, "plan-file-undeclared")

    def test_undeclared_top_level_directory_is_rejected(self) -> None:
        with _temporary_fixture() as (root, package):
            manifest, lock = _fixture_payload(root=root, package=package)
            (package / "workflow/task-packets").mkdir(parents=True)

            with self.assertRaises(LifecycleError) as raised:
                verify_plan_package_integrity(manifest, lock, repository_root=root)

        self.assertEqual(raised.exception.code, "plan-directory-undeclared")

    def test_duplicate_manifest_path_is_rejected(self) -> None:
        manifest, _lock = _fixture_payload()
        manifest["planFiles"].append(manifest["planFiles"][-1])

        with self.assertRaises(LifecycleError) as raised:
            build_plan_lock_v2(manifest, repository_root=ROOT)

        self.assertEqual(raised.exception.code, "plan-file-duplicate")

    def test_escaping_manifest_path_is_rejected(self) -> None:
        manifest, _lock = _fixture_payload()
        manifest["planFiles"][0] = "tests/freeze/fixtures/canonical-v2-plan-package/../outside.md"

        with self.assertRaises(LifecycleError) as raised:
            build_plan_lock_v2(manifest, repository_root=ROOT)

        self.assertEqual(raised.exception.code, "invalid-repo-path")

    def test_symlinked_declared_file_is_rejected(self) -> None:
        with _temporary_fixture() as (root, package):
            manifest, lock = _fixture_payload(root=root, package=package)
            target = package / "plan.md"
            target.unlink()
            target.symlink_to(root / "outside.md")
            (root / "outside.md").write_text("outside", encoding="utf-8")

            with self.assertRaises(LifecycleError) as raised:
                verify_plan_package_integrity(manifest, lock, repository_root=root)

        self.assertEqual(raised.exception.code, "repository-input-symlink")


def _fixture_payload(*, root: Path = ROOT, package: Path = FIXTURE) -> tuple[dict, dict]:
    manifest = json.loads((package / "plan.manifest.json").read_text(encoding="utf-8"))
    lock = build_plan_lock_v2(manifest, repository_root=root)
    return manifest, lock


class _temporary_fixture:
    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        destination = self.root / "tests/freeze/fixtures/canonical-v2-plan-package"
        destination.parent.mkdir(parents=True)
        shutil.copytree(FIXTURE, destination)
        return self.root, destination

    def __exit__(self, exc_type, exc_value, traceback):
        self.temp.cleanup()


if __name__ == "__main__":
    unittest.main()

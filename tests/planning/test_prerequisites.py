"""Local prerequisite identity, acceptance and non-mutation regressions."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.planning.manifest_contract import validate_plan_manifest_contract
from agent_lifecycle.planning.prerequisites import prerequisite_dependencies, validate_prerequisite_acceptance


class PrerequisiteAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.receipt = {
            "packageId": "previous",
            "sourceRevision": "a" * 40,
            "reviewer": {"id": "independent", "independent": True},
            "verdict": "ACCEPTED",
            "findings": [],
        }
        self.path = self.root / "accepted.json"
        self.path.write_text(json.dumps(self.receipt), encoding="utf-8")
        self.entry = {
            "packageId": "previous",
            "sourceRevision": "a" * 40,
            "evidencePath": "accepted.json",
            "sha256": self.digest(),
        }
        self.manifest = {
            "dependsOn": ["previous"],
            "extensions": {"prerequisiteAcceptance": {"required": True, "dependencies": [self.entry]}},
        }

    def digest(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def check(self, manifest: dict | None = None) -> dict:
        return validate_prerequisite_acceptance(manifest or self.manifest, repository_root=self.root)

    def test_accepting_local_identity_checks_without_mutation_or_promotion(self) -> None:
        before = copy.deepcopy(self.manifest), self.path.read_bytes()
        report = self.check()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["guarantee"], "DECLARED")
        self.assertFalse(report["productionPromotionClaimed"])
        self.assertEqual((self.manifest, self.path.read_bytes()), before)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_bare_history_and_empty_standalone_policy_need_no_receipts(self) -> None:
        manifests = [
            {"dependsOn": ["descriptive-only"]},
            {"extensions": {"prerequisiteAcceptance": {"required": True, "dependencies": []}}},
            {
                "dependsOn": ["optional"],
                "extensions": {"prerequisiteAcceptance": {"required": False, "dependencies": []}},
            },
        ]
        for manifest in manifests:
            with self.subTest(manifest=manifest):
                self.assertEqual(self.check(manifest)["dependencies"], [])

    def test_closed_shape_duplicates_and_required_coverage_fail(self) -> None:
        policy = self.manifest["extensions"]["prerequisiteAcceptance"]
        mutations = [
            None,
            {},
            {**policy, "required": 1},
            {**policy, "extra": True},
            {**policy, "dependencies": {}},
            {**policy, "dependencies": []},
            {**policy, "dependencies": [self.entry, self.entry]},
            {**policy, "dependencies": [{**self.entry, "extra": True}]},
            {**policy, "dependencies": [{**self.entry, "packageId": "unknown"}]},
            {**policy, "dependencies": [{**self.entry, "sha256": "ABC"}]},
        ]
        for mutation in mutations:
            with self.subTest(policy=mutation):
                manifest = copy.deepcopy(self.manifest)
                manifest["extensions"]["prerequisiteAcceptance"] = mutation
                with self.assertRaises(LifecycleError):
                    prerequisite_dependencies(manifest)

    def test_optional_supplied_evidence_is_not_ignored(self) -> None:
        self.manifest["extensions"]["prerequisiteAcceptance"]["required"] = False
        self.entry["sha256"] = "0" * 64
        with self.assertRaises(LifecycleError) as caught:
            self.check()
        self.assertEqual(caught.exception.code, "prerequisite-acceptance-hash-mismatch")

    def test_raw_bytes_not_parsed_equivalence_define_identity(self) -> None:
        self.path.write_text(json.dumps(self.receipt, indent=2), encoding="utf-8")
        with self.assertRaises(LifecycleError) as caught:
            self.check()
        self.assertEqual(caught.exception.code, "prerequisite-acceptance-hash-mismatch")

    def test_wrong_package_source_or_nonaccepting_review_refuses(self) -> None:
        mutations = [
            {"packageId": "other"},
            {"sourceRevision": "b" * 40},
            {"verdict": "READY_TO_FREEZE"},
            {"verdict": "CHANGES_REQUIRED"},
            {"verdict": "BLOCKED"},
            {"reviewer": {"independent": False}},
            {"findings": [{"id": "open", "severity": "HIGH", "status": "open"}]},
            {"reviewerProvenance": {"guarantee": "ATTESTED", "attestation": None}},
        ]
        for patch in mutations:
            with self.subTest(patch=patch):
                self.path.write_text(json.dumps({**self.receipt, **patch}), encoding="utf-8")
                self.entry["sha256"] = self.digest()
                with self.assertRaises(LifecycleError):
                    self.check()

    def test_unsafe_missing_and_symlinked_receipts_fail_without_outputs(self) -> None:
        for path in ("../outside.json", str(self.path), "./accepted.json", "attempt-{attempt}.json", "missing.json"):
            with self.subTest(path=path):
                self.entry["evidencePath"] = path
                with self.assertRaises(LifecycleError):
                    self.check()
        link = self.root / "link.json"
        link.symlink_to(self.path)
        self.entry["evidencePath"] = "link.json"
        with self.assertRaises(LifecycleError) as caught:
            self.check()
        self.assertEqual(caught.exception.code, "repository-input-symlink")

    def test_malformed_json_is_bounded_and_unambiguous(self) -> None:
        for raw in (b"[]", b'{"verdict":"ACCEPTED","verdict":"BLOCKED"}', b"{bad", b'{"n":NaN}'):
            with self.subTest(raw=raw):
                self.path.write_bytes(raw)
                self.entry["sha256"] = self.digest()
                with self.assertRaises(LifecycleError):
                    self.check()

    def test_manifest_contract_checks_policy_shape_without_reading_receipts(self) -> None:
        fixture = Path(__file__).parent / "fixtures/canonical-plan-manifest.v1.json"
        manifest = json.loads(fixture.read_text(encoding="utf-8"))
        manifest.update(copy.deepcopy(self.manifest))
        self.assertEqual(validate_plan_manifest_contract(manifest)["status"], "PASS")
        manifest["extensions"]["prerequisiteAcceptance"]["extra"] = True
        self.assertEqual(validate_plan_manifest_contract(manifest)["status"], "FAIL")

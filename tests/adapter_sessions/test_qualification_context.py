"""Frozen profile selection tests; no native success or model dispatch claims."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from contextlib import closing
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.accounting.host_bridge import BoundedReader
from agent_lifecycle.adapter_sessions import limited_native_evidence as native
from agent_lifecycle.adapter_sessions.qualification_context import (
    ADMISSION_PATH,
    CLAIM,
    LEGACY_CONTRACT_PATH,
    LEGACY_LOCK_PATH,
    LEGACY_MANIFEST_PATH,
    PRODUCERS,
    ROUTE,
    load_qualification_context,
)
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.freeze.package_integrity import build_plan_lock_v2
from tests.workflow.test_limited_usage import put


class QualificationContextTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        source = Path(__file__).parents[2]
        self.contract = json.loads((source / LEGACY_CONTRACT_PATH).read_bytes())
        self.manifest = {
            "schemaVersion": "agent-plan-manifest.v1",
            "status": "FROZEN",
            "planRevision": 1,
            "package": {"id": "release-2-16", "planArtifactRoot": "tasks/release-2-16"},
            "baseRevision": {"sha": "a" * 40},
            "packageIntegrity": {"required": True, "allowedUnlistedFiles": ["plan.lock.json"]},
            "planFiles": sorted([LEGACY_MANIFEST_PATH, LEGACY_CONTRACT_PATH]),
        }
        self.freeze()

    def freeze(self):
        put(self.root, LEGACY_CONTRACT_PATH, self.contract)
        put(self.root, LEGACY_MANIFEST_PATH, self.manifest)
        put(self.root, LEGACY_LOCK_PATH, build_plan_lock_v2(self.manifest, repository_root=self.root))

    def load(self, manifest=None):
        with closing(BoundedReader()) as reader:
            return load_qualification_context(
                self.root, reader, manifest=self.manifest if manifest is None else manifest
            )

    def test_exact_frozen_profile_derives_only_the_pinned_historical_context(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*.json")}
        context = self.load()
        self.assertEqual((ROUTE, CLAIM, ADMISSION_PATH), (context.route_id, context.claim, context.admission_path))
        self.assertEqual(PRODUCERS, context.producer_paths)
        self.assertEqual(24, len(context.rows))
        self.assertEqual(
            hashlib.sha256((self.root / LEGACY_CONTRACT_PATH).read_bytes()).hexdigest(), context.profile_sha256
        )
        with self.assertRaises(FrozenInstanceError):
            context.claim = "COMPLETE_HOST_INPUT_FIT"
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_forged_context_and_caller_manifest_cannot_replace_frozen_authority(self):
        forged = replace(self.load(), route_id="generic-route", claim="COMPLETE_HOST_INPUT_FIT")
        self.assertNotEqual(forged, self.load())
        changed = copy.deepcopy(self.manifest)
        changed["planRevision"] += 1
        with self.assertRaises(LifecycleError):
            self.load(changed)
        changed = copy.deepcopy(self.manifest)
        changed["status"] = "DRAFT"
        with self.assertRaises(LifecycleError):
            self.load(changed)

    def test_changed_profile_or_lock_bytes_and_missing_profile_refuse(self):
        for relative in (LEGACY_CONTRACT_PATH, LEGACY_LOCK_PATH):
            with self.subTest(path=relative):
                target = self.root / relative
                original = target.read_bytes()
                value = json.loads(original)
                value["manifestHash"] = "0" * 64
                put(self.root, relative, value)
                with self.assertRaises(LifecycleError):
                    self.load()
                target.write_bytes(original)
        (self.root / LEGACY_CONTRACT_PATH).unlink()
        with self.assertRaises((LifecycleError, OSError)):
            self.load()

    def test_even_refrozen_other_package_claim_path_or_producer_is_not_a_registered_route(self):
        original_contract = copy.deepcopy(self.contract)
        mutations = [
            ("claim", "COMPLETE_HOST_INPUT_FIT"),
            ("caseCount", 25),
            ("schemaVersion", "generic-native-matrix.v1"),
        ]
        for field, value in mutations:
            with self.subTest(field=field):
                self.contract = copy.deepcopy(original_contract)
                self.contract["validation"]["limitedNativeMatrix"][field] = value
                self.freeze()
                with self.assertRaises(LifecycleError):
                    self.load()
        for field, value in [("admissionPath", "work/other/admission.json"), ("producerSources", ["other.py"])]:
            with self.subTest(field=field):
                self.contract = copy.deepcopy(original_contract)
                self.contract["validation"]["limitedNativeMatrix"]["evidenceContract"][field] = value
                self.freeze()
                with self.assertRaises(LifecycleError):
                    self.load()
        self.contract = original_contract
        self.manifest["package"]["id"] = "another-package"
        self.freeze()
        with self.assertRaises(LifecycleError):
            self.load()

    def test_collector_selects_profile_before_processing_any_case(self):
        put(self.root, LEGACY_CONTRACT_PATH, {"forged": True})
        with (
            patch.object(native, "read_native_admission") as admission,
            closing(BoundedReader()) as reader,
            self.assertRaises(LifecycleError),
        ):
            native.verify_native_observations(
                self.root,
                {"commands": []},
                reader=reader,
                manifest=self.manifest,
                state={},
                task={},
                candidate_digest="a" * 64,
            )
        admission.assert_not_called()

    def test_frozen_collector_keeps_exact_per_case_commands_and_duplicate_refusals(self):
        # UNIT_ONLY doubles for native observations; frozen profile reads are real.
        context = self.load()
        admission_value = {"cases": {row["caseId"]: {} for row in context.rows}, "maxSelectedCodexInvocations": 6}
        commands = [
            {
                "commandDigest": native.canonical_digest(row["command"]),
                "status": "PASS",
                "exitCode": 0,
                "cases": [{"id": row["caseId"], "status": "PASS", "evidence": {}}],
            }
            for row in context.rows
        ]
        for path in context.producer_paths:
            put(self.root, path, b"unit-only producer")
        with (
            patch.object(native, "read_native_admission", return_value=(admission_value, {})),
            patch.object(
                native, "verify_limited_native_case", return_value={"selectedCodexInvocationsStarted": 0}
            ) as case,
        ):
            with closing(BoundedReader()) as reader:
                rows = native.verify_native_observations(
                    self.root,
                    {"commands": commands},
                    reader=reader,
                    manifest=self.manifest,
                    state={},
                    task={},
                    candidate_digest="unit-only",
                )
            self.assertEqual(24, len(rows))
            self.assertEqual(24, case.call_count)
            for mutation in ("missing", "duplicate", "alias", "skip"):
                changed = copy.deepcopy(commands)
                if mutation == "missing":
                    changed.pop(0)
                elif mutation == "duplicate":
                    changed.append(copy.deepcopy(changed[0]))
                elif mutation == "alias":
                    changed[0]["cases"][0]["id"] = "wrong-alias"
                else:
                    changed[0]["cases"][0]["status"] = "SKIP"
                with self.subTest(mutation=mutation), closing(BoundedReader()) as reader:
                    with self.assertRaises(LifecycleError) as caught:
                        native.verify_native_observations(
                            self.root,
                            {"commands": changed},
                            reader=reader,
                            manifest=self.manifest,
                            state={},
                            task={},
                            candidate_digest="unit-only",
                        )
                    self.assertIn("Exact native per-case command result missing", str(caught.exception))

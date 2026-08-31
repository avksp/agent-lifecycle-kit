from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest, write_json_create
from agent_lifecycle.quality import (
    BUILT_IN_PROTECTED_PATH_PREFIXES,
    build_validation_check_catalog,
    build_validation_ladder_profile,
    build_validation_selection,
    validate_release_full_validation_receipt,
)


class ValidationLadderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.commands_by_id = {
            "acceptance": "python -m unittest tests.acceptance -q",
            "fast": "python -m unittest tests.fast -q",
            "release": "python -m unittest discover -s tests -t . -q",
        }
        self.commands = list(reversed(self.commands_by_id.values()))
        self.catalog = build_validation_check_catalog(self.commands_by_id)
        self.profile = build_validation_ladder_profile(
            [
                {"id": "acceptance", "pathPrefix": "src", "level": "TASK_ACCEPTANCE", "checkIds": ["acceptance"]},
                {"id": "fast", "pathPrefix": "src/example", "level": "TASK_FAST", "checkIds": ["fast"]},
            ]
        )

    def test_overlapping_mappings_union_checks_at_strongest_level(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            selection = self._select(Path(tmp), changed_files=["src/example/module.py"])

        self.assertEqual(selection["status"], "PASS")
        self.assertEqual(selection["level"], "TASK_ACCEPTANCE")
        self.assertEqual(selection["selectedCheckIds"], ["acceptance", "fast"])
        self.assertEqual(selection["matchedMappingIds"], ["acceptance", "fast"])
        self.assertFalse(selection["commandsExecuted"])
        self.assertFalse(selection["stateWritten"])

    def test_every_built_in_protected_path_selects_release_full(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for protected in BUILT_IN_PROTECTED_PATH_PREFIXES:
                with self.subTest(path=protected):
                    selection = self._select(root, changed_files=[protected])
                    self.assertEqual(selection["level"], "RELEASE_FULL")
                    self.assertEqual(selection["selectedCheckIds"], ["acceptance", "fast", "release"])

    def test_no_match_and_legacy_absence_select_release_full(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            no_match = self._select(root, changed_files=["examples/demo.py"])
            legacy = self._select(root, changed_files=["examples/demo.py"], legacy=True)

        self.assertEqual(no_match["level"], "RELEASE_FULL")
        self.assertEqual(no_match["reasons"], ["NO_MAPPING_MATCH"])
        self.assertEqual(legacy["level"], "RELEASE_FULL")
        self.assertEqual(legacy["reasons"], ["LEGACY_PROFILE_ABSENT"])
        self.assertEqual(legacy["selectedCheckIds"], [])
        self.assertIsNone(legacy["profileDigest"])

    def test_legacy_absence_precedes_opted_in_lineage_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, lock, state, snapshot = self._inputs(root, ["examples/demo.py"], legacy=True)
            lock["manifestHash"] = "e" * 64
            state["planDigest"] = "f" * 64
            selection = build_validation_selection(
                manifest=manifest,
                lock=lock,
                state=state,
                snapshot=snapshot,
                repository_root=root,
            )

        self.assertEqual(selection["status"], "PASS")
        self.assertEqual(selection["level"], "RELEASE_FULL")
        self.assertEqual(selection["reasons"], ["LEGACY_PROFILE_ABSENT"])
        self.assertEqual(selection["blockers"], [])

    def test_failure_classes_are_disjoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, lock, state, snapshot = self._inputs(root, ["src/example.py"], write_profile=False)
            unreadable = build_validation_selection(
                manifest=manifest, lock=lock, state=state, snapshot=snapshot, repository_root=root
            )
            self.assertEqual(unreadable["blockers"][0]["code"], "validation-ladder-profile-unreadable")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, lock, state, snapshot = self._inputs(root, ["src/example.py"])
            changed = dict(self.profile)
            changed["additionalProtectedPathPrefixes"] = ["examples"]
            (root / "profiles/ladder.json").unlink()
            write_json_create(root / "profiles/ladder.json", changed)
            mismatch = build_validation_selection(
                manifest=manifest, lock=lock, state=state, snapshot=snapshot, repository_root=root
            )
            self.assertEqual(mismatch["blockers"][0]["code"], "validation-ladder-profile-digest-mismatch")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            invalid_profile = {**self.profile, "command": "python -m tests"}
            invalid = self._select(root, changed_files=["src/example.py"], profile=invalid_profile)
            self.assertEqual(invalid["blockers"][0]["code"], "validation-ladder-profile-invalid")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, lock, state, snapshot = self._inputs(root, ["src/example.py"])
            state["planDigest"] = "f" * 64
            stale = build_validation_selection(
                manifest=manifest, lock=lock, state=state, snapshot=snapshot, repository_root=root
            )
            self.assertEqual(stale["blockers"][0]["code"], "validation-ladder-profile-stale")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing_profile = build_validation_ladder_profile(
                [{"id": "missing", "pathPrefix": "src", "level": "TASK_FAST", "checkIds": ["absent"]}]
            )
            missing = self._select(root, changed_files=["src/example.py"], profile=missing_profile)
            self.assertEqual(missing["blockers"][0]["code"], "validation-ladder-check-missing")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            duplicate_body = {
                "schemaVersion": "agent-validation-ladder-profile.v1",
                "mappings": [
                    {"id": "same", "pathPrefix": "src/a", "level": "TASK_FAST", "checkIds": ["fast"]},
                    {
                        "id": "same",
                        "pathPrefix": "src/b",
                        "level": "TASK_ACCEPTANCE",
                        "checkIds": ["acceptance"],
                    },
                ],
                "additionalProtectedPathPrefixes": [],
            }
            duplicate_profile = {**duplicate_body, "profileDigest": canonical_digest(duplicate_body)}
            duplicate = self._select(root, changed_files=["src/a.py"], profile=duplicate_profile)
            self.assertEqual(duplicate["blockers"][0]["code"], "validation-ladder-duplicate-conflict")

    def test_release_full_receipt_requires_exact_fresh_full_evidence(self) -> None:
        required = ["acceptance", "fast", "release"]
        body = {
            "schemaVersion": "agent-release-full-validation-receipt.v1",
            "status": "PASS",
            "sourceRevision": "source",
            "currentTreeDigest": "1" * 64,
            "planDigest": "2" * 64,
            "planLockDigest": "3" * 64,
            "catalogDigest": self.catalog["catalogDigest"],
            "requiredCheckIds": required,
            "passedCheckIds": required,
            "gateEvidenceDigests": ["4" * 64, "5" * 64, "6" * 64],
            "completedAt": "2026-08-31T00:00:00Z",
            "blockers": [],
            "productionPromotionClaimed": False,
        }
        receipt = {**body, "receiptDigest": canonical_digest(body)}
        expected = {
            "source_revision": "source",
            "current_tree_digest": "1" * 64,
            "plan_digest": "2" * 64,
            "plan_lock_digest": "3" * 64,
            "catalog_digest": self.catalog["catalogDigest"],
            "required_check_ids": required,
        }

        self.assertEqual(validate_release_full_validation_receipt(receipt, **expected)["status"], "PASS")
        for field, replacement in (
            ("status", "FAIL"),
            ("currentTreeDigest", "9" * 64),
            ("passedCheckIds", ["fast"]),
            ("gateEvidenceDigests", ["4" * 64, "5" * 64]),
            ("productionPromotionClaimed", True),
        ):
            with self.subTest(field=field):
                changed = {**receipt, field: replacement}
                changed_body = {key: value for key, value in changed.items() if key != "receiptDigest"}
                changed["receiptDigest"] = canonical_digest(changed_body)
                self.assertEqual(validate_release_full_validation_receipt(changed, **expected)["status"], "FAIL")

    def test_selector_and_phase_packet_modules_do_not_import_planning_or_workflow(self) -> None:
        root = Path(__file__).resolve().parents[2]
        for relative in (
            "src/agent_lifecycle/quality/validation_ladder.py",
            "src/agent_lifecycle/compiler/phase_packets.py",
        ):
            with self.subTest(path=relative):
                tree = ast.parse((root / relative).read_text(encoding="utf-8"))
                imported = {
                    node.module
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and isinstance(node.module, str)
                }
                self.assertFalse(any(name.startswith("agent_lifecycle.planning") for name in imported))
                self.assertFalse(any(name.startswith("agent_lifecycle.workflow") for name in imported))

    def _select(
        self,
        root: Path,
        *,
        changed_files: list[str],
        legacy: bool = False,
        profile: dict | None = None,
    ) -> dict:
        manifest, lock, state, snapshot = self._inputs(
            root,
            changed_files,
            legacy=legacy,
            profile=profile,
        )
        return build_validation_selection(
            manifest=manifest,
            lock=lock,
            state=state,
            snapshot=snapshot,
            repository_root=root,
        )

    def _inputs(
        self,
        root: Path,
        changed_files: list[str],
        *,
        legacy: bool = False,
        profile: dict | None = None,
        write_profile: bool = True,
    ) -> tuple[dict, dict, dict, dict]:
        active_profile = profile or self.profile
        validation = {"commands": self.commands}
        if not legacy:
            profile_digest = canonical_digest(active_profile)
            validation.update(
                {
                    "checkCatalog": self.catalog,
                    "validationLadderProfile": {"path": "profiles/ladder.json", "digest": profile_digest},
                }
            )
            if write_profile:
                profile_path = root / "profiles/ladder.json"
                if not profile_path.exists():
                    write_json_create(profile_path, active_profile)
        manifest = {"schemaVersion": "agent-plan-manifest.v1", "validation": validation}
        plan_digest = canonical_digest(manifest)
        lock = {"schemaVersion": "agent-plan-lock.v2", "manifestHash": plan_digest}
        state = {"stateRevision": 7, "sourceRevision": "source", "planDigest": plan_digest}
        snapshot = {"snapshotHash": "7" * 64, "changedFiles": changed_files}
        return manifest, lock, state, snapshot


if __name__ == "__main__":
    unittest.main()

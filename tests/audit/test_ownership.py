from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.audit import build_ownership_report  # noqa: E402
from agent_lifecycle.audit.ownership import (  # noqa: E402
    build_ownership_report_from_manifest,
    declared_ownership_paths,
)
from agent_lifecycle.contracts import LifecycleError  # noqa: E402


class OwnershipTests(unittest.TestCase):
    def test_conflicting_declarations_block_an_empty_ownership_report(self) -> None:
        with self.assertRaises(LifecycleError) as raised:
            build_ownership_report_from_manifest(
                {
                    "readOnly": ["src"],
                    "workstreams": [{"id": "A", "writes": ["src"]}],
                },
                [],
            )
        self.assertEqual(raised.exception.code, "ambiguous-authority-path")

    def test_runtime_root_protects_aliases_in_every_authority_category(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Protected").mkdir()
            (root / "Protected/file.py").write_text("one")
            insensitive = (root / "protected").exists()
            for category in ("read-only", "forbidden", "lead-owned", "plan-authority", "workstream-owned"):
                manifest = {"package": {}, "workstreams": []}
                if category == "plan-authority":
                    manifest["package"]["planArtifactRoot"] = "Protected"
                elif category == "workstream-owned":
                    manifest["workstreams"] = [{"id": "WS-01", "writes": ["Protected"]}]
                else:
                    field = {"read-only": "readOnly", "forbidden": "forbiddenWrites", "lead-owned": "leadOwned"}[
                        category
                    ]
                    manifest[field] = [{"path": "Protected"}] if category == "lead-owned" else ["Protected"]
                with self.subTest(category=category):
                    if insensitive and category == "workstream-owned":
                        with self.assertRaises(LifecycleError) as raised:
                            build_ownership_report_from_manifest(
                                manifest,
                                ["protected/file.py"],
                                repository_root=root,
                            )
                        self.assertEqual(raised.exception.code, "ambiguous-authority-path")
                        continue
                    report = build_ownership_report_from_manifest(
                        manifest,
                        ["protected/file.py"],
                        repository_root=root,
                    )
                    self.assertEqual(report["entries"][0]["path"], "protected/file.py")
                    self.assertEqual(report["entries"][0]["category"], category if insensitive else "unowned")

    def test_runtime_missing_case_policy_is_a_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(LifecycleError) as raised:
                build_ownership_report_from_manifest(
                    {"readOnly": ["Protected"]},
                    ["protected/file.py"],
                    repository_root=Path(tmp),
                )
            self.assertEqual(raised.exception.code, "filesystem-policy-unavailable")

    def test_nfd_observation_matches_each_nfc_authority_without_rewriting_path(self) -> None:
        observed = "src/cafe\u0301/file.py"
        for category in ("read-only", "forbidden", "lead-owned", "plan-authority", "workstream-owned"):
            manifest = {"package": {}, "workstreams": []}
            root = "src/caf\u00e9"
            if category == "plan-authority":
                manifest["package"]["planArtifactRoot"] = root
            elif category == "workstream-owned":
                manifest["workstreams"] = [{"id": "WS-01", "writes": [root]}]
            else:
                field = {"read-only": "readOnly", "forbidden": "forbiddenWrites", "lead-owned": "leadOwned"}[category]
                manifest[field] = [{"path": root}] if category == "lead-owned" else [root]
            with self.subTest(category=category):
                report = build_ownership_report_from_manifest(manifest, [observed])
                self.assertEqual(report["entries"][0]["path"], observed)
                self.assertEqual(report["entries"][0]["category"], category)

    def test_observed_normalization_collision_is_not_reduced_to_one_entry(self) -> None:
        with self.assertRaises(LifecycleError) as raised:
            build_ownership_report_from_manifest(_manifest(), ["other/caf\u00e9", "other/cafe\u0301"])
        self.assertEqual(raised.exception.code, "ambiguous-authority-path")

    def test_report_classifies_workstream_lead_plan_and_unowned_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                manifest = Path("plan.manifest.json")
                manifest.write_text(json.dumps(_manifest()), encoding="utf-8")
                report = build_ownership_report(
                    manifest,
                    [
                        "plan.manifest.json",
                        "src/package/core.py",
                        "runtime/state.json",
                        "plan/files/spec.json",
                        "README.extra.md",
                        "LICENSE",
                    ],
                    base="main",
                )
            finally:
                os.chdir(previous_cwd)
            by_path = {entry["path"]: entry for entry in report["entries"]}
            self.assertEqual(by_path["plan.manifest.json"]["category"], "plan-authority")
            self.assertEqual(by_path["src/package/core.py"]["owners"], ["WS-01"])
            self.assertEqual(by_path["runtime/state.json"]["category"], "lead-owned")
            self.assertEqual(by_path["plan/files/spec.json"]["category"], "plan-authority")
            self.assertEqual(by_path["README.extra.md"]["category"], "unowned")
            self.assertEqual(by_path["LICENSE"]["category"], "forbidden")

    def test_pseudo_glob_authority_is_rejected_before_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "plan.manifest.json"
            value = _manifest()
            value["readOnly"] = ["src/agent_lifecycle/**"]
            manifest.write_text(json.dumps(value), encoding="utf-8")

            with self.assertRaises(LifecycleError) as raised:
                build_ownership_report(manifest, ["src/agent_lifecycle/neutrality/gate.py"])

            self.assertEqual(raised.exception.code, "invalid-authority-path")

    def test_loaded_manifest_classification_matches_file_backed_report(self) -> None:
        manifest = _manifest()
        loaded_report = build_ownership_report_from_manifest(
            manifest,
            ["src/package/core.py", "runtime/state.json", "LICENSE"],
            base="main",
        )

        by_path = {entry["path"]: entry for entry in loaded_report["entries"]}
        self.assertEqual(loaded_report["packageId"], "sample")
        self.assertEqual(by_path["src/package/core.py"]["owners"], ["WS-01"])
        self.assertEqual(by_path["runtime/state.json"]["category"], "lead-owned")
        self.assertEqual(by_path["LICENSE"]["category"], "forbidden")

    def test_declared_ownership_paths_are_literal_and_deterministic(self) -> None:
        self.assertEqual(declared_ownership_paths(_manifest()), ["src/package"])


def _manifest() -> dict:
    return {
        "status": "FROZEN",
        "planRevision": 1,
        "package": {
            "id": "sample",
            "planArtifactRoot": "plan/files",
        },
        "leadOwned": [{"path": "runtime", "reason": "controller artifacts"}],
        "readOnly": ["LICENSE", "plan/files"],
        "forbiddenWrites": ["LICENSE", "plan/files"],
        "workstreams": [
            {
                "id": "WS-01",
                "writes": ["src/package"],
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()


class FrozenPathEntryPointMatrixTests(unittest.TestCase):
    def test_all_authority_classes_reject_noncanonical_and_ambiguous_observations(self) -> None:
        import copy

        from agent_lifecycle.planning.manifest_contract import validate_plan_manifest_contract

        fixture = json.loads(
            (ROOT / "tests/planning/fixtures/canonical-plan-manifest.v1.json").read_text(encoding="utf-8")
        )
        for field in ("readOnly", "forbiddenWrites", "leadOwned", "writes"):
            for spelling in ("scope/cafe\u0301", "scope/caf\u00e9"):
                with self.subTest(field=field, spelling=spelling):
                    manifest = copy.deepcopy(fixture)
                    manifest["readOnly"] = []
                    manifest["forbiddenWrites"] = []
                    manifest["leadOwned"] = []
                    manifest["workstreams"][0]["writes"] = ["different"]
                    target = manifest["workstreams"][0] if field == "writes" else manifest
                    target[field] = [{"path": spelling, "reason": "controller"}] if field == "leadOwned" else [spelling]
                    before = copy.deepcopy(manifest)
                    if "\u0301" in spelling:
                        with self.assertRaises(LifecycleError) as raised:
                            validate_plan_manifest_contract(manifest)
                        self.assertEqual(raised.exception.code, "noncanonical-authority-path")
                        with self.assertRaises(LifecycleError) as raised:
                            build_ownership_report_from_manifest(manifest, [])
                        self.assertEqual(raised.exception.code, "noncanonical-authority-path")
                    else:
                        self.assertEqual(validate_plan_manifest_contract(manifest)["status"], "PASS")
                        report = build_ownership_report_from_manifest(manifest, ["scope/cafe\u0301/file.py"])
                        self.assertEqual(report["entries"][0]["path"], "scope/cafe\u0301/file.py")
                        with self.assertRaises(LifecycleError) as raised:
                            build_ownership_report_from_manifest(
                                manifest, ["scope/caf\u00e9/file.py", "scope/cafe\u0301/file.py"]
                            )
                        self.assertEqual(raised.exception.code, "ambiguous-authority-path")
                    self.assertEqual(manifest, before)

    def test_native_case_policy_and_unknown_root_apply_to_every_authority_class(self) -> None:
        from agent_lifecycle.planning.manifest_contract import validate_plan_manifest_contract

        for field, category in (
            ("readOnly", "read-only"),
            ("forbiddenWrites", "forbidden"),
            ("leadOwned", "lead-owned"),
            ("writes", "workstream-owned"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = {"package": {}, "workstreams": []}
                target = manifest
                if field == "writes":
                    manifest["workstreams"] = [{"id": "WS-CASE"}]
                    target = manifest["workstreams"][0]
                target[field] = (
                    [{"path": "Protected", "reason": "controller"}] if field == "leadOwned" else ["Protected"]
                )
                before = dict(manifest)
                self.assertEqual(
                    build_ownership_report_from_manifest(manifest, ["protected/file.py"])["entries"][0]["category"],
                    "unowned",
                )
                with self.assertRaises(LifecycleError) as raised:
                    build_ownership_report_from_manifest(manifest, ["protected/file.py"], repository_root=root)
                self.assertEqual(raised.exception.code, "filesystem-policy-unavailable")
                self.assertEqual(list(root.iterdir()), [])
                (root / "Protected").mkdir()
                insensitive = (root / "protected").exists()
                if insensitive and field == "writes":
                    with self.assertRaises(LifecycleError) as raised:
                        build_ownership_report_from_manifest(manifest, ["protected/file.py"], repository_root=root)
                    self.assertEqual(raised.exception.code, "ambiguous-authority-path")
                else:
                    report = build_ownership_report_from_manifest(manifest, ["protected/file.py"], repository_root=root)
                    self.assertEqual(report["entries"][0]["category"], category if insensitive else "unowned")
                self.assertEqual(manifest, before)
                # Rootless contract checking never substitutes CWD case semantics.
                validate_plan_manifest_contract(manifest)

    def test_identical_restrictions_are_legal_and_competing_nfc_grants_are_not(self) -> None:
        from agent_lifecycle.planning.manifest_contract import validate_plan_manifest_contract

        for field in ("readOnly", "forbiddenWrites", "leadOwned", "writes"):
            manifest = {
                "readOnly": ["same"],
                "forbiddenWrites": ["same"],
                "workstreams": [{"id": "A", "writes": ["allowed"]}],
            }
            self.assertEqual(
                build_ownership_report_from_manifest(manifest, ["same/file"])["entries"][0]["category"], "forbidden"
            )
            if field == "writes":
                manifest["workstreams"].append({"id": "B", "writes": ["allowed"]})
            elif field == "leadOwned":
                manifest[field] = [{"path": "allowed", "reason": "controller"}]
            else:
                manifest[field] = ["allowed"]
            with self.assertRaises(LifecycleError) as raised:
                validate_plan_manifest_contract(manifest)
            self.assertEqual(raised.exception.code, "ambiguous-authority-path")
            with self.assertRaises(LifecycleError) as raised:
                build_ownership_report_from_manifest(manifest, [])
            self.assertEqual(raised.exception.code, "ambiguous-authority-path")

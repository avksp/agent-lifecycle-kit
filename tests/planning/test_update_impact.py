from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.plugin_update_schemas import UPDATE_INVENTORY_SCHEMA
from agent_lifecycle.planning.update_impact import assess_plugin_update
from tests.contracts.test_plugin_update_schemas import make_descriptor, make_request


def write_plan(root, *, status="DRAFT", phase=None):
    folder = root / "plan"
    folder.mkdir()
    manifest = {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": status,
        "planRevision": 1,
        "package": {"id": "update-fixture", "planArtifactRoot": "plan"},
        "releaseTarget": {"targetVersion": "1.0.0"},
        "specification": {"tier": "S1", "requirements": [{"id": "R1", "description": "bounded advice"}]},
        "acceptance": {"criteria": [{"id": "AC1", "requirementIds": ["R1"], "evidenceIds": ["EV1"]}]},
        "workstreams": [{"id": "WS1", "dependsOn": [], "writes": ["src/example.py"], "evidenceIds": ["EV1"]}],
        "validation": {"commands": ["python -m unittest"], "extraEvidence": []},
    }
    (folder / "plan.manifest.json").write_bytes(canonical_bytes(manifest) + b"\n")
    (folder / "acceptance-criteria.md").write_text(
        "| ID | Requirements | Evidence | Statement |\n| --- | --- | --- | --- |\n"
        "| `AC1` | `R1` | `EV1` | Verify advice. |\n"
    )
    item = {"manifest": "plan/plan.manifest.json"}
    if phase:
        state = {
            "schemaVersion": "agent-workflow-state.v4",
            "runId": "fixture",
            "packageId": "update-fixture",
            "planRevision": 1,
            "planDigest": canonical_digest(manifest),
            "stateRevision": 9,
            "phase": phase,
            "expenses": {"prior": 123, "actualTokens": None},
            "originalStartedAt": "2026-11-01T00:00:00Z",
        }
        (folder / "state.json").write_bytes(canonical_bytes(state) + b"\n")
        item["state"] = "plan/state.json"
    if status == "FROZEN":
        lock = {"schemaVersion": "agent-plan-lock.v1", "planRevision": 1, "manifestHash": canonical_digest(manifest)}
        (folder / "plan.lock.json").write_bytes(canonical_bytes(lock) + b"\n")
    return manifest, {"schemaVersion": UPDATE_INVENTORY_SCHEMA, "currentVersion": "2.47.0", "plans": [item]}


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class PluginUpdateImpactTests(unittest.TestCase):
    def test_scoped_lock_or_review_policy_refuses_before_canonical_or_transitive_reads(self):
        for kind in ("v3", "reviewPolicy"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest, inventory = write_plan(root)
                if kind == "v3":
                    lock = {"schemaVersion": "agent-plan-lock.v3", "reviewEvidence": [{"path": "outside/huge.json"}]}
                    (root / "plan/plan.lock.json").write_bytes(canonical_bytes(lock))
                else:
                    manifest["extensions"] = {"reviewPolicy": {"scope": "FULL"}}
                    (root / "plan/plan.manifest.json").write_bytes(canonical_bytes(manifest))
                before = snapshot(root)
                with patch("agent_lifecycle.planning.update_impact.build_plan_verification") as canonical:
                    report = assess_plugin_update(make_request(), make_descriptor(), inventory, repository_root=root)
                self.assertEqual(report["status"], "UNKNOWN")
                self.assertEqual(report["details"]["reason"], "plugin-update-scoped-verification-unsupported")
                canonical.assert_not_called()
                self.assertEqual(snapshot(root), before)

    def test_flat_v2_canonical_integrity_remains_supported(self):
        from agent_lifecycle.freeze.package_integrity import build_plan_lock_v2

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, inventory = write_plan(root, status="FROZEN")
            manifest["packageIntegrity"] = {
                "required": True,
                "inventorySource": "planFiles",
                "lockSchemaVersion": "agent-plan-lock.v2",
                "undeclaredTopLevelFiles": "reject",
                "allowedUnlistedFiles": ["plan.lock.json"],
            }
            manifest["planFiles"] = ["plan/acceptance-criteria.md", "plan/plan.manifest.json"]
            (root / "plan/plan.manifest.json").write_bytes(canonical_bytes(manifest))
            lock = build_plan_lock_v2(manifest, repository_root=root)
            (root / "plan/plan.lock.json").write_bytes(canonical_bytes(lock))
            report = assess_plugin_update(make_request(), make_descriptor(), inventory, repository_root=root)
            self.assertEqual(report["status"], "ASSESSED")
            self.assertEqual(report["details"]["plans"][0]["structuralResult"], "PASS")

    def test_missing_coverage_and_equal_version_labels_do_not_prove_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, inventory = write_plan(root)
            report = assess_plugin_update(make_request(), make_descriptor(), inventory, repository_root=root)
            self.assertTrue(report["details"]["assessmentComplete"])
            plan = report["details"]["plans"][0]
            self.assertEqual(plan["structuralResult"], "PASS")
            self.assertEqual(plan["semanticResult"], "UNKNOWN")
            self.assertEqual(plan["installationEligibility"], "UNQUALIFIED")
            self.assertIn("quality", plan["domains"])

    def test_changed_review_obligation_requires_adaptation_despite_same_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, inventory = write_plan(root)
            descriptor = make_descriptor()
            descriptor["changes"] = [
                {
                    "domain": "review",
                    "identifier": "orchestration.finalAuditRequired",
                    "impact": "ADAPTATION_REQUIRED",
                    "reason": "required evidence changed",
                }
            ]
            report = assess_plugin_update(make_request(), descriptor, inventory, repository_root=root)
            self.assertEqual(report["details"]["plans"][0]["semanticResult"], "ADAPTATION_REQUIRED")

    def test_all_lifecycle_advice_keeps_original_bytes_expenses_and_clocks(self):
        for phase in ("RUNNING", "VERIFYING", "PAUSED", "BLOCKED", "FINAL_AUDIT", "COMPLETE"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _, inventory = write_plan(root, status="FROZEN", phase=phase)
                before = snapshot(root)
                report = assess_plugin_update(make_request(), make_descriptor(), inventory, repository_root=root)
                self.assertEqual(snapshot(root), before)
                plan = report["details"]["plans"][0]
                expected = "PRESERVE_IMMUTABLE_HISTORY" if phase == "COMPLETE" else "DEFER_ACTIVATION"
                self.assertEqual(plan["lifecycle"]["action"], expected)
                self.assertEqual(plan["proposedEdits"], [])

    def test_draft_literal_proposal_is_unapplied_and_requires_independent_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, inventory = write_plan(root)
            descriptor = make_descriptor()
            descriptor["changes"] = [
                {
                    "domain": "path",
                    "identifier": "src/example.py",
                    "impact": "ADAPTATION_REQUIRED",
                    "reason": "explicit draft proposal",
                    "proposedEdit": {
                        "path": "plan/plan.manifest.json",
                        "pointer": "/package/id",
                        "expectedValue": "update-fixture",
                        "proposedValue": "update-fixture-new",
                    },
                }
            ]
            before = snapshot(root)
            report = assess_plugin_update(make_request(), descriptor, inventory, repository_root=root)
            proposals = report["details"]["plans"][0]["proposedEdits"]
            self.assertEqual(len(proposals), 1)
            self.assertIs(proposals[0]["applied"], False)
            self.assertIs(proposals[0]["requiresIndependentReview"], True)
            self.assertEqual(snapshot(root), before)

    def test_wrong_expected_literal_does_not_create_a_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, inventory = write_plan(root)
            descriptor = make_descriptor()
            descriptor["changes"] = [
                {
                    "domain": "path",
                    "identifier": "src/example.py",
                    "impact": "UNKNOWN",
                    "reason": "unknown",
                    "proposedEdit": {
                        "path": "plan/plan.manifest.json",
                        "pointer": "/planRevision",
                        "expectedValue": True,
                        "proposedValue": 2,
                    },
                }
            ]
            report = assess_plugin_update(make_request(), descriptor, inventory, repository_root=root)
            self.assertEqual(report["details"]["plans"][0]["proposedEdits"], [])

    def test_unreadable_or_foreign_state_is_not_assumed_idle(self):
        for content in (b"{}", b'{"phase":"COMPLETE"}', b"not-json"):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _, inventory = write_plan(root, phase="RUNNING")
                (root / "plan/state.json").write_bytes(content)
                before = snapshot(root)
                report = assess_plugin_update(make_request(), make_descriptor(), inventory, repository_root=root)
                self.assertEqual(report["status"], "UNKNOWN")
                self.assertIs(report["details"]["assessmentComplete"], False)
                self.assertEqual(snapshot(root), before)

    def test_actual_canonical_integrity_failure_is_not_a_schema_match_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, inventory = write_plan(root, status="FROZEN")
            (root / "plan/plan.lock.json").write_bytes(b'{"schemaVersion":"agent-plan-lock.v1"}')
            report = assess_plugin_update(make_request(), make_descriptor(), inventory, repository_root=root)
            self.assertEqual(report["details"]["plans"][0]["structuralResult"], "FAIL")
            self.assertEqual(report["details"]["plans"][0]["semanticResult"], "UNKNOWN")

    def test_plan_commands_and_metadata_are_never_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, inventory = write_plan(root)
            marker = root / "must-not-exist"
            manifest["validation"]["commands"] = ["touch " + str(marker) + "; echo untrusted"]
            (root / "plan/plan.manifest.json").write_bytes(canonical_bytes(manifest))
            before = snapshot(root)
            report = assess_plugin_update(make_request(), make_descriptor(), inventory, repository_root=root)
            self.assertEqual(report["details"]["plans"][0]["semanticResult"], "UNKNOWN")
            self.assertFalse(marker.exists())
            self.assertEqual(snapshot(root), before)

    def test_file_cap_refuses_instead_of_partially_accepting_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, inventory = write_plan(root)
            (root / "plan/acceptance-criteria.md").write_bytes(b"x" * 262145)
            report = assess_plugin_update(make_request(), make_descriptor(), inventory, repository_root=root)
            self.assertEqual(report["status"], "UNKNOWN")
            self.assertFalse(report["details"]["assessmentComplete"])
            self.assertEqual(report["details"]["unassessedPlanCount"], 1)

    def test_total_file_cap_includes_manifest_and_refuses_before_read65(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, inventory = write_plan(root)
            manifest["planFiles"] = [f"plan/input-{i}.json" for i in range(64)]
            for name in manifest["planFiles"]:
                (root / name).write_bytes(b"{}")
            (root / "plan/plan.manifest.json").write_bytes(canonical_bytes(manifest))
            from agent_lifecycle.contracts.paths import read_stable_repository_file

            with patch(
                "agent_lifecycle.planning.update_impact.read_stable_repository_file", wraps=read_stable_repository_file
            ) as read:
                report = assess_plugin_update(make_request(), make_descriptor(), inventory, repository_root=root)
            self.assertEqual(report["status"], "UNKNOWN")
            self.assertEqual(read.call_count, 64)

    def test_target_commit_and_pin_are_rechecked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, inventory = write_plan(root)
            for request in (make_request(pin="v2.47.0"), make_request(trustedTargetCommit="c" * 40)):
                with self.subTest(request=request), self.assertRaises(LifecycleError):
                    assess_plugin_update(request, make_descriptor(), copy.deepcopy(inventory), repository_root=root)

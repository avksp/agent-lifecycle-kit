from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError  # noqa: E402
from agent_lifecycle.planning.completeness import (  # noqa: E402
    build_plan_completeness_profile,
    validate_plan_completeness,
)
from agent_lifecycle.planning.validation import validate_plan_manifest  # noqa: E402
from agent_lifecycle.quality.validation_ladder import build_validation_check_catalog  # noqa: E402


class CanonicalPlanCompletenessTests(unittest.TestCase):
    def test_paired_compact_and_verbose_graphs_share_existing_completeness_failures(self) -> None:
        from agent_lifecycle.contracts.ownership_paths import require_manifest_authority_paths
        from agent_lifecycle.planning.compact_packages import compile_compact_plan
        from agent_lifecycle.planning.traceability import validate_plan_traceability
        from tests.metrics.test_plan_package_comparison import MANIFEST, SOURCE, paired_inputs

        for tier in ("S0", "S1"):
            legacy, source = paired_inputs(tier)
            compact = compile_compact_plan(json.loads(source), source_path=SOURCE, manifest_path=MANIFEST)
            control = json.loads(legacy)
            for mutation in ("intact", "acceptance", "requirement", "evidence", "checks", "ownership"):
                outcomes = []
                for original in (control, compact):
                    manifest = json.loads(json.dumps(original))
                    if mutation == "acceptance":
                        manifest["workstreams"][0]["acceptanceIds"] = ["AC-MISSING"]
                    elif mutation == "requirement":
                        manifest["acceptance"]["criteria"][0]["requirementIds"] = ["R-MISSING"]
                    elif mutation == "evidence":
                        manifest["workstreams"][0]["evidenceIds"] = ["EV-MISSING"]
                    elif mutation == "checks":
                        del manifest["validation"]
                    elif mutation == "ownership":
                        manifest["workstreams"][0]["writes"] = ["tasks/compact-example"]
                    try:
                        validate_plan_manifest(manifest, require_completeness=True)
                        require_manifest_authority_paths(manifest)
                        trace = validate_plan_traceability(manifest)
                        outcomes.append((trace["status"], sorted(_codes(trace))))
                    except LifecycleError as exc:
                        outcomes.append(("FAIL", [exc.code]))
                with self.subTest(tier=tier, mutation=mutation):
                    self.assertEqual(outcomes[0], outcomes[1])
                    self.assertEqual(outcomes[0][0], "PASS" if mutation == "intact" else "FAIL")

    def test_canonical_graph_and_literal_paths_pass(self) -> None:
        result = validate_plan_completeness(_manifest())

        self.assertEqual(result["status"], "PASS")
        self.assertIn("traceability", result["requiredChecks"])
        self.assertIn("path-authority", result["requiredChecks"])

    def test_pseudo_glob_path_is_rejected(self) -> None:
        manifest = _manifest()
        manifest["readOnly"] = ["src/agent_lifecycle/**"]

        result = validate_plan_completeness(manifest)

        self.assertEqual(result["status"], "FAIL")
        self.assertIn("authority-path-invalid", _codes(result))

    def test_unordered_cross_workstream_writes_are_rejected(self) -> None:
        manifest = _manifest()
        manifest["workstreams"] = [
            {
                "id": "WS-01",
                "dependsOn": [],
                "writes": ["src/shared"],
                "acceptanceIds": ["AC-01"],
                "evidenceIds": ["EV-01"],
            },
            {
                "id": "WS-02",
                "dependsOn": [],
                "writes": ["src/shared/file.py"],
                "acceptanceIds": ["AC-02"],
                "evidenceIds": ["EV-02"],
            },
        ]

        result = validate_plan_completeness(manifest)

        self.assertIn("authority-write-conflict", _codes(result))

    def test_validation_ladder_authority_is_all_or_none_and_resolved(self) -> None:
        manifest = _manifest()
        command = manifest["validation"]["commands"][0]
        manifest["validation"]["checkCatalog"] = build_validation_check_catalog({"full": command})

        missing_peer = validate_plan_completeness(manifest)
        self.assertIn("validation-ladder-authority", missing_peer["requiredChecks"])
        self.assertIn("validation-ladder-authority-missing-peer", _codes(missing_peer))

        manifest["validation"]["validationLadderProfile"] = {
            "path": "profiles/validation.json",
            "digest": "1" * 64,
        }
        self.assertEqual(validate_plan_completeness(manifest)["status"], "PASS")

        manifest["validation"]["checkCatalog"]["checks"][0]["commandDigest"] = "2" * 64
        self.assertIn("validation-ladder-check-missing", _codes(validate_plan_completeness(manifest)))


class StrictReadinessBoundaryTests(unittest.TestCase):
    def test_missing_or_unsupported_tier_never_defaults_to_s1(self) -> None:
        for value in (None, "", "S3", True, []):
            with self.subTest(value=value):
                manifest = _manifest()
                manifest["specification"]["tier"] = value
                self.assertIn("invalid-plan-tier", _codes(validate_plan_completeness(manifest)))
        manifest = _manifest()
        del manifest["specification"]["tier"]
        self.assertIn("invalid-plan-tier", _codes(validate_plan_completeness(manifest)))

    def test_s2_checks_cannot_be_removed_by_missing_integrity_or_custom_profile(self) -> None:
        manifest = _manifest()
        del manifest["packageIntegrity"]
        del manifest["budgets"]
        profile = build_plan_completeness_profile()
        profile["profiles"]["S2"]["requiredChecks"] = ["requirements"]
        result = validate_plan_completeness(manifest, profile=profile)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("missing-package-integrity", _codes(result))
        self.assertTrue(
            {"budget-policy", "context-limits", "traceability", "path-authority"}.issubset(result["requiredChecks"])
        )

    def test_unsorted_inventory_is_refused_before_lock_creation(self) -> None:
        manifest = _manifest()
        manifest["planFiles"] = ["tasks/canonical-fixture/z.json", "tasks/canonical-fixture/plan.manifest.json"]
        self.assertIn("plan-files-unsorted", _codes(validate_plan_completeness(manifest)))

    def test_incomplete_draft_import_stays_structurally_valid_but_public_check_refuses(self) -> None:
        from agent_lifecycle.cli.main import main

        manifest = _manifest()
        manifest["status"] = "DRAFT"
        del manifest["packageIntegrity"]
        manifest["workstreams"][0]["writes"] = []
        self.assertEqual(validate_plan_manifest(manifest)["status"], "DRAFT")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "draft.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["plan", "check", "--manifest", str(path)])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out.getvalue())["code"], "plan-completeness-failed")
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_legacy_and_canonical_frozen_inputs_share_strict_validation(self) -> None:
        for schema in ("3.0", "agent-plan-manifest.v1"):
            manifest = _manifest()
            manifest["schemaVersion"] = schema
            del manifest["specification"]["tier"]
            with self.subTest(schema=schema), self.assertRaises(LifecycleError) as raised:
                validate_plan_manifest(manifest)
            self.assertEqual(raised.exception.code, "plan-completeness-failed")
            self.assertIn("invalid-plan-tier", _codes(raised.exception.details["validation"]))

    def test_compilation_and_adoption_refuse_before_persistent_mutation(self) -> None:
        from agent_lifecycle.compiler import compile_task_packets
        from agent_lifecycle.workflow.initialization import initialize_workflow_state
        from agent_lifecycle.workflow.plan_adoption import adopt_plan

        for missing in ("tier", "packageIntegrity"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = _manifest()
                manifest["package"]["artifactRoot"] = "work/output"
                if missing == "tier":
                    del manifest["specification"]["tier"]
                else:
                    del manifest["packageIntegrity"]
                plan = root / "tasks/canonical-fixture/plan.manifest.json"
                plan.parent.mkdir(parents=True)
                plan.write_text(json.dumps(manifest), encoding="utf-8")
                state = root / "run.state.json"
                initialize_workflow_state(state, run_id="run", package_id="canonical-fixture")
                before = state.read_bytes()
                with self.assertRaises(LifecycleError) as compiled:
                    compile_task_packets(plan, write=True, repository_root=root)
                self.assertEqual(compiled.exception.code, "plan-completeness-failed")
                with self.assertRaises(LifecycleError) as adopted:
                    adopt_plan(
                        state,
                        manifest_path=plan,
                        operation_id="adopt",
                        expected_revision=1,
                        source_revision="source",
                        reset_tasks=False,
                        start_mode="approval-required",
                    )
                self.assertEqual(adopted.exception.code, "plan-completeness-failed")
                self.assertEqual(state.read_bytes(), before)
                self.assertFalse((root / "events.jsonl").exists())
                self.assertFalse((root / "work").exists())


def _manifest() -> dict:
    return {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "canonical-fixture", "planArtifactRoot": "tasks/canonical-fixture"},
        "planFiles": ["tasks/canonical-fixture/plan.manifest.json"],
        "packageIntegrity": {
            "required": True,
            "lockSchemaVersion": "agent-plan-lock.v2",
            "inventorySource": "planFiles",
            "undeclaredTopLevelFiles": "reject",
        },
        "specification": {
            "tier": "S2",
            "requirements": [
                {"id": "REQ-01", "description": "first"},
                {"id": "REQ-02", "description": "second"},
            ],
            "tierResolutionRequest": {"requirementsBytes": 1024},
        },
        "acceptance": {
            "criteria": [
                {"id": "AC-01", "requirementIds": ["REQ-01"], "evidenceIds": ["EV-01"]},
                {"id": "AC-02", "requirementIds": ["REQ-02"], "evidenceIds": ["EV-02"]},
            ]
        },
        "workstreams": [
            {
                "id": "WS-01",
                "dependsOn": [],
                "writes": ["src/one.py"],
                "acceptanceIds": ["AC-01", "AC-02"],
                "evidenceIds": ["EV-01", "EV-02"],
            }
        ],
        "validation": {"commands": ["python -m unittest"]},
        "budgets": {"maxInvocations": 3},
        "contextLimits": {"targetTokens": 1024},
        "forbiddenWrites": [".git"],
        "finalAuditGates": [
            "[AC-01|EV-01] first",
            "[AC-02|EV-02] second",
        ],
        "releaseTarget": {"targetVersion": "1.0.0"},
    }


def _codes(result: dict) -> set[str]:
    return {item["code"] for item in result["blockers"]}


if __name__ == "__main__":
    unittest.main()

"""Compact authoring preserves native canonical authority and refusal boundaries."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError, canonical_bytes
from agent_lifecycle.contracts.compact_plan_schemas import COMPACT_RISKS, load_compact_plan_input
from agent_lifecycle.contracts.evidence_receipt_schemas import validate_expected_evidence
from agent_lifecycle.planning.compact_packages import (
    build_plan_package_profiles,
    compile_compact_plan,
    explain_compact_plan,
)
from agent_lifecycle.planning.completeness import build_plan_completeness_profile, validate_plan_completeness
from agent_lifecycle.planning.traceability import validate_plan_traceability
from agent_lifecycle.planning.validation import validate_plan_manifest
from agent_lifecycle.workflow.audit_evidence import validate_task_evidence_paths

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SOURCE = "tasks/compact-example/compact-input.json"
_OUTPUT = "tasks/compact-example/plan.manifest.json"


def _source(tier: str = "S0") -> dict:
    return load_compact_plan_input((_FIXTURES / ("compact-" + tier.lower() + "-plan.json")).read_bytes())


def _compile(source: dict) -> dict:
    return compile_compact_plan(source, source_path=_SOURCE, manifest_path=_OUTPUT)


class CompactPackageTests(unittest.TestCase):
    def test_both_tiers_pass_existing_canonical_completeness_and_traceability(self) -> None:
        for tier in ("S0", "S1"):
            with self.subTest(tier=tier):
                manifest = _compile(_source(tier))
                self.assertEqual(validate_plan_manifest(manifest, require_completeness=True)["status"], "DRAFT")
                self.assertEqual(validate_plan_completeness(manifest)["status"], "PASS")
                self.assertEqual(validate_plan_traceability(manifest)["status"], "PASS")
                self.assertEqual(manifest["specification"]["tier"], tier)

    def test_translation_is_deterministic_detached_and_key_order_independent(self) -> None:
        source = _source("S1")
        original = deepcopy(source)
        first = _compile(source)
        second = _compile(dict(reversed(list(source.items()))))
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        self.assertEqual(source, original)
        first["orchestration"]["maxReportedTokensPerRun"] = 1
        first["workstreams"][0]["writes"].append("elsewhere.py")
        self.assertEqual(source, original)

    def test_caller_facts_and_caps_remain_explicit_in_canonical_fields(self) -> None:
        source = _source("S1")
        manifest = _compile(source)
        for field in (
            "author",
            "baseRevision",
            "releaseImpact",
            "securityGates",
            "contextLimits",
            "readOnly",
            "forbiddenWrites",
        ):
            self.assertEqual(manifest[field], source[field])
        for field, value in source["orchestration"].items():
            self.assertEqual(manifest["orchestration"][field], value)
        self.assertEqual(manifest["workstreams"][1]["dependsOn"], ["WS-Import"])
        self.assertEqual(manifest["workstreams"][0]["owner"], source["owner"])
        item = source["changes"][0]
        self.assertEqual(manifest["specification"]["requirements"][0]["description"], item["requirement"])
        self.assertEqual(manifest["acceptance"]["criteria"][0]["statement"], item["acceptance"])
        self.assertEqual(manifest["acceptance"]["evidence"][0]["artifactPath"], item["evidencePath"])
        self.assertNotIn("validation", manifest["acceptance"]["evidence"][0])
        for change, workstream in zip(source["changes"], manifest["workstreams"], strict=True):
            self.assertEqual(
                workstream["plannedItems"],
                [
                    {
                        "id": "AC-" + change["id"],
                        "title": change["title"],
                        "acceptanceIds": ["AC-" + change["id"]],
                        "evidenceIds": ["EV-" + change["id"]],
                        "validationCommands": change["validationCommands"],
                    }
                ],
            )

    def test_generated_ordinary_evidence_passes_actual_native_consumer(self) -> None:
        for tier in ("S0", "S1"):
            source = _source(tier)
            manifest = _compile(source)
            with self.subTest(tier=tier), TemporaryDirectory() as temporary:
                root = Path(temporary)
                for entry, task in zip(manifest["acceptance"]["evidence"], manifest["workstreams"], strict=True):
                    path = root / entry["artifactPath"]
                    path.parent.mkdir(parents=True, exist_ok=True)
                    raw = canonical_bytes({"case": "CONTROLLED_ORDINARY_EVIDENCE", "evidenceId": entry["id"]}) + b"\n"
                    path.write_bytes(raw)
                    actual = validate_task_evidence_paths(root, manifest, {}, task, {}, None, [entry["artifactPath"]])
                    self.assertEqual(actual["requiredEvidenceIds"], [entry["id"]])
                    self.assertEqual(actual["missingEvidenceIds"], [])
                    self.assertEqual(actual["suppliedEvidence"][0]["path"], entry["artifactPath"])
                    self.assertEqual(path.read_bytes(), raw)

    def test_commands_only_typed_descriptor_and_unsupported_source_guarantees_still_refuse(self) -> None:
        with self.assertRaises(LifecycleError) as raised:
            validate_expected_evidence({"commands": _source()["changes"][0]["validationCommands"]})
        self.assertEqual(raised.exception.code, "evidence-receipt-invalid")
        for field in ("validation", "producerRequirement", "provenance"):
            source = _source()
            source["changes"][0][field] = {"required": True}
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                _compile(source)

    def test_pending_review_marker_never_supplies_acceptance_or_authorization(self) -> None:
        manifest = _compile(_source())
        self.assertEqual(manifest["status"], "DRAFT")
        self.assertTrue(manifest["planReview"]["required"])
        self.assertEqual(manifest["planReview"]["report"], "tasks/compact-example/independent-plan-review.json")
        self.assertEqual(manifest["planFiles"], sorted([_SOURCE, _OUTPUT, manifest["planReview"]["report"]]))
        self.assertEqual(manifest["packageIntegrity"]["lockSchemaVersion"], "agent-plan-lock.v2")
        self.assertEqual(manifest["orchestration"]["startMode"], "manual-after-freeze")
        self.assertTrue(manifest["implementationAudit"]["required"])
        for field in ("authorization", "modelRoute", "reviewer", "immutableInput", "runtimePolicy"):
            self.assertNotIn(field, manifest)

    def test_risk_and_missing_tier_cannot_downgrade(self) -> None:
        for risk in COMPACT_RISKS:
            source = _source()
            source["riskFlags"][risk] = True
            with self.subTest(risk=risk), self.assertRaises(LifecycleError) as raised:
                _compile(source)
            self.assertEqual(raised.exception.code, "compact-plan-full-s2-required")
        for tier in (None, "", "S2", "S9", True, []):
            source = _source()
            source["tier"] = tier
            with self.subTest(tier=tier), self.assertRaises(LifecycleError):
                _compile(source)

    def test_caller_cannot_hide_count_or_owner_or_authority(self) -> None:
        for field, value in (("owner", "second-worker"), ("taskCount", 1), ("reviewer", "same-worker")):
            source = _source()
            source["changes"][0][field] = value
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                _compile(source)
        source = _source("S1")
        source["tier"] = "S0"
        source["mechanical"] = True
        with self.assertRaises(LifecycleError):
            _compile(source)

    def test_explicit_higher_s1_tier_does_not_silently_downgrade(self) -> None:
        source = _source()
        source["tier"] = "S1"
        self.assertEqual(_compile(source)["specification"]["tier"], "S1")

    def test_large_embedded_requirements_require_s2(self) -> None:
        source = _source("S1")
        source["changes"] = []
        for index in range(9):
            item = deepcopy(_source()["changes"][0])
            item.update(
                id="Item" + str(index),
                requirement="x" * 3700,
                writes=[f"src/item{index}.py"],
                evidencePath=f"work/compact-example/{index}.json",
            )
            source["changes"].append(item)
        with self.assertRaises(LifecycleError) as raised:
            _compile(source)
        self.assertEqual(raised.exception.code, "compact-plan-full-s2-required")

    def test_protected_source_runtime_and_input_output_collisions_refuse(self) -> None:
        for path in (
            ".git/config",
            "tasks/compact-example/compact-input.json",
            "work/compact-example/result.json",
            "src/existing_input.py",
            "src/existing_input.py/child",
        ):
            source = _source()
            source["changes"][0]["writes"] = [path]
            with self.subTest(path=path), self.assertRaises(LifecycleError):
                _compile(source)
        for source_path in (
            _OUTPUT,
            "tasks/compact-example/independent-plan-review.json",
            "other/input.json",
            "tasks/compact-example/*.json",
        ):
            with self.subTest(source=source_path), self.assertRaises(LifecycleError):
                compile_compact_plan(_source(), source_path=source_path, manifest_path=_OUTPUT)
        for output in ("outside/plan.manifest.json", _SOURCE):
            with self.subTest(output=output), self.assertRaises(LifecycleError):
                compile_compact_plan(_source(), source_path=_SOURCE, manifest_path=output)

    def test_root_and_restriction_aliases_evidence_escape_and_shared_writes_refuse(self) -> None:
        for mutate in (
            lambda s: s["package"].update(artifactRoot="tasks/compact-example/runtime"),
            lambda s: s["package"].update(artifactRoot="TASKS/COMPACT-EXAMPLE"),
            lambda s: s["readOnly"].append("work"),
            lambda s: s["changes"][0].update(evidencePath="outside/result.json"),
            lambda s: s["changes"][1].update(writes=["src/example_worker.py"]),
        ):
            source = _source("S1")
            mutate(source)
            with self.assertRaises(LifecycleError):
                _compile(source)

    def test_budget_and_evidence_facts_cannot_disappear(self) -> None:
        for field in ("orchestration", "contextLimits", "securityGates", "releaseImpact"):
            source = _source()
            del source[field]
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                _compile(source)

    def test_source_cannot_be_nested_under_manifest_or_pending_review(self) -> None:
        for source_path in (
            "tasks/compact-example/plan.manifest.json/input.json",
            "tasks/compact-example/independent-plan-review.json/input.json",
            "tasks/compact-example/PLAN.MANIFEST.JSON/input.json",
            "tasks/compact-example/INDEPENDENT-PLAN-REVIEW.JSON/input.json",
            "tasks/compact-example",
        ):
            with self.subTest(source=source_path), self.assertRaises(LifecycleError):
                compile_compact_plan(_source(), source_path=source_path, manifest_path=_OUTPUT)
            explanation = explain_compact_plan(_source(), source_path=source_path, manifest_path=_OUTPUT)
            self.assertEqual(explanation["status"], "FAIL")
            self.assertFalse(explanation["filesWritten"])

    def test_distinct_sibling_source_names_with_shared_text_prefix_are_valid(self) -> None:
        for source_path in (
            "tasks/compact-example/plan.manifest.json-input.json",
            "tasks/compact-example/independent-plan-review.json.source.json",
            "tasks/compact-example/source/input.json",
        ):
            with self.subTest(source=source_path):
                manifest = compile_compact_plan(_source(), source_path=source_path, manifest_path=_OUTPUT)
                self.assertEqual(manifest["status"], "DRAFT")
                self.assertIn(source_path, manifest["planFiles"])

    def test_output_size_bound_is_checked_before_return(self) -> None:
        with (
            patch("agent_lifecycle.planning.compact_packages.MAX_COMPACT_OUTPUT_BYTES", 100),
            self.assertRaises(LifecycleError) as raised,
        ):
            _compile(_source())
        self.assertEqual(raised.exception.code, "compact-plan-output-too-large")

    def test_existing_full_s2_fixture_and_global_profiles_remain_unchanged(self) -> None:
        path = _FIXTURES / "full-s2-plan.json"
        raw = path.read_bytes()
        legacy = json.loads(raw)
        before = canonical_bytes(build_plan_completeness_profile())
        self.assertEqual(validate_plan_manifest(legacy, require_completeness=True)["status"], "FROZEN")
        profiles = build_plan_package_profiles()
        self.assertEqual([x["tier"] for x in profiles["profiles"]], ["S0", "S1", "S2"])
        self.assertFalse(profiles["profiles"][2]["compactSupported"])
        for profile in profiles["profiles"]:
            self.assertTrue(profile["reviewedLockRequired"])
            self.assertTrue(profile["separateAuthorizationRequired"])
            self.assertTrue(profile["requiredArtifacts"])
            self.assertIn("independent", profile["reviewLevel"])
        _compile(_source("S1"))
        self.assertEqual(canonical_bytes(build_plan_completeness_profile()), before)
        self.assertEqual(path.read_bytes(), raw)

    def test_explanation_is_read_only_and_reports_escalation_without_payload_echo(self) -> None:
        source = _source("S1")
        original = deepcopy(source)
        explanation = explain_compact_plan(source, source_path=_SOURCE, manifest_path=_OUTPUT)
        self.assertEqual(explanation["status"], "PASS")
        self.assertEqual(explanation["mapping"][1]["requirementId"], "R-Guide")
        self.assertFalse(explanation["filesWritten"])
        self.assertFalse(explanation["authorityClaimed"])
        self.assertEqual(source, original)
        source["riskFlags"]["security"] = True
        refusal = explain_compact_plan(source, source_path=_SOURCE, manifest_path=_OUTPUT)
        self.assertEqual(refusal["status"], "FAIL")
        self.assertEqual(refusal["resolvedTier"], "S2")
        self.assertFalse(refusal["filesWritten"])
        self.assertTrue(refusal["nextCommands"])


if __name__ == "__main__":
    unittest.main()

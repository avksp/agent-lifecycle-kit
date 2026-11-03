"""Decision research contracts and synthetic native fixtures, not host proof."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_bytes,
    canonical_digest,
)
from agent_lifecycle.contracts.plan_manifest_schemas import (
    DECISION_CAPS,
    DECISION_CRITERIA,
    DECISION_RECORD_SCHEMA,
    DECISION_REQUIREMENT_SCHEMA,
    DECISION_SCOPE,
    MANIFEST_SCHEMA,
)
from agent_lifecycle.contracts.schemas import get_schema
from agent_lifecycle.planning.completeness import validate_plan_completeness
from agent_lifecycle.planning.manifest_contract import validate_plan_manifest_contract
from agent_lifecycle.planning.task_compatibility import (
    canonical_task_contract,
    task_contract_digest,
    task_contracts_compatible,
)
from agent_lifecycle.research import preflight
from agent_lifecycle.workflow import adopt_plan, start_execution, start_task, status
from agent_lifecycle.workflow.continuation import continue_workflow
from agent_lifecycle.workflow.initialization import initialize_workflow_state
from tests.research.test_evidence_validation import _package as _evidence_fixture
from tests.workflow.helpers import _write_state
from tests.workflow.plan_helpers import _plan_manifest, _write_plan_bundle


def _raw_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _declaration(tier: str = "S1") -> tuple[dict, dict, dict]:
    manifest = _plan_manifest()
    manifest.update(
        {
            "schemaVersion": MANIFEST_SCHEMA,
            "author": {"id": "fixture-author", "runId": "fixture-author-run"},
            "baseRevision": {"ref": "fixture", "sha": "source-2"},
            "planFiles": ["plan.manifest.json", "spec.md", "decision.json"],
        }
    )
    manifest["specification"]["tier"] = tier
    manifest["specification"]["source"] = "spec.md"
    workstream = manifest["workstreams"][0]
    workstream.update(
        {
            "contextRefs": ["spec.md"],
            "plannedItems": ["REQ-WORK"],
            "acceptanceIds": ["AC-WORK"],
            "evidenceIds": ["EV-WORK"],
        }
    )
    requirement = {
        "schemaVersion": DECISION_REQUIREMENT_SCHEMA,
        "scope": DECISION_SCOPE,
        "profile": {
            "tier": tier,
            "requiredCriteria": list(DECISION_CRITERIA[tier]),
            **{name: high for name, (_, high) in DECISION_CAPS.items()},
        },
        "inputs": [
            {
                "sourceId": "specification",
                "path": "spec.md",
                "sha256": _raw_digest(b"Fixture requirement\n"),
            }
        ],
        "record": {"path": "decision.json", "sha256": "f" * 64},
    }
    workstream["decisionResearch"] = requirement
    _seal(manifest, workstream)
    return manifest, workstream, requirement


def _seal(manifest: dict, workstream: dict) -> None:
    requirement = workstream["decisionResearch"]
    requirement["inputDigest"] = preflight.decision_input_digest(requirement["inputs"])
    requirement["policyDigest"] = preflight.decision_policy_digest(requirement)
    requirement["scopeDigest"] = preflight.decision_scope_digest(manifest, workstream)


def _record(requirement: dict) -> dict:
    return {
        "schemaVersion": DECISION_RECORD_SCHEMA,
        **{key: requirement[key] for key in ("scopeDigest", "policyDigest", "inputDigest")},
        "ownerId": "worker",
        "entryPoints": ["src/task.py"],
        "alternatives": [
            {
                "id": "unchanged",
                "kind": "NO_CHANGE",
                "title": "Keep",
                "rationale": "The existing route already fits this fixture.",
            }
        ],
        "selectedAlternativeId": "unchanged",
        "outcome": "KEEP",
        "assessments": [
            {
                "criterion": criterion,
                "status": "ADDRESSED",
                "rationale": "Bounded local inspection.",
                "sourceIds": ["specification"],
            }
            for criterion in requirement["profile"]["requiredCriteria"]
        ],
        "budget": {
            "maxCommands": 2,
            "reservedCommands": 1,
            "maxActiveSeconds": 60,
            "usageStatus": "UNAVAILABLE",
            "usedCommands": None,
            "usedActiveSeconds": None,
        },
        "probeCount": 0,
        "reviewRoundCount": 1,
        "sourceOfTruth": False,
        "lifecycleAuthority": "none",
        "productionPromotionClaimed": False,
        "optimalityClaimed": False,
    }


def _native_fixture(
    root: Path,
    *,
    enabled: bool = True,
    state_schema: str | None = None,
    input_data: bytes = b"Fixture requirement\n",
    record_data: bytes | None = None,
) -> tuple[Path, Path]:
    """Use real adoption/start writers with explicitly synthetic authorities."""
    _write_plan_bundle(root)
    if state_schema == "agent-workflow-state.v4":
        state_path = root / "run.state.json"
        initialize_workflow_state(state_path, run_id="run", package_id="package")
    else:
        state_path = _write_state(root, phase="READY")
        initial = json.loads(state_path.read_bytes())
        initial["runStartedAt"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        state_path.write_bytes(canonical_bytes(initial))
    manifest_path = root / "plans/package/plan.manifest.json"
    manifest, workstream, requirement = _declaration()
    plan_root = "plans/package/.agent-plan/package"
    manifest["planFiles"] = [
        manifest_path.relative_to(root).as_posix(),
        f"{plan_root}/spec.md",
        f"{plan_root}/decision.json",
        manifest["planReview"]["report"],
    ]
    manifest["specification"]["source"] = f"{plan_root}/spec.md"
    workstream["contextRefs"] = [f"{plan_root}/spec.md"]
    requirement["inputs"][0]["sha256"] = _raw_digest(input_data)
    _seal(manifest, workstream)
    (root / plan_root / "spec.md").write_bytes(input_data)
    raw = canonical_bytes(_record(requirement)) if record_data is None else record_data
    (root / plan_root / "decision.json").write_bytes(raw)
    requirement["record"]["sha256"] = _raw_digest(raw)
    if not enabled:
        workstream.pop("decisionResearch")
    manifest_path.write_bytes(canonical_bytes(manifest))
    digest = canonical_digest(manifest)
    review = {
        "schemaVersion": "agent-plan-review.v1",
        "reviewId": "SYNTHETIC-FIXTURE-REVIEW",
        "reviewer": {
            "id": "fixture-reviewer",
            "runId": "fixture-review-run",
            "surface": "unit-fixture",
            "independent": True,
        },
        "reviewedPlanHash": digest,
        "planRevision": 2,
        "verdict": "READY_TO_FREEZE",
        "fullReview": True,
        "findings": [],
    }
    (root / manifest["planReview"]["report"]).write_bytes(canonical_bytes(review))
    lock = {
        "schemaVersion": "agent-plan-lock.v1",
        "planRevision": 2,
        "manifestHash": digest,
    }
    (root / plan_root / "plan.lock.json").write_bytes(canonical_bytes(lock))
    index_path = root / "plans/package/workflow/task-packets/index.json"
    index = json.loads(index_path.read_bytes())
    index["manifestDigest"] = digest
    index_path.write_bytes(canonical_bytes(index) + b"\n")
    adopt_plan(
        state_path,
        manifest_path=manifest_path,
        operation_id="fixture-adopt",
        expected_revision=1,
        source_revision="source-2",
        reset_tasks=True,
        start_mode="auto-after-freeze",
        authorized_by="fixture",
    )
    start_execution(
        state_path,
        operation_id="fixture-run",
        expected_revision=2,
        source_revision="source-2",
        reason="synthetic test",
    )
    return state_path, manifest_path


class DecisionResearchContractTests(unittest.TestCase):
    def test_registered_closed_schemas(self) -> None:
        for schema in (DECISION_REQUIREMENT_SCHEMA, DECISION_RECORD_SCHEMA):
            value = get_schema(schema)
            self.assertFalse(value["additionalProperties"])
            self.assertEqual(len(value["required"]), len(set(value["required"])))

    def test_descriptor_is_structural_without_filesystem_reads(self) -> None:
        manifest, workstream, _ = _declaration()
        with patch.object(preflight, "read_authority_bytes", side_effect=AssertionError):
            self.assertEqual(
                preflight.validate_decision_requirement(manifest, workstream),
                {"spec.md": "spec.md", "decision.json": "decision.json"},
            )
            self.assertEqual(validate_plan_manifest_contract(manifest)["status"], "PASS")

    def test_partial_unknown_bool_and_scope_are_not_opt_out(self) -> None:
        invalid = [None, {}, {"secret": "do-not-echo"}]
        for value in invalid:
            manifest, workstream, _ = _declaration()
            workstream["decisionResearch"] = value
            result = validate_plan_completeness(manifest)
            self.assertEqual(result["status"], "FAIL")
            self.assertNotIn("do-not-echo", json.dumps(result["blockers"]))
        for field, value in (
            ("scope", "LIVE_WORKSPACE"),
            ("schemaVersion", "future"),
            ("profile", None),
        ):
            manifest, workstream, requirement = _declaration()
            requirement[field] = value
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                preflight.validate_decision_requirement(manifest, workstream)
        for cap in DECISION_CAPS:
            for value in (True, -1, 999999, None):
                manifest, workstream, requirement = _declaration()
                requirement["profile"][cap] = value
                with self.subTest(cap=cap, value=value), self.assertRaises(LifecycleError):
                    preflight.validate_decision_requirement(manifest, workstream)

    def test_s0_brief_and_s2_floor(self) -> None:
        for tier in ("S0", "S1", "S2"):
            manifest, workstream, requirement = _declaration(tier)
            preflight.validate_decision_requirement(manifest, workstream)
            preflight.validate_decision_record(_record(requirement), requirement, owner="worker", snapshots={})
        manifest, workstream, requirement = _declaration("S2")
        requirement["profile"]["tier"] = "S0"
        _seal(manifest, workstream)
        with self.assertRaises(LifecycleError):
            preflight.validate_decision_requirement(manifest, workstream)

    def test_raw_digest_scope_and_reference_domains(self) -> None:
        manifest, workstream, requirement = _declaration()
        original = requirement["scopeDigest"]
        manifest["planRevision"] += 1
        workstream["artifactPaths"]["result"] = "different/attempt-{attempt}/result.json"
        manifest["workstreams"].append({"id": "unrelated", "title": "other"})
        manifest["specification"]["requirements"].append({"id": "other"})
        self.assertEqual(preflight.decision_scope_digest(manifest, workstream), original)
        workstream["writes"].append("additional")
        self.assertNotEqual(preflight.decision_scope_digest(manifest, workstream), original)
        for name in ("../spec.md", "/spec.md", "C:spec.md", "a\\b", "plan.manifest.json"):
            manifest, workstream, requirement = _declaration()
            requirement["inputs"][0]["path"] = name
            _seal(manifest, workstream)
            with self.subTest(name=name), self.assertRaises(LifecycleError):
                preflight.validate_decision_requirement(manifest, workstream)
        manifest, workstream, requirement = _declaration()
        manifest["planFiles"].append("other/spec.md")
        with self.assertRaises(LifecycleError):
            preflight.validate_decision_requirement(manifest, workstream)
        self.assertNotEqual(_raw_digest(b'{"a": 1}\n'), canonical_digest({"a": 1}))

    def test_reference_duplicates_input_scope_and_digest_mismatches(self) -> None:
        for mode in ("duplicate", "outside", "spec-missing", "overlap", "hash"):
            manifest, workstream, requirement = _declaration()
            if mode == "duplicate":
                requirement["inputs"].append(deepcopy(requirement["inputs"][0]))
            elif mode == "outside":
                workstream["contextRefs"] = []
            elif mode == "spec-missing":
                manifest["specification"]["source"] = "other.md"
            elif mode == "overlap":
                requirement["record"]["path"] = "spec.md"
            else:
                requirement["inputDigest"] = "0" * 64
            if mode != "hash":
                _seal(manifest, workstream)
            with self.subTest(mode=mode), self.assertRaises(LifecycleError):
                preflight.validate_decision_requirement(manifest, workstream)

    def test_bounded_real_reads_and_json_errors_do_not_echo_contents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "input.txt"
            path.write_bytes(b"a" * 17)
            self.assertEqual(preflight._read(root, "input.txt", 17, _raw_digest(b"a" * 17)), b"a" * 17)
            for name, cap in (("input.txt", 16), ("absent", 17), (".", 17)):
                with self.subTest(name=name), self.assertRaises(LifecycleError):
                    preflight._read(root, name, cap, "0" * 64)
            for raw in (b"\xff", b'{"x": "SECRET", "x": 1}', b"SECRET", b"[]"):
                with self.subTest(raw=raw), self.assertRaises(LifecycleError) as caught:
                    preflight._json(raw)
                self.assertNotIn("SECRET", str(caught.exception))

    def test_invalid_assessments_and_declared_usage_refuse(self) -> None:
        _, _, requirement = _declaration()
        record = _record(requirement)
        record["budget"].update({"usageStatus": "DECLARED", "usedCommands": 1, "usedActiveSeconds": 2.5})
        preflight.validate_decision_record(record, requirement, owner="worker", snapshots={})
        for mode in ("reason", "source", "duplicate", "no-change", "over-time", "bool-time"):
            bad = deepcopy(record)
            if mode == "reason":
                bad["assessments"][0].update({"status": "NOT_APPLICABLE", "rationale": ""})
            elif mode == "source":
                bad["assessments"][0]["sourceIds"] = ["undeclared"]
            elif mode == "duplicate":
                bad["alternatives"].append(deepcopy(bad["alternatives"][0]))
            elif mode == "no-change":
                bad["alternatives"][0]["kind"] = "REPLACE"
            else:
                bad["budget"]["usedActiveSeconds"] = 61 if mode == "over-time" else True
            with self.subTest(mode=mode), self.assertRaises(LifecycleError):
                preflight.validate_decision_record(bad, requirement, owner="worker", snapshots={})

    def test_optional_evidence_requires_actual_declared_snapshots(self) -> None:
        manifest, workstream, requirement = _declaration()
        package, texts = _evidence_fixture()
        raw = texts["source-1"].encode("utf-8")
        requirement["inputs"][0].update({"sourceId": "source-1", "sha256": _raw_digest(raw)})
        _seal(manifest, workstream)
        record = _record(requirement)
        for assessment in record["assessments"]:
            assessment["sourceIds"] = ["source-1"]
        record["evidencePackage"] = package
        preflight.validate_decision_record(record, requirement, owner="worker", snapshots={"source-1": raw})
        for snapshots in ({}, {"source-1": b"different"}, {"undeclared": raw}):
            with self.subTest(sources=list(snapshots)), self.assertRaises(LifecycleError):
                preflight.validate_decision_record(record, requirement, owner="worker", snapshots=snapshots)

    def test_record_rejects_authority_bad_usage_and_incomplete_assessment(self) -> None:
        _, _, requirement = _declaration("S2")
        for field, value in (
            ("sourceOfTruth", True),
            ("optimalityClaimed", 0),
            ("lifecycleAuthority", "native"),
            ("ownerId", "wrong"),
            ("outcome", "STOP"),
            ("outcome", "SPLIT"),
            ("selectedAlternativeId", []),
            ("assessments", []),
            ("evidencePackage", {}),
            ("reviewRoundCount", True),
        ):
            record = _record(requirement)
            record[field] = value
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                preflight.validate_decision_record(record, requirement, owner="worker", snapshots={})
        for field, value in (
            ("usedCommands", 0),
            ("usedActiveSeconds", 0),
            ("maxCommands", True),
            ("reservedCommands", 2),
        ):
            record = _record(requirement)
            record["budget"][field] = value
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                preflight.validate_decision_record(record, requirement, owner="worker", snapshots={})


class DecisionResearchCompatibilityTests(unittest.TestCase):
    def test_legacy_digest_unchanged_when_absent(self) -> None:
        task = {
            "id": "LEGACY-01",
            "title": "Legacy compatibility fixture",
            "owner": "legacy-owner",
            "writes": ["src/example.py"],
            "dependsOn": [],
            "contextRefs": ["plan/specification.md"],
            "acceptanceIds": ["AC01"],
            "evidenceIds": ["EV01"],
            "artifactPaths": {"result": "work/result.json", "review": "work/review.json"},
        }
        self.assertNotIn("decisionResearch", canonical_task_contract(task))
        self.assertEqual(
            task_contract_digest(task),
            "5515d58179082cda734b62444acc80255bf052889a35330630480c2bb373c410",
        )

    def test_policy_change_prevents_accepted_preservation(self) -> None:
        old = {"id": "one", "status": "ACCEPTED"}
        new = {**old, "decisionResearch": {"scopeDigest": "a" * 64}}
        changed = deepcopy(new)
        changed["decisionResearch"]["scopeDigest"] = "b" * 64
        self.assertFalse(task_contracts_compatible(old, new))
        self.assertFalse(task_contracts_compatible(new, old))
        self.assertFalse(task_contracts_compatible(new, changed))
        self.assertTrue(task_contracts_compatible(new, deepcopy(new)))


class DecisionResearchNativeTests(unittest.TestCase):
    def test_invalid_or_overcap_actual_bytes_refuse_without_mutation(self) -> None:
        for mode, input_data, record_data in (
            ("utf8", b"\xff", None),
            ("input-cap", b"a" * 65537, None),
            ("record-cap", b"Fixture requirement\n", b"x" * 262145),
            ("record-json", b"Fixture requirement\n", b'{"SECRET":'),
            ("missing-record", b"Fixture requirement\n", None),
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state_path, _ = _native_fixture(root, input_data=input_data, record_data=record_data)
                if mode == "missing-record":
                    (root / "plans/package/.agent-plan/package/decision.json").unlink()
                before = state_path.read_bytes(), (root / "events.jsonl").read_bytes()
                with self.assertRaises(LifecycleError) as caught:
                    start_task(
                        state_path,
                        task_id="WS-01",
                        operation_id="invalid",
                        expected_revision=3,
                        source_revision="source-2",
                        reason="test",
                    )
                self.assertTrue(caught.exception.code.startswith("decision-research-"))
                self.assertNotIn("SECRET", str(caught.exception))
                self.assertEqual((state_path.read_bytes(), (root / "events.jsonl").read_bytes()), before)

    def test_symlink_input_refuses_even_with_matching_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path, _ = _native_fixture(root)
            source = root / "plans/package/.agent-plan/package/spec.md"
            target = root / "same-bytes.md"
            target.write_bytes(source.read_bytes())
            source.unlink()
            try:
                source.symlink_to(target)
            except OSError:
                self.skipTest("This fixture cannot create a symlink on this host")
            before = state_path.read_bytes(), (root / "events.jsonl").read_bytes()
            with self.assertRaises(LifecycleError):
                start_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="symlink",
                    expected_revision=3,
                    source_revision="source-2",
                    reason="test",
                )
            self.assertEqual((state_path.read_bytes(), (root / "events.jsonl").read_bytes()), before)

    def test_unverifiable_read_identity_refuses_without_echo_or_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path, _ = _native_fixture(root)
            before = state_path.read_bytes(), (root / "events.jsonl").read_bytes()
            failure = LifecycleError("authority-input-changed", "SECRET-read-detail")
            with (
                patch.object(preflight, "read_authority_bytes", side_effect=failure),
                self.assertRaises(LifecycleError) as caught,
            ):
                start_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="growth",
                    expected_revision=3,
                    source_revision="source-2",
                    reason="test",
                )
            self.assertNotIn("SECRET", str(caught.exception))
            self.assertEqual((state_path.read_bytes(), (root / "events.jsonl").read_bytes()), before)

    def test_v4_adoption_status_roundtrip_preserves_optional_slot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path, _ = _native_fixture(root, state_schema="agent-workflow-state.v4")
            self.assertEqual(json.loads(state_path.read_bytes())["schemaVersion"], "agent-workflow-state.v4")
            self.assertEqual(status(state_path)["phase"], "RUNNING")
            self.assertIn("decisionResearch", json.loads(state_path.read_bytes())["tasks"][0])

    def test_adoption_status_and_successful_start_use_actual_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path, _ = _native_fixture(root)
            stored = json.loads(state_path.read_bytes())
            self.assertIn("decisionResearch", stored["tasks"][0])
            self.assertEqual(status(state_path)["phase"], "RUNNING")
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="fixture-task",
                expected_revision=3,
                source_revision="source-2",
                reason="test",
            )
            events = (root / "events.jsonl").read_text()
            self.assertIn('"decisionResearch"', events)
            self.assertNotIn("Bounded local inspection.", events)

    def test_stale_input_refuses_direct_start_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path, _ = _native_fixture(root)
            (root / "plans/package/.agent-plan/package/spec.md").write_text(
                "changed SECRET_VALUE_DO_NOT_ECHO", encoding="utf-8"
            )
            before = state_path.read_bytes(), (root / "events.jsonl").read_bytes()
            with self.assertRaises(LifecycleError) as caught:
                start_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="stale",
                    expected_revision=3,
                    source_revision="source-2",
                    reason="test",
                )
            self.assertEqual(caught.exception.code, "decision-research-input-stale")
            self.assertNotIn("SECRET_VALUE", str(caught.exception))
            self.assertEqual(
                (state_path.read_bytes(), (root / "events.jsonl").read_bytes()),
                before,
            )

    def test_opt_out_retains_legacy_behavior_without_reads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path, _ = _native_fixture(root, enabled=False)
            with patch.object(preflight, "read_authority_bytes", side_effect=AssertionError):
                start_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="legacy",
                    expected_revision=3,
                    source_revision="source-2",
                    reason="test",
                )
            state = json.loads(state_path.read_bytes())
            self.assertNotIn("decisionResearch", state["tasks"][0])
            last = json.loads((root / "events.jsonl").read_text().splitlines()[-1])
            self.assertNotIn("decisionResearch", last["payload"])

    def test_unchanged_inputs_allow_planned_output_without_research_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path, manifest_path = _native_fixture(root)
            state = json.loads(state_path.read_bytes())
            manifest = json.loads(manifest_path.read_bytes())
            first, _ = preflight.check_decision_preflight(root, manifest, state, state["tasks"][0])
            (root / "src").mkdir(exist_ok=True)
            (root / "src/task.py").write_text("# Planned output\n", encoding="utf-8")
            second, _ = preflight.check_decision_preflight(root, manifest, state, state["tasks"][0])
            self.assertEqual(first, second)
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="output",
                expected_revision=3,
                source_revision="source-2",
                reason="synthetic test",
            )

    def test_copied_policy_or_context_tampering_refuses(self) -> None:
        for mode in ("policy", "context", "unadopted", "missing-copy", "stale-review"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state_path, manifest_path = _native_fixture(root)
                state = json.loads(state_path.read_bytes())
                manifest = json.loads(manifest_path.read_bytes())
                if mode == "policy":
                    state["tasks"][0]["decisionResearch"]["profile"]["maxInputs"] = True
                elif mode == "context":
                    state["tasks"][0]["contextRefs"] = []
                elif mode == "missing-copy":
                    state["tasks"][0].pop("decisionResearch")
                elif mode == "stale-review":
                    (root / manifest["planReview"]["report"]).write_bytes(b'{"secret":"SECRET"}')
                else:
                    manifest = None
                with self.assertRaises(LifecycleError):
                    preflight.check_decision_preflight(root, manifest, state, state["tasks"][0])

    def test_continue_reuses_native_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path, manifest_path = _native_fixture(root)
            common = {
                "state_path": state_path,
                "manifest_path": manifest_path,
                "operation_id": "continue",
                "expected_revision": 3,
                "source_revision": "source-2",
                "reason": "synthetic test",
                "lock_path": root / "plans/package/.agent-plan/package/plan.lock.json",
            }
            projection = continue_workflow(**common)
            (root / "plans/package/.agent-plan/package/spec.md").write_bytes(b"changed")
            applied = continue_workflow(
                **common,
                apply=True,
                projected_state_revision=3,
                projected_action_digest=projection["action"]["actionDigest"],
            )
            self.assertEqual(applied["status"], "BLOCKED")
            self.assertIn("decision-research-input-stale", json.dumps(applied))
            state = json.loads(state_path.read_bytes())
            self.assertEqual(state["tasks"][0]["status"], "READY")
            self.assertNotIn('"task-started"', (root / "events.jsonl").read_text())


if __name__ == "__main__":
    unittest.main()

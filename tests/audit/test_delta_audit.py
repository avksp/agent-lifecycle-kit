from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.audit import build_rework_delta_audit, validate_rework_delta_audit
from agent_lifecycle.audit.delta import _declared_gate_ids
from agent_lifecycle.changesets import capture_task_change_set
from agent_lifecycle.contracts import canonical_digest, write_json_create
from agent_lifecycle.contracts.finding_check_schemas import (
    build_finding_check_binding,
    build_finding_check_evidence,
    build_finding_impact_scope,
    transition_finding_check_binding,
)
from agent_lifecycle.quality.dependency_impact import build_module_dependency_report
from agent_lifecycle.workflow.artifacts import artifact_identity


class DeltaAuditTests(unittest.TestCase):
    def test_adjacent_attempt_delta_can_prove_finding_not_affected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _bundle(Path(tmp), transitive=False)

            receipt = build_rework_delta_audit(**bundle["args"])

            self.assertEqual(receipt["status"], "PASS")
            self.assertEqual(receipt["disposition"], "DELTA_REVIEW_AVAILABLE")
            self.assertEqual(receipt["previousAttempt"], 1)
            self.assertEqual(receipt["currentAttempt"], 2)
            self.assertEqual(receipt["findingDispositions"][0]["disposition"], "NOT_AFFECTED")
            self.assertFalse(receipt["commandsExecuted"])
            self.assertEqual(validate_rework_delta_audit(receipt)["status"], "PASS")
            self.assertNotIn("content", json.dumps(receipt))

    def test_transitive_dependency_impact_forces_full_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _bundle(Path(tmp), transitive=True)

            receipt = build_rework_delta_audit(**bundle["args"])

            self.assertEqual(receipt["status"], "FAIL")
            self.assertEqual(receipt["disposition"], "FULL_AUDIT_REQUIRED")
            self.assertEqual(receipt["findingDispositions"][0]["disposition"], "UNAVAILABLE")
            self.assertIn(
                "FINDING_SCOPE_TRANSITIVELY_AFFECTED",
                receipt["findingDispositions"][0]["reasons"],
            )
            self.assertEqual(validate_rework_delta_audit(receipt)["status"], "PASS")

    def test_pass_evidence_cannot_close_a_transitively_affected_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _bundle(Path(tmp), transitive=True)
            evidence = build_finding_check_evidence(
                bundle["binding"],
                result="PASS",
                source_revision=bundle["sourceRevision"],
                evidence_ids=["EV-1"],
            )
            evidence_path = Path(tmp) / "evidence.json"
            write_json_create(evidence_path, evidence)
            bundle["args"]["finding_check_evidence_paths"] = [evidence_path]

            receipt = build_rework_delta_audit(**bundle["args"])

            self.assertEqual(receipt["status"], "FAIL")
            self.assertEqual(receipt["findingDispositions"][0]["disposition"], "UNAVAILABLE")
            self.assertEqual(receipt["findingDispositions"][0]["evidenceDigest"], evidence["evidenceDigest"])
            self.assertIn(
                "FINDING_SCOPE_TRANSITIVELY_AFFECTED",
                receipt["findingDispositions"][0]["reasons"],
            )
            self.assertFalse(receipt["commandsExecuted"])

    def test_approved_pass_evidence_closes_disjoint_finding_without_executing_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _bundle(Path(tmp), transitive=False)
            evidence = build_finding_check_evidence(
                bundle["binding"],
                result="PASS",
                source_revision=bundle["sourceRevision"],
                evidence_ids=["EV-1"],
            )
            evidence_path = Path(tmp) / "evidence.json"
            write_json_create(evidence_path, evidence)
            bundle["args"]["finding_check_evidence_paths"] = [evidence_path]

            receipt = build_rework_delta_audit(**bundle["args"])

            self.assertEqual(receipt["status"], "PASS")
            self.assertEqual(receipt["findingDispositions"][0]["disposition"], "VERIFIED_CLOSED")
            self.assertFalse(receipt["commandsExecuted"])

    def test_legacy_snapshot_without_entries_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _bundle(Path(tmp), transitive=False)
            audit_path = Path(bundle["previousAuditPath"])
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            audit["result"]["changeSetEvidence"].pop("entries")
            audit["reportDigest"] = canonical_digest(
                {key: value for key, value in audit.items() if key != "reportDigest"}
            )
            audit_path.unlink()
            write_json_create(audit_path, audit)
            state_path = Path(bundle["args"]["state_path"])
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["attemptHistory"][0]["implementationAuditReport"] = artifact_identity(
                Path(tmp), "work/WS-01/attempt-1/implementation-audit.json", audit
            )
            state_path.write_text(json.dumps(state), encoding="utf-8")

            with self.assertRaisesRegex(Exception, "bounded entry snapshot"):
                build_rework_delta_audit(**bundle["args"])

    def test_snapshot_entry_with_invalid_mode_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _bundle(Path(tmp), transitive=False)
            audit_path = Path(bundle["previousAuditPath"])
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            audit["result"]["changeSetEvidence"]["entries"][0]["mode"] = 100644
            _rewrite_previous_audit(bundle, audit)

            with self.assertRaisesRegex(Exception, "bounded entry snapshot"):
                build_rework_delta_audit(**bundle["args"])

    def test_stale_dependency_report_and_selection_force_full_audit(self) -> None:
        for stale_input in ("dependency", "selection"):
            with self.subTest(stale_input=stale_input), tempfile.TemporaryDirectory() as tmp:
                bundle = _bundle(Path(tmp), transitive=False)
                if stale_input == "dependency":
                    (Path(tmp) / "src/agent_lifecycle/consumer.py").write_text("VALUE = 2\n", encoding="utf-8")
                    expected = "DEPENDENCY_REPORT_INVALID_OR_STALE"
                else:
                    selection_path = Path(bundle["args"]["validation_selection_path"])
                    selection = json.loads(selection_path.read_text(encoding="utf-8"))
                    selection["stateRevision"] = 6
                    selection["selectionDigest"] = canonical_digest(
                        {key: value for key, value in selection.items() if key != "selectionDigest"}
                    )
                    selection_path.unlink()
                    write_json_create(selection_path, selection)
                    expected = "VALIDATION_SELECTION_INVALID_OR_STALE"

                receipt = build_rework_delta_audit(**bundle["args"])

                self.assertEqual(receipt["disposition"], "FULL_AUDIT_REQUIRED")
                self.assertIn(expected, {item["reason"] for item in receipt["blockers"]})

    def test_protected_and_unexpected_paths_force_full_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _bundle(Path(tmp), transitive=False)
            with patch(
                "agent_lifecycle.audit.delta.BUILT_IN_PROTECTED_PATH_PREFIXES",
                ("src/agent_lifecycle/leaf.py",),
            ):
                protected = build_rework_delta_audit(**bundle["args"])
            self.assertIn("PROTECTED_PATH", {item["reason"] for item in protected["blockers"]})

        with tempfile.TemporaryDirectory() as tmp:
            bundle = _bundle(Path(tmp), transitive=False)
            tool_path = Path(tmp) / "tools/check.py"
            tool_path.parent.mkdir()
            tool_path.write_text("VALUE = 1\n", encoding="utf-8")
            _refresh_current_result(bundle, ["src/agent_lifecycle/leaf.py", "tools/check.py"])

            unexpected = build_rework_delta_audit(**bundle["args"])

            reasons = {item["reason"] for item in unexpected["blockers"]}
            self.assertIn("UNEXPECTED_DELTA_PATH", reasons)
            self.assertIn("DELTA_PATH_OUTSIDE_MODULE_GRAPH", reasons)

    def test_scope_path_and_missing_gate_reference_force_full_audit(self) -> None:
        for mutation, expected in (
            ({"paths": ["src/agent_lifecycle/leaf.py"], "modules": ["agent_lifecycle.leaf"]}, "FINDING_SCOPE_PATH_AFFECTED"),
            ({"gate_ids": ["missing-gate"]}, "FINDING_IMPACT_SCOPE_REFERENCE_MISSING"),
        ):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                bundle = _bundle(Path(tmp), transitive=False)
                _replace_binding_scope(bundle, **mutation)

                receipt = build_rework_delta_audit(**bundle["args"])

                self.assertIn(expected, receipt["findingDispositions"][0]["reasons"])
                self.assertEqual(receipt["disposition"], "FULL_AUDIT_REQUIRED")

    def test_duplicate_and_invalid_finding_inputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _bundle(Path(tmp), transitive=False)
            binding_path = bundle["args"]["finding_check_binding_paths"][0]
            bundle["args"]["finding_check_binding_paths"] = [binding_path, binding_path]
            with self.assertRaisesRegex(Exception, "unique by findingId"):
                build_rework_delta_audit(**bundle["args"])

        with tempfile.TemporaryDirectory() as tmp:
            bundle = _bundle(Path(tmp), transitive=False)
            evidence = build_finding_check_evidence(
                bundle["binding"],
                result="PASS",
                source_revision=bundle["sourceRevision"],
                evidence_ids=["EV-1"],
            )
            evidence["checkIdentity"] = {"id": "other", "route": "validation/other"}
            evidence["evidenceDigest"] = canonical_digest(
                {key: value for key, value in evidence.items() if key != "evidenceDigest"}
            )
            evidence_path = Path(tmp) / "evidence.json"
            write_json_create(evidence_path, evidence)
            bundle["args"]["finding_check_evidence_paths"] = [evidence_path]

            receipt = build_rework_delta_audit(**bundle["args"])

            self.assertIn("FINDING_CHECK_EVIDENCE_INVALID", receipt["findingDispositions"][0]["reasons"])

    def test_receipt_validator_rechecks_derived_lineage_and_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _bundle(Path(tmp), transitive=False)
            receipt = build_rework_delta_audit(**bundle["args"])
            self.assertEqual(validate_rework_delta_audit(receipt)["status"], "PASS")

            def mutated(change) -> dict:
                value = json.loads(json.dumps(receipt))
                change(value)
                value["receiptDigest"] = canonical_digest(
                    {key: item for key, item in value.items() if key != "receiptDigest"}
                )
                return value

            cases = (
                (
                    "delta-audit-attempt-not-adjacent",
                    lambda value: value.__setitem__("currentAttempt", 3),
                ),
                (
                    "delta-audit-plan-lineage-invalid",
                    lambda value: value["planLineage"].__setitem__("planDigest", "invalid"),
                ),
                (
                    "delta-audit-attempt-delta-digest-mismatch",
                    lambda value: value["attemptDelta"].__setitem__("currentSnapshotHash", "f" * 64),
                ),
                (
                    "delta-audit-attempt-delta-invalid",
                    lambda value: value["attemptDelta"]["entries"][0]["current"].__setitem__("mode", 100644),
                ),
                (
                    "delta-audit-shape-invalid",
                    lambda value: value.__setitem__("reviewerText", "not authority"),
                ),
                (
                    "delta-audit-authority-boundary",
                    lambda value: value.__setitem__("commandsExecuted", True),
                ),
            )
            for code, change in cases:
                with self.subTest(code=code):
                    validation = validate_rework_delta_audit(mutated(change))
                    self.assertIn(code, {item["code"] for item in validation["blockers"]})

    def test_final_audit_gate_prefix_exposes_stable_ids(self) -> None:
        self.assertEqual(
            _declared_gate_ids(["[AC-1|EV-1] prose can change", {"id": "gate-2"}]),
            {"[AC-1|EV-1] prose can change", "AC-1", "EV-1", "gate-2"},
        )


def _bundle(root: Path, *, transitive: bool) -> dict:
    _init_repo(root, transitive=transitive)
    baseline = _git(root, "rev-parse", "HEAD")
    manifest = _manifest(baseline)
    plan_digest = canonical_digest(manifest)
    manifest_path = root / "tasks/release/plan.manifest.json"
    lock_path = root / "tasks/release/plan.lock.json"
    write_json_create(manifest_path, manifest)
    lock = {"schemaVersion": "agent-plan-lock.v1", "planRevision": 1, "manifestHash": plan_digest}
    write_json_create(lock_path, lock)

    changed = root / "src/agent_lifecycle/leaf.py"
    changed.write_text("VALUE = 2\n", encoding="utf-8")
    previous_snapshot = capture_task_change_set(root, baseline=baseline, write_paths=["src/agent_lifecycle/leaf.py"])
    previous_result = _result(plan_digest, baseline, attempt=1, snapshot=previous_snapshot)
    previous_review = {"schemaVersion": "agent-task-review.v2", "reviewId": "review-1", "verdict": "REWORK"}
    previous_result_path = "work/WS-01/attempt-1/task-result.json"
    previous_review_path = "work/WS-01/attempt-1/task-review.json"
    write_json_create(root / previous_result_path, previous_result)
    write_json_create(root / previous_review_path, previous_review)
    previous_audit = _audit(plan_digest, baseline, previous_snapshot)
    previous_audit_path = "work/WS-01/attempt-1/implementation-audit.json"
    write_json_create(root / previous_audit_path, previous_audit)

    changed.write_text("VALUE = 3\n", encoding="utf-8")
    current_snapshot = capture_task_change_set(root, baseline=baseline, write_paths=["src/agent_lifecycle/leaf.py"])
    current_result = _result(plan_digest, baseline, attempt=2, snapshot=current_snapshot)
    current_result_path = "work/WS-01/attempt-2/task-result.json"
    write_json_create(root / current_result_path, current_result)
    state = {
        "schemaVersion": "agent-workflow-state.v3",
        "runId": "run-1",
        "packageId": "release-test",
        "planRevision": 1,
        "planDigest": plan_digest,
        "sourceRevision": baseline,
        "stateRevision": 7,
        "phase": "STEP_REVIEW",
        "manifestPath": "tasks/release/plan.manifest.json",
        "authorization": {"required": False, "granted": True},
        "budgets": {"maxTaskAttempts": 2},
        "tasks": [
            {
                "id": "WS-01",
                "status": "VERIFYING",
                "attempt": 2,
                "dependsOn": [],
                "required": True,
                "writes": ["src/agent_lifecycle/leaf.py"],
                "acceptanceIds": ["AC-1"],
                "evidenceIds": [],
                "artifactPaths": {
                    "result": "work/WS-01/attempt-{attempt}/task-result.json",
                    "review": "work/WS-01/attempt-{attempt}/task-review.json",
                },
                "result": artifact_identity(root, current_result_path, current_result),
                "remediationFindingIds": ["F-1"],
                "attemptHistory": [
                    {
                        "schemaVersion": "agent-task-attempt-history-entry.v1",
                        "runId": "run-1",
                        "packageId": "release-test",
                        "taskId": "WS-01",
                        "attempt": 1,
                        "planRevision": 1,
                        "planDigest": plan_digest,
                        "sourceRevision": baseline,
                        "result": artifact_identity(root, previous_result_path, previous_result),
                        "review": artifact_identity(root, previous_review_path, previous_review),
                        "implementationAuditReport": artifact_identity(root, previous_audit_path, previous_audit),
                        "findingIds": ["F-1"],
                        "archivedAt": "2026-09-01T00:00:00Z",
                    }
                ],
            }
        ],
        "eventLog": "events.jsonl",
    }
    state_path = root / "run.state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    dependency_report = build_module_dependency_report(root / "src/agent_lifecycle", repository_root=root)
    dependency_report_path = root / "dependency-report.json"
    write_json_create(
        dependency_report_path,
        {"schemaVersion": "agent-module-dependency-validation.v2", "dependencyReport": dependency_report},
    )
    selection = {
        "schemaVersion": "agent-validation-selection.v1",
        "status": "PASS",
        "disposition": "SELECTED",
        "level": "TASK_ACCEPTANCE",
        "selectedCheckIds": ["check-1"],
        "matchedMappingIds": ["mapping-1"],
        "reasons": ["MAPPING_MATCH"],
        "planDigest": plan_digest,
        "planLockDigest": canonical_digest(lock),
        "stateRevision": 7,
        "sourceRevision": baseline,
        "currentTreeDigest": current_snapshot["snapshotHash"],
        "profileDigest": "1" * 64,
        "catalogDigest": "2" * 64,
        "commandsExecuted": False,
        "stateWritten": False,
        "blockers": [],
    }
    selection["selectionDigest"] = canonical_digest(selection)
    selection_path = root / "selection.json"
    write_json_create(selection_path, selection)

    scope_module = "agent_lifecycle.consumer" if transitive else "agent_lifecycle"
    scope_path = "src/agent_lifecycle/consumer.py" if transitive else "src/agent_lifecycle/__init__.py"
    scope = build_finding_impact_scope(
        finding_id="F-1",
        finding_digest="a" * 64,
        plan_revision=1,
        plan_digest=plan_digest,
        source_revision=baseline,
        paths=[scope_path],
        modules=[scope_module],
        acceptance_ids=["AC-1"],
        gate_ids=["gate-1"],
    )
    binding = build_finding_check_binding(
        finding_id="F-1",
        finding_digest="a" * 64,
        plan_delta_digest="b" * 64,
        plan_lineage={
            "packageId": "release-test",
            "planRevision": 1,
            "planDigest": plan_digest,
            "sourceRevision": baseline,
        },
        check_identity={"id": "check-1", "route": "validation/check-1"},
        owner="WS-01",
        scope=scope,
        source_revision=baseline,
    )
    accepted = transition_finding_check_binding(
        binding,
        "ACCEPTED",
        authorization={"status": "APPROVED", "actor": "operator", "operationId": "accept-1", "authorityClaimed": False},
    )["binding"]
    binding_path = root / "binding.json"
    write_json_create(binding_path, accepted)
    return {
        "root": root,
        "binding": accepted,
        "sourceRevision": baseline,
        "previousAuditPath": root / previous_audit_path,
        "args": {
            "manifest_path": manifest_path,
            "lock_path": lock_path,
            "state_path": state_path,
            "task_id": "WS-01",
            "dependency_report_path": dependency_report_path,
            "validation_selection_path": selection_path,
            "finding_check_binding_paths": [binding_path],
            "finding_check_evidence_paths": [],
        },
    }


def _rewrite_previous_audit(bundle: dict, audit: dict) -> None:
    audit["reportDigest"] = canonical_digest({key: value for key, value in audit.items() if key != "reportDigest"})
    audit_path = Path(bundle["previousAuditPath"])
    audit_path.unlink()
    write_json_create(audit_path, audit)
    state_path = Path(bundle["args"]["state_path"])
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["tasks"][0]["attemptHistory"][0]["implementationAuditReport"] = artifact_identity(
        bundle["root"], "work/WS-01/attempt-1/implementation-audit.json", audit
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")


def _refresh_current_result(bundle: dict, write_paths: list[str]) -> None:
    root = bundle["root"]
    state_path = Path(bundle["args"]["state_path"])
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["tasks"][0]["writes"] = write_paths
    snapshot = capture_task_change_set(root, baseline=bundle["sourceRevision"], write_paths=write_paths)
    result = _result(state["planDigest"], bundle["sourceRevision"], attempt=2, snapshot=snapshot)
    result_path = root / "work/WS-01/attempt-2/task-result.json"
    result_path.unlink()
    write_json_create(result_path, result)
    state["tasks"][0]["result"] = artifact_identity(root, "work/WS-01/attempt-2/task-result.json", result)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    selection_path = Path(bundle["args"]["validation_selection_path"])
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    selection["currentTreeDigest"] = snapshot["snapshotHash"]
    selection["selectionDigest"] = canonical_digest(
        {key: value for key, value in selection.items() if key != "selectionDigest"}
    )
    selection_path.unlink()
    write_json_create(selection_path, selection)


def _replace_binding_scope(bundle: dict, **overrides) -> None:
    binding = bundle["binding"]
    old_scope = binding["scope"]
    scope = build_finding_impact_scope(
        finding_id=binding["findingId"],
        finding_digest=binding["findingDigest"],
        plan_revision=old_scope["planRevision"],
        plan_digest=old_scope["planDigest"],
        source_revision=old_scope["sourceRevision"],
        paths=overrides.get("paths", old_scope["paths"]),
        modules=overrides.get("modules", old_scope["modules"]),
        ownership_paths=overrides.get("ownership_paths", old_scope["ownershipPaths"]),
        acceptance_ids=overrides.get("acceptance_ids", old_scope["acceptanceIds"]),
        gate_ids=overrides.get("gate_ids", old_scope["gateIds"]),
    )
    proposed = build_finding_check_binding(
        finding_id=binding["findingId"],
        finding_digest=binding["findingDigest"],
        plan_delta_digest=binding["planDeltaDigest"],
        plan_lineage=binding["planLineage"],
        check_identity=binding["checkIdentity"],
        owner=binding["owner"],
        scope=scope,
        source_revision=binding["sourceRevision"],
        expected_result=binding["expectedResult"],
    )
    accepted = transition_finding_check_binding(
        proposed,
        "ACCEPTED",
        authorization={"status": "APPROVED", "actor": "operator", "operationId": "accept-2", "authorityClaimed": False},
    )["binding"]
    binding_path = Path(bundle["args"]["finding_check_binding_paths"][0])
    binding_path.unlink()
    write_json_create(binding_path, accepted)
    bundle["binding"] = accepted


def _manifest(baseline: str) -> dict:
    return {
        "schemaVersion": "3.0",
        "status": "FROZEN",
        "planRevision": 1,
        "baseRevision": {"ref": "main", "sha": baseline},
        "package": {"id": "release-test", "artifactRoot": "work/release", "planArtifactRoot": "tasks/release"},
        "workstreams": [{"id": "WS-01", "writes": ["src/agent_lifecycle/leaf.py"]}],
        "acceptance": {"criteria": [{"id": "AC-1", "requirementIds": [], "evidenceIds": []}]},
        "finalAuditGates": ["gate-1"],
    }


def _result(plan_digest: str, baseline: str, *, attempt: int, snapshot: dict) -> dict:
    return {
        "schemaVersion": "agent-task-result.v2",
        "runId": "run-1",
        "taskId": "WS-01",
        "attempt": attempt,
        "planDigest": plan_digest,
        "sourceRevision": baseline,
        "actor": "worker",
        "actorRunId": "worker-run",
        "changedFiles": snapshot["changedFiles"],
        "changeSet": {
            "schemaVersion": "agent-task-change-set-claim.v1",
            **{key: snapshot[key] for key in ("provider", "baselineSha", "fileSetHash", "diffHash", "snapshotHash")},
        },
        "itemOutcomes": [
            {"plannedItemId": "I-1", "status": "COMPLETE", "changedFiles": snapshot["changedFiles"], "commandIds": []}
        ],
        "commands": [],
        "blocker": None,
        "contractChangeRequest": None,
    }


def _audit(plan_digest: str, baseline: str, snapshot: dict) -> dict:
    body = {
        "schemaVersion": "agent-implementation-audit-report.v1",
        "status": "FAIL",
        "verdict": "REWORK",
        "runId": "run-1",
        "packageId": "release-test",
        "taskId": "WS-01",
        "attempt": 1,
        "planRevision": 1,
        "planDigest": plan_digest,
        "sourceRevision": baseline,
        "auditor": {"id": "independent-auditor", "surface": "test", "independent": True},
        "result": {"changeSetEvidence": snapshot},
        "findings": [{"id": "F-1", "status": "open", "severity": "HIGH"}],
        "blockers": [{"code": "F-1"}],
        "productionPromotionClaimed": False,
    }
    return {**body, "reportDigest": canonical_digest(body)}


def _init_repo(root: Path, *, transitive: bool) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "ALK Tests"], cwd=root, check=True)
    package = root / "src/agent_lifecycle"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "leaf.py").write_text("VALUE = 1\n", encoding="utf-8")
    consumer = "from agent_lifecycle.leaf import VALUE\n" if transitive else "VALUE = 1\n"
    (package / "consumer.py").write_text(consumer, encoding="utf-8")
    subprocess.run(["git", "add", "src"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


if __name__ == "__main__":
    unittest.main()

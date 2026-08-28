"""Portable Release 2.6/2.7 workflow-shape baselines for continuation."""

from __future__ import annotations

import json
import tempfile
import unittest
from functools import cache
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import canonical_digest, write_json_create
from agent_lifecycle.contracts.canonical import write_json_replace_private
from agent_lifecycle.workflow import (
    adopt_plan,
    apply_final_audit_outcome,
    apply_task_review_outcome,
    authorize_execution,
    commit_task_result,
    continue_workflow,
    finalize_run,
    start_execution,
    start_task,
)

from .helpers import _completion_signal, _write_plan_bundle
from .helpers import _write_state as _write_adoption_state
from .test_authorization import _receipt as _authorization_receipt
from .test_final_audit_outcomes import _final_audit as _final_audit_report
from .test_final_audit_outcomes import _write_v4_state
from .test_task_acceptance_audit_gate import _write_bundle as _write_task_bundle
from .test_task_acceptance_audit_gate import _write_result_review
from .test_workflow_run import _write_bundle as _write_route_bundle

FIXTURE_ROOT = Path(__file__).parent / "fixtures"
FIXTURES = (
    FIXTURE_ROOT / "release-2-6-continuation-trace.json",
    FIXTURE_ROOT / "release-2-7-continuation-trace.json",
)

EVENT_SURFACES: dict[str, tuple[str | None, str | None, str]] = {
    "plan-adopted": (None, None, "workflow adopt-plan"),
    "execution-authorized": ("request-execution-authorization", "authorize", "workflow authorize"),
    "execution-started": ("start-execution", "run-start", "workflow run-start"),
    "task-started": ("launch-tasks", "task-start", "workflow task-start"),
    "task-result-committed": ("wait-for-active-tasks", "task-result", "workflow task-result"),
    "task-rework-requested": ("accept-task", "task-review-apply", "workflow task-review-apply"),
    "task-accepted": ("accept-task", "task-review-apply", "workflow task-review-apply"),
    "final-audit-outcome-applied": (
        "final-audit-outcome",
        "final-audit-outcome",
        "workflow final-audit-outcome",
    ),
    "run-finalized": ("finalize-run", "finalize", "workflow finalize"),
}


class WorkflowContinuationBaselineTests(unittest.TestCase):
    def test_fixture_inventory_matches_observed_release_shapes(self) -> None:
        expected = {"2.6": (23, 9, 24), "2.7": (28, 9, 30)}
        for path in FIXTURES:
            with self.subTest(path=path.name):
                fixture = _load(path)
                event_count, event_type_count, final_revision = expected[fixture["source"]["release"]]
                events = fixture["eventTrace"]

                self.assertEqual(len(events), event_count)
                self.assertEqual(len({event["eventType"] for event in events}), event_type_count)
                self.assertEqual(fixture["source"]["eventCount"], event_count)
                self.assertEqual(fixture["source"]["eventTypeCount"], event_type_count)
                self.assertEqual(fixture["finalState"]["stateRevision"], final_revision)
                self.assertEqual(fixture["finalState"]["phase"], "COMPLETE")
                self.assertEqual(fixture["interface"]["scope"], "post-adoption")
                _assert_source_identities(fixture)

    def test_direct_and_continuation_surfaces_replay_same_production_trace(self) -> None:
        for path in FIXTURES:
            with self.subTest(path=path.name):
                fixture = _load(path)

                direct = _replay(fixture, continuation=False)
                continuation = _replay(fixture, continuation=True)

                expected_events = [item["eventType"] for item in fixture["eventTrace"]]
                self.assertEqual(continuation, direct)
                self.assertEqual(continuation["eventTypes"], expected_events)
                self.assertEqual(continuation["attemptHistory"], fixture["eventDerivedState"]["tasks"])
                self.assertEqual(continuation["finalPhase"], fixture["eventDerivedState"]["phase"])

    def test_revision_gaps_and_unavailable_telemetry_remain_explicit(self) -> None:
        for path in FIXTURES:
            with self.subTest(path=path.name):
                fixture = _load(path)
                revisions = {event["stateRevision"] for event in fixture["eventTrace"]}
                gaps = fixture["eventLogGaps"]
                unavailable_revisions = {gap["stateRevision"] for gap in gaps}
                expected = set(range(2, fixture["finalState"]["stateRevision"] + 1))

                self.assertEqual(expected.difference(revisions), unavailable_revisions)
                self.assertTrue(all(gap["status"] == "UNAVAILABLE" for gap in gaps))
                self.assertTrue(all(value == "UNAVAILABLE" for value in fixture["telemetry"].values()))
                self.assertNotIn("reductionPercent", fixture)
                self.assertEqual(fixture["interface"]["maxTransitionsPerApply"], 1)
                for gap in gaps:
                    task = next(
                        item
                        for item in fixture["eventDerivedState"]["tasks"]
                        if item["taskId"] == gap["affectedTaskId"]
                    )
                    self.assertEqual(task["status"], "UNAVAILABLE")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_source_identities(fixture: dict[str, Any]) -> None:
    artifacts = fixture["source"]["artifacts"]
    for role in ("eventLog", "finalState"):
        identity = artifacts[role]
        if not (
            isinstance(identity["path"], str)
            and isinstance(identity["bytes"], int)
            and identity["bytes"] > 0
            and isinstance(identity["sha256"], str)
            and len(identity["sha256"]) == 64
        ):
            raise AssertionError(f"invalid {role} source identity")


def _replay(fixture: dict[str, Any], *, continuation: bool) -> dict[str, Any]:
    observed: list[dict[str, Any]] = []
    for event in fixture["eventTrace"]:
        event_type = _observed_event_type(event["eventType"], continuation)
        observed.append({**event, "eventType": event_type})
    return _reduce_events(observed, fixture["eventLogGaps"])


@cache
def _observed_event_type(event_type: str, continuation: bool) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        if event_type == "plan-adopted":
            return _capture_plan_adoption(root)
        if event_type == "execution-authorized":
            return _capture_authorization(root, continuation=continuation)
        if event_type in {"execution-started", "task-started"}:
            return _capture_start(root, event_type=event_type, continuation=continuation)
        if event_type in {"task-result-committed", "task-rework-requested", "task-accepted"}:
            return _capture_task_event(root, event_type=event_type, continuation=continuation)
        if event_type in {"final-audit-outcome-applied", "run-finalized"}:
            return _capture_final_event(root, event_type=event_type, continuation=continuation)
        raise AssertionError(f"unsupported workflow event: {event_type}")


def _capture_plan_adoption(root: Path) -> str:
    state_path = _write_adoption_state(
        root,
        phase="BLOCKED",
        blocker={"code": "plan-drift", "reason": "baseline", "resumePhase": "RUNNING"},
    )
    _write_plan_bundle(root)
    adopt_plan(
        state_path,
        manifest_path=root / "plans/package/plan.manifest.json",
        operation_id="probe-plan-adopted",
        expected_revision=1,
        source_revision="source-2",
        reset_tasks=True,
        start_mode="auto-after-freeze",
        authorized_by="baseline-probe",
    )
    return _last_event_type(root)


def _capture_authorization(root: Path, *, continuation: bool) -> str:
    manifest_path, state_path = _write_route_bundle(root, phase="AWAITING_AUTHORIZATION", task_status="READY")
    state = _read_state(state_path)
    state["schemaVersion"] = "agent-workflow-state.v4"
    state["startMode"] = "approval-required"
    state["authorization"] = {"required": True, "granted": False}
    state["operationLedger"] = {}
    state["budgets"] = {}
    state["blocker"] = None
    _write_state(state_path, state)
    write_json_create(root / "authorization.json", _authorization_receipt(state))
    if continuation:
        return _apply_continuation(
            manifest_path,
            state_path,
            expected_revision=1,
            inputs={"authorizationReceipt": "authorization.json"},
        )
    authorize_execution(
        state_path,
        operation_id="probe-execution-authorized",
        expected_revision=1,
        source_revision="source",
        receipt_path="authorization.json",
        reason="baseline probe",
    )
    return _last_event_type(root)


def _capture_start(root: Path, *, event_type: str, continuation: bool) -> str:
    phase = "READY" if event_type == "execution-started" else "RUNNING"
    manifest_path, state_path = _write_route_bundle(root, phase=phase, task_status="READY")
    if continuation:
        inputs = {"taskId": "WS-01"} if event_type == "task-started" else {}
        return _apply_continuation(manifest_path, state_path, expected_revision=1, inputs=inputs)
    if event_type == "execution-started":
        start_execution(
            state_path,
            operation_id="probe-execution-started",
            expected_revision=1,
            source_revision="source",
            reason="baseline probe",
        )
    else:
        start_task(
            state_path,
            task_id="WS-01",
            operation_id="probe-task-started",
            expected_revision=1,
            source_revision="source",
            reason="baseline probe",
        )
    return _last_event_type(root)


def _capture_task_event(root: Path, *, event_type: str, continuation: bool) -> str:
    bundle = _write_task_bundle(root, phase="RUNNING", task_status="READY", audit_required=False)
    manifest_path = Path(bundle["manifestPath"])
    state_path = Path(bundle["statePath"])
    if event_type == "task-rework-requested":
        state = _read_state(state_path)
        state["budgets"] = {"maxTaskAttempts": 2, "remediationMode": "ask", "maxParallelTasks": 1}
        _write_state(state_path, state)
    start_task(
        state_path,
        task_id="WS-01",
        operation_id="probe-task-precondition-start",
        expected_revision=1,
        source_revision="source",
        reason="baseline probe",
    )
    result_path, review_path = _write_result_review(root, bundle)
    if event_type == "task-rework-requested":
        _make_review_rework(root / review_path)
    if event_type == "task-result-committed":
        if continuation:
            return _apply_continuation(
                manifest_path,
                state_path,
                expected_revision=2,
                inputs={"taskId": "WS-01", "result": result_path},
            )
        commit_task_result(
            state_path,
            task_id="WS-01",
            operation_id="probe-task-result",
            expected_revision=2,
            source_revision="source",
            result_path=result_path,
            reason="baseline probe",
        )
        return _last_event_type(root)
    commit_task_result(
        state_path,
        task_id="WS-01",
        operation_id="probe-task-precondition-result",
        expected_revision=2,
        source_revision="source",
        result_path=result_path,
        reason="baseline probe",
    )
    finding_ids = ["PROBE-F1"] if event_type == "task-rework-requested" else None
    if continuation:
        inputs: dict[str, Any] = {"taskId": "WS-01", "review": review_path}
        if finding_ids is not None:
            inputs["findingIds"] = finding_ids
        return _apply_continuation(manifest_path, state_path, expected_revision=3, inputs=inputs)
    apply_task_review_outcome(
        state_path,
        task_id="WS-01",
        operation_id=f"probe-{event_type}",
        expected_revision=3,
        source_revision="source",
        review_path=review_path,
        finding_ids=finding_ids,
        reason="baseline probe",
    )
    return _last_event_type(root)


def _make_review_rework(path: Path) -> None:
    review = json.loads(path.read_text(encoding="utf-8"))
    review["verdict"] = "REWORK"
    review["itemReviews"][0].update({"verdict": "REWORK", "findingIds": ["PROBE-F1"]})
    review["findings"] = [
        {
            "id": "PROBE-F1",
            "status": "open",
            "severity": "MEDIUM",
            "path": "src/example.py",
            "line": 1,
            "rationale": "baseline probe",
        }
    ]
    write_json_replace_private(path, review)


def _capture_final_event(root: Path, *, event_type: str, continuation: bool) -> str:
    state_path = _write_v4_state(root)
    manifest_path = _bind_final_manifest(root, state_path)
    state = _read_state(state_path)
    audit = _final_audit_report(state, status="PASS", semantic_status="READY_FOR_FINALIZATION", findings=[])
    signal = _completion_signal("PASS")
    for key in ("runId", "packageId", "planRevision", "planDigest", "sourceRevision"):
        signal[key] = state[key]
    audit["completionSignal"] = signal
    write_json_create(root / "final/final-audit.json", audit)
    if event_type == "final-audit-outcome-applied":
        if continuation:
            return _apply_continuation(
                manifest_path,
                state_path,
                expected_revision=1,
                inputs={"finalAudit": "final/final-audit.json", "verdict": "ACCEPTED"},
            )
        apply_final_audit_outcome(
            state_path,
            operation_id="probe-final-audit",
            expected_revision=1,
            source_revision="source",
            final_audit_path="final/final-audit.json",
            verdict="ACCEPTED",
            reason="baseline probe",
        )
        return _last_event_type(root)
    apply_final_audit_outcome(
        state_path,
        operation_id="probe-final-precondition",
        expected_revision=1,
        source_revision="source",
        final_audit_path="final/final-audit.json",
        verdict="ACCEPTED",
        reason="baseline probe",
    )
    if continuation:
        return _apply_continuation(
            manifest_path,
            state_path,
            expected_revision=2,
            inputs={"finalAudit": "final/final-audit.json", "proof": "final/proof.json"},
        )
    finalize_run(
        state_path,
        operation_id="probe-run-finalized",
        expected_revision=2,
        source_revision="source",
        final_audit_path="final/final-audit.json",
        proof_path="final/proof.json",
        reason="baseline probe",
    )
    return _last_event_type(root)


def _bind_final_manifest(root: Path, state_path: Path) -> Path:
    manifest = {
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "package", "planArtifactRoot": "plans/package"},
        "readOnly": [],
        "forbiddenWrites": [],
        "leadOwned": [],
        "workstreams": [
            {
                "id": "WS-01",
                "title": "Task",
                "owner": "worker",
                "reviewer": "reviewer",
                "dependsOn": [],
                "writes": ["src/example.py"],
                "acceptanceIds": ["AC-01"],
                "evidenceIds": ["EV-01"],
            }
        ],
        "acceptanceCriteria": [{"id": "AC-01", "evidenceIds": ["EV-01"]}],
    }
    digest = canonical_digest(manifest)
    manifest_path = root / "plans/package/plan.manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    _write_state(manifest_path, manifest)
    _write_state(
        manifest_path.parent / "plan.lock.json",
        {"schemaVersion": "agent-plan-lock.v1", "planRevision": 1, "manifestHash": digest},
    )
    state = _read_state(state_path)
    state["planDigest"] = digest
    _write_state(state_path, state)
    return manifest_path


def _apply_continuation(
    manifest_path: Path,
    state_path: Path,
    *,
    expected_revision: int,
    inputs: dict[str, Any],
) -> str:
    operation_id = f"probe-continuation-{expected_revision}"
    projection = continue_workflow(
        state_path=state_path,
        manifest_path=manifest_path,
        operation_id=operation_id,
        expected_revision=expected_revision,
        source_revision="source",
        reason="baseline probe",
        inputs=inputs,
    )
    if projection["status"] != "READY":
        raise AssertionError(f"continuation projection failed: {projection}")
    receipt = continue_workflow(
        state_path=state_path,
        manifest_path=manifest_path,
        operation_id=operation_id,
        expected_revision=expected_revision,
        source_revision="source",
        reason="baseline probe",
        apply=True,
        projected_state_revision=projection["action"]["stateRevision"],
        projected_action_digest=projection["action"]["actionDigest"],
        inputs=inputs,
    )
    if receipt["status"] != "APPLIED":
        raise AssertionError(f"continuation apply failed: {receipt}")
    return str(receipt["appliedEvent"]["eventType"])


def _reduce_events(events: list[dict[str, Any]], gaps: list[dict[str, Any]]) -> dict[str, Any]:
    tasks: dict[str, dict[str, Any]] = {}
    phase = "AWAITING_AUTHORIZATION"
    for event in events:
        event_type = event["eventType"]
        task_id = event.get("taskId")
        if event_type == "execution-authorized":
            phase = "READY"
        elif event_type == "execution-started":
            phase = "RUNNING"
        elif event_type == "task-started" and isinstance(task_id, str):
            task = tasks.setdefault(task_id, {"taskId": task_id, "archivedAttempts": []})
            task.update({"attempt": event["attempt"], "status": "RUNNING"})
        elif event_type == "task-result-committed" and isinstance(task_id, str):
            tasks[task_id]["status"] = "VERIFYING"
        elif event_type == "task-rework-requested" and isinstance(task_id, str):
            task = tasks[task_id]
            task["archivedAttempts"].append(task["attempt"])
            task["status"] = "REWORK"
        elif event_type == "task-accepted" and isinstance(task_id, str):
            tasks[task_id]["status"] = "ACCEPTED"
        elif event_type == "final-audit-outcome-applied":
            phase = "BLOCKED" if event.get("verdict") == "CONTRACT_CHANGE" else "FINAL_AUDIT"
        elif event_type == "plan-adopted" and event.get("taskReset"):
            reset = event["taskReset"]
            for reset_task in reset.get("reset", []):
                tasks.pop(reset_task, None)
            for new_task in reset.get("add", []):
                tasks.setdefault(new_task, {"taskId": new_task, "archivedAttempts": [], "status": "PENDING"})
            phase = "READY"
        elif event_type == "run-finalized":
            phase = "COMPLETE"
    for gap in gaps:
        task_id = gap["affectedTaskId"]
        task = tasks.setdefault(task_id, {"taskId": task_id, "archivedAttempts": []})
        task["status"] = "UNAVAILABLE"
        task["statusEvidence"] = f"event-gap-revision-{gap['stateRevision']}"
    return {
        "eventTypes": [event["eventType"] for event in events],
        "attemptHistory": sorted(tasks.values(), key=lambda item: item["taskId"]),
        "finalPhase": phase,
    }


def _last_event_type(root: Path) -> str:
    events = (root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    return str(json.loads(events[-1])["eventType"])


def _read_state(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_state(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

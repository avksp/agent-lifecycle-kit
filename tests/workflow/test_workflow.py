from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError  # noqa: E402
from agent_lifecycle.contracts import canonical_digest, write_json_create  # noqa: E402
from agent_lifecycle.workflow import (  # noqa: E402
    accept_task,
    adopt_plan,
    block_run,
    commit_task_result,
    finalize_run,
    resolve_blocker,
    start_execution,
    start_task,
    status,
)


class WorkflowTests(unittest.TestCase):
    def test_status_reports_ready_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = _write_state(Path(tmp), phase="RUNNING")
            payload = status(state_path)
            self.assertEqual(payload["phase"], "RUNNING")
            self.assertEqual(payload["nextAction"]["type"], "launch-tasks")
            self.assertEqual(payload["nextAction"]["taskIds"], ["WS-01"])

    def test_block_run_uses_expected_revision_and_appends_wal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            payload = block_run(
                state_path,
                operation_id="block-op",
                expected_revision=1,
                blocker_code="test-blocker",
                reason="blocked for test",
            )
            self.assertEqual(payload["phase"], "BLOCKED")
            self.assertEqual(payload["identity"]["stateRevision"], 2)
            events = (root / "events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(events), 1)
            self.assertEqual(json.loads(events[0])["eventType"], "run-blocked")

    def test_block_run_rejects_revision_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = _write_state(Path(tmp), phase="RUNNING")
            with self.assertRaises(LifecycleError):
                block_run(
                    state_path,
                    operation_id="block-op",
                    expected_revision=2,
                    blocker_code="drift",
                    reason="wrong revision",
                )

    def test_resolve_blocker_restores_resume_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = _write_state(Path(tmp), phase="BLOCKED", blocker={"code": "x", "reason": "x", "resumePhase": "RUNNING"})
            payload = resolve_blocker(
                state_path,
                operation_id="resolve-op",
                expected_revision=1,
                reason="fixed",
            )
            self.assertEqual(payload["phase"], "RUNNING")
            self.assertIsNone(payload["blocker"])

    def test_start_task_skips_occupied_attempt_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING", max_attempts=2)
            occupied = root / "tasks/WS-01/attempt-1"
            occupied.mkdir(parents=True)
            (occupied / "task-result.json").write_text("{}", encoding="utf-8")
            payload = start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            task = next(item for item in payload["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "RUNNING")
            self.assertEqual(task["attempt"], 2)

    def test_start_task_requires_pre_launch_gate_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = _write_state(Path(tmp), phase="RUNNING")
            _add_gate(state_path, _gate("G-PRE", ["pre-launch"]))
            with self.assertRaises(LifecycleError):
                start_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="start-op",
                    expected_revision=1,
                    source_revision="source",
                    reason="launch",
                )

    def test_start_task_records_pre_launch_gate_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            gate = _gate("G-PRE", ["pre-launch"])
            _add_gate(state_path, gate)
            _write_gate_receipt(root, gate, phase="pre-launch", operation_id="start-op", attempt=1)
            payload = start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            task = next(item for item in payload["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "RUNNING")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            stored = next(item for item in state["tasks"] if item["id"] == "WS-01")
            self.assertEqual(stored["controllerGateReceipts"][0]["gateId"], "G-PRE")

    def test_start_task_accepts_state_level_gate_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            gate = _gate("G-PRE", ["pre-launch"])
            gate["dependsOnGateIds"] = ["G-AUTH"]
            _add_gate(state_path, gate)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["controllerGateReceipts"] = [{"gateId": "G-AUTH", "path": "gates/auth.json"}]
            state_path.write_text(json.dumps(state), encoding="utf-8")
            _write_gate_receipt(root, gate, phase="pre-launch", operation_id="start-op", attempt=1)

            payload = start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )

            task = next(item for item in payload["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "RUNNING")

    def test_commit_result_requires_post_attempt_gate_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            _add_gate(state_path, _gate("G-POST", ["post-attempt"]))
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            result_path = "tasks/WS-01/attempt-1/task-result.json"
            write_json_create(root / result_path, _result(attempt=1))
            with self.assertRaises(LifecycleError):
                commit_task_result(
                    state_path,
                    task_id="WS-01",
                    operation_id="result-op",
                    expected_revision=2,
                    source_revision="source",
                    result_path=result_path,
                    reason="done",
                )

    def test_commit_result_and_accept_review_unlocks_next_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            result_path = "tasks/WS-01/attempt-1/task-result.json"
            result = _result(attempt=1)
            write_json_create(root / result_path, result)
            commit_task_result(
                state_path,
                task_id="WS-01",
                operation_id="result-op",
                expected_revision=2,
                source_revision="source",
                result_path=result_path,
                reason="done",
            )
            review_path = "tasks/WS-01/attempt-1/task-review.json"
            review = _review(attempt=1, result_hash=canonical_digest(result))
            write_json_create(root / review_path, review)
            payload = accept_task(
                state_path,
                task_id="WS-01",
                operation_id="accept-op",
                expected_revision=3,
                review_path=review_path,
                reason="accepted",
            )
            task = next(item for item in payload["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "ACCEPTED")
            self.assertEqual(payload["phase"], "FINAL_AUDIT")

    def test_adopt_plan_resets_changed_plan_and_starts_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="BLOCKED", blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"})
            _write_plan_bundle(root)
            payload = adopt_plan(
                state_path,
                manifest_path=root / "plans/package/plan.manifest.json",
                operation_id="adopt-op",
                expected_revision=1,
                source_revision="source-2",
                reset_tasks=True,
                start_mode="auto-after-freeze",
                authorized_by="tester",
            )
            self.assertEqual(payload["phase"], "READY")
            self.assertEqual(payload["planRevision"], 2)
            self.assertEqual(payload["nextAction"]["type"], "start-execution")
            task = next(item for item in payload["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "READY")

            payload = start_execution(
                state_path,
                operation_id="run-op",
                expected_revision=2,
                source_revision="source-2",
                reason="go",
            )
            self.assertEqual(payload["phase"], "RUNNING")
            self.assertEqual(payload["nextAction"]["taskIds"], ["WS-01"])

    def test_adopt_plan_preserves_compatible_accepted_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="BLOCKED", blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"})
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["status"] = "ACCEPTED"
            state["tasks"][0]["attempt"] = 1
            state["tasks"][0]["result"] = {"path": "tasks/WS-01/attempt-1/task-result.json", "sha256": "2" * 64, "bytes": 10}
            state["tasks"][0]["review"] = {"path": "tasks/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            _write_plan_bundle(root)

            payload = adopt_plan(
                state_path,
                manifest_path=root / "plans/package/plan.manifest.json",
                operation_id="adopt-op",
                expected_revision=1,
                source_revision="source-2",
                reset_tasks=True,
                preserve_accepted_compatible=True,
                start_mode="auto-after-freeze",
                authorized_by="tester",
            )

            task = next(item for item in payload["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "ACCEPTED")
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            stored_task = next(item for item in stored["tasks"] if item["id"] == "WS-01")
            self.assertEqual(stored_task["adoptedFromPlanRevision"], 1)
            self.assertEqual(payload["phase"], "READY")

    def test_adopt_plan_preserve_unlocks_new_dependents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="BLOCKED", blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"})
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["status"] = "ACCEPTED"
            state["tasks"][0]["attempt"] = 1
            state_path.write_text(json.dumps(state), encoding="utf-8")
            _write_plan_bundle(root, include_dependent=True)

            payload = adopt_plan(
                state_path,
                manifest_path=root / "plans/package/plan.manifest.json",
                operation_id="adopt-op",
                expected_revision=1,
                source_revision="source-2",
                reset_tasks=True,
                preserve_accepted_compatible=True,
                start_mode="auto-after-freeze",
                authorized_by="tester",
            )

            task = next(item for item in payload["tasks"] if item["id"] == "WS-02")
            self.assertEqual(task["status"], "READY")

    def test_finalize_run_writes_proof_and_completes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["status"] = "ACCEPTED"
            state["tasks"][0]["attempt"] = 1
            state["tasks"][0]["review"] = {"path": "tasks/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            write_json_create(root / "final/final-audit.json", _final_audit())

            payload = finalize_run(
                state_path,
                operation_id="finalize-op",
                expected_revision=1,
                source_revision="source",
                final_audit_path="final/final-audit.json",
                proof_path="final/proof.json",
                reason="done",
            )

            self.assertEqual(payload["phase"], "COMPLETE")
            self.assertEqual(payload["nextAction"]["type"], "none")
            proof = json.loads((root / "final/proof.json").read_text(encoding="utf-8"))
            self.assertEqual(proof["schemaVersion"], "agent-run-final-proof.v1")
            self.assertFalse(proof["productionPromotionClaimed"])
            self.assertEqual(proof["finalAudit"]["path"], "final/final-audit.json")

    def test_finalize_run_rejects_final_audit_with_open_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["status"] = "ACCEPTED"
            state["tasks"][0]["attempt"] = 1
            state["tasks"][0]["review"] = {"path": "tasks/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            audit = _final_audit()
            audit["findings"] = [{"id": "F-1", "status": "open", "severity": "MEDIUM"}]
            write_json_create(root / "final/final-audit.json", audit)

            with self.assertRaises(LifecycleError):
                finalize_run(
                    state_path,
                    operation_id="finalize-op",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="final/final-audit.json",
                    proof_path="final/proof.json",
                    reason="done",
                )

    def test_finalize_run_requires_finalization_gate_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["status"] = "ACCEPTED"
            state["tasks"][0]["attempt"] = 1
            state["tasks"][0]["review"] = {"path": "tasks/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
            state["tasks"][0]["controllerGates"] = [_gate("G-FINAL", ["finalization"])]
            state_path.write_text(json.dumps(state), encoding="utf-8")
            write_json_create(root / "final/final-audit.json", _final_audit())

            with self.assertRaises(LifecycleError):
                finalize_run(
                    state_path,
                    operation_id="finalize-op",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="final/final-audit.json",
                    proof_path="final/proof.json",
                    reason="done",
                )


def _write_state(
    root: Path,
    *,
    phase: str,
    blocker: dict | None = None,
    max_attempts: int = 1,
) -> Path:
    path = root / "run.state.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "agent-workflow-state.v3",
                "runId": "run",
                "packageId": "package",
                "planRevision": 1,
                "planDigest": "0" * 64,
                "sourceRevision": "source",
                "stateRevision": 1,
                "phase": phase,
                "runStartedAt": "2026-07-22T00:00:00Z",
                "authorization": {"required": False, "granted": True},
                "budgets": {
                    "maxParallelTasks": 1,
                    "maxTaskAttempts": max_attempts,
                    "maxTaskWallSeconds": 3600,
                },
                "tasks": [
                    {
                        "id": "WS-01",
                        "title": "Task",
                        "owner": "worker",
                        "status": "READY",
                        "attempt": 0,
                        "dependsOn": [],
                        "writes": ["src"],
                        "reviewer": "reviewer",
                        "launchGate": "ready",
                        "capabilityHints": [],
                        "requiredTools": [],
                        "contextRefs": [],
                        "evidenceIds": [],
                        "executionPolicy": {"network": "denied", "approvals": "none"},
                        "required": True,
                        "artifactPaths": {
                            "result": "tasks/WS-01/attempt-{attempt}/task-result.json",
                            "review": "tasks/WS-01/attempt-{attempt}/task-review.json",
                        },
                        "packet": {
                            "sha256": "1" * 64,
                        },
                    }
                ],
                "eventLog": "events.jsonl",
                "blocker": blocker,
            }
        ),
        encoding="utf-8",
    )
    return path


def _add_gate(state_path: Path, gate: dict) -> None:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["tasks"][0].setdefault("controllerGateReceipts", [])
    state["tasks"][0]["controllerGates"] = [gate]
    state_path.write_text(json.dumps(state), encoding="utf-8")


def _gate(gate_id: str, phases: list[str]) -> dict:
    return {
        "id": gate_id,
        "phases": phases,
        "receiptPath": "gates/{gateId}/{taskId}/attempt-{attempt}/{phase}-{operationId}.json",
        "maxAgeSeconds": 7200,
        "attestationRequired": True,
        "dependsOnGateIds": [],
    }


def _write_gate_receipt(
    root: Path,
    gate: dict,
    *,
    phase: str,
    operation_id: str,
    attempt: int,
) -> None:
    path = _gate_receipt_path(gate, phase=phase, operation_id=operation_id, attempt=attempt)
    write_json_create(root / path, _gate_receipt(gate, phase=phase, operation_id=operation_id, attempt=attempt))


def _gate_receipt_path(gate: dict, *, phase: str, operation_id: str, attempt: int) -> str:
    return (
        str(gate["receiptPath"])
        .replace("{gateId}", gate["id"])
        .replace("{taskId}", "WS-01")
        .replace("{attempt}", str(attempt))
        .replace("{phase}", phase)
        .replace("{operationId}", operation_id)
    )


def _gate_receipt(gate: dict, *, phase: str, operation_id: str, attempt: int) -> dict:
    return {
        "schemaVersion": "agent-controller-gate-receipt.v1",
        "gateId": gate["id"],
        "runId": "run",
        "packageId": "package",
        "taskId": "WS-01",
        "attempt": attempt,
        "phase": phase,
        "operationId": operation_id,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "verdict": "PASS",
        "generatedAt": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "attestation": {
            "schemaVersion": "agent-controller-gate-attestation.v1",
            "claimsDigest": "a" * 64,
            "subjectDigest": "b" * 64,
            "scopeDigest": "c" * 64,
            "authorityDigest": "d" * 64,
            "signature": "signature",
        },
    }


def _write_plan_bundle(root: Path, *, include_dependent: bool = False) -> None:
    plan_root = root / "plans/package/.agent-plan/package"
    packet_root = root / "plans/package/workflow/task-packets"
    review_path = plan_root / "reviews/plan-review-r01.json"
    review = {
        "reviewId": "plan-review-r01",
        "reviewer": {"id": "reviewer", "runId": "review-run", "surface": "test"},
        "verdict": "READY_TO_FREEZE",
    }
    write_json_create(review_path, review)
    manifest = _plan_manifest(include_dependent=include_dependent)
    digest = canonical_digest(manifest)
    write_json_create(
        plan_root / "plan.lock.json",
        {"schemaVersion": "agent-plan-lock.v1", "planRevision": 2, "manifestHash": digest},
    )
    packets = []
    for index, workstream in enumerate(manifest["workstreams"], start=1):
        task_id = workstream["id"]
        packet = {
            "taskId": task_id,
            "path": f"plans/package/workflow/task-packets/{task_id}.task-packet.json",
            "sha256": hex(index)[2:] * 64,
            "bytes": 1,
            "dependsOn": workstream.get("dependsOn", []),
        }
        packets.append(packet)
        write_json_create(packet_root / f"{task_id}.task-packet.json", {"schemaVersion": "packet", "taskId": task_id})
    write_json_create(
        packet_root / "index.json",
        {
            "manifestDigest": digest,
            "packetSetHash": "b" * 64,
            "controllerValidation": None,
            "packets": packets,
        },
    )
    write_json_create(root / "plans/package/plan.manifest.json", manifest)


def _plan_manifest(*, include_dependent: bool = False) -> dict:
    workstreams = [
        {
            "id": "WS-01",
            "title": "Task",
            "owner": "worker",
            "dependsOn": [],
            "writes": ["src"],
            "reviewer": "reviewer",
            "launchGate": "ready",
            "capabilityHints": [],
            "requiredTools": [],
            "contextRefs": [],
            "evidenceIds": [],
            "executionPolicy": {"network": "denied", "approvals": "none"},
            "artifactPaths": {
                "result": "tasks/WS-01/attempt-{attempt}/task-result.json",
                "review": "tasks/WS-01/attempt-{attempt}/task-review.json",
            },
            "required": True,
        }
    ]
    if include_dependent:
        workstreams.append({
            "id": "WS-02",
            "title": "Dependent task",
            "owner": "worker",
            "dependsOn": ["WS-01"],
            "writes": ["docs"],
            "reviewer": "reviewer",
            "launchGate": "after WS-01",
            "capabilityHints": [],
            "requiredTools": [],
            "contextRefs": [],
            "evidenceIds": [],
            "executionPolicy": {"network": "denied", "approvals": "none"},
            "artifactPaths": {
                "result": "tasks/WS-02/attempt-{attempt}/task-result.json",
                "review": "tasks/WS-02/attempt-{attempt}/task-review.json",
            },
            "required": True,
        })
    return {
        "schemaVersion": "3.0",
        "status": "FROZEN",
        "planRevision": 2,
        "package": {
            "id": "package",
            "artifactRoot": "plans/package",
            "planArtifactRoot": "plans/package/.agent-plan/package",
        },
        "planReview": {
            "required": True,
            "verdict": "READY_TO_FREEZE",
            "reviewedRevision": 2,
            "report": "plans/package/.agent-plan/package/reviews/plan-review-r01.json",
        },
        "orchestration": {
            "maxParallelTasks": 1,
            "maxTaskAttempts": 1,
            "maxTaskWallSeconds": 3600,
            "maxRunWallSeconds": 86400,
        },
        "workstreams": workstreams,
    }


def _result(*, attempt: int) -> dict:
    return {
        "schemaVersion": "agent-task-result.v2",
        "runId": "run",
        "taskId": "WS-01",
        "attempt": attempt,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "actor": "worker",
        "actorRunId": "worker-run",
        "surface": "test",
        "taskPacketHash": "1" * 64,
        "traceDigest": "2" * 64,
        "changedFiles": ["src/example.py"],
        "changeSet": {
            "provider": "git-worktree-v1",
            "baselineRef": "main",
            "baselineSha": "source",
            "fileSetHash": "3" * 64,
            "diffHash": "4" * 64,
            "snapshotHash": "5" * 64,
        },
        "commands": [],
        "itemOutcomes": [
            {
                "plannedItemId": "REQ-FOUNDATION",
                "status": "COMPLETE",
                "changedFiles": ["src/example.py"],
                "commandIds": [],
            }
        ],
        "summary": "done",
        "assumptions": [],
        "blocker": None,
        "contractChangeRequest": None,
    }


def _review(*, attempt: int, result_hash: str) -> dict:
    return {
        "schemaVersion": "agent-task-review.v2",
        "reviewId": "review-1",
        "runId": "run",
        "taskId": "WS-01",
        "attempt": attempt,
        "planDigest": "0" * 64,
        "resultHash": result_hash,
        "taskPacketHash": "1" * 64,
        "traceDigest": "2" * 64,
        "reviewer": {
            "id": "reviewer",
            "independent": True,
            "surface": "test",
            "runId": "review-run",
        },
        "reviewedAt": "2026-07-22T00:00:00Z",
        "verdict": "ACCEPTED",
        "itemReviews": [
            {
                "plannedItemId": "REQ-FOUNDATION",
                "verdict": "ACCEPTED",
                "findingIds": [],
            }
        ],
        "acceptanceChecks": [
            {
                "acceptanceId": "AC-FOUNDATION",
                "status": "PASS",
                "evidenceIds": ["EV-FOUNDATION"],
                "findingIds": [],
            }
        ],
        "findings": [],
        "summary": "accepted",
    }


def _final_audit() -> dict:
    return {
        "schemaVersion": "agent-final-candidate-audit.v1",
        "status": "PASS",
        "semanticStatus": "READY_FOR_FINALIZATION",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "productionPromotionClaimed": False,
        "notAcceptedTasks": [],
        "missingReleaseEvidence": [],
        "findings": [],
    }


if __name__ == "__main__":
    unittest.main()

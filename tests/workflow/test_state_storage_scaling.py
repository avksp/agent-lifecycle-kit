"""Candidate native incident path; all review identities are fixture-only."""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
import tracemalloc
import unittest
from copy import deepcopy
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.workflow_storage import (
    iter_historical_snapshots,
    persist_storage,
    prepare_storage,
    validate_storage,
)
from agent_lifecycle.planning.task_compatibility import validate_task_plan_compatibility_receipt
from tests.workflow.storage_helpers import build_native_fixture, candidate_accept_assertions
from tests.workflow.test_state_storage import scale_fixture
from tests.workflow.test_state_storage_failures import RUNTIME, native, observe


def successor(root, revision, *, three_tasks=False):
    """Keep every old frozen manifest; synthetic reviews are fixture-only."""
    manifest = json.loads((root / "plans/package/plan.manifest.json").read_bytes())
    manifest["planRevision"] = revision
    manifest["orchestration"] = json.loads((root / "run.state.json").read_bytes())["budgets"]
    plan_root = f"plans/package-r{revision}"
    manifest["package"]["planArtifactRoot"] = plan_root
    if three_tasks:
        for number in (2, 3):
            task_id = f"WS-0{number}"
            manifest["workstreams"].append(
                {
                    "id": task_id,
                    "owner": "worker",
                    "writes": [f"src/example{number}.py"],
                    "dependsOn": [],
                    "artifactPaths": {
                        "result": f"work/{task_id}/attempt-{{attempt}}/task-result.json",
                        "review": f"work/{task_id}/attempt-{{attempt}}/task-review.json",
                    },
                }
            )
    manifest_path = root / plan_root / "plan.manifest.json"
    manifest_path.parent.mkdir()
    review_path = plan_root + "/fixture-only-plan-review.json"
    (root / review_path).write_bytes(
        canonical_bytes(
            {
                "schemaVersion": "fixture-only-plan-review.v1",
                "fixtureOnly": True,
                "reviewId": f"fixture-only-plan-review-{revision}",
                "reviewer": {
                    "id": "fixture-only-plan-reviewer",
                    "runId": "fixture-only-review-run",
                    "surface": "test",
                },
                "verdict": "READY_TO_FREEZE",
            }
        )
        + b"\n"
    )
    digest = canonical_digest(manifest)
    manifest_path.write_bytes(canonical_bytes(manifest) + b"\n")
    lock = {
        "schemaVersion": "agent-plan-lock.v1",
        "planRevision": revision,
        "manifestHash": digest,
        "reviewPath": review_path,
        "reviewId": f"fixture-only-plan-review-{revision}",
        "frozenBy": "fixture-only-operator",
    }
    (manifest_path.parent / "plan.lock.json").write_bytes(canonical_bytes(lock) + b"\n")
    index = root / "work/workflow/task-packets/index.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    packets = [
        {
            "taskId": task["id"],
            "path": f"work/workflow/task-packets/{task['id']}.task-packet.json",
            "sha256": "1" * 64,
            "bytes": 1,
            "dependsOn": [],
        }
        for task in manifest["workstreams"]
    ]
    index.write_bytes(
        canonical_bytes(
            {"manifestDigest": digest, "packetSetHash": "b" * 64, "controllerValidation": None, "packets": packets}
        )
        + b"\n"
    )
    return manifest_path


def artifact_hashes(root):
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((root / "work/WS-01").rglob("*.json"))
    }


class NativeIncidentCandidateTests(unittest.TestCase):
    def test_same_red_fingerprint_migrates_accepts_and_preserves_adoption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "fixture"
            path, review, audit, source, _ = build_native_fixture(RUNTIME, root)
            before = json.loads(path.read_bytes())
            old = artifact_hashes(root)
            native(
                root,
                "state-migrate",
                "--state",
                path,
                "--target-schema",
                "agent-workflow-state.v5",
                "--operation-id",
                "candidate-migrate",
                "--expected-revision",
                "3",
                "--source-revision",
                source,
            )
            native(
                root,
                "task-accept",
                "--state",
                path,
                "--task",
                "WS-01",
                "--operation-id",
                "candidate-accept",
                "--expected-revision",
                "4",
                "--source-revision",
                source,
                "--review",
                review,
                "--implementation-audit",
                audit,
                "--reason",
                "fixture only",
            )
            accepted = json.loads(path.read_bytes())
            candidate_accept_assertions(
                before, accepted, old_artifact_hashes=old, new_artifact_hashes=artifact_hashes(root)
            )
            manifest = successor(root, 2)
            native(
                root,
                "adopt-plan",
                "--state",
                path,
                "--manifest",
                manifest,
                "--operation-id",
                "candidate-adopt",
                "--expected-revision",
                "5",
                "--source-revision",
                source,
                "--reset-tasks",
                "--preserve-accepted-compatible",
                "--start-mode",
                "auto-after-freeze",
                "--authorized-by",
                "fixture-only",
            )
            adopted = json.loads(path.read_bytes())
            observe(
                {
                    "kind": "same-fingerprint-candidate",
                    "beforeBytes": len(canonical_bytes(before)) + 1,
                    "acceptedBytes": len(canonical_bytes(accepted)) + 1,
                    "adoptedBytes": len(canonical_bytes(adopted)) + 1,
                    "taskStatuses": [task["status"] for task in adopted["tasks"]],
                    "fixtureOnly": True,
                }
            )
            self.assertEqual(adopted["tasks"][0]["status"], "ACCEPTED")
            self.assertEqual(artifact_hashes(root), old)

    def test_three_tasks_ten_native_plan_revisions_with_rework(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "fixture"
            path, review, audit, source, _ = build_native_fixture(RUNTIME, root)
            before = json.loads(path.read_bytes())
            old = artifact_hashes(root)
            invoke(root, path, source, "state-migrate", "--target-schema", "agent-workflow-state.v5")
            invoke(
                root,
                path,
                source,
                "task-accept",
                "--task",
                "WS-01",
                "--review",
                review,
                "--implementation-audit",
                audit,
                "--reason",
                "fixture only",
            )
            for revision in range(2, 11):
                manifest = successor(root, revision, three_tasks=True)
                invoke(
                    root,
                    path,
                    source,
                    "adopt-plan",
                    "--manifest",
                    manifest,
                    "--reset-tasks",
                    "--preserve-accepted-compatible",
                    "--start-mode",
                    "auto-after-freeze",
                    "--authorized-by",
                    "fixture-only-operator",
                )
                if revision == 2:
                    invoke(root, path, source, "run-start", "--reason", "fixture only")
                    complete_fixture_task(root, path, source, "WS-02", rework=True)
                    complete_fixture_task(root, path, source, "WS-03")
            state = json.loads(path.read_bytes())
            history = list(iter_historical_snapshots(root, state))
            logical = len(canonical_bytes(history))
            self.assertGreater(logical, 1_048_576)
            self.assertEqual(len(history), 10)
            self.assertEqual([task["status"] for task in state["tasks"]], ["ACCEPTED"] * 3)
            self.assertEqual(len(state["tasks"][1]["attemptHistory"]), 1)
            self.assertEqual(state["tasks"][1]["attempt"], 2)
            self.assertEqual(artifact_hashes(root), old)
            for task in state["tasks"]:
                report = validate_task_plan_compatibility_receipt(
                    task["planCompatibilityReceipt"], state=state, task=task
                )
                self.assertEqual(report["status"], "PASS", report)
            self.assertEqual(history[0], before["priorSnapshots"][0])
            for field in ("runStartedAt", "runDeadlineAt"):
                self.assertEqual(before[field], state[field])
            objects = list((root / state["storage"]["root"]).rglob("*.json"))
            observe(
                {
                    "kind": "native-ten-revision-chain",
                    "fixtureOnly": True,
                    "planRevisions": 10,
                    "taskCount": 3,
                    "reworkAttempts": 1,
                    "logicalHistoryBytes": logical,
                    "rootBytes": path.stat().st_size,
                    "storageObjects": len(objects),
                    "maxObjectBytes": max(p.stat().st_size for p in objects),
                    "status": "PASS",
                }
            )

    def test_combined_component_scale_measurement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tracemalloc.start()
            started = time.monotonic()
            prepared = prepare_storage(scale_fixture(), storage_root="work/storage")
            persist_storage(root, prepared)
            report = validate_storage(root, prepared.state)
            history = list(iter_historical_snapshots(root, prepared.state))
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            size = len(canonical_bytes(prepared.state)) + 1
            self.assertLessEqual(size, 768 * 1024)
            self.assertEqual(len(history), 128)
            self.assertEqual(report.object_count, 129)
            observe(
                {
                    "kind": "component-combined-scale",
                    "nativeWorkflow": False,
                    "tasks": 32,
                    "snapshots": 128,
                    "operations": 2048,
                    "rootBytes": size,
                    "objectReads": report.object_reads,
                    "reachableBytes": report.reachable_bytes,
                    "objects": report.object_count,
                    "elapsedSeconds": time.monotonic() - started,
                    "peakTracemallocBytes": peak,
                    "status": "PASS",
                }
            )

    def test_actual_64_mib_reachable_boundary_and_single_object_limit(self):
        """Actual byte ceilings, without substituting smaller patched constants."""
        state = scale_fixture()
        state["priorSnapshots"] = state["priorSnapshots"][:64]
        state["tasks"] = []
        state["operationLedger"] = {}
        for snapshot in state["priorSnapshots"]:
            snapshot["tasks"] = []
            snapshot["fixtureOnlyPadding"] = ""
            snapshot["fixtureOnlyPadding"] = "x" * (1_048_576 - len(canonical_bytes(snapshot)) - 1)
        with tempfile.TemporaryDirectory() as tmp:
            prepared = prepare_storage(state, storage_root="work/storage")
            report = validate_storage(Path(tmp), prepared.state, prepared=prepared)
            self.assertEqual(report.reachable_bytes, 64 * 1024 * 1024)
            self.assertEqual(report.object_count, 64)
            self.assertEqual(max(map(len, prepared.objects.values())), 1_048_576)
            state["priorSnapshots"].append(deepcopy(state["priorSnapshots"][0]))
            state["priorSnapshots"][-1].update(planRevision=999, planDigest="f" * 64)
            state["priorSnapshots"][-1]["fixtureOnlyPadding"] = ""
            with self.assertRaises(LifecycleError) as caught:
                prepare_storage(state, storage_root="work/storage")
            self.assertEqual(caught.exception.code, "workflow-storage-capacity-exceeded")
            observe(
                {
                    "kind": "component-real-byte-boundary",
                    "nativeWorkflow": False,
                    "reachableBytes": report.reachable_bytes,
                    "objectBytes": 1_048_576,
                    "oneMoreRefused": caught.exception.details,
                    "status": "PASS",
                }
            )


def invoke(root, path, source, command, *args):
    state = json.loads(path.read_bytes())
    native(
        root,
        command,
        "--state",
        path,
        "--source-revision",
        source,
        "--expected-revision",
        state["stateRevision"],
        "--operation-id",
        f"fixture-only-{command}-{state['stateRevision']}",
        *args,
    )


def complete_fixture_task(root, path, source, task_id, *, rework=False):
    """Use ordinary start/result/audit/review routes, never edit runtime history."""
    from agent_lifecycle.audit import build_implementation_audit_report
    from agent_lifecycle.changesets import capture_task_change_set

    for attempt in range(1, 3 if rework else 2):
        invoke(root, path, source, "task-start", "--task", task_id, "--reason", "fixture only")
        state = json.loads(path.read_bytes())
        task = next(task for task in state["tasks"] if task["id"] == task_id)
        evidence = capture_task_change_set(root, baseline=source, write_paths=task["writes"])
        result = deepcopy(json.loads((root / "work/WS-01/attempt-1/task-result.json").read_bytes()))
        result.update(
            taskId=task_id,
            attempt=attempt,
            planDigest=state["planDigest"],
            changedFiles=evidence["changedFiles"],
            summary="Synthetic fixture-only result",
        )
        result["changeSet"] = {
            "schemaVersion": "agent-task-change-set-claim.v1",
            **{key: evidence[key] for key in ("provider", "baselineSha", "fileSetHash", "diffHash", "snapshotHash")},
        }
        result["itemOutcomes"][0]["changedFiles"] = evidence["changedFiles"]
        result_path = f"work/{task_id}/attempt-{attempt}/task-result.json"
        target = root / result_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(canonical_bytes(result) + b"\n")
        invoke(
            root, path, source, "task-result", "--task", task_id, "--result", result_path, "--reason", "fixture only"
        )
        review = deepcopy(json.loads((root / "work/WS-01/attempt-1/task-review.json").read_bytes()))
        review.update(
            taskId=task_id,
            attempt=attempt,
            planDigest=state["planDigest"],
            resultHash=canonical_digest(result),
            reviewId=f"fixture-{task_id}-{attempt}",
            summary="Synthetic fixture-only review",
        )
        wants_rework = rework and attempt == 1
        if wants_rework:
            review["verdict"] = review["itemReviews"][0]["verdict"] = "REWORK"
            review["findings"] = [
                {
                    "id": "FIXTURE-REWORK",
                    "severity": "HIGH",
                    "status": "open",
                    "message": "Synthetic fixture-only remediation",
                }
            ]
            review["itemReviews"][0]["findingIds"] = ["FIXTURE-REWORK"]
        elif task.get("remediationFindingIds"):
            review["findings"] = [
                {
                    "id": finding,
                    "severity": "HIGH",
                    "status": "closed",
                    "message": "Synthetic fixture-only finding resolved",
                }
                for finding in task["remediationFindingIds"]
            ]
        review_path = f"work/{task_id}/attempt-{attempt}/task-review.json"
        (root / review_path).write_bytes(canonical_bytes(review) + b"\n")
        audit = build_implementation_audit_report(
            manifest_path=root / state["manifestPath"],
            state_path=path,
            task_id=task_id,
            result_path=result_path,
            review_path=review_path,
            auditor_id="fixture-only-auditor",
        )
        audit_path = f"work/{task_id}/attempt-{attempt}/implementation-audit.json"
        (root / audit_path).write_bytes(canonical_bytes(audit) + b"\n")
        finding_ids = {"FIXTURE-REWORK"} | {
            finding["id"] for finding in audit["findings"] if finding.get("status") == "open"
        }
        extra = (
            tuple(value for finding in sorted(finding_ids) for value in ("--finding-id", finding))
            if wants_rework
            else ()
        )
        invoke(
            root,
            path,
            source,
            "task-review-apply",
            "--task",
            task_id,
            "--review",
            review_path,
            "--implementation-audit",
            audit_path,
            "--reason",
            "fixture only",
            *extra,
        )


if __name__ == "__main__":
    unittest.main()

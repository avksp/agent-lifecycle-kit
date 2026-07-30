from __future__ import annotations

import json
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest, write_json_create

def _write_plan_bundle(
    root: Path,
    *,
    include_dependent: bool = False,
    include_model_route: bool = False,
    include_completion_check: bool = False,
    include_plan_review_report: bool = True,
) -> None:
    plan_root = root / "plans/package/.agent-plan/package"
    packet_root = root / "plans/package/workflow/task-packets"
    review_path = plan_root / "reviews/plan-review-r01.json"
    if include_plan_review_report:
        review = {
            "reviewId": "plan-review-r01",
            "reviewer": {"id": "reviewer", "runId": "review-run", "surface": "test"},
            "verdict": "READY_TO_FREEZE",
        }
        write_json_create(review_path, review)
    else:
        (root / "plans/package").mkdir(parents=True, exist_ok=True)
        (root / "plans/package/07-plan-review-request.md").write_text("READY_TO_FREEZE\n", encoding="utf-8")
    manifest = _plan_manifest(
        include_dependent=include_dependent,
        include_model_route=include_model_route,
        include_completion_check=include_completion_check,
        include_plan_review_report=include_plan_review_report,
    )
    digest = canonical_digest(manifest)
    lock = {"schemaVersion": "agent-plan-lock.v1", "planRevision": 2, "manifestHash": digest}
    if not include_plan_review_report:
        lock.update({
            "reviewId": "plan-review-r02",
            "reviewPath": "plans/package/07-plan-review-request.md",
            "reviewedPlanHash": digest,
            "frozenBy": "test-freezer",
        })
    write_json_create(plan_root / "plan.lock.json", lock)
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


def _plan_manifest(
    *,
    include_dependent: bool = False,
    include_model_route: bool = False,
    include_completion_check: bool = False,
    include_plan_review_report: bool = True,
) -> dict:
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
                "result": "work/WS-01/attempt-{attempt}/task-result.json",
                "review": "work/WS-01/attempt-{attempt}/task-review.json",
            },
            "required": True,
        }
    ]
    if include_model_route:
        workstreams[0]["modelRoute"] = {
            "schemaVersion": "agent-lifecycle-model-route-decision.v1",
            "operationId": "route-WS-01",
            "modelClass": "standard-code",
            "decisionDigest": "4" * 64,
        }
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
                "result": "work/WS-02/attempt-{attempt}/task-result.json",
                "review": "work/WS-02/attempt-{attempt}/task-review.json",
            },
            "required": True,
        })
    manifest = {
        "schemaVersion": "3.0",
        "status": "FROZEN",
        "planRevision": 2,
        "package": {
            "id": "package",
            "artifactRoot": "plans/package",
            "planArtifactRoot": "plans/package/.agent-plan/package",
        },
        "planReview": _plan_review_block(include_report=include_plan_review_report),
        "orchestration": {
            "maxParallelTasks": 1,
            "maxTaskAttempts": 1,
            "maxTaskWallSeconds": 3600,
            "maxRunWallSeconds": 86400,
        },
        "workstreams": workstreams,
    }
    if include_completion_check:
        manifest["specification"] = {
            "completionCheck": {
                "schemaVersion": "agent-completion-check.v1",
                "checkId": "done-check",
                "kind": "verification",
                "description": "Observable completion evidence for the requested outcome.",
                "receiptPath": "final/completion-check-receipt.json",
                "requiredEvidenceIds": ["EV-FINAL"],
            }
        }
    return manifest


def _plan_review_block(*, include_report: bool) -> dict:
    if include_report:
        return {
            "required": True,
            "verdict": "READY_TO_FREEZE",
            "reviewedRevision": 2,
            "report": "plans/package/.agent-plan/package/reviews/plan-review-r01.json",
        }
    return {
        "request": "plans/package/07-plan-review-request.md",
        "requiredVerdict": "READY_TO_FREEZE",
    }


__all__ = [name for name in globals() if name.startswith("_") and not name.startswith("__")]

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError  # noqa: E402
from agent_lifecycle.contracts import canonical_digest, write_json_create  # noqa: E402
from agent_lifecycle.workflow import (  # noqa: E402
    accept_task,
    adopt_plan,
    apply_budget_decision,
    block_run,
    check_lineage,
    commit_task_result,
    finalize_run,
    pause_for_budget_decision,
    resolve_blocker,
    select_auto_budget_action,
    start_execution,
    start_task,
    status,
    validate_budget_exceeded_policy,
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


def _set_task_model_route(state_path: Path, route: dict) -> None:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["tasks"][0]["modelRoute"] = route
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


try:
    from .plan_helpers import _plan_manifest, _plan_review_block, _write_plan_bundle
except ImportError:
    from plan_helpers import _plan_manifest, _plan_review_block, _write_plan_bundle

def _model_route() -> dict:
    return {
        "schemaVersion": "agent-lifecycle-model-route-decision.v1",
        "operationId": "route-WS-01",
        "phase": "task-implementation",
        "sddTier": "S1",
        "routingPolicy": "balanced",
        "modelClass": "standard-code",
        "allowedFallbackModelClasses": ["strong-reasoning"],
        "targetContextWindow": "8k",
        "criticalReview": False,
        "requiresUsageReceipt": True,
        "maxBillableTokens": 120000,
        "reasonCodes": ["tier-s1"],
        "requestDigest": "6" * 64,
        "profileDigest": "7" * 64,
        "decisionDigest": "4" * 64,
    }


def _model_usage_receipt(route: dict) -> dict:
    return {
        "schemaVersion": "agent-lifecycle-model-usage-receipt.v1",
        "operationId": route["operationId"],
        "runId": "run",
        "packageId": "package",
        "taskId": "WS-01",
        "attempt": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "host": "codex",
        "modelClass": route["modelClass"],
        "providerModelHash": "redacted-provider-model",
        "routeDecisionDigest": route["decisionDigest"],
        "usage": {
            "inputTokens": 100,
            "outputTokens": 20,
            "billableTokens": 120,
            "cumulativeContextBytes": 4096,
            "toolCalls": 1,
            "wallSeconds": 2,
        },
        "attestation": {
            "source": "host",
            "status": "ATTESTED",
        },
    }


def _budget_policy(*, mode: str) -> dict:
    policy = {
        "schemaVersion": "agent-lifecycle-budget-exceeded-policy.v1",
        "mode": mode,
        "allowedActions": ["reroute-cheaper", "reroute-stronger", "split-task", "abort"],
        "forbidDowngradeForCriticalReview": True,
        "maxAutoReroutesPerTask": 1,
        "budgetModes": {
            "metered": {
                "budgetCapUsd": 5.0,
            },
            "subscription": {
                "maxInvocations": 33,
                "maxBillableTokens": 1200000,
                "maxWallSeconds": 1800.0,
            },
            "local": {
                "maxInvocations": 33,
                "maxBillableTokens": 1200000,
                "maxWallSeconds": 1800.0,
            },
        },
    }
    if mode == "auto":
        policy["defaultAutoAction"] = "reroute-cheaper"
    return policy


def _pause_budget_overrun(
    root: Path,
    state_path: Path,
    *,
    route: dict | None = None,
    policy: dict | None = None,
) -> None:
    route = route or _model_route()
    _set_task_model_route(state_path, route)
    start_task(
        state_path,
        task_id="WS-01",
        operation_id="start-op",
        expected_revision=1,
        source_revision="source",
        reason="launch",
    )
    usage_path = "tasks/WS-01/attempt-1/model-usage-receipt.json"
    receipt = _model_usage_receipt(route)
    receipt["usage"]["billableTokens"] = route["maxBillableTokens"] + 1
    write_json_create(root / usage_path, receipt)
    policy_path = "budget-policy.json"
    write_json_create(root / policy_path, policy or _budget_policy(mode="manual"))
    pause_for_budget_decision(
        state_path,
        task_id="WS-01",
        operation_id="budget-op",
        expected_revision=2,
        source_revision="source",
        usage_receipt_path=usage_path,
        budget_policy_path=policy_path,
        decision_receipt_path="tasks/WS-01/attempt-1/budget-decision.json",
        reason="budget overrun",
    )


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


__all__ = [
    "LifecycleError",
    "accept_task",
    "adopt_plan",
    "apply_budget_decision",
    "block_run",
    "canonical_digest",
    "check_lineage",
    "commit_task_result",
    "finalize_run",
    "pause_for_budget_decision",
    "resolve_blocker",
    "select_auto_budget_action",
    "start_execution",
    "start_task",
    "status",
    "validate_budget_exceeded_policy",
    "write_json_create",
    *[name for name in globals() if name.startswith("_") and not name.startswith("__")],
]

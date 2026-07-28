from __future__ import annotations

import contextlib
import json
import os
import sys
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle import __version__  # noqa: E402
from agent_lifecycle.cli import main  # noqa: E402
from agent_lifecycle.contracts import canonical_digest, write_json_create  # noqa: E402

def _run_cli(args: list[str]) -> tuple[int, dict]:
    stdout = StringIO()
    with contextlib.redirect_stdout(stdout):
        code = main(args)
    data = stdout.getvalue()
    return code, json.loads(data)


def _write_state(root: Path) -> Path:
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
                "phase": "RUNNING",
                "authorization": {"required": False, "granted": True},
                "tasks": [
                    {
                        "id": "WS-01",
                        "status": "READY",
                        "attempt": 0,
                        "dependsOn": [],
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
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_context_inputs(root: Path, *, oversized: bool) -> tuple[Path, Path]:
    packet_path = root / "task-packet.json"
    summary_path = root / "summary.json"
    packet = {
        "schemaVersion": "agent-task-packet.v1",
        "plan": {"packageId": "package", "planRevision": 1, "planDigest": "0" * 64},
        "task": {
            "id": "WS-01",
            "title": "Add compact context support",
            "owner": "worker",
            "reviewer": "reviewer",
            "dependsOn": [],
            "required": True,
            "plannedItems": _context_planned_items(oversized=oversized),
            "acceptanceIds": ["AC-CONTEXT"],
            "evidenceIds": ["EV-CONTEXT"],
            "artifactPaths": {},
            "capabilityHints": [],
            "requiredTools": [],
            "executionPolicy": {},
        },
        "ownership": {
            "writes": ["src/agent_lifecycle/context"],
            "readOnly": ["profiles/small-context-profile.v1.json"],
            "forbiddenWrites": [],
            "leadOwned": [],
        },
        "specification": {
            "tier": "S1",
            "revision": 1,
            "requirements": ["REQ-CONTEXT"],
            "traceDigest": "1" * 64,
        },
        "context": {"refs": ["profiles/small-context-profile.v1.json"]},
        "validation": {"acceptanceIds": ["AC-CONTEXT"], "evidenceIds": ["EV-CONTEXT"]},
        "acceptance": [{"id": "AC-CONTEXT", "statement": "context receipt passes"}],
    }
    summary = {
        "latestUserIntent": "Add compact context mode for small local models.",
        "activeDecisions": ["Use deterministic renderer and fail closed on overflow."],
        "openBlockers": [],
        "acceptedEvidence": [{"id": "EV-CONTEXT", "status": "pending"}],
        "changedFiles": ["src/agent_lifecycle/context/rendering.py"],
        "nextRequiredAction": "render compact envelope",
        "doNotDo": ["Do not load the full plan package into a small context."],
    }
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    return packet_path, summary_path


def _context_planned_items(*, oversized: bool) -> list[str]:
    if oversized:
        return ["REQ-" + ("x" * 200)] * 300
    return ["REQ-CONTEXT"]


def _write_task_compile_bundle(root: Path) -> Path:
    manifest = {
        "status": "FROZEN",
        "planRevision": 1,
        "package": {
            "id": "p",
            "artifactRoot": "plans/p",
            "planArtifactRoot": "plans/p/.agent-plan/p",
        },
        "specification": {"tier": "S1", "revision": 1, "artifact": "spec.json"},
        "readOnly": [],
        "forbiddenWrites": [],
        "leadOwned": [],
        "workstreams": [
            {
                "id": "WS-01",
                "title": "Compile",
                "owner": "worker",
                "reviewer": "reviewer",
                "dependsOn": [],
                "writes": ["src"],
                "plannedItems": [{"id": "REQ-1", "description": "Do it"}],
                "acceptanceIds": ["AC-1"],
                "evidenceIds": ["EV-1"],
                "artifactPaths": {
                    "result": "tasks/WS-01/attempt-{attempt}/task-result.json",
                    "review": "tasks/WS-01/attempt-{attempt}/task-review.json",
                },
            }
        ],
        "acceptanceCriteria": [{"id": "AC-1", "evidenceIds": ["EV-1"]}],
    }
    lock = {
        "schemaVersion": "agent-plan-lock.v1",
        "manifestHash": canonical_digest(manifest),
        "planRevision": 1,
    }
    lock_path = root / "plans/p/.agent-plan/p/plan.lock.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    manifest_path = root / "plans/p/plan.manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _task(payload: dict) -> dict:
    return next(item for item in payload["tasks"] if item["id"] == "WS-01")


def _result() -> dict:
    return {
        "schemaVersion": "agent-task-result.v2",
        "runId": "run",
        "taskId": "WS-01",
        "attempt": 1,
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


def _budget_policy() -> dict:
    return {
        "schemaVersion": "agent-lifecycle-budget-exceeded-policy.v1",
        "mode": "manual",
        "allowedActions": ["reroute-cheaper", "reroute-stronger", "split-task", "abort"],
        "forbidDowngradeForCriticalReview": True,
        "maxAutoReroutesPerTask": 1,
        "budgetModes": {
            "metered": {"budgetCapUsd": 5.0},
            "subscription": {"maxInvocations": 33, "maxBillableTokens": 1200000, "maxWallSeconds": 1800.0},
            "local": {"maxInvocations": 33, "maxBillableTokens": 1200000, "maxWallSeconds": 1800.0},
        },
    }


def _review(result_hash: str) -> dict:
    return {
        "schemaVersion": "agent-task-review.v2",
        "reviewId": "review-1",
        "runId": "run",
        "taskId": "WS-01",
        "attempt": 1,
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


def _manifest() -> dict:
    return {
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "package", "planArtifactRoot": "plans/package"},
        "leadOwned": [],
        "readOnly": [],
        "forbiddenWrites": [],
        "workstreams": [{"id": "WS-01", "writes": ["src"]}],
    }


__all__ = [
    "__version__",
    "ROOT",
    "canonical_digest",
    "os",
    "write_json_create",
    *[name for name in globals() if name.startswith("_") and not name.startswith("__")],
]

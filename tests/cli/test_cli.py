from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle import __version__  # noqa: E402
from agent_lifecycle.cli import main  # noqa: E402
from agent_lifecycle.contracts import canonical_digest, write_json_create  # noqa: E402


class CliTests(unittest.TestCase):
    def test_version_outputs_compact_json(self) -> None:
        code, payload = _run_cli(["version"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-version.v1")
        self.assertEqual(payload["version"], __version__)

    def test_schema_list_outputs_index(self) -> None:
        code, payload = _run_cli(["schema", "list"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-schema-index.v1")
        self.assertTrue(payload["schemas"])

    def test_schema_show_outputs_schema(self) -> None:
        code, payload = _run_cli(["schema", "show", "agent-host-operation-request.v1"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["$id"], "agent-host-operation-request.v1")

    def test_reserved_group_fails_with_stable_error(self) -> None:
        code, payload = _run_cli(["adapter"])
        self.assertEqual(code, 2)
        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-error.v1")
        self.assertEqual(payload["code"], "command-not-implemented")

    def test_workflow_status_outputs_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = _write_state(Path(tmp))
            code, payload = _run_cli(["workflow", "status", "--state", str(state_path)])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-workflow-status.v1")
            self.assertEqual(payload["nextAction"]["type"], "launch-tasks")

    def test_audit_ownership_outputs_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "plan.manifest.json"
            manifest.write_text(json.dumps(_manifest()), encoding="utf-8")
            code, payload = _run_cli(
                [
                    "audit",
                    "ownership",
                    "--manifest",
                    str(manifest),
                    "--path",
                    "src/core.py",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-ownership-report.v1")
            self.assertEqual(payload["entries"][0]["owners"], ["WS-01"])

    def test_workflow_task_lifecycle_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root)
            code, payload = _run_cli(
                [
                    "workflow",
                    "task-start",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "start-op",
                    "--expected-revision",
                    "1",
                    "--source-revision",
                    "source",
                    "--reason",
                    "launch",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(_task(payload)["status"], "RUNNING")

            result_path = "tasks/WS-01/attempt-1/task-result.json"
            result = _result()
            write_json_create(root / result_path, result)
            code, payload = _run_cli(
                [
                    "workflow",
                    "task-result",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "result-op",
                    "--expected-revision",
                    "2",
                    "--source-revision",
                    "source",
                    "--result",
                    result_path,
                    "--reason",
                    "done",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(_task(payload)["status"], "VERIFYING")

            review_path = "tasks/WS-01/attempt-1/task-review.json"
            write_json_create(root / review_path, _review(canonical_digest(result)))
            code, payload = _run_cli(
                [
                    "workflow",
                    "task-accept",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "accept-op",
                    "--expected-revision",
                    "3",
                    "--review",
                    review_path,
                    "--reason",
                    "accepted",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(_task(payload)["status"], "ACCEPTED")

    def test_workflow_task_result_cli_accepts_model_usage_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root)
            route = _model_route()
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["modelRoute"] = route
            state_path.write_text(json.dumps(state), encoding="utf-8")
            code, _payload = _run_cli(
                [
                    "workflow",
                    "task-start",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "start-op",
                    "--expected-revision",
                    "1",
                    "--source-revision",
                    "source",
                    "--reason",
                    "launch",
                ]
            )
            self.assertEqual(code, 0)
            result_path = "tasks/WS-01/attempt-1/task-result.json"
            usage_path = "tasks/WS-01/attempt-1/model-usage-receipt.json"
            write_json_create(root / result_path, _result())
            write_json_create(root / usage_path, _model_usage_receipt(route))

            code, payload = _run_cli(
                [
                    "workflow",
                    "task-result",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "result-op",
                    "--expected-revision",
                    "2",
                    "--source-revision",
                    "source",
                    "--result",
                    result_path,
                    "--model-usage-receipt",
                    usage_path,
                    "--reason",
                    "done",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(_task(payload)["status"], "VERIFYING")

    def test_context_profile_check_cli(self) -> None:
        code, payload = _run_cli([
            "context",
            "profile-check",
            "--profile",
            str(ROOT / "profiles/small-context-profile.v1.json"),
        ])
        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-small-context-profile-validation.v1")
        self.assertEqual(payload["defaultWindow"], "8k")
        self.assertIn("4k-strict", payload["windows"])

    def test_context_check_overflow_returns_non_zero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet, summary = _write_context_inputs(Path(tmp), oversized=True)
            code, payload = _run_cli([
                "context",
                "check",
                "--profile",
                str(ROOT / "profiles/small-context-profile.v1.json"),
                "--task-packet",
                str(packet),
                "--summary",
                str(summary),
                "--target-window",
                "4k-strict",
            ])
            self.assertEqual(code, 2)
            self.assertEqual(payload["schemaVersion"], "agent-lifecycle-error.v1")
            self.assertEqual(payload["code"], "context-overflow")
            self.assertEqual(payload["details"]["receipt"]["status"], "FAIL")

    def test_context_render_overflow_returns_non_zero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet, summary = _write_context_inputs(Path(tmp), oversized=True)
            code, payload = _run_cli([
                "context",
                "render",
                "--profile",
                str(ROOT / "profiles/small-context-profile.v1.json"),
                "--task-packet",
                str(packet),
                "--summary",
                str(summary),
                "--target-window",
                "4k-strict",
            ])
            self.assertEqual(code, 2)
            self.assertEqual(payload["schemaVersion"], "agent-lifecycle-error.v1")
            self.assertEqual(payload["code"], "context-overflow")
            self.assertEqual(payload["details"]["receipt"]["status"], "FAIL")

    def test_model_profile_check_cli_validates_routing_profile(self) -> None:
        code, payload = _run_cli([
            "model",
            "profile-check",
            "--profile",
            str(ROOT / "profiles/model-routing-profile.v1.json"),
        ])
        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-model-routing-profile-validation.v1")
        self.assertIn("strong-reasoning", payload["classes"])

    def test_model_route_cli_outputs_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp) / "request.json"
            request.write_text(
                json.dumps({
                    "schemaVersion": "agent-lifecycle-model-route-request.v1",
                    "operationId": "route-op",
                    "phase": "triage",
                    "sddTier": "S0",
                    "riskFlags": {},
                    "capabilityRequirements": ["text", "json"],
                    "targetContextWindow": "8k",
                    "routingPolicy": "balanced",
                    "budgetClass": "normal",
                    "userPolicy": {"localModelsAllowed": False, "cloudModelsAllowed": True},
                }),
                encoding="utf-8",
            )
            code, payload = _run_cli([
                "model",
                "route",
                "--profile",
                str(ROOT / "profiles/model-routing-profile.v1.json"),
                "--request",
                str(request),
            ])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-lifecycle-model-route-decision.v1")
            self.assertEqual(payload["modelClass"], "budget")

    def test_model_usage_check_cli_fails_unattested_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decision = {
                "schemaVersion": "agent-lifecycle-model-route-decision.v1",
                "operationId": "route-op",
                "phase": "task-implementation",
                "sddTier": "S1",
                "routingPolicy": "balanced",
                "modelClass": "standard-code",
                "allowedFallbackModelClasses": ["strong-reasoning"],
                "targetContextWindow": "8k",
                "requiresUsageReceipt": True,
                "maxBillableTokens": 120000,
                "reasonCodes": ["tier-s1"],
                "profileDigest": "a" * 64,
                "decisionDigest": "b" * 64,
            }
            receipt = {
                "schemaVersion": "agent-lifecycle-model-usage-receipt.v1",
                "operationId": "route-op",
                "host": "codex",
                "modelClass": "standard-code",
                "providerModelHash": "redacted",
                "routeDecisionDigest": "b" * 64,
                "usage": {
                    "inputTokens": 1,
                    "outputTokens": 1,
                    "billableTokens": 2,
                    "cumulativeContextBytes": 10,
                    "toolCalls": 0,
                    "wallSeconds": 1,
                },
                "attestation": {"source": "host", "status": "MISSING"},
            }
            decision_path = root / "decision.json"
            receipt_path = root / "receipt.json"
            decision_path.write_text(json.dumps(decision), encoding="utf-8")
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            code, payload = _run_cli([
                "model",
                "usage-check",
                "--receipt",
                str(receipt_path),
                "--route-decision",
                str(decision_path),
            ])
            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "model-usage-validation-failed")

    def test_tier_resolve_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tier-request.json"
            path.write_text(
                json.dumps({
                    "schemaVersion": "agent-sdd-tier-resolution-request.v1",
                    "taskCount": 1,
                    "executableOwners": ["worker"],
                    "capabilityHints": ["bounded-mechanical"],
                    "riskFlags": {},
                    "requirementsBytes": 1200,
                    "externalSpecification": False,
                }),
                encoding="utf-8",
            )
            code, payload = _run_cli(["tier", "resolve", "--request", str(path)])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-sdd-tier-resolution.v1")
            self.assertEqual(payload["tier"], "S0")

    def test_specification_check_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "specification.json"
            path.write_text(
                json.dumps({
                    "tier": "S1",
                    "status": "FROZEN",
                    "requirements": [{"id": "REQ-1", "required": True}],
                }),
                encoding="utf-8",
            )
            code, payload = _run_cli(["specification", "check", "--specification", str(path)])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-specification-validation.v1")
            self.assertEqual(payload["requirementCount"], 1)

    def test_plan_check_cli_validates_manifest_and_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "plan.manifest.json"
            manifest = _manifest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            lock_path = root / "plan.lock.json"
            lock_path.write_text(
                json.dumps({
                    "schemaVersion": "agent-plan-lock.v1",
                    "planRevision": manifest["planRevision"],
                    "manifestHash": canonical_digest(manifest),
                }),
                encoding="utf-8",
            )
            code, payload = _run_cli([
                "plan",
                "check",
                "--manifest",
                str(manifest_path),
                "--lock",
                str(lock_path),
            ])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-plan-check.v1")
            self.assertEqual(payload["manifest"]["schemaVersion"], "agent-plan-validation.v1")
            self.assertEqual(payload["lock"]["schemaVersion"], "agent-plan-lock-verification.v1")

    def test_task_compile_cli_writes_packets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = _write_task_compile_bundle(root)
            previous_cwd = Path.cwd()
            os.chdir(root)
            try:
                code, payload = _run_cli(["task", "compile", "--manifest", str(manifest_path), "--write"])
            finally:
                os.chdir(previous_cwd)
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-task-packet-compile-result.v1")
            self.assertEqual(payload["index"]["packetCount"], 1)
            packet_path = root / "plans/p/workflow/task-packets/WS-01.task-packet.json"
            self.assertTrue(packet_path.exists())


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


if __name__ == "__main__":
    unittest.main()

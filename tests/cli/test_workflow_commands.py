from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from itertools import combinations
from pathlib import Path
from unittest.mock import patch

try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402

from agent_lifecycle.audit.proof_integrity import (  # noqa: E402
    build_finding_identity,
    build_fix_impact_receipt,
    build_hash_chain_migration_policy,
    build_proof_integrity_receipt,
    build_receipt_hash_chain,
    build_root_cause_evidence,
)
from agent_lifecycle.compiler import validate_phase_packet  # noqa: E402


def _cli_risk_profile(*, operation_id: str) -> dict:
    route_body = {
        "schemaVersion": "agent-lifecycle-model-route-decision.v1",
        "operationId": operation_id,
        "phase": "task-implementation",
        "sddTier": "S2",
        "routingPolicy": "balanced",
        "modelClass": "strong-reasoning",
        "allowedFallbackModelClasses": [],
        "targetContextWindow": "8k",
        "capabilityRequirements": [],
        "criticalReview": False,
        "requiresUsageReceipt": True,
        "maxBillableTokens": 1000,
        "reasonCodes": ["tier-s2"],
        "requestDigest": "1" * 64,
        "profileDigest": "2" * 64,
        "host": "codex",
        "hostProfileDigest": "4" * 64,
    }
    route = {**route_body, "decisionDigest": canonical_digest(route_body)}
    floor_body = {
        "schemaVersion": "agent-lifecycle-quality-floor-decision.v1",
        "status": "PASS",
        "taskShape": "architecture",
        "sddTier": "S2",
        "riskFlags": ["architecture"],
        "requiredEvidence": [],
        "minMode": "strict",
        "qualityFloor": "strict",
        "reasonCodes": ["risk-floor-S2-strict"],
        "blockers": [],
        "baselineProfileDigest": "5" * 64,
        "productionPromotionClaimed": False,
    }
    body = {
        "schemaVersion": "agent-risk-execution-profile.v1",
        "status": "PASS",
        "requestedRisk": "auto",
        "planRiskTier": "S2",
        "resolvedRiskTier": "S2",
        "adapterId": "codex",
        "operationId": operation_id,
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "taskId": "WS-01",
        "sourceRevision": "source",
        "qualityFloorDecision": {**floor_body, "floorDigest": canonical_digest(floor_body)},
        "modelRoute": route,
        "resourceCaps": {"maxBillableTokens": 1000, "maxInvocations": 2, "maxWallSeconds": 120},
        "usageEvidence": {
            "required": True,
            "hostAttestationRequired": True,
            "requiredMetrics": ["billableTokens", "invocations", "wallSeconds"],
            "estimatesAccepted": False,
        },
        "policyDigest": "3" * 64,
        "hostProfileDigest": "4" * 64,
        "blockers": [],
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "profileDigest": canonical_digest(body)}


class CliWorkflowCommandTests(unittest.TestCase):
    def test_workflow_status_outputs_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = _write_state(Path(tmp))
            code, payload = _run_cli(["workflow", "status", "--state", str(state_path)])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-workflow-status.v1")
            self.assertEqual(payload["nextAction"]["type"], "launch-tasks")

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

            result_path = "work/WS-01/attempt-1/task-result.json"
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

            review_path = "work/WS-01/attempt-1/task-review.json"
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

    def test_workflow_task_rework_cli_runs_second_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["budgets"] = {
                "remediationMode": "ask",
                "maxTaskAttempts": 2,
                "maxParallelTasks": 1,
                "maxTaskWallSeconds": 3600,
            }
            state_path.write_text(json.dumps(state), encoding="utf-8")
            code, _ = _run_cli(
                [
                    "workflow",
                    "task-start",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "start-1",
                    "--expected-revision",
                    "1",
                    "--source-revision",
                    "source",
                    "--reason",
                    "first attempt",
                ]
            )
            self.assertEqual(code, 0)
            result_1 = _result()
            result_1_path = "work/WS-01/attempt-1/task-result.json"
            write_json_create(root / result_1_path, result_1)
            code, _ = _run_cli(
                [
                    "workflow",
                    "task-result",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "result-1",
                    "--expected-revision",
                    "2",
                    "--source-revision",
                    "source",
                    "--result",
                    result_1_path,
                    "--reason",
                    "result",
                ]
            )
            self.assertEqual(code, 0)
            review_1 = _review(canonical_digest(result_1))
            review_1["verdict"] = "REWORK"
            review_1["findings"] = [{"id": "F-CLI-1", "severity": "MEDIUM", "status": "open", "message": "rework"}]
            review_1_path = "work/WS-01/attempt-1/task-review.json"
            write_json_create(root / review_1_path, review_1)
            code, payload = _run_cli(
                [
                    "workflow",
                    "task-rework",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "rework-1",
                    "--expected-revision",
                    "3",
                    "--source-revision",
                    "source",
                    "--review",
                    review_1_path,
                    "--finding-id",
                    "F-CLI-1",
                    "--reason",
                    "review requested rework",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(_task(payload)["status"], "REWORK")
            code, payload = _run_cli(
                [
                    "workflow",
                    "task-start",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "start-2",
                    "--expected-revision",
                    "4",
                    "--source-revision",
                    "source",
                    "--reason",
                    "second attempt",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(_task(payload)["attempt"], 2)
            result_2 = _result()
            result_2["attempt"] = 2
            result_2_path = "work/WS-01/attempt-2/task-result.json"
            write_json_create(root / result_2_path, result_2)
            code, _ = _run_cli(
                [
                    "workflow",
                    "task-result",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "result-2",
                    "--expected-revision",
                    "5",
                    "--source-revision",
                    "source",
                    "--result",
                    result_2_path,
                    "--reason",
                    "fixed",
                ]
            )
            self.assertEqual(code, 0)
            review_2 = _review(canonical_digest(result_2))
            review_2["attempt"] = 2
            review_2_path = "work/WS-01/attempt-2/task-review.json"
            write_json_create(root / review_2_path, review_2)
            code, payload = _run_cli(
                [
                    "workflow",
                    "task-accept",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "accept-2",
                    "--expected-revision",
                    "6",
                    "--review",
                    review_2_path,
                    "--reason",
                    "accepted",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(_task(payload)["status"], "ACCEPTED")

    def test_workflow_task_snapshot_cli_returns_embeddable_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "ALK Tests"], cwd=root, check=True)
            (root / ".gitignore").write_text("run.state.json\nevents.jsonl\nwork/\n", encoding="utf-8")
            source = root / "src/example.py"
            source.parent.mkdir(parents=True)
            source.write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", ".gitignore", "src/example.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
            ).stdout.strip()
            state_path = _write_state(root)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["sourceRevision"] = revision
            state["tasks"][0]["writes"] = ["src"]
            state_path.write_text(json.dumps(state), encoding="utf-8")
            code, _ = _run_cli(
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
                    revision,
                    "--reason",
                    "launch",
                ]
            )
            self.assertEqual(code, 0)
            source.write_text("value = 2\n", encoding="utf-8")

            code, payload = _run_cli(["workflow", "task-snapshot", "--state", str(state_path), "--task", "WS-01"])

            self.assertEqual(code, 0)
            self.assertEqual(payload["changedFiles"], ["src/example.py"])
            self.assertEqual(payload["claim"]["schemaVersion"], "agent-task-change-set-claim.v1")
            self.assertFalse(payload["stateWritten"])

    def test_workflow_task_snapshot_emits_bounded_phase_packets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "ALK Tests"], cwd=root, check=True)
            (root / ".gitignore").write_text("run.state.json\nevents.jsonl\nwork/\n", encoding="utf-8")
            source = root / "src/example.py"
            source.parent.mkdir(parents=True)
            source.write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", ".gitignore", "src/example.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
            ).stdout.strip()
            manifest = _phase_packet_manifest(revision)
            manifest_path = root / "plan.manifest.json"
            lock_path = root / "plan.lock.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            lock_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-plan-lock.v1",
                        "manifestHash": canonical_digest(manifest),
                        "planRevision": 1,
                    }
                ),
                encoding="utf-8",
            )
            state_path = _write_state(root)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["planDigest"] = canonical_digest(manifest)
            state["sourceRevision"] = revision
            state["tasks"][0].update(
                {
                    "writes": ["src"],
                    "readOnly": ["docs"],
                    "forbiddenWrites": [".github/workflows"],
                    "reviewer": "independent-reviewer",
                }
            )
            state_path.write_text(json.dumps(state), encoding="utf-8")
            code, _started = _run_cli(
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
                    revision,
                    "--reason",
                    "launch",
                ]
            )
            self.assertEqual(code, 0)
            source.write_text("value = 2\n", encoding="utf-8")

            code, legacy = _run_cli(["workflow", "task-snapshot", "--state", str(state_path), "--task", "WS-01"])
            self.assertEqual(code, 0)
            implementation_path = root / "implementation-phase.json"
            code, packet_snapshot = _run_cli(
                _task_snapshot_packet_args(
                    state_path,
                    manifest_path,
                    lock_path,
                    purpose="IMPLEMENTATION",
                    out=implementation_path,
                )
            )
            self.assertEqual(code, 0)
            self.assertEqual(packet_snapshot, legacy)
            implementation = json.loads(implementation_path.read_text(encoding="utf-8"))
            validate_phase_packet(implementation)
            self.assertEqual(implementation["purpose"], "IMPLEMENTATION")
            self.assertFalse(implementation["implementationAuthorized"])

            optional = {
                "manifest": ["--manifest", str(manifest_path)],
                "lock": ["--lock", str(lock_path)],
                "purpose": ["--phase-packet-purpose", "IMPLEMENTATION"],
                "out": ["--phase-packet-out", str(root / "partial.json")],
            }
            for size in range(1, len(optional)):
                for selected in combinations(optional, size):
                    args = ["workflow", "task-snapshot", "--state", str(state_path), "--task", "WS-01"]
                    for key in selected:
                        args.extend(optional[key])
                    code, failure = _run_cli(args)
                    self.assertEqual(code, 2, selected)
                    self.assertEqual(failure["code"], "phase-packet-required-fact-missing", selected)

            stored_state = json.loads(state_path.read_text(encoding="utf-8"))
            task = stored_state["tasks"][0]
            task["status"] = "VERIFYING"
            task["result"] = {"path": "work/result.json", "sha256": "6" * 64, "bytes": 10}
            task["resultChangeSetEvidence"] = {
                key: legacy[key]
                for key in ("provider", "baselineSha", "fileSetHash", "diffHash", "snapshotHash", "changedFiles")
            }
            state_path.write_text(json.dumps(stored_state), encoding="utf-8")
            audit_path = root / "audit-phase.json"
            code, audit_snapshot = _run_cli(
                _task_snapshot_packet_args(
                    state_path,
                    manifest_path,
                    lock_path,
                    purpose="TASK_AUDIT",
                    out=audit_path,
                )
            )
            self.assertEqual(code, 0)
            self.assertEqual(audit_snapshot["snapshotHash"], legacy["snapshotHash"])
            audit_packet = json.loads(audit_path.read_text(encoding="utf-8"))
            validate_phase_packet(audit_packet)
            self.assertEqual(audit_packet["payload"]["resultDigest"], "6" * 64)

            stored_state = json.loads(state_path.read_text(encoding="utf-8"))
            task = stored_state["tasks"][0]
            task["status"] = "RUNNING"
            task["attempt"] = 2
            task["remediationFindingIds"] = ["F-WS211-03"]
            task["attemptHistory"] = [
                {
                    "result": {"sha256": "7" * 64},
                    "review": {"sha256": "8" * 64},
                }
            ]
            state_path.write_text(json.dumps(stored_state), encoding="utf-8")
            remediation_path = root / "remediation-phase.json"
            code, _remediation_snapshot = _run_cli(
                _task_snapshot_packet_args(
                    state_path,
                    manifest_path,
                    lock_path,
                    purpose="REMEDIATION",
                    out=remediation_path,
                )
            )
            self.assertEqual(code, 0)
            remediation = json.loads(remediation_path.read_text(encoding="utf-8"))
            validate_phase_packet(remediation)
            self.assertEqual(remediation["payload"]["openFindingIds"], ["F-WS211-03"])
            self.assertEqual(remediation["payload"]["remainingAttempts"], 2)

    def test_workflow_validation_select_is_read_only_and_legacy_conservative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = _phase_packet_manifest("source")
            manifest_path = root / "plan.manifest.json"
            lock_path = root / "plan.lock.json"
            snapshot_path = root / "snapshot.json"
            out_path = root / "selection.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            lock_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-plan-lock.v1",
                        "manifestHash": canonical_digest(manifest),
                        "planRevision": 1,
                    }
                ),
                encoding="utf-8",
            )
            snapshot_path.write_text(
                json.dumps({"taskId": "WS-01", "snapshotHash": "9" * 64, "changedFiles": ["src/example.py"]}),
                encoding="utf-8",
            )
            state_path = _write_state(root)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["planDigest"] = canonical_digest(manifest)
            state_path.write_text(json.dumps(state), encoding="utf-8")
            before = state_path.read_bytes()

            code, selection = _run_cli(
                [
                    "workflow",
                    "validation-select",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--manifest",
                    str(manifest_path),
                    "--lock",
                    str(lock_path),
                    "--snapshot",
                    str(snapshot_path),
                    "--out",
                    str(out_path),
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(selection["status"], "PASS")
            self.assertEqual(selection["level"], "RELEASE_FULL")
            self.assertEqual(selection["reasons"], ["LEGACY_PROFILE_ABSENT"])
            self.assertFalse(selection["commandsExecuted"])
            self.assertFalse(selection["stateWritten"])
            self.assertEqual(state_path.read_bytes(), before)
            self.assertEqual(json.loads(out_path.read_text(encoding="utf-8")), selection)

    @patch("agent_lifecycle.cli.dispatch_lifecycle.finalize_run")
    def test_workflow_finalize_cli_forwards_release_full_receipt(self, finalize_mock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = _write_state(Path(tmp))
            finalize_mock.return_value = {"schemaVersion": "agent-workflow-status.v1", "phase": "COMPLETE"}

            code, _payload = _run_cli(
                [
                    "workflow",
                    "finalize",
                    "--state",
                    str(state_path),
                    "--operation-id",
                    "finalize-op",
                    "--expected-revision",
                    "1",
                    "--source-revision",
                    "source",
                    "--final-audit",
                    "final/final-audit.json",
                    "--proof",
                    "final/proof.json",
                    "--release-full-receipt",
                    "final/release-full.json",
                    "--reason",
                    "done",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(finalize_mock.call_args.kwargs["release_full_receipt_path"], "final/release-full.json")

    def test_workflow_task_start_cli_consumes_risk_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root)
            profile_path = "work/WS-01/risk-profile.json"
            profile = _cli_risk_profile(operation_id="start-op")
            write_json_create(root / profile_path, profile)

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
                    "--risk-profile",
                    profile_path,
                    "--reason",
                    "risk-aware launch",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(_task(payload)["status"], "RUNNING")
            task = json.loads(state_path.read_text(encoding="utf-8"))["tasks"][0]
            self.assertEqual(task["riskExecutionProfile"]["profileDigest"], profile["profileDigest"])
            self.assertEqual(task["attemptRiskExecutionProfile"]["attempt"], 1)
            self.assertEqual(task["attemptModelRoute"]["decisionDigest"], profile["modelRoute"]["decisionDigest"])

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
            result_path = "work/WS-01/attempt-1/task-result.json"
            usage_path = "work/WS-01/attempt-1/model-usage-receipt.json"
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

    def test_workflow_finalize_cli_accepts_proof_integrity_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["phase"] = "FINAL_AUDIT"
            state["proofIntegrityRequired"] = True
            state["tasks"][0]["status"] = "ACCEPTED"
            state["tasks"][0]["attempt"] = 1
            state["tasks"][0]["review"] = {
                "path": "work/WS-01/attempt-1/task-review.json",
                "sha256": "3" * 64,
                "bytes": 10,
            }
            state_path.write_text(json.dumps(state), encoding="utf-8")
            finding, root_cause, fix_impact, integrity = _cli_proof_integrity_receipt()
            final_audit = _cli_final_audit()
            final_audit["proofIntegrityRequired"] = True
            final_audit["proofIntegrityEvidence"] = {
                "required": True,
                "requiredFindingIds": [finding["findingId"]],
                "requiredRootCauseDigests": [root_cause["rootCauseDigest"]],
                "requiredFixImpactDigests": [fix_impact["impactDigest"]],
                "requiredEvidenceIds": ["EV-ROOT", "EV-FIX"],
            }
            write_json_create(root / "final/final-audit.json", final_audit)
            write_json_create(root / "final/proof-integrity.json", integrity)

            code, payload = _run_cli(
                [
                    "workflow",
                    "finalize",
                    "--state",
                    str(state_path),
                    "--operation-id",
                    "finalize-op",
                    "--expected-revision",
                    "1",
                    "--source-revision",
                    "source",
                    "--final-audit",
                    "final/final-audit.json",
                    "--proof",
                    "final/proof.json",
                    "--proof-integrity",
                    "final/proof-integrity.json",
                    "--reason",
                    "done",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload["phase"], "COMPLETE")
            proof = json.loads((root / "final/proof.json").read_text(encoding="utf-8"))
            self.assertEqual(proof["proofIntegrity"]["validation"]["status"], "PASS")

    def test_workflow_budget_policy_check_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            policy_path = Path(tmp) / "budget-policy.json"
            policy_path.write_text(json.dumps(_budget_policy()), encoding="utf-8")

            code, payload = _run_cli(["workflow", "budget-policy-check", "--policy", str(policy_path)])

            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-lifecycle-budget-exceeded-policy-validation.v1")
            self.assertEqual(payload["status"], "PASS")

    def test_workflow_budget_decision_cli_pauses_overrun(self) -> None:
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
            usage_path = "work/WS-01/attempt-1/model-usage-receipt.json"
            receipt = _model_usage_receipt(route)
            receipt["usage"]["billableTokens"] = route["maxBillableTokens"] + 1
            write_json_create(root / usage_path, receipt)
            policy_path = "budget-policy.json"
            write_json_create(root / policy_path, _budget_policy())

            code, payload = _run_cli(
                [
                    "workflow",
                    "budget-decision",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "budget-op",
                    "--expected-revision",
                    "2",
                    "--source-revision",
                    "source",
                    "--model-usage-receipt",
                    usage_path,
                    "--budget-policy",
                    policy_path,
                    "--receipt",
                    "work/WS-01/attempt-1/budget-decision.json",
                    "--reason",
                    "operator decision required",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload["phase"], "WAITING_FOR_BUDGET_DECISION")
            self.assertEqual(payload["nextAction"]["type"], "record-budget-decision")
            self.assertTrue((root / "work/WS-01/attempt-1/budget-decision.json").is_file())

    def test_workflow_budget_decision_cli_applies_reroute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root)
            route = _model_route()
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["modelRoute"] = route
            state_path.write_text(json.dumps(state), encoding="utf-8")
            self.assertEqual(
                _run_cli(
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
                )[0],
                0,
            )
            usage_path = "work/WS-01/attempt-1/model-usage-receipt.json"
            receipt = _model_usage_receipt(route)
            receipt["usage"]["billableTokens"] = route["maxBillableTokens"] + 1
            write_json_create(root / usage_path, receipt)
            policy_path = "budget-policy.json"
            write_json_create(root / policy_path, _budget_policy())
            self.assertEqual(
                _run_cli(
                    [
                        "workflow",
                        "budget-decision",
                        "--state",
                        str(state_path),
                        "--task",
                        "WS-01",
                        "--operation-id",
                        "budget-op",
                        "--expected-revision",
                        "2",
                        "--source-revision",
                        "source",
                        "--model-usage-receipt",
                        usage_path,
                        "--budget-policy",
                        policy_path,
                        "--receipt",
                        "work/WS-01/attempt-1/budget-decision.json",
                        "--reason",
                        "operator decision required",
                    ]
                )[0],
                0,
            )
            reroute = _model_route()
            reroute["operationId"] = "route-WS-01-reroute"
            reroute["modelClass"] = "strong-reasoning"
            reroute["decisionDigest"] = "8" * 64
            route_path = "routes/WS-01-reroute.json"
            write_json_create(root / route_path, reroute)

            code, payload = _run_cli(
                [
                    "workflow",
                    "budget-decision",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "budget-apply-op",
                    "--expected-revision",
                    "3",
                    "--source-revision",
                    "source",
                    "--action",
                    "reroute-stronger",
                    "--decision-receipt",
                    "work/WS-01/attempt-1/budget-decision.json",
                    "--route-decision",
                    route_path,
                    "--receipt",
                    "work/WS-01/attempt-1/budget-decision-applied.json",
                    "--operator-identity-hash",
                    "operator-hash",
                    "--reason",
                    "operator selected stronger route",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload["phase"], "RUNNING")
            self.assertEqual(_task(payload)["status"], "READY")
            applied = json.loads(
                (root / "work/WS-01/attempt-1/budget-decision-applied.json").read_text(encoding="utf-8")
            )
            self.assertEqual(applied["selectedAction"], "reroute-stronger")
            self.assertEqual(applied["nextRouteDecisionDigest"], "8" * 64)


def _phase_packet_manifest(source_revision: str) -> dict:
    return {
        "status": "FROZEN",
        "planRevision": 1,
        "baseRevision": {"ref": source_revision, "sha": source_revision},
        "package": {"id": "package", "planArtifactRoot": "plans/package"},
        "readOnly": ["docs"],
        "forbiddenWrites": [".github/workflows"],
        "leadOwned": [],
        "orchestration": {"maxTaskAttempts": 3},
        "acceptance": {
            "criteria": [
                {
                    "id": "AC-WS-01",
                    "statement": "The task behavior is accepted.",
                    "evidenceIds": ["EV-WS-01"],
                }
            ]
        },
        "workstreams": [
            {
                "id": "WS-01",
                "dependsOn": [],
                "writes": ["src"],
                "readOnly": [],
                "forbiddenWrites": [],
                "acceptanceIds": ["AC-WS-01"],
                "evidenceIds": ["EV-WS-01"],
            }
        ],
    }


def _task_snapshot_packet_args(
    state_path: Path,
    manifest_path: Path,
    lock_path: Path,
    *,
    purpose: str,
    out: Path,
) -> list[str]:
    return [
        "workflow",
        "task-snapshot",
        "--state",
        str(state_path),
        "--task",
        "WS-01",
        "--manifest",
        str(manifest_path),
        "--lock",
        str(lock_path),
        "--phase-packet-purpose",
        purpose,
        "--phase-packet-out",
        str(out),
    ]


def _cli_lineage() -> dict:
    return {
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
    }


def _cli_final_audit() -> dict:
    return {
        "schemaVersion": "agent-final-candidate-audit.v1",
        "status": "PASS",
        "semanticStatus": "READY_FOR_FINALIZATION",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "productionPromotionClaimed": False,
        "completionSignal": {
            "schemaVersion": "agent-completion-signal.v1",
            "runId": "run",
            "packageId": "package",
            "planRevision": 1,
            "planDigest": "0" * 64,
            "sourceRevision": "source",
            "status": "PASS",
            "evidenceIds": ["EV-FINAL"],
            "verifier": {"id": "final-auditor", "independent": True},
            "completedAt": "2026-07-31T08:00:00Z",
        },
        "notAcceptedTasks": [],
        "missingReleaseEvidence": [],
        "findings": [],
    }


def _cli_proof_integrity_receipt() -> tuple[dict, dict, dict, dict]:
    lineage = _cli_lineage()
    finding = build_finding_identity(
        {
            "category": "api-contract",
            "severity": "MEDIUM",
            "path": "src/service.py",
            "function": "load_user",
            "message": "Missing null handling",
        }
    )
    root_cause = build_root_cause_evidence(
        finding_id=finding["findingId"],
        root_cause={"class": "null-edge-case", "summary": "repository response can be absent"},
        evidence_ids=["EV-ROOT"],
        verifier={"id": "reviewer"},
    )
    fix_impact = build_fix_impact_receipt(
        lineage=lineage,
        changed_files=["src/service.py"],
        related_finding_ids=[finding["findingId"]],
        root_cause_digests=[root_cause["rootCauseDigest"]],
        behavior_changes=[{"contract": "missing profile returns None"}],
        preserved_behaviors=[{"contract": "existing profile response remains unchanged"}],
        validation_evidence_ids=["EV-FIX"],
        collateral_damage={"status": "PASS", "checks": ["tests/test_service.py"]},
        verifier={"id": "reviewer"},
    )
    chain = build_receipt_hash_chain(
        [
            {"path": "final/root-cause.json", "digest": canonical_digest(root_cause)},
            {"path": "final/fix-impact.json", "digest": canonical_digest(fix_impact)},
        ],
        chain_id="run-proof",
        lineage=lineage,
    )
    receipt = build_proof_integrity_receipt(
        lineage=lineage,
        findings=[finding],
        root_causes=[root_cause],
        fix_impact_receipts=[fix_impact],
        hash_chain=chain,
        migration_policy=build_hash_chain_migration_policy(),
        required_evidence_ids=["EV-ROOT", "EV-FIX"],
        verifier={"id": "final-auditor"},
    )
    return finding, root_cause, fix_impact, receipt


if __name__ == "__main__":
    unittest.main()

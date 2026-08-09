from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

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
            state["tasks"][0]["review"] = {"path": "work/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
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
            applied = json.loads((root / "work/WS-01/attempt-1/budget-decision-applied.json").read_text(encoding="utf-8"))
            self.assertEqual(applied["selectedAction"], "reroute-stronger")
            self.assertEqual(applied["nextRouteDecisionDigest"], "8" * 64)


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

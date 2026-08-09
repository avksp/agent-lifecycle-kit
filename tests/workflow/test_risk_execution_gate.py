from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

try:
    from .helpers import *  # noqa: F401,F403
except ImportError:
    from helpers import *  # type: ignore  # noqa: F401,F403


class RiskExecutionGateTests(unittest.TestCase):
    def test_task_start_persists_validated_profile_and_caps_attempt_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            profile = _risk_profile(operation_id="start-op")
            profile_path = "work/WS-01/risk-profile.json"
            write_json_create(root / profile_path, profile)

            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                risk_profile_path=profile_path,
                reason="risk-aware launch",
            )

            task = json.loads(state_path.read_text(encoding="utf-8"))["tasks"][0]
            self.assertEqual(task["modelRoute"]["decisionDigest"], profile["modelRoute"]["decisionDigest"])
            self.assertEqual(task["attemptModelRoute"]["attempt"], 1)
            self.assertEqual(task["attemptRiskExecutionProfile"]["resourceCaps"]["maxInvocations"], 2)
            started = datetime.fromisoformat(task["attemptStartedAt"].replace("Z", "+00:00"))
            deadline = datetime.fromisoformat(task["attemptDeadlineAt"].replace("Z", "+00:00"))
            self.assertEqual((deadline - started).total_seconds(), 120)

    def test_task_result_enforces_all_bound_caps(self) -> None:
        overages = {
            "billableTokens": (1001, "model-usage-validation-failed"),
            "invocations": (3, "risk-usage-cap-exceeded"),
            "wallSeconds": (121, "risk-usage-cap-exceeded"),
        }
        for metric, (value, expected_code) in overages.items():
            with self.subTest(metric=metric), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state_path, profile, result_path, usage_path = _started_risk_attempt(root)
                receipt = _model_usage_receipt(profile["modelRoute"])
                receipt["usage"]["invocations"] = 1
                receipt["usage"][metric] = value
                write_json_create(root / usage_path, receipt)

                with self.assertRaises(LifecycleError) as raised:
                    commit_task_result(
                        state_path,
                        task_id="WS-01",
                        operation_id="result-op",
                        expected_revision=2,
                        source_revision="source",
                        result_path=result_path,
                        model_usage_receipt_path=usage_path,
                        reason="done",
                    )

                self.assertEqual(raised.exception.code, expected_code)
                self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["tasks"][0]["status"], "RUNNING")

    def test_valid_attested_usage_records_risk_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, profile, result_path, usage_path = _started_risk_attempt(root)
            receipt = _model_usage_receipt(profile["modelRoute"])
            receipt["usage"]["invocations"] = 1
            write_json_create(root / usage_path, receipt)

            commit_task_result(
                state_path,
                task_id="WS-01",
                operation_id="result-op",
                expected_revision=2,
                source_revision="source",
                result_path=result_path,
                model_usage_receipt_path=usage_path,
                reason="done",
            )

            task = json.loads(state_path.read_text(encoding="utf-8"))["tasks"][0]
            self.assertEqual(task["modelUsageReceipt"]["riskValidation"]["status"], "PASS")

    def test_estimated_usage_is_rejected_on_risk_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, profile, result_path, usage_path = _started_risk_attempt(root)
            receipt = _model_usage_receipt(profile["modelRoute"])
            receipt["usage"]["invocations"] = 1
            receipt["attestation"] = {"source": "estimate", "status": "ESTIMATED"}
            write_json_create(root / usage_path, receipt)

            with self.assertRaises(LifecycleError) as raised:
                commit_task_result(
                    state_path,
                    task_id="WS-01",
                    operation_id="result-op",
                    expected_revision=2,
                    source_revision="source",
                    result_path=result_path,
                    model_usage_receipt_path=usage_path,
                    reason="done",
                )

            self.assertEqual(raised.exception.code, "model-usage-validation-failed")
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["tasks"][0]["status"], "RUNNING")

    def test_recomputed_profile_digest_cannot_disable_usage_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            profile = _risk_profile(operation_id="start-op")
            profile["usageEvidence"]["hostAttestationRequired"] = False
            profile["profileDigest"] = canonical_digest({key: value for key, value in profile.items() if key != "profileDigest"})
            profile_path = "work/WS-01/risk-profile.json"
            write_json_create(root / profile_path, profile)

            with self.assertRaises(LifecycleError) as raised:
                start_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="start-op",
                    expected_revision=1,
                    source_revision="source",
                    risk_profile_path=profile_path,
                    reason="risk-aware launch",
                )

            self.assertEqual(raised.exception.code, "risk-profile-usage-evidence-invalid")

    def test_retry_without_profile_drops_prior_risk_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING", max_attempts=2)
            profile = _risk_profile(operation_id="start-op")
            profile_path = "work/WS-01/risk-profile.json"
            write_json_create(root / profile_path, profile)
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                risk_profile_path=profile_path,
                reason="risk-aware launch",
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["status"] = "REWORK"
            state_path.write_text(json.dumps(state), encoding="utf-8")

            start_task(
                state_path,
                task_id="WS-01",
                operation_id="retry-op",
                expected_revision=2,
                source_revision="source",
                reason="legacy retry",
            )

            task = json.loads(state_path.read_text(encoding="utf-8"))["tasks"][0]
            for field in ("riskExecutionProfile", "attemptRiskExecutionProfile", "modelRoute", "attemptModelRoute"):
                self.assertNotIn(field, task)

    def test_profile_lineage_drift_is_rejected_before_state_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            profile = _risk_profile(operation_id="other-op")
            profile_path = "work/WS-01/risk-profile.json"
            write_json_create(root / profile_path, profile)

            with self.assertRaises(LifecycleError) as raised:
                start_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="start-op",
                    expected_revision=1,
                    source_revision="source",
                    risk_profile_path=profile_path,
                    reason="risk-aware launch",
                )

            self.assertEqual(raised.exception.code, "risk-profile-lineage-mismatch")
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["stateRevision"], 1)


def _risk_profile(*, operation_id: str) -> dict:
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


def _started_risk_attempt(root: Path) -> tuple[Path, dict, str, str]:
    state_path = _write_state(root, phase="RUNNING")
    profile = _risk_profile(operation_id="start-op")
    profile_path = "work/WS-01/risk-profile.json"
    write_json_create(root / profile_path, profile)
    start_task(
        state_path,
        task_id="WS-01",
        operation_id="start-op",
        expected_revision=1,
        source_revision="source",
        risk_profile_path=profile_path,
        reason="risk-aware launch",
    )
    result_path = "work/WS-01/attempt-1/task-result.json"
    usage_path = "work/WS-01/attempt-1/model-usage-receipt.json"
    write_json_create(root / result_path, _result(attempt=1))
    return state_path, profile, result_path, usage_path


if __name__ == "__main__":
    unittest.main()

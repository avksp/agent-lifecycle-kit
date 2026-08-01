from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import (  # noqa: E402
    LifecycleError,
    canonical_digest,
    is_under_repo_path,
    normalize_repo_path,
    read_json_object,
    write_json_create,
)
from agent_lifecycle.contracts.schemas import get_schema, list_schemas  # noqa: E402
from agent_lifecycle.host_protocol import HostAdapterEvent, HostOperationReceipt, HostOperationRequest  # noqa: E402


class ContractTests(unittest.TestCase):
    def test_canonical_digest_is_key_order_stable(self) -> None:
        self.assertEqual(canonical_digest({"b": 2, "a": 1}), canonical_digest({"a": 1, "b": 2}))

    def test_write_json_create_is_write_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.json"
            write_json_create(path, {"ok": True})
            self.assertEqual(read_json_object(path)["ok"], True)
            with self.assertRaises(FileExistsError):
                write_json_create(path, {"ok": False})

    def test_repo_path_rejects_absolute_and_traversal(self) -> None:
        self.assertEqual(normalize_repo_path("plans/run/state.json"), "plans/run/state.json")
        for bad in ["/tmp/x", "../x", "a/../x", "a\\b", "file://x"]:
            with self.assertRaises(LifecycleError):
                normalize_repo_path(bad)

    def test_repo_path_under_helper_matches_path_segment_boundaries(self) -> None:
        self.assertTrue(is_under_repo_path("plans/run/state.json", "plans"))
        self.assertTrue(is_under_repo_path("plans", "plans"))
        self.assertFalse(is_under_repo_path("plans-old/state.json", "plans"))

    def test_host_operation_request_is_closed(self) -> None:
        request = HostOperationRequest(
            operation_id="op-1",
            capability="run-tests",
            inputs={"target": "tests"},
            outputs=[],
            constraints={"network": "denied"},
        )
        self.assertEqual(HostOperationRequest.from_json(request.to_json()), request)
        invalid = request.to_json()
        invalid["provider"] = "opaque-host-name"
        with self.assertRaises(LifecycleError):
            HostOperationRequest.from_json(invalid)

    def test_host_operation_request_carries_attempt_model_route(self) -> None:
        request = HostOperationRequest(
            operation_id="op-1",
            capability="task-attempt",
            inputs={"taskId": "WS-01"},
            outputs=[{"role": "task-result", "path": "work/WS-01/attempt-1/task-result.json"}],
            constraints={"usageReceiptRequired": True},
            model_route={
                "schemaVersion": "agent-lifecycle-model-route-decision.v1",
                "operationId": "route-WS-01",
                "modelClass": "standard-code",
                "decisionDigest": "4" * 64,
            },
        )
        decoded = HostOperationRequest.from_json(request.to_json())
        self.assertEqual(decoded.model_route["modelClass"], "standard-code")

    def test_host_operation_receipt_status_is_bounded(self) -> None:
        receipt = HostOperationReceipt(
            operation_id="op-1",
            capability="run-tests",
            status="PASS",
            outputs=[],
            usage={"toolCalls": 1},
        )
        self.assertEqual(HostOperationReceipt.from_json(receipt.to_json()), receipt)
        invalid = receipt.to_json()
        invalid["status"] = "OK"
        with self.assertRaises(LifecycleError):
            HostOperationReceipt.from_json(invalid)

    def test_host_adapter_event_is_closed_and_typed(self) -> None:
        event = HostAdapterEvent(
            event_id="evt-1",
            host="claude-code",
            adapter_id="claude",
            run_id="run-1",
            task_id="WS-01",
            operation_id="op-1",
            sequence=1,
            event_type="session.started",
            status="INFO",
            recorded_at="2026-07-29T08:00:00Z",
            payload={"mode": "live"},
        )
        self.assertEqual(HostAdapterEvent.from_json(event.to_json()), event)
        invalid = event.to_json()
        invalid["providerSpecificShape"] = {}
        with self.assertRaises(LifecycleError):
            HostAdapterEvent.from_json(invalid)

    def test_schema_registry_is_stable_and_closed(self) -> None:
        index = list_schemas()
        ids = {item["id"] for item in index["schemas"]}
        self.assertIn("agent-host-operation-request.v1", ids)
        self.assertIn("agent-lifecycle-version.v1", ids)
        self.assertIn("agent-lifecycle-schema-index.v1", ids)
        self.assertIn("agent-adapter-event.v1", ids)
        self.assertIn("agent-adapter-event-stream-validation.v1", ids)
        self.assertIn("agent-adapter-event-stream-receipt.v1", ids)
        self.assertIn("agent-adapter-event-capture-validation.v1", ids)
        self.assertIn("agent-review-verdict.v1", ids)
        self.assertIn("agent-review-verdict-validation.v1", ids)
        self.assertIn("agent-review-routing-summary.v1", ids)
        self.assertIn("agent-optional-quality-pack.v1", ids)
        self.assertIn("agent-optional-quality-pack-validation.v1", ids)
        self.assertIn("agent-behavior-check-fixture.v1", ids)
        self.assertIn("agent-behavior-check-run.v1", ids)
        self.assertIn("agent-diagnostic-bundle.v1", ids)
        self.assertIn("agent-readonly-status-view.v1", ids)
        self.assertIn("agent-workflow-event-feed.v1", ids)
        self.assertIn("agent-lifecycle-progress-view.v1", ids)
        self.assertIn("agent-completion-signal.v1", ids)
        self.assertIn("agent-completion-signal-validation.v1", ids)
        self.assertIn("agent-completion-check.v1", ids)
        self.assertIn("agent-completion-check-validation.v1", ids)
        self.assertIn("agent-completion-check-receipt.v1", ids)
        self.assertIn("agent-completion-check-receipt-validation.v1", ids)
        self.assertIn("agent-goal-record.v1", ids)
        self.assertIn("agent-goal-record-validation.v1", ids)
        self.assertIn("agent-objective-snapshot.v1", ids)
        self.assertIn("agent-follow-up-register.v1", ids)
        self.assertIn("agent-follow-up-register-validation.v1", ids)
        self.assertIn("agent-follow-up-close-result.v1", ids)
        self.assertIn("agent-follow-up-summary.v1", ids)
        self.assertIn("agent-worktree-isolation-policy.v1", ids)
        self.assertIn("agent-worktree-isolation-policy-validation.v1", ids)
        self.assertIn("agent-worktree-attempt-receipt.v1", ids)
        self.assertIn("agent-worktree-attempt-receipt-validation.v1", ids)
        self.assertIn("agent-worktree-writeback-receipt.v1", ids)
        self.assertIn("agent-worktree-writeback-receipt-validation.v1", ids)
        self.assertIn("agent-runner-policy.v1", ids)
        self.assertIn("agent-runner-state.v1", ids)
        self.assertIn("agent-runner-state-validation.v1", ids)
        self.assertIn("agent-runner-transition-request.v1", ids)
        self.assertIn("agent-runner-transition-result.v1", ids)
        self.assertIn("agent-runner-snapshot.v1", ids)
        self.assertIn("agent-baseline-reconciliation-receipt.v1", ids)
        self.assertIn("agent-external-action-receipt.v1", ids)
        self.assertIn("agent-host-model-selection-profile.v1", ids)
        self.assertIn("agent-host-model-selection-receipt.v1", ids)
        self.assertIn("agent-lifecycle-budget-exceeded-policy.v1", ids)
        self.assertIn("agent-lifecycle-budget-decision-receipt.v1", ids)
        self.assertIn("agent-cursor-compat-evidence.v1", ids)
        self.assertIn("agent-lifecycle-model-route-request.v1", ids)
        self.assertIn("agent-lifecycle-model-usage-receipt.v1", ids)
        for schema_id in [
            "agent-adapter-capability-manifest.v1",
            "agent-adapter-capability-manifest-validation.v1",
            "agent-adapter-conformance-verification.v1",
            "agent-host-adapter-inspection.v1",
            "agent-host-adapter-validation.v1",
            "agent-release-candidate-inventory.v1",
            "agent-release-assembly-evidence.v1",
            "agent-release-verification-evidence.v1",
            "agent-final-candidate-audit.v1",
            "agent-support-matrix-contract-evidence.v1",
            "agent-deferred-promotion-contract-evidence.v1",
            "agent-neutrality-report.v1",
            "agent-live-calibration-verification.v1",
            "agent-lifecycle-live-calibration-receipt.v1",
            "agent-lifecycle-live-host-conformance-receipt.v1",
            "agent-live-host-conformance-verification.v1",
            "agent-adapter-probe-profile.v1",
            "agent-adapter-probe-plan.v1",
            "agent-adapter-probe-evidence-validation.v1",
            "agent-adapter-package-discovery.v1",
            "agent-live-host-promotion-plan.v1",
            "agent-live-host-promotion-plan-validation.v1",
            "agent-digest-authority-evidence.v1",
            "agent-docs-compat-evidence.v1",
            "agent-negative-suite-coverage.v1",
            "agent-task-packet-context-fit.v1",
            "agent-packaging-smoke-evidence.v1",
            "agent-adapter-scaffold-result.v1",
            "agent-workflow-lineage-check.v1",
            "agent-public-contract-policy.v1",
            "agent-public-contract-policy-validation.v1",
            "agent-lifecycle-cost-report.v1",
            "agent-lifecycle-cost-validation.v1",
            "agent-lifecycle-cost-generation.v1",
            "agent-lifecycle-cost-summary.v1",
            "agent-lifecycle-baselines.v1",
            "agent-lifecycle-baselines-validation.v1",
            "agent-lifecycle-overhead-statistics.v1",
            "agent-lifecycle-recommendation.v1",
            "agent-lifecycle-recommendation-summary.v1",
            "agent-lifecycle-regression-signals.v1",
            "agent-lifecycle-policy-proposal.v1",
            "agent-lifecycle-policy-summary.v1",
            "agent-lifecycle-tuned-policy.v1",
            "agent-lifecycle-policy-apply-result.v1",
            "agent-lifecycle-policy-tune-result.v1",
            "agent-runtime-policy-receipt.v1",
            "agent-runtime-policy-receipt-validation.v1",
            "agent-plan-reference-validation.v1",
            "agent-plan-snapshot.v1",
            "agent-plan-reconciliation.v1",
            "agent-plan-handoff.v1",
            "agent-evidence-index.v1",
            "agent-evidence-index-validation.v1",
            "agent-evidence-search-summary.v1",
            "agent-planning-import-result.v1",
            "agent-planning-import-validation.v1",
            "agent-skill-improvement-proposal.v1",
            "agent-skill-improvement-proposal-validation.v1",
            "agent-sandbox-receipt.v1",
            "agent-sandbox-receipt-validation.v1",
            "agent-sandbox-requirement.v1",
            "agent-sandbox-requirement-validation.v1",
            "agent-sandbox-capability.v1",
            "agent-sandbox-capability-validation.v1",
            "agent-cross-check-profile.v1",
            "agent-cross-check-profile-validation.v1",
            "agent-cross-check-receipt.v1",
            "agent-cross-check-receipt-validation.v1",
            "agent-runner-attempt-snapshot-receipt.v1",
            "agent-runner-attempt-snapshot-receipt-validation.v1",
            "agent-worker-lease-receipt.v1",
            "agent-worker-lease-receipt-validation.v1",
            "agent-import-dialect-profile.v1",
            "agent-import-dialect-profile-validation.v1",
            "agent-episode-index.v1",
            "agent-episode-index-validation.v1",
            "agent-episode-retrieval.v1",
            "agent-phase-resource-measurement.v1",
            "agent-phase-resource-measurement-validation.v1",
            "agent-task-template-library.v1",
            "agent-task-template-library-validation.v1",
            "agent-task-template-render.v1",
            "agent-bug-forensics-recipe-library.v1",
            "agent-bug-forensics-recipe-validation.v1",
        ]:
            self.assertIn(schema_id, ids)
        self.assertEqual(get_schema("agent-lifecycle-error.v1")["additionalProperties"], False)
        self.assertIn("status", get_schema("agent-final-candidate-audit.v1")["required"])
        self.assertEqual(
            get_schema("agent-release-verification-evidence.v1")["properties"]["productionPromotionClaimed"],
            {"const": False},
        )
        self.assertEqual(get_schema("agent-host-adapter-inspection.v1")["properties"]["liveCallsStarted"], {"const": False})
        self.assertEqual(get_schema("agent-host-adapter-inspection.v1")["properties"]["productionPromotionClaimed"], {"const": False})
        self.assertEqual(get_schema("agent-adapter-capability-manifest.v1")["properties"]["unsupportedOperationPolicy"], {"const": "fail-closed"})
        self.assertEqual(get_schema("agent-adapter-capability-manifest.v1")["properties"]["coreSemantics"], {"const": "delegated-to-agent-lifecycle-core"})
        self.assertEqual(get_schema("agent-adapter-event-stream-receipt.v1")["properties"]["productionPromotionClaimed"], {"const": False})
        self.assertEqual(get_schema("agent-adapter-event-capture-validation.v1")["properties"]["productionPromotionClaimed"], {"const": False})
        self.assertEqual(get_schema("agent-optional-quality-pack.v1")["properties"]["enabledByDefault"], {"const": False})
        self.assertEqual(get_schema("agent-optional-quality-pack.v1")["properties"]["productionPromotionClaimed"], {"const": False})
        self.assertEqual(get_schema("agent-diagnostic-bundle.v1")["properties"]["sourceOfTruth"], {"const": False})
        self.assertEqual(get_schema("agent-readonly-status-view.v1")["properties"]["sourceOfTruth"], {"const": False})
        self.assertEqual(get_schema("agent-workflow-event-feed.v1")["properties"]["readOnly"], {"const": True})
        self.assertEqual(get_schema("agent-workflow-event-feed.v1")["properties"]["modelCallsStarted"], {"const": False})
        self.assertEqual(get_schema("agent-lifecycle-progress-view.v1")["properties"]["tokenSpendForProgress"], {"const": False})
        self.assertEqual(get_schema("agent-lifecycle-progress-view.v1")["properties"]["stateWritten"], {"const": False})
        self.assertEqual(get_schema("agent-adapter-conformance-verification.v1")["properties"]["productionPromotionClaimed"], {"const": False})
        self.assertIn("commands", get_schema("agent-packaging-smoke-evidence.v1")["required"])
        self.assertEqual(get_schema("agent-completion-check.v1")["properties"]["kind"]["enum"], ["verification", "external-action"])
        self.assertEqual(get_schema("agent-completion-check-receipt-validation.v1")["properties"]["status"], {"const": "PASS"})
        self.assertEqual(get_schema("agent-goal-record.v1")["properties"]["status"]["enum"], ["ACTIVE", "BLOCKED", "READY_FOR_FINALIZATION", "COMPLETE"])
        self.assertIn("items", get_schema("agent-follow-up-register.v1")["required"])
        self.assertIn("finalizationBlockers", get_schema("agent-follow-up-register-validation.v1")["required"])
        self.assertIn("worktreeRoot", get_schema("agent-worktree-isolation-policy.v1")["required"])
        self.assertIn("cleanupDecision", get_schema("agent-worktree-attempt-receipt-validation.v1")["required"])
        self.assertIn("decision", get_schema("agent-worktree-writeback-receipt-validation.v1")["required"])
        self.assertIn("attempt", get_schema("agent-runner-transition-request.v1")["properties"]["action"]["enum"])
        self.assertEqual(get_schema("agent-runner-policy.v1")["properties"]["maxAttemptsPerTask"]["minimum"], 0)
        self.assertEqual(get_schema("agent-plan-snapshot.v1")["properties"]["immutable"], {"const": True})
        self.assertEqual(get_schema("agent-plan-reconciliation.v1")["properties"]["classification"]["enum"], ["MATCH", "REQUIRES_NEW_PLAN", "BLOCKED"])
        self.assertEqual(get_schema("agent-evidence-index.v1")["properties"]["sourceOfTruth"], {"const": False})
        self.assertEqual(get_schema("agent-evidence-index.v1")["properties"]["enabledByDefault"], {"const": False})
        self.assertEqual(get_schema("agent-planning-import-result.v1")["properties"]["freezeBlocked"], {"const": True})
        self.assertEqual(get_schema("agent-skill-improvement-proposal.v1")["properties"]["autoApply"], {"const": False})
        self.assertEqual(get_schema("agent-lifecycle-recommendation.v1")["properties"]["advisoryOnly"], {"const": True})
        self.assertEqual(get_schema("agent-lifecycle-recommendation.v1")["properties"]["autoApply"], {"const": False})
        self.assertEqual(get_schema("agent-lifecycle-recommendation.v1")["properties"]["qualityFloorPreserved"], {"const": True})
        self.assertEqual(get_schema("agent-lifecycle-policy-proposal.v1")["properties"]["advisoryOnly"], {"const": True})
        self.assertEqual(get_schema("agent-lifecycle-policy-proposal.v1")["properties"]["autoApply"], {"const": False})
        self.assertEqual(get_schema("agent-lifecycle-tuned-policy.v1")["properties"]["productionPromotionClaimed"], {"const": False})
        self.assertEqual(get_schema("agent-adapter-scaffold-result.v1")["properties"]["maturity"], {"const": "EXPERIMENTAL"})
        self.assertEqual(get_schema("agent-lifecycle-live-host-conformance-receipt.v1")["properties"]["syntheticReplayUsed"], {"const": False})
        self.assertIn("validationCommands", get_schema("agent-live-host-promotion-plan.v1")["required"])
        self.assertEqual(get_schema("agent-live-host-promotion-plan-validation.v1")["properties"]["productionPromotionClaimed"], {"const": False})
        self.assertEqual(get_schema("agent-sandbox-receipt.v1")["properties"]["productionPromotionClaimed"], {"const": False})
        self.assertIn("writeScopeBoundary", get_schema("agent-sandbox-receipt.v1")["required"])
        self.assertIn("partialBoundaryCount", get_schema("agent-sandbox-receipt-validation.v1")["properties"])
        self.assertIn("credentialProxyCount", get_schema("agent-sandbox-receipt-validation.v1")["properties"])
        self.assertEqual(get_schema("agent-adapter-probe-plan.v1")["properties"]["liveCallsStarted"], {"const": False})
        self.assertEqual(get_schema("agent-adapter-probe-plan.v1")["properties"]["productionPromotionClaimed"], {"const": False})
        self.assertEqual(get_schema("agent-adapter-probe-evidence-validation.v1")["properties"]["maturityChangeClaimed"], {"const": False})
        self.assertEqual(get_schema("agent-adapter-package-discovery.v1")["properties"]["advisoryOnly"], {"const": True})
        self.assertEqual(get_schema("agent-adapter-package-discovery.v1")["properties"]["discoveryCanOverrideDescriptors"], {"const": False})
        self.assertEqual(get_schema("agent-cross-check-profile.v1")["properties"]["enabledByDefault"], {"const": False})
        self.assertEqual(get_schema("agent-cross-check-profile.v1")["properties"]["budgetUnits"], {"const": "tokens-and-resources"})
        self.assertEqual(get_schema("agent-runner-attempt-snapshot-receipt.v1")["properties"]["productionPromotionClaimed"], {"const": False})
        self.assertEqual(get_schema("agent-worker-lease-receipt.v1")["properties"]["productionPromotionClaimed"], {"const": False})
        self.assertEqual(get_schema("agent-phase-resource-measurement.v1")["properties"]["productionPromotionClaimed"], {"const": False})
        self.assertEqual(get_schema("agent-import-dialect-profile.v1")["properties"]["sourceTrusted"], {"const": False})
        self.assertEqual(get_schema("agent-episode-index.v1")["properties"]["sourceOfTruth"], {"const": False})
        self.assertEqual(get_schema("agent-task-template-library.v1")["properties"]["draftOnly"], {"const": True})
        self.assertEqual(get_schema("agent-task-template-library.v1")["properties"]["freezeBlocked"], {"const": True})
        self.assertEqual(get_schema("agent-bug-forensics-recipe-library.v1")["properties"]["enabledByDefault"], {"const": False})
        self.assertEqual(get_schema("agent-bug-forensics-recipe-library.v1")["properties"]["budgetUnits"], {"const": "tokens-and-resources"})
        with self.assertRaises(LifecycleError):
            get_schema("missing.v1")

    def test_json_object_loader_rejects_arrays(self) -> None:
        with self.assertRaises(LifecycleError):
            read_json_object(_json_array_file())


def _json_array_file() -> Path:
    path = Path(tempfile.mkdtemp()) / "array.json"
    path.write_text(json.dumps([]), encoding="utf-8")
    return path


if __name__ == "__main__":
    unittest.main()

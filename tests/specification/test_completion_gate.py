from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError, canonical_digest  # noqa: E402
from agent_lifecycle.specification import (  # noqa: E402
    build_completion_gate_receipt,
    require_completion_gate_finalization,
    validate_completion_gate_receipt,
)


class CompletionGateTests(unittest.TestCase):
    def test_stop_when_acceptance_validation_and_final_proof_are_ready(self) -> None:
        receipt = build_completion_gate_receipt(
            state=_state(task_status="ACCEPTED"),
            final_audit=_final_audit(),
            validation_results=[{"id": "VAL-FULL", "status": "PASS"}],
            required_validation_ids=["VAL-FULL"],
        )
        validation = validate_completion_gate_receipt(receipt, state=_state(task_status="ACCEPTED"), final_audit=_final_audit())

        self.assertEqual(receipt["decision"], "STOP")
        self.assertEqual(receipt["reasonCodes"], ["all-required-evidence-passed"])
        self.assertTrue(validation["finalizationAllowed"])

    def test_continue_when_required_acceptance_is_missing(self) -> None:
        receipt = build_completion_gate_receipt(
            state=_state(task_status="READY"),
            final_audit=_final_audit(),
            validation_results=[{"id": "VAL-FULL", "status": "PASS"}],
            required_validation_ids=["VAL-FULL"],
        )

        self.assertEqual(receipt["decision"], "CONTINUE")
        self.assertIn("required-acceptance-missing", receipt["reasonCodes"])
        self.assertEqual(receipt["acceptance"]["missingTaskIds"], ["WS-01"])

    def test_continue_when_validation_is_missing_or_failing(self) -> None:
        missing = build_completion_gate_receipt(
            state=_state(task_status="ACCEPTED"),
            final_audit=_final_audit(),
            validation_results=[],
            required_validation_ids=["VAL-FULL"],
        )
        failing = build_completion_gate_receipt(
            state=_state(task_status="ACCEPTED"),
            final_audit=_final_audit(),
            validation_results=[{"id": "VAL-FULL", "status": "FAIL"}],
            required_validation_ids=["VAL-FULL"],
        )

        self.assertEqual(missing["decision"], "CONTINUE")
        self.assertIn("validation-missing", missing["reasonCodes"])
        self.assertEqual(failing["decision"], "CONTINUE")
        self.assertIn("validation-failed", failing["reasonCodes"])

    def test_escalate_for_open_blocker_risk_or_blocking_follow_up(self) -> None:
        state = _state(task_status="ACCEPTED")
        state["blocker"] = {"code": "external-authority", "reason": "needs operator"}
        receipt = build_completion_gate_receipt(state=state, final_audit=_final_audit())
        risk = build_completion_gate_receipt(
            state=_state(task_status="ACCEPTED"),
            final_audit=_final_audit(),
            risk_flags=[{"id": "RISK-1", "severity": "HIGH"}],
        )
        follow_up = build_completion_gate_receipt(
            state=_state(task_status="ACCEPTED"),
            final_audit=_final_audit(),
            follow_up_register=_follow_up_register(current_scope_impact="completion-proof"),
        )

        self.assertEqual(receipt["decision"], "ESCALATE")
        self.assertEqual(risk["decision"], "ESCALATE")
        self.assertEqual(follow_up["decision"], "ESCALATE")
        self.assertIn("follow-up-blocks-finalization", follow_up["reasonCodes"])

    def test_split_decision_takes_priority_over_continue(self) -> None:
        receipt = build_completion_gate_receipt(
            state=_state(task_status="READY"),
            final_audit=_final_audit(),
            split_candidates=[{"id": "SPLIT-1", "required": True}],
        )

        self.assertEqual(receipt["decision"], "SPLIT")
        self.assertIn("split-required", receipt["reasonCodes"])

    def test_follow_up_decision_requires_non_blocking_work(self) -> None:
        receipt = build_completion_gate_receipt(
            state=_state(task_status="ACCEPTED"),
            final_audit=_final_audit(),
            follow_up_candidates=[{"id": "FU-1"}],
        )
        validation = require_completion_gate_finalization(receipt, state=_state(task_status="ACCEPTED"), final_audit=_final_audit())

        self.assertEqual(receipt["decision"], "FOLLOW_UP")
        self.assertEqual(receipt["reasonCodes"], ["non-blocking-follow-up"])
        self.assertTrue(validation["finalizationAllowed"])

    def test_finalization_requirement_rejects_continue_decision(self) -> None:
        receipt = build_completion_gate_receipt(state=_state(task_status="READY"), final_audit=_final_audit())

        with self.assertRaises(LifecycleError) as raised:
            require_completion_gate_finalization(receipt, state=_state(task_status="READY"), final_audit=_final_audit())

        self.assertEqual(raised.exception.code, "completion-gate-not-ready")

    def test_validation_rejects_forged_stop_when_acceptance_is_missing(self) -> None:
        receipt = build_completion_gate_receipt(state=_state(task_status="READY"), final_audit=_final_audit())
        forged = {
            **receipt,
            "decision": "STOP",
            "reasonCodes": ["all-required-evidence-passed"],
            "blockers": [],
        }
        forged["gateDigest"] = canonical_digest({key: value for key, value in forged.items() if key != "gateDigest"})

        with self.assertRaises(LifecycleError) as raised:
            validate_completion_gate_receipt(forged, state=_state(task_status="READY"), final_audit=_final_audit())

        self.assertEqual(raised.exception.code, "completion-gate-blocked")

    def test_validation_rejects_tampered_digest_and_input_mismatch(self) -> None:
        receipt = build_completion_gate_receipt(state=_state(task_status="ACCEPTED"), final_audit=_final_audit())
        tampered = {**receipt, "decision": "CONTINUE"}
        with self.assertRaises(LifecycleError) as raised:
            validate_completion_gate_receipt(tampered, state=_state(task_status="ACCEPTED"), final_audit=_final_audit())
        self.assertEqual(raised.exception.code, "completion-gate-digest-mismatch")

        with self.assertRaises(LifecycleError) as mismatch:
            validate_completion_gate_receipt(receipt, state=_state(task_status="READY"), final_audit=_final_audit())
        self.assertEqual(mismatch.exception.code, "completion-gate-input-mismatch")


def _state(*, task_status: str) -> dict:
    return {
        "schemaVersion": "agent-workflow-state.v3",
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "stateRevision": 1,
        "phase": "FINAL_AUDIT",
        "tasks": [{"id": "WS-01", "status": task_status, "required": True}],
        "blocker": None,
    }


def _final_audit() -> dict:
    return {
        "schemaVersion": "agent-run-final-audit.v1",
        "status": "PASS",
        "semanticStatus": "READY_FOR_FINALIZATION",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "productionPromotionClaimed": False,
        "notAcceptedTasks": [],
        "missingReleaseEvidence": [],
        "findings": [],
    }


def _follow_up_register(*, current_scope_impact: str) -> dict:
    return {
        "schemaVersion": "agent-follow-up-register.v1",
        "lineage": {
            "runId": "run",
            "packageId": "package",
            "planRevision": 1,
            "planDigest": "0" * 64,
            "sourceRevision": "source",
        },
        "items": [
            {
                "id": "FU-01",
                "title": "Follow-up",
                "owner": {"id": "owner"},
                "status": "SCHEDULED",
                "source": {"outOfScopeReason": "deferred"},
                "targetRelease": "next",
                "currentScopeImpact": current_scope_impact,
                "closureEvidence": {"requiredEvidenceIds": [], "requiredArtifacts": []},
                "reason": "deferred",
            }
        ],
        "updatedAt": "2026-08-01T12:00:00Z",
    }


if __name__ == "__main__":
    unittest.main()

"""Typed fixtures match runtime shapes; existing validators own rejection."""

from __future__ import annotations

import copy
import inspect
import unittest
from unittest.mock import patch

from agent_lifecycle.contracts import canonical_bytes, canonical_digest
from agent_lifecycle.contracts.implementation_audit_validation import validate_final_audit_outcome_report
from agent_lifecycle.contracts.workflow_finalization_types import (
    AcceptedTaskProof,
    FinalAuditOutcomeValidation,
    FinalizationProof,
    FinalizationProofBody,
    FinalizationProofInputs,
)
from agent_lifecycle.workflow.finalization import _proof_body


def _inputs() -> FinalizationProofInputs:
    return {
        "operation_id": "finalize",
        "final_audit": {"path": "final/audit.json", "sha256": "a" * 64, "bytes": 15},
        "completion_check_receipt": None,
        "completion_gate": None,
        "goal_record": None,
        "follow_up_register": None,
        "proof_integrity": None,
        "final_implementation_audit": None,
        "release_full_validation": None,
        "finalization_gate_receipts": [],
        "review_mesh_quorum": None,
        "reason": "complete",
    }


def _state() -> dict:
    return {
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "stateRevision": 4,
        "tasks": [{"id": "WS-01", "attempt": 1, "status": "ACCEPTED", "review": None}],
    }


class WorkflowFinalizationTypeTests(unittest.TestCase):
    def test_input_contract_matches_builder_keywords_and_required_arguments(self) -> None:
        parameters = inspect.signature(_proof_body).parameters
        input_keys = FinalizationProofInputs.__required_keys__ | FinalizationProofInputs.__optional_keys__
        self.assertEqual(input_keys, parameters.keys() - {"state", "lifecycle_control_stop"})
        self.assertEqual(FinalizationProofInputs.__optional_keys__, {"source_usage_assurance"})
        self.assertEqual(FinalizationProofInputs.__required_keys__, _inputs().keys())
        for key in FinalizationProofInputs.__required_keys__:
            with self.subTest(field=key):
                self.assertEqual(parameters[key].default, inspect.Parameter.empty)

    def test_typed_proof_preserves_canonical_body_and_absent_evidence(self) -> None:
        inputs = _inputs()
        accepted: AcceptedTaskProof = {"id": "WS-01", "attempt": 1, "review": None}
        body: FinalizationProofBody = {
            "schemaVersion": "agent-run-final-proof.v1",
            "runId": "run",
            "packageId": "package",
            "planRevision": 1,
            "planDigest": "0" * 64,
            "sourceRevision": "source",
            "operationId": "finalize",
            "stateRevisionBeforeFinalization": 4,
            "semanticStatus": "READY_FOR_FINALIZATION",
            "productionPromotionClaimed": False,
            "acceptedTasks": [accepted],
            "finalAudit": inputs["final_audit"],
            "completionCheck": None,
            "completionGate": None,
            "goalRecord": None,
            "followUpRegister": None,
            "proofIntegrity": None,
            "finalImplementationAudit": None,
            "releaseFullValidation": None,
            "finalizationGateReceipts": [],
            "reviewMeshQuorum": None,
            "lifecycleControlStop": None,
            "reason": "complete",
            "createdAt": "2026-10-23T00:00:00Z",
        }
        expected: FinalizationProof = {**body, "bodyDigest": canonical_digest(body)}
        with patch("agent_lifecycle.workflow.finalization.now_iso", return_value=body["createdAt"]):
            actual = _proof_body(_state(), **inputs, lifecycle_control_stop=None)
        self.assertEqual(canonical_bytes(actual), canonical_bytes(expected))
        self.assertEqual(actual.keys(), FinalizationProof.__required_keys__)
        self.assertNotIn("usageAssurance", actual)

    def test_source_assurance_preserves_unknown_values_and_task_projection(self) -> None:
        inputs = _inputs()
        assurance = {"status": "UNAVAILABLE", "actualTokens": None, "actualCost": None}
        inputs["source_usage_assurance"] = {"tasks": [{"taskId": "WS-01", "assurance": assurance}]}
        before = copy.deepcopy(inputs)
        actual = _proof_body(_state(), **inputs, lifecycle_control_stop=None)
        self.assertEqual(actual["usageAssurance"], inputs["source_usage_assurance"])
        self.assertEqual(actual["acceptedTasks"][0]["usageAssurance"], assurance)
        self.assertEqual(inputs, before)
        self.assertEqual(actual.keys(), FinalizationProof.__required_keys__ | {"usageAssurance"})
        self.assertEqual(actual["acceptedTasks"][0].keys(), AcceptedTaskProof.__required_keys__ | {"usageAssurance"})
        self.assertEqual(actual["bodyDigest"], canonical_digest({k: v for k, v in actual.items() if k != "bodyDigest"}))

    def test_existing_outcome_validator_rejects_missing_and_malformed_fields(self) -> None:
        report = {
            **{key: value for key, value in _state().items() if key not in {"tasks", "stateRevision"}},
            "status": "PASS",
            "semanticStatus": "READY_FOR_FINALIZATION",
            "productionPromotionClaimed": False,
            "findings": [],
            "verifier": {"independent": True},
        }
        cases: tuple[tuple[str, str | dict[str, str] | list[str] | None, str], ...] = (
            ("findings", None, "final-audit-outcome-findings-invalid"),
            ("findings", {}, "final-audit-outcome-findings-invalid"),
            ("verifier", None, "final-audit-outcome-not-independent"),
            ("verifier", [], "final-audit-outcome-not-independent"),
            ("productionPromotionClaimed", None, "final-audit-outcome-production-claim"),
            ("productionPromotionClaimed", "false", "final-audit-outcome-production-claim"),
        )
        for field, value, code in cases:
            with self.subTest(field=field, value=value):
                malformed = copy.deepcopy(report)
                if value is None:
                    malformed.pop(field)
                else:
                    malformed[field] = value
                before = copy.deepcopy(malformed)
                result = validate_final_audit_outcome_report(
                    malformed, state=_state(), verdict="ACCEPTED", task_ids=[], finding_ids=[]
                )
                self.assertEqual(result["status"], "FAIL")
                self.assertIn(code, [blocker["code"] for blocker in result["blockers"]])
                self.assertEqual(result.keys(), FinalAuditOutcomeValidation.__required_keys__)
                self.assertEqual(malformed, before)
                self.assertEqual(
                    result["validationDigest"],
                    canonical_digest({k: v for k, v in result.items() if k != "validationDigest"}),
                )

    def test_failed_outcome_validation_keeps_unsupported_verdict(self) -> None:
        result = validate_final_audit_outcome_report({}, state=_state(), verdict="UNKNOWN", task_ids=[], finding_ids=[])
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["verdict"], "UNKNOWN")
        self.assertIn({"code": "final-audit-outcome-verdict-invalid"}, result["blockers"])

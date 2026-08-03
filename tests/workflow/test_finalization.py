from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402

from agent_lifecycle.specification import build_completion_gate_receipt  # noqa: E402

class WorkflowFinalizationTests(unittest.TestCase):
    def test_finalize_run_writes_proof_and_completes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["status"] = "ACCEPTED"
            state["tasks"][0]["attempt"] = 1
            state["tasks"][0]["review"] = {"path": "work/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            write_json_create(root / "final/final-audit.json", _final_audit())

            payload = finalize_run(
                state_path,
                operation_id="finalize-op",
                expected_revision=1,
                source_revision="source",
                final_audit_path="final/final-audit.json",
                proof_path="final/proof.json",
                reason="done",
            )

            self.assertEqual(payload["phase"], "COMPLETE")
            self.assertEqual(payload["nextAction"]["type"], "none")
            proof = json.loads((root / "final/proof.json").read_text(encoding="utf-8"))
            self.assertEqual(proof["schemaVersion"], "agent-run-final-proof.v1")
            self.assertFalse(proof["productionPromotionClaimed"])
            self.assertEqual(proof["operationId"], "finalize-op")
            self.assertEqual(proof["finalAudit"]["path"], "final/final-audit.json")

            with self.assertRaises(LifecycleError) as raised:
                finalize_run(
                    state_path,
                    operation_id="finalize-op",
                    expected_revision=2,
                    source_revision="source",
                    final_audit_path="final/final-audit.json",
                    proof_path="final/proof-replay.json",
                    reason="replay",
                )
            self.assertEqual(raised.exception.code, "duplicate-operation")

    def test_finalize_run_rejects_final_audit_with_open_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["status"] = "ACCEPTED"
            state["tasks"][0]["attempt"] = 1
            state["tasks"][0]["review"] = {"path": "work/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            audit = _final_audit()
            audit["findings"] = [{"id": "F-1", "status": "open", "severity": "MEDIUM"}]
            write_json_create(root / "final/final-audit.json", audit)

            with self.assertRaises(LifecycleError):
                finalize_run(
                    state_path,
                    operation_id="finalize-op",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="final/final-audit.json",
                    proof_path="final/proof.json",
                    reason="done",
                )

    def test_finalize_run_requires_completion_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["status"] = "ACCEPTED"
            state["tasks"][0]["attempt"] = 1
            state["tasks"][0]["review"] = {"path": "work/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            audit = _final_audit()
            audit.pop("completionSignal")
            write_json_create(root / "final/final-audit.json", audit)

            with self.assertRaises(LifecycleError) as raised:
                finalize_run(
                    state_path,
                    operation_id="finalize-op",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="final/final-audit.json",
                    proof_path="final/proof.json",
                    reason="done",
                )

            self.assertEqual(raised.exception.code, "completion-signal-required")

    def test_finalize_run_accepts_explicit_completion_signal_waiver(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["status"] = "ACCEPTED"
            state["tasks"][0]["attempt"] = 1
            state["tasks"][0]["review"] = {"path": "work/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            audit = _final_audit()
            audit["completionSignal"] = _completion_signal("WAIVED")
            write_json_create(root / "final/final-audit.json", audit)

            payload = finalize_run(
                state_path,
                operation_id="finalize-op",
                expected_revision=1,
                source_revision="source",
                final_audit_path="final/final-audit.json",
                proof_path="final/proof.json",
                reason="done",
            )

            self.assertEqual(payload["phase"], "COMPLETE")

    def test_finalize_run_records_passing_completion_check_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            _accept_only_task(state_path)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["completionCheck"] = _completion_check()
            state_path.write_text(json.dumps(state), encoding="utf-8")
            write_json_create(root / "final/final-audit.json", _final_audit())
            write_json_create(root / "final/completion-check-receipt.json", _completion_check_receipt("PASS"))

            payload = finalize_run(
                state_path,
                operation_id="finalize-op",
                expected_revision=1,
                source_revision="source",
                final_audit_path="final/final-audit.json",
                proof_path="final/proof.json",
                reason="done",
            )

            self.assertEqual(payload["phase"], "COMPLETE")
            proof = json.loads((root / "final/proof.json").read_text(encoding="utf-8"))
            self.assertEqual(proof["completionCheck"]["receipt"]["path"], "final/completion-check-receipt.json")
            self.assertEqual(proof["completionCheck"]["validation"]["status"], "PASS")
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["completionCheckReceipt"]["path"], "final/completion-check-receipt.json")

    def test_finalize_run_fails_closed_when_completion_check_receipt_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            _accept_only_task(state_path)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["completionCheck"] = _completion_check()
            state_path.write_text(json.dumps(state), encoding="utf-8")
            write_json_create(root / "final/final-audit.json", _final_audit())

            with self.assertRaises(LifecycleError) as raised:
                finalize_run(
                    state_path,
                    operation_id="finalize-op",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="final/final-audit.json",
                    proof_path="final/proof.json",
                    reason="done",
                )

            self.assertEqual(raised.exception.code, "completion-check-receipt-missing")

    def test_finalize_run_rejects_failed_completion_check_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            _accept_only_task(state_path)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["completionCheck"] = _completion_check()
            state_path.write_text(json.dumps(state), encoding="utf-8")
            write_json_create(root / "final/final-audit.json", _final_audit())
            write_json_create(root / "final/completion-check-receipt.json", _completion_check_receipt("FAIL"))

            with self.assertRaises(LifecycleError) as raised:
                finalize_run(
                    state_path,
                    operation_id="finalize-op",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="final/final-audit.json",
                    proof_path="final/proof.json",
                    reason="done",
                )

            self.assertEqual(raised.exception.code, "completion-check-not-satisfied")

    def test_finalize_run_external_action_check_binds_existing_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            _accept_only_task(state_path)
            external_identity = {"path": "human/approval.json", "sha256": "a" * 64, "bytes": 100}
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["completionCheck"] = _completion_check(kind="external-action")
            state["externalActionReceipt"] = external_identity
            state_path.write_text(json.dumps(state), encoding="utf-8")
            write_json_create(root / "final/final-audit.json", _final_audit())
            receipt = _completion_check_receipt("PASS")
            receipt["externalActionReceipt"] = external_identity
            write_json_create(root / "final/completion-check-receipt.json", receipt)

            payload = finalize_run(
                state_path,
                operation_id="finalize-op",
                expected_revision=1,
                source_revision="source",
                final_audit_path="final/final-audit.json",
                proof_path="final/proof.json",
                reason="done",
            )

            self.assertEqual(payload["phase"], "COMPLETE")
            proof = json.loads((root / "final/proof.json").read_text(encoding="utf-8"))
            self.assertEqual(proof["completionCheck"]["validation"]["checkKind"], "external-action")

    def test_finalize_run_records_current_goal_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            _accept_only_task(state_path)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            check = _completion_check()
            check_digest = canonical_digest(check)
            state["completionCheck"] = check
            state["completionCheckValidation"] = {
                "schemaVersion": "agent-completion-check-validation.v1",
                "status": "PASS",
                "checkId": check["checkId"],
                "checkKind": check["kind"],
                "receiptPath": check["receiptPath"],
                "requiredEvidenceIds": check["requiredEvidenceIds"],
                "checkDigest": check_digest,
            }
            state_path.write_text(json.dumps(state), encoding="utf-8")
            write_json_create(root / "final/final-audit.json", _final_audit())
            write_json_create(root / "final/completion-check-receipt.json", _completion_check_receipt("PASS"))
            write_json_create(root / "final/goal-record.json", _goal_record(state, check_digest=check_digest))

            payload = finalize_run(
                state_path,
                operation_id="finalize-op",
                expected_revision=1,
                source_revision="source",
                final_audit_path="final/final-audit.json",
                proof_path="final/proof.json",
                goal_record_path="final/goal-record.json",
                reason="done",
            )

            self.assertEqual(payload["phase"], "COMPLETE")
            proof = json.loads((root / "final/proof.json").read_text(encoding="utf-8"))
            self.assertEqual(proof["goalRecord"]["record"]["path"], "final/goal-record.json")
            self.assertEqual(proof["goalRecord"]["validation"]["goalStatus"], "READY_FOR_FINALIZATION")
            self.assertEqual(proof["completionCheck"]["validation"]["checkDigest"], check_digest)
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["goalRecord"]["path"], "final/goal-record.json")

    def test_finalize_run_rejects_stale_goal_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            _accept_only_task(state_path)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state_path.write_text(json.dumps(state), encoding="utf-8")
            write_json_create(root / "final/final-audit.json", _final_audit())
            record = _goal_record(state)
            record["lineage"]["stateRevision"] = 2
            write_json_create(root / "final/goal-record.json", record)

            with self.assertRaises(LifecycleError) as raised:
                finalize_run(
                    state_path,
                    operation_id="finalize-op",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="final/final-audit.json",
                    proof_path="final/proof.json",
                    goal_record_path="final/goal-record.json",
                    reason="done",
                )

            self.assertEqual(raised.exception.code, "goal-state-stale")

    def test_finalize_run_rejects_blocking_follow_up_register(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            _accept_only_task(state_path)
            write_json_create(root / "final/final-audit.json", _final_audit())
            write_json_create(root / "final/follow-up-register.json", _follow_up_register(current_scope_impact="completion-proof"))

            with self.assertRaises(LifecycleError) as raised:
                finalize_run(
                    state_path,
                    operation_id="finalize-op",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="final/final-audit.json",
                    proof_path="final/proof.json",
                    follow_up_register_path="final/follow-up-register.json",
                    reason="done",
                )

            self.assertEqual(raised.exception.code, "follow-up-finalization-blocked")

    def test_finalize_run_records_checked_follow_up_register(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            _accept_only_task(state_path)
            write_json_create(root / "final/final-audit.json", _final_audit())
            write_json_create(root / "final/follow-up-register.json", _follow_up_register(status="SCHEDULED"))

            payload = finalize_run(
                state_path,
                operation_id="finalize-op",
                expected_revision=1,
                source_revision="source",
                final_audit_path="final/final-audit.json",
                proof_path="final/proof.json",
                follow_up_register_path="final/follow-up-register.json",
                reason="done",
            )

            self.assertEqual(payload["phase"], "COMPLETE")
            proof = json.loads((root / "final/proof.json").read_text(encoding="utf-8"))
            self.assertEqual(proof["followUpRegister"]["register"]["path"], "final/follow-up-register.json")
            self.assertEqual(proof["followUpRegister"]["validation"]["status"], "PASS")

    def test_finalize_run_records_passing_completion_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            _accept_only_task(state_path)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            final_audit = _final_audit()
            write_json_create(root / "final/final-audit.json", final_audit)
            gate = build_completion_gate_receipt(state=state, final_audit=final_audit)
            write_json_create(root / "final/completion-gate.json", gate)

            payload = finalize_run(
                state_path,
                operation_id="finalize-op",
                expected_revision=1,
                source_revision="source",
                final_audit_path="final/final-audit.json",
                proof_path="final/proof.json",
                completion_gate_receipt_path="final/completion-gate.json",
                reason="done",
            )

            self.assertEqual(payload["phase"], "COMPLETE")
            proof = json.loads((root / "final/proof.json").read_text(encoding="utf-8"))
            self.assertEqual(proof["completionGate"]["validation"]["decision"], "STOP")
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["completionGateReceipt"]["path"], "final/completion-gate.json")

    def test_finalize_run_rejects_completion_gate_continue_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            _accept_only_task(state_path)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            final_audit = _final_audit()
            write_json_create(root / "final/final-audit.json", final_audit)
            gate = build_completion_gate_receipt(
                state=state,
                final_audit=final_audit,
                validation_results=[{"id": "VAL-FULL", "status": "FAIL"}],
                required_validation_ids=["VAL-FULL"],
            )
            write_json_create(root / "final/completion-gate.json", gate)

            with self.assertRaises(LifecycleError) as raised:
                finalize_run(
                    state_path,
                    operation_id="finalize-op",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="final/final-audit.json",
                    proof_path="final/proof.json",
                    completion_gate_receipt_path="final/completion-gate.json",
                    reason="done",
                )

            self.assertEqual(raised.exception.code, "completion-gate-not-ready")

    def test_finalize_run_rejects_final_audit_plan_digest_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["status"] = "ACCEPTED"
            state["tasks"][0]["attempt"] = 1
            state["tasks"][0]["review"] = {"path": "work/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            audit = _final_audit()
            audit["planDigest"] = "9" * 64
            write_json_create(root / "final/final-audit.json", audit)

            with self.assertRaises(LifecycleError) as raised:
                finalize_run(
                    state_path,
                    operation_id="finalize-op",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="final/final-audit.json",
                    proof_path="final/proof.json",
                    reason="done",
                )
            self.assertEqual(raised.exception.code, "final-audit-lineage-mismatch")

    def test_finalize_run_rejects_stale_state_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["status"] = "ACCEPTED"
            state["tasks"][0]["attempt"] = 1
            state["tasks"][0]["review"] = {"path": "work/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            write_json_create(root / "final/final-audit.json", _final_audit())

            with self.assertRaises(LifecycleError) as raised:
                finalize_run(
                    state_path,
                    operation_id="finalize-op",
                    expected_revision=2,
                    source_revision="source",
                    final_audit_path="final/final-audit.json",
                    proof_path="final/proof.json",
                    reason="done",
                )
            self.assertEqual(raised.exception.code, "state-revision-mismatch")

    def test_finalize_run_requires_finalization_gate_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["status"] = "ACCEPTED"
            state["tasks"][0]["attempt"] = 1
            state["tasks"][0]["review"] = {"path": "work/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
            state["tasks"][0]["controllerGates"] = [_gate("G-FINAL", ["finalization"])]
            state_path.write_text(json.dumps(state), encoding="utf-8")
            write_json_create(root / "final/final-audit.json", _final_audit())

            with self.assertRaises(LifecycleError):
                finalize_run(
                    state_path,
                    operation_id="finalize-op",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="final/final-audit.json",
                    proof_path="final/proof.json",
                    reason="done",
                )

    def test_finalize_run_rejects_missing_required_implementation_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            _accept_only_task(state_path)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["implementationAuditRequired"] = True
            state_path.write_text(json.dumps(state), encoding="utf-8")
            write_json_create(root / "final/final-audit.json", _final_audit())

            with self.assertRaises(LifecycleError) as raised:
                finalize_run(
                    state_path,
                    operation_id="finalize-op",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="final/final-audit.json",
                    proof_path="final/proof.json",
                    reason="done",
                )

            self.assertEqual(raised.exception.code, "implementation-audit-required")

    def test_finalize_run_rejects_missing_final_implementation_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            _accept_only_task(state_path)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["finalImplementationAuditRequired"] = True
            state["tasks"][0]["implementationAuditReport"] = {
                "path": "work/WS-01/attempt-1/implementation-audit.json",
                "sha256": "4" * 64,
                "bytes": 10,
                "taskId": "WS-01",
                "attempt": 1,
                "verdict": "ACCEPTED",
                "reportDigest": "5" * 64,
                "validation": {"status": "PASS", "validationDigest": "6" * 64},
            }
            state_path.write_text(json.dumps(state), encoding="utf-8")
            write_json_create(root / "final/final-audit.json", _final_audit())

            with self.assertRaises(LifecycleError) as raised:
                finalize_run(
                    state_path,
                    operation_id="finalize-op",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="final/final-audit.json",
                    proof_path="final/proof.json",
                    reason="done",
                )

            self.assertEqual(raised.exception.code, "final-implementation-audit-required")

def _accept_only_task(state_path: Path) -> None:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["tasks"][0]["status"] = "ACCEPTED"
    state["tasks"][0]["attempt"] = 1
    state["tasks"][0]["review"] = {"path": "work/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
    state_path.write_text(json.dumps(state), encoding="utf-8")


def _completion_check(*, kind: str = "verification") -> dict:
    return {
        "schemaVersion": "agent-completion-check.v1",
        "checkId": "done-check",
        "kind": kind,
        "description": "Observable completion evidence for the requested outcome.",
        "receiptPath": "final/completion-check-receipt.json",
        "requiredEvidenceIds": ["EV-FINAL"],
    }


def _completion_check_receipt(status: str) -> dict:
    return {
        "schemaVersion": "agent-completion-check-receipt.v1",
        "checkId": "done-check",
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "status": status,
        "evidenceIds": ["EV-FINAL"],
        "verifier": {"id": "observable-check"},
        "checkedAt": "2026-07-30T08:00:00Z",
    }


def _goal_record(state: dict, *, check_digest: str | None = None) -> dict:
    record = {
        "schemaVersion": "agent-goal-record.v1",
        "goalId": "release-015",
        "userIntent": "Finish the requested release with validation.",
        "ownerOutcome": "Final proof links accepted work, completion evidence and continuity context.",
        "constraints": ["Do not commit work/", "Fail closed on stale state"],
        "status": "READY_FOR_FINALIZATION",
        "lineage": {
            "runId": state["runId"],
            "packageId": state["packageId"],
            "planRevision": state["planRevision"],
            "planDigest": state["planDigest"],
            "sourceRevision": state["sourceRevision"],
            "stateRevision": state["stateRevision"],
        },
        "evidenceIds": ["EV-FINAL"],
        "updatedAt": "2026-07-30T08:00:00Z",
    }
    if check_digest is not None:
        record["completionCheck"] = {"checkId": "done-check", "checkDigest": check_digest}
    return record


def _follow_up_register(*, status: str = "SCHEDULED", current_scope_impact: str = "none") -> dict:
    item = {
        "id": "FU-01",
        "title": "Deferred documentation polish",
        "owner": {"id": "release-lead"},
        "status": status,
        "source": {
            "requirementIds": ["R-1"],
            "acceptanceIds": ["AC-1"],
            "outOfScopeReason": "Outside current release boundary.",
        },
        "targetRelease": "next",
        "currentScopeImpact": current_scope_impact,
        "closureEvidence": {"requiredEvidenceIds": ["EV-FOLLOWUP"], "requiredArtifacts": []},
        "reason": "scheduled outside current scope",
    }
    if status == "CLOSED":
        item["closure"] = {
            "status": "PASS",
            "evidenceIds": ["EV-FOLLOWUP"],
            "artifacts": [],
            "verifier": {"id": "reviewer"},
            "reason": "closed",
            "closedAt": "2026-07-30T09:30:00Z",
        }
    return {
        "schemaVersion": "agent-follow-up-register.v1",
        "lineage": {
            "runId": "run",
            "packageId": "package",
            "planRevision": 1,
            "planDigest": "0" * 64,
            "sourceRevision": "source",
        },
        "items": [item],
        "updatedAt": "2026-07-30T09:30:00Z",
    }


if __name__ == "__main__":
    unittest.main()

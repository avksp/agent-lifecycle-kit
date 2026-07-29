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

class WorkflowFinalizationTests(unittest.TestCase):
    def test_finalize_run_writes_proof_and_completes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["status"] = "ACCEPTED"
            state["tasks"][0]["attempt"] = 1
            state["tasks"][0]["review"] = {"path": "tasks/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
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
            state["tasks"][0]["review"] = {"path": "tasks/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
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
            state["tasks"][0]["review"] = {"path": "tasks/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
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
            state["tasks"][0]["review"] = {"path": "tasks/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
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

    def test_finalize_run_rejects_final_audit_plan_digest_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["status"] = "ACCEPTED"
            state["tasks"][0]["attempt"] = 1
            state["tasks"][0]["review"] = {"path": "tasks/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
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
            state["tasks"][0]["review"] = {"path": "tasks/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
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
            state["tasks"][0]["review"] = {"path": "tasks/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
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


if __name__ == "__main__":
    unittest.main()

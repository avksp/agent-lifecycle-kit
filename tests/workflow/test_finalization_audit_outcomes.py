"""Closing-only finalization refuses before consuming evidence without native authority."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest, write_json_create
from agent_lifecycle.contracts.persistence import prepared_artifact_identity
from agent_lifecycle.contracts.workflow_finalization_types import (
    FinalAuditOutcome,
    FinalAuditOutcomeBody,
    FinalAuditOutcomeValidation,
)
from agent_lifecycle.workflow.finalization import apply_final_audit_outcome, finalize_run
from tests.contracts.test_workflow_state_schemas import _state
from tests.workflow.helpers import _final_audit, _write_state
from tests.workflow.test_closing_policy import _context


class ClosingFinalizationTests(unittest.TestCase):
    def test_applied_accepted_outcome_matches_typed_body_and_canonical_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            audit = {**_final_audit(), "runId": "run", "packageId": "package", "sourceRevision": "source"}
            write_json_create(root / "final/audit.json", audit)
            with patch("agent_lifecycle.workflow.finalization.now_iso", return_value="2026-10-23T00:00:00Z"):
                payload = apply_final_audit_outcome(
                    state_path,
                    operation_id="accepted-outcome",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="final/audit.json",
                    verdict="ACCEPTED",
                    reason="reviewed",
                )
            validation_body = {
                "schemaVersion": "agent-final-audit-outcome-validation.v1",
                "status": "PASS",
                "verdict": "ACCEPTED",
                "taskIds": [],
                "findingIds": [],
                "blockers": [],
            }
            validation: FinalAuditOutcomeValidation = {
                "schemaVersion": "agent-final-audit-outcome-validation.v1",
                "status": "PASS",
                "verdict": "ACCEPTED",
                "taskIds": [],
                "findingIds": [],
                "blockers": [],
                "validationDigest": canonical_digest(validation_body),
            }
            body: FinalAuditOutcomeBody = {
                "schemaVersion": "agent-final-audit-outcome.v1",
                "status": "PASS",
                "verdict": "ACCEPTED",
                "runId": "run",
                "packageId": "package",
                "planRevision": 1,
                "planDigest": "0" * 64,
                "sourceRevision": "source",
                "finalAudit": prepared_artifact_identity("final/audit.json", audit),
                "taskIds": [],
                "findingIds": [],
                "validation": validation,
                "blocker": None,
                "contractChangeRequest": None,
                "productionPromotionClaimed": False,
                "reason": "reviewed",
                "appliedAt": "2026-10-23T00:00:00Z",
            }
            expected: FinalAuditOutcome = {**body, "outcomeDigest": canonical_digest(body)}
            actual = json.loads(state_path.read_text(encoding="utf-8"))["finalAuditOutcome"]
            self.assertEqual(payload["phase"], "FINAL_AUDIT")
            self.assertEqual(actual.keys(), FinalAuditOutcome.__required_keys__)
            self.assertEqual(canonical_bytes(actual), canonical_bytes(expected))

    def test_missing_or_malformed_outcome_fields_preserve_state_and_error_codes(self) -> None:
        values: tuple[dict[str, str] | None, ...] = (None, {})
        for value in values:
            with self.subTest(findings=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state_path = _write_state(root, phase="FINAL_AUDIT")
                audit = {**_final_audit(), "runId": "run", "packageId": "package", "sourceRevision": "source"}
                if value is None:
                    audit.pop("findings")
                else:
                    audit["findings"] = value
                write_json_create(root / "final/audit.json", audit)
                before = state_path.read_bytes()
                with self.assertRaises(LifecycleError) as raised:
                    apply_final_audit_outcome(
                        state_path,
                        operation_id="invalid-outcome-field",
                        expected_revision=1,
                        source_revision="source",
                        final_audit_path="final/audit.json",
                        verdict="ACCEPTED",
                        reason="invalid evidence",
                    )
                self.assertEqual(raised.exception.code, "final-audit-outcome-invalid")
                validation = raised.exception.details["validation"]
                self.assertIn({"code": "final-audit-outcome-findings-invalid"}, validation["blockers"])
                self.assertEqual(state_path.read_bytes(), before)
                self.assertFalse((root / "events.jsonl").exists())

    def test_final_outcome_and_finalize_cannot_treat_context_as_authority(self) -> None:
        state = _state()
        state["phase"] = "FINAL_AUDIT"
        state["tasks"][0]["status"] = "ACCEPTED"
        state["closingWindow"] = _context()
        before = copy.deepcopy(state)
        with (
            patch("agent_lifecycle.workflow.finalization.load_for_update", return_value=state),
            patch("agent_lifecycle.workflow.finalization.now_iso", return_value="2026-09-23T01:30:00Z"),
            patch("agent_lifecycle.workflow.finalization.read_json_object") as read,
        ):
            with self.assertRaises(LifecycleError) as outcome:
                apply_final_audit_outcome(
                    Path("state.json"),
                    operation_id="outcome",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="audit.json",
                    verdict="ACCEPTED",
                    reason="fixture",
                )
            self.assertEqual(outcome.exception.code, "closing-native-authority-required")
            with self.assertRaises(LifecycleError) as final:
                finalize_run(
                    Path("state.json"),
                    operation_id="final",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="audit.json",
                    proof_path="proof.json",
                    reason="fixture",
                )
            self.assertEqual(final.exception.code, "closing-native-authority-required")
            with self.assertRaises(LifecycleError) as rework:
                apply_final_audit_outcome(
                    Path("state.json"),
                    operation_id="rework",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="audit.json",
                    verdict="REWORK",
                    reason="fixture",
                )
            self.assertEqual(rework.exception.code, "closing-action-refused")
            read.assert_not_called()
        self.assertEqual(state, before)

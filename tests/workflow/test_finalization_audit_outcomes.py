"""Closing-only finalization refuses before consuming evidence without native authority."""

from __future__ import annotations

import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.workflow.finalization import apply_final_audit_outcome, finalize_run
from tests.contracts.test_workflow_state_schemas import _state
from tests.workflow.test_closing_policy import _context


class ClosingFinalizationTests(unittest.TestCase):
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
                    Path("state.json"), operation_id="outcome", expected_revision=1,
                    source_revision="source", final_audit_path="audit.json", verdict="ACCEPTED",
                    reason="fixture",
                )
            self.assertEqual(outcome.exception.code, "closing-native-authority-required")
            with self.assertRaises(LifecycleError) as final:
                finalize_run(
                    Path("state.json"), operation_id="final", expected_revision=1,
                    source_revision="source", final_audit_path="audit.json", proof_path="proof.json",
                    reason="fixture",
                )
            self.assertEqual(final.exception.code, "closing-native-authority-required")
            with self.assertRaises(LifecycleError) as rework:
                apply_final_audit_outcome(
                    Path("state.json"), operation_id="rework", expected_revision=1,
                    source_revision="source", final_audit_path="audit.json", verdict="REWORK",
                    reason="fixture",
                )
            self.assertEqual(rework.exception.code, "closing-action-refused")
            read.assert_not_called()
        self.assertEqual(state, before)

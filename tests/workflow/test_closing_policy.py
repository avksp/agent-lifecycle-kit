"""Pure closing scope cannot grant work or rewrite historical facts."""

from __future__ import annotations

import copy
import unittest

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.schemas import get_schema
from agent_lifecycle.contracts.workflow_state_schemas import (
    CLOSING_CONTEXT_V1,
    validate_closing_context,
    validate_workflow_state,
)
from agent_lifecycle.workflow.closing_policy import evaluate_closing_action
from tests.contracts.test_workflow_state_schemas import _state


def _context() -> dict:
    context = {
        "schemaVersion": "agent-closing-context.v1",
        "mode": "CLOSING_ONLY",
        "runId": "run",
        "packageId": "package",
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "bindingId": "binding",
        "journalIdentity": "journal",
        "closingWindowId": "window",
        "activationRevision": 1,
        "windowGrantDigest": "a" * 64,
        "authorityDecisionDigest": "b" * 64,
        "resourcePolicyEffectDigest": "c" * 64,
        "deadlineDecisionDigest": "d" * 64,
        "originalDeadlineDigest": "e" * 64,
        "originalOutcomeDigest": "f" * 64,
        "originalFinancialDigest": "1" * 64,
        "validFrom": "2026-09-23T01:00:00Z",
        "expiresAt": "2026-09-23T02:00:00Z",
        "allowedActions": ["read-evidence", "final-check", "apply-final-outcome", "finalize", "accounting-closeout"],
    }
    context["contextDigest"] = canonical_digest(context)
    return context


def _subject() -> dict:
    return {"runId": "run", "packageId": "package", "planDigest": "0" * 64,
            "sourceRevision": "source", "stateRevision": 1}


class ClosingPolicyTests(unittest.TestCase):
    def test_enumerated_scope_is_only_a_data_candidate(self) -> None:
        context = _context()
        original = copy.deepcopy(context)
        result = evaluate_closing_action(context, "finalize", "2026-09-23T01:30:00Z", _subject())
        self.assertEqual(result["disposition"], "DATA_CANDIDATE")
        for key in ("ownerAuthenticated", "nonceConsumed", "nativeStateChanged", "dispatchAuthorized", "financialAdmission"):
            self.assertIs(result[key], False)
        self.assertIs(result["requiresCurrentAuthorityResourceDeadlineAndEvidenceGates"], True)
        self.assertEqual(context, original)

    def test_task_work_and_arbitrary_actions_refuse_even_with_time_remaining(self) -> None:
        for action in ("task-start", "task-rework", "raise-cap", "run-process", "final-audit"):
            with self.subTest(action=action):
                result = evaluate_closing_action(_context(), action, "2026-09-23T01:30:00Z", _subject())
                self.assertEqual(result["disposition"], "REFUSED")
                self.assertIs(result["dispatchAuthorized"], False)

    def test_expiry_does_not_reauthorize_or_mutate_history(self) -> None:
        context = _context()
        for instant in ("2026-09-23T00:59:59Z", "2026-09-23T02:00:00Z"):
            result = evaluate_closing_action(context, "finalize", instant, _subject())
            self.assertEqual(result["reason"], "WINDOW_NOT_ACTIVE")
        self.assertEqual(context["originalOutcomeDigest"], "f" * 64)
        self.assertEqual(context["originalFinancialDigest"], "1" * 64)

    def test_active_context_is_closed_and_bound_to_state(self) -> None:
        self.assertEqual(get_schema(CLOSING_CONTEXT_V1)["$id"], CLOSING_CONTEXT_V1)
        state = _state()
        state["closingWindow"] = _context()
        self.assertIs(validate_workflow_state(state), state)
        for mutation in ("schemaVersion", "runId", "contextDigest"):
            changed = copy.deepcopy(state)
            changed["closingWindow"][mutation] = "wrong"
            with self.subTest(mutation=mutation), self.assertRaises(LifecycleError):
                validate_workflow_state(changed)
        changed = copy.deepcopy(state)
        changed["closingWindow"]["unknown"] = True
        with self.assertRaises(LifecycleError):
            validate_closing_context(changed["closingWindow"])
        changed = copy.deepcopy(state)
        changed["closingWindow"]["allowedActions"] = ["finalize", "finalize"]
        changed["closingWindow"]["contextDigest"] = canonical_digest(
            {key: value for key, value in changed["closingWindow"].items() if key != "contextDigest"}
        )
        with self.assertRaises(LifecycleError):
            validate_workflow_state(changed)

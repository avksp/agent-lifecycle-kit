from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError  # noqa: E402
from agent_lifecycle.specification import (  # noqa: E402
    validate_completion_check,
    validate_completion_check_receipt,
    validate_specification,
)


class CompletionCheckTests(unittest.TestCase):
    def test_validate_specification_accepts_optional_completion_check(self) -> None:
        result = validate_specification({
            "tier": "S2",
            "status": "FROZEN",
            "requirements": [{"id": "REQ-1"}],
            "completionCheck": _check(),
        })

        self.assertEqual(result["completionCheckId"], "done-check")
        self.assertEqual(result["completionCheckKind"], "verification")
        self.assertEqual(len(result["completionCheckDigest"]), 64)

    def test_completion_check_rejects_invalid_receipt_path(self) -> None:
        check = _check()
        check["receiptPath"] = "../final/receipt.json"

        with self.assertRaises(LifecycleError) as raised:
            validate_completion_check(check)

        self.assertEqual(raised.exception.code, "invalid-repo-path")

    def test_completion_check_receipt_passes_with_matching_lineage_and_evidence(self) -> None:
        result = validate_completion_check_receipt(_receipt("PASS"), check=_check(), state=_state())

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["checkId"], "done-check")
        self.assertEqual(result["evidenceIds"], ["EV-FINAL"])

    def test_completion_check_receipt_rejects_fail_status(self) -> None:
        with self.assertRaises(LifecycleError) as raised:
            validate_completion_check_receipt(_receipt("FAIL"), check=_check(), state=_state())

        self.assertEqual(raised.exception.code, "completion-check-not-satisfied")

    def test_completion_check_receipt_rejects_missing_required_evidence(self) -> None:
        receipt = _receipt("PASS")
        receipt["evidenceIds"] = ["EV-OTHER"]

        with self.assertRaises(LifecycleError) as raised:
            validate_completion_check_receipt(receipt, check=_check(), state=_state())

        self.assertEqual(raised.exception.code, "completion-check-evidence-missing")

    def test_external_action_completion_check_binds_existing_receipt_identity(self) -> None:
        check = _check(kind="external-action")
        state = _state()
        state["externalActionReceipt"] = {
            "path": "human/approval.json",
            "sha256": "a" * 64,
            "bytes": 100,
        }
        receipt = _receipt("PASS")
        receipt["externalActionReceipt"] = dict(state["externalActionReceipt"])

        result = validate_completion_check_receipt(receipt, check=check, state=state)

        self.assertEqual(result["checkKind"], "external-action")

    def test_external_action_completion_check_fails_without_state_receipt(self) -> None:
        check = _check(kind="external-action")
        receipt = _receipt("PASS")
        receipt["externalActionReceipt"] = {
            "path": "human/approval.json",
            "sha256": "a" * 64,
            "bytes": 100,
        }

        with self.assertRaises(LifecycleError) as raised:
            validate_completion_check_receipt(receipt, check=check, state=_state())

        self.assertEqual(raised.exception.code, "completion-check-external-action-missing")


def _state() -> dict[str, object]:
    return {
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
    }


def _check(*, kind: str = "verification") -> dict[str, object]:
    return {
        "schemaVersion": "agent-completion-check.v1",
        "checkId": "done-check",
        "kind": kind,
        "description": "Observable completion evidence for the requested outcome.",
        "receiptPath": "final/completion-check-receipt.json",
        "requiredEvidenceIds": ["EV-FINAL"],
    }


def _receipt(status: str) -> dict[str, object]:
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


if __name__ == "__main__":
    unittest.main()

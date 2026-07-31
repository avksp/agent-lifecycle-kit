from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.runner import (
    build_attempt_snapshot_receipt,
    require_attempt_snapshot_receipt_pass,
    validate_attempt_snapshot_receipt,
)


class AttemptSnapshotReceiptTests(unittest.TestCase):
    def test_snapshot_receipt_records_state_digest(self) -> None:
        snapshot = {"runnerRevision": 3, "status": "VALIDATING", "stateDigest": "a" * 64}
        receipt = build_attempt_snapshot_receipt(
            lineage=_lineage(),
            task_id="WS22-01",
            attempt=1,
            action="snapshot",
            snapshot=snapshot,
            evidence_ids=["ev-snapshot"],
        )

        validation = validate_attempt_snapshot_receipt(receipt, expected_lineage=_lineage(), task_id="WS22-01", attempt=1)

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(receipt["snapshotDigest"], canonical_digest(snapshot))
        self.assertFalse(receipt["productionPromotionClaimed"])
        self.assertEqual(require_attempt_snapshot_receipt_pass(validation), validation)

    def test_restore_abandon_and_select_metadata_are_validated(self) -> None:
        snapshot_digest = "b" * 64
        restore = build_attempt_snapshot_receipt(
            lineage=_lineage(),
            task_id="WS22-01",
            attempt=2,
            action="restore",
            restore_source_digest=snapshot_digest,
        )
        abandon = build_attempt_snapshot_receipt(
            lineage=_lineage(),
            task_id="WS22-01",
            attempt=2,
            action="abandon",
            abandon_reason="attempt exceeded write scope",
        )
        selected = build_attempt_snapshot_receipt(
            lineage=_lineage(),
            task_id="WS22-01",
            attempt=2,
            action="select",
            selected_attempt=1,
            selected_attempt_digest=snapshot_digest,
        )

        self.assertEqual(validate_attempt_snapshot_receipt(restore)["status"], "PASS")
        self.assertEqual(validate_attempt_snapshot_receipt(abandon)["status"], "PASS")
        self.assertEqual(validate_attempt_snapshot_receipt(selected)["status"], "PASS")

    def test_select_without_digest_is_not_a_required_pass(self) -> None:
        receipt = build_attempt_snapshot_receipt(
            lineage=_lineage(),
            task_id="WS22-01",
            attempt=2,
            action="select",
            selected_attempt=1,
        )

        validation = validate_attempt_snapshot_receipt(receipt)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("attempt-selected-digest-missing", {item["code"] for item in validation["blockers"]})
        with self.assertRaises(LifecycleError):
            require_attempt_snapshot_receipt_pass(validation)


def _lineage() -> dict:
    return {
        "runId": "run-22",
        "packageId": "release-1-12",
        "planRevision": 5,
        "planDigest": "0" * 64,
        "sourceRevision": "1" * 40,
    }


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from agent_lifecycle.workflow import build_worker_lease_receipt, classify_lease_status, validate_worker_lease_receipt


class WorkerLeaseReceiptTests(unittest.TestCase):
    def test_active_expired_and_completed_leases_are_classified(self) -> None:
        active = _receipt(observed_at="2026-07-31T10:04:00Z")
        expired = _receipt(observed_at="2026-07-31T10:06:00Z")
        completed = _receipt(observed_at="2026-07-31T10:06:00Z", completed_at="2026-07-31T10:03:00Z")

        self.assertEqual(active["leaseStatus"], "active")
        self.assertEqual(expired["leaseStatus"], "expired")
        self.assertEqual(completed["leaseStatus"], "completed")
        self.assertEqual(validate_worker_lease_receipt(active, expected_lineage=_lineage())["status"], "PASS")
        self.assertEqual(validate_worker_lease_receipt(expired)["status"], "PASS")
        self.assertEqual(validate_worker_lease_receipt(completed)["status"], "PASS")

    def test_status_mismatch_is_rejected(self) -> None:
        receipt = _receipt(observed_at="2026-07-31T10:06:00Z")
        receipt["leaseStatus"] = "active"

        validation = validate_worker_lease_receipt(receipt)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("worker-lease-status-mismatch", {item["code"] for item in validation["blockers"]})

    def test_classifier_is_deterministic(self) -> None:
        self.assertEqual(
            classify_lease_status(expires_at="2026-07-31T10:05:00Z", observed_at="2026-07-31T10:05:00Z"),
            "active",
        )
        self.assertEqual(
            classify_lease_status(expires_at="2026-07-31T10:05:00Z", observed_at="2026-07-31T10:05:01Z"),
            "expired",
        )


def _receipt(*, observed_at: str, completed_at: str | None = None) -> dict:
    return build_worker_lease_receipt(
        lineage=_lineage(),
        worker_id="worker-1",
        lease_id="lease-1",
        task_id="WS22-02",
        acquired_at="2026-07-31T10:00:00Z",
        expires_at="2026-07-31T10:05:00Z",
        observed_at=observed_at,
        heartbeat_at="2026-07-31T10:02:00Z",
        completed_at=completed_at,
    )


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

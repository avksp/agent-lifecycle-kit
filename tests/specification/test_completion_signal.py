from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError  # noqa: E402
from agent_lifecycle.specification import validate_completion_signal  # noqa: E402


class CompletionSignalTests(unittest.TestCase):
    def test_completion_signal_passes_with_matching_lineage(self) -> None:
        result = validate_completion_signal(_signal("PASS"), state=_state())

        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["waived"])

    def test_completion_signal_accepts_explicit_waiver_with_evidence(self) -> None:
        signal = _signal("WAIVED")
        signal["waiver"] = {
            "reason": "external deployment action remains operator-owned",
            "approvedBy": "release-lead",
            "evidenceIds": ["EV-WAIVER"],
        }

        result = validate_completion_signal(signal, state=_state())

        self.assertEqual(result["signalStatus"], "WAIVED")
        self.assertTrue(result["waived"])

    def test_completion_signal_rejects_lineage_drift(self) -> None:
        signal = _signal("PASS")
        signal["planDigest"] = "9" * 64

        with self.assertRaises(LifecycleError) as raised:
            validate_completion_signal(signal, state=_state())

        self.assertEqual(raised.exception.code, "completion-signal-lineage-mismatch")

    def test_completion_signal_rejects_fail_status(self) -> None:
        with self.assertRaises(LifecycleError) as raised:
            validate_completion_signal(_signal("FAIL"), state=_state())

        self.assertEqual(raised.exception.code, "completion-signal-not-ready")

    def test_completion_signal_rejects_waiver_without_evidence(self) -> None:
        signal = _signal("WAIVED")
        signal["waiver"] = {"reason": "operator action", "approvedBy": "lead", "evidenceIds": []}

        with self.assertRaises(LifecycleError) as raised:
            validate_completion_signal(signal, state=_state())

        self.assertEqual(raised.exception.code, "invalid-completion-signal-waiver")


def _state() -> dict[str, object]:
    return {
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
    }


def _signal(status: str) -> dict[str, object]:
    return {
        "schemaVersion": "agent-completion-signal.v1",
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "status": status,
        "evidenceIds": ["EV-FINAL"],
        "verifier": {"id": "final-auditor", "independent": True},
        "completedAt": "2026-07-29T08:00:00Z",
    }


if __name__ == "__main__":
    unittest.main()

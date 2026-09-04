from __future__ import annotations

import sys
import unittest

from agent_lifecycle.adapter_sessions.process import run_process
from agent_lifecycle.reporting.execution_resources import (
    build_execution_resource_report,
    validate_execution_resource_report,
)


class ExecutionResourceReportTests(unittest.TestCase):
    def test_report_aggregates_receipts_without_output(self) -> None:
        result = run_process(
            [sys.executable, "-c", "print('private output')"],
            env={},
            timeout_seconds=5,
            operation_id="op-1",
            attempt_id="attempt-1",
            adapter_id="fixture",
        )

        report = build_execution_resource_report([result["processReceipt"]], lineage={"operationId": "op-1"})
        validation = validate_execution_resource_report(report)

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(validation["status"], "PASS")
        self.assertNotIn("private output", str(report))
        self.assertEqual(report["workflowEconomics"]["metrics"]["toolCalls"]["value"], 1)
        self.assertEqual(report["workflowEconomics"]["metrics"]["elapsedWallMs"]["status"], "MEASURED")
        self.assertEqual(report["workflowEconomics"]["metrics"]["modelInputTokens"]["status"], "UNAVAILABLE")

    def test_multiple_receipts_need_an_explicit_enclosing_wall(self) -> None:
        first = run_process(
            [sys.executable, "-c", "pass"],
            env={},
            timeout_seconds=5,
            operation_id="op-1",
            attempt_id="attempt-1",
            adapter_id="fixture",
        )["processReceipt"]
        second = run_process(
            [sys.executable, "-c", "pass"],
            env={},
            timeout_seconds=5,
            operation_id="op-2",
            attempt_id="attempt-1",
            adapter_id="fixture",
        )["processReceipt"]

        unavailable = build_execution_resource_report([first, second])
        measured = build_execution_resource_report(
            [first, second],
            enclosing_elapsed_wall={"status": "MEASURED", "value": 50},
        )

        self.assertEqual(unavailable["workflowEconomics"]["metrics"]["elapsedWallMs"]["status"], "UNAVAILABLE")
        self.assertEqual(measured["workflowEconomics"]["metrics"]["elapsedWallMs"]["value"], 50)
        self.assertEqual(measured["workflowEconomics"]["metrics"]["toolCalls"]["value"], 2)

    def test_cleanup_blocker_is_not_hidden(self) -> None:
        receipt = {
            "schemaVersion": "agent-process-execution-receipt.v1",
            "status": "BLOCKED",
            "operationId": "op-1",
            "attemptId": "attempt-1",
            "adapterId": "fixture",
            "commandIdentityHash": "a" * 64,
            "processIdentityHash": None,
            "groupIdentityHash": None,
            "timing": {"clock": "monotonic", "elapsedMs": 1, "availability": "ATTESTED"},
            "resources": {
                "cpuMs": {"value": None, "unit": "ms", "availability": "UNAVAILABLE", "source": "none"},
                "peakMemoryMb": {"value": None, "unit": "MB", "availability": "UNAVAILABLE", "source": "none"},
                "processCount": {"value": None, "unit": "processes", "availability": "UNAVAILABLE", "source": "none"},
            },
            "cleanup": {"status": "BLOCKED"},
            "exitCode": None,
            "timedOut": True,
            "cancelled": False,
            "retry": {"attempted": False, "count": 0, "reason": None},
            "limits": {},
            "blockers": [{"code": "adapter-process-cleanup-unverified"}],
            "rawOutputStored": False,
            "secretsStored": False,
            "modelCallsStarted": False,
            "networkCallsStarted": False,
            "productionPromotionClaimed": False,
        }
        from agent_lifecycle.contracts import canonical_digest

        receipt["receiptDigest"] = canonical_digest(
            {key: value for key, value in receipt.items() if key != "receiptDigest"}
        )
        report = build_execution_resource_report([receipt])

        self.assertEqual(report["status"], "BLOCKED")
        self.assertTrue(report["blockers"])


if __name__ == "__main__":
    unittest.main()

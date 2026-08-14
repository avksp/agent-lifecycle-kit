from __future__ import annotations

import sys
import unittest

from agent_lifecycle.adapter_sessions.process import run_process
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.workflow.model_usage import (
    bounded_process_retry_decision,
    process_execution_receipt_projection,
    validate_task_process_execution_receipt,
)


class ProcessExecutionIntegrationTests(unittest.TestCase):
    def test_task_lineage_can_consume_process_receipt_projection(self) -> None:
        result = run_process(
            [sys.executable, "-c", "print('safe')"],
            env={},
            timeout_seconds=5,
            operation_id="operation-1",
            attempt_id="attempt-1",
            adapter_id="fixture",
        )
        task = {"id": "WS-01", "attempt": 1}

        validation = validate_task_process_execution_receipt(
            task,
            result["processReceipt"],
            operation_id="operation-1",
            attempt_id="attempt-1",
        )
        projection = process_execution_receipt_projection(result["processReceipt"])

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(projection["receiptDigest"], result["processReceipt"]["receiptDigest"])
        self.assertNotIn("safe", str(projection))

    def test_cleanup_blocker_is_rejected_for_task_acceptance(self) -> None:
        result = run_process(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            env={},
            timeout_seconds=0.05,
            operation_id="operation-2",
            attempt_id="attempt-2",
            adapter_id="fixture",
        )
        task = {"id": "WS-01", "attempt": 2}

        with self.assertRaises(LifecycleError):
            validate_task_process_execution_receipt(task, result["processReceipt"], operation_id="operation-2", attempt_id="attempt-2")

    def test_timeout_has_one_bounded_retry_decision(self) -> None:
        result = run_process(
            [sys.executable, "-c", "import time; time.sleep(1)"],
            env={},
            timeout_seconds=0.05,
            operation_id="retry-op",
            attempt_id="attempt-1",
        )

        decision = bounded_process_retry_decision(result["processReceipt"], attempt=0, max_retries=1)

        self.assertEqual(decision["decision"], "RETRY")
        self.assertTrue(decision["retry"])

    def test_cleanup_failure_blocks_retry(self) -> None:
        decision = bounded_process_retry_decision(
            {"status": "FAIL", "timedOut": True, "cleanup": {"status": "BLOCKED"}},
            attempt=0,
            max_retries=1,
        )

        self.assertEqual(decision["decision"], "BLOCKED")
        self.assertFalse(decision["retry"])


if __name__ == "__main__":
    unittest.main()

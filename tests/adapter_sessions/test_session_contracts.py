from __future__ import annotations

import unittest

from agent_lifecycle.adapter_sessions.contracts import (
    build_adapter_session_receipt,
    build_launch_receipt,
    build_resume_receipt,
)


class AdapterSessionContractTests(unittest.TestCase):
    def test_session_without_task_does_not_claim_lifecycle_coverage(self) -> None:
        receipt = build_adapter_session_receipt(
            status="WAITING_FOR_TASK",
            session_id="session-1",
            adapter_id="codex",
            mode="INTERACTIVE",
            launch_profile={"status": "WRAPPER_ONLY", "shell": False},
        )

        self.assertEqual(receipt["schemaVersion"], "agent-adapter-session-receipt.v1")
        self.assertFalse(receipt["managedWorkflow"])
        self.assertFalse(receipt["lifecycleCoverageClaimed"])
        self.assertFalse(receipt["secretsWritten"])

    def test_launch_receipt_is_redacted_and_shell_false(self) -> None:
        receipt = build_launch_receipt(
            status="PASS",
            adapter_id="codex",
            session_id="session-1",
            launch_mode="interactive",
            argv=["/bin/echo", "ok"],
            timeout_seconds=1.0,
            env={"includedNames": ["SAFE_TOKEN"], "valuesRedacted": True, "secretValuesStored": False},
            exit_code=0,
            timed_out=False,
            stdout_tail="ok",
            stderr_tail="",
            host_launch_started=True,
        )

        self.assertFalse(receipt["shell"])
        self.assertTrue(receipt["env"]["valuesRedacted"])
        self.assertFalse(receipt["modelCallsStarted"])

    def test_launch_receipt_records_actual_output_redaction(self) -> None:
        local_path = "/" + "Users/operator/private.log"
        receipt = build_launch_receipt(
            status="PASS",
            adapter_id="codex",
            session_id="session-1",
            launch_mode="interactive",
            argv=["codex"],
            timeout_seconds=1.0,
            env={"includedNames": [], "valuesRedacted": True, "secretValuesStored": False},
            exit_code=0,
            timed_out=False,
            stdout_tail="safe output",
            stderr_tail=f"Authorization: Bearer secret-value {local_path}",
        )

        self.assertFalse(receipt["stdout"]["redacted"])
        self.assertTrue(receipt["stderr"]["redacted"])
        self.assertNotIn("secret-value", receipt["stderr"]["tail"])
        self.assertNotIn(local_path, receipt["stderr"]["tail"])

    def test_resume_receipt_blocks_lineage_mismatch(self) -> None:
        receipt = build_resume_receipt(
            session_id="session-1",
            adapter_id="codex",
            expected_identity={"runId": "expected"},
            actual_identity={"runId": "actual"},
            blockers=[{"code": "adapter-session-lineage-mismatch"}],
        )

        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertEqual(receipt["lineageStatus"], "FAIL")
        self.assertFalse(receipt["lifecycleCoverageClaimed"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from agent_lifecycle.contracts.process_execution_schemas import (
    build_process_execution_receipt,
    command_identity_hash,
    validate_process_execution_receipt,
)


class ProcessExecutionSchemaTests(unittest.TestCase):
    def test_receipt_is_digest_bound_and_redacted(self) -> None:
        receipt = build_process_execution_receipt(
            status="PASS",
            operation_id="op-1",
            attempt_id="attempt-1",
            adapter_id="fixture",
            command_identity_hash=command_identity_hash(["python", "-c", "secret"]),
            process_identity_hash="a" * 64,
            group_identity_hash="b" * 64,
            elapsed_ms=12,
            cpu_ms={"value": 3.0, "availability": "ATTESTED", "source": "procfs"},
            peak_memory_mb={"value": 4.0, "availability": "ATTESTED", "source": "procfs"},
            process_count={"value": 1, "availability": "ATTESTED", "source": "procfs-group"},
            cleanup={"status": "PASS", "attestation": "ATTESTED"},
            exit_code=0,
            timed_out=False,
            cancelled=False,
        )

        validation = validate_process_execution_receipt(receipt)

        self.assertEqual(validation["status"], "PASS")
        self.assertNotIn("argv", receipt)
        self.assertFalse(receipt["rawOutputStored"])

    def test_tampering_and_raw_fields_fail_closed(self) -> None:
        receipt = build_process_execution_receipt(
            status="PASS",
            operation_id="op-1",
            attempt_id="attempt-1",
            adapter_id="fixture",
            command_identity_hash="a" * 64,
            process_identity_hash=None,
            group_identity_hash=None,
            elapsed_ms=0,
            cpu_ms={"value": None, "availability": "UNAVAILABLE", "source": "none"},
            peak_memory_mb={"value": None, "availability": "UNAVAILABLE", "source": "none"},
            process_count={"value": None, "availability": "UNAVAILABLE", "source": "none"},
            cleanup={"status": "PASS"},
            exit_code=0,
            timed_out=False,
            cancelled=False,
        )
        receipt["argv"] = ["secret"]
        receipt["timing"]["elapsedMs"] = 99

        validation = validate_process_execution_receipt(receipt)

        self.assertEqual(validation["status"], "FAIL")
        self.assertTrue({item["code"] for item in validation["blockers"]} & {"process-execution-raw-field", "process-execution-digest-mismatch"})


if __name__ == "__main__":
    unittest.main()

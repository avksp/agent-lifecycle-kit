from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.metrics.audit_samples import (  # noqa: E402
    build_audit_sample,
    build_audit_samples,
    validate_audit_sample,
)


class AuditSampleTests(unittest.TestCase):
    def test_projection_keeps_structure_and_drops_sensitive_values(self) -> None:
        sample = build_audit_sample(
            {
                "schemaVersion": "agent-task-result.v2",
                "operationId": "op-1",
                "runId": "run-1",
                "packageId": "package",
                "taskId": "task-1",
                "taskShape": "feature",
                "prompt": "Requirements: do the work\nSecret: sk-abcdefghijklmnopqrstuv",
                "provider": "private-provider",
                "modelName": "private-model",
                "status": "PASS",
                "usage": {"inputTokens": 100, "outputTokens": 20, "billableTokens": 120, "wallSeconds": 4, "toolCalls": 2},
            }
        )

        self.assertEqual(sample["request"]["promptBytes"], len("Requirements: do the work\nSecret: sk-abcdefghijklmnopqrstuv".encode()))
        self.assertTrue(sample["request"]["sectionFlags"]["requirements"])
        self.assertNotIn("Requirements: do the work", str(sample))
        self.assertNotIn("private-provider", str(sample))
        self.assertNotIn("sk-abcdefghijklmnopqrstuv", str(sample))
        self.assertFalse(sample["rawPromptStored"])
        self.assertEqual(validate_audit_sample(sample)["status"], "PASS")

    def test_review_usage_and_process_receipts_are_combined(self) -> None:
        bundle = {
            "operationId": "op-2",
            "runId": "run-2",
            "packageId": "package",
            "taskId": "task-2",
            "reviewReceipt": {
                "schemaVersion": "agent-review-mesh-result.v1",
                "status": "PASS",
                "phase": "implementation-audit",
                "subject": {"taskShape": "bugfix"},
                "reviewer": {"role": "auditor", "modelClass": "strong-reasoning", "modelIdentityHash": "a" * 64},
                "findings": [{"id": "F1", "severity": "LOW", "status": "accepted"}],
                "independence": {"status": "INDEPENDENT"},
            },
            "usageReceipt": {
                "schemaVersion": "agent-lifecycle-model-usage-receipt.v1",
                "usage": {"inputTokens": 40, "outputTokens": 10, "billableTokens": 50, "wallSeconds": 3, "toolCalls": 1},
                "attestation": {"status": "ATTESTED"},
            },
            "processReceipt": {
                "schemaVersion": "agent-process-execution-receipt.v1",
                "timing": {"elapsedMs": 3000},
                "resources": {
                    "cpuMs": {"value": 100, "availability": "ATTESTED"},
                    "peakMemoryMb": {"value": 20, "availability": "ATTESTED"},
                    "processCount": {"value": 1, "availability": "ATTESTED"},
                },
                "cleanup": {"status": "PASS"},
                "retry": {"count": 1},
                "timedOut": False,
            },
        }

        sample = build_audit_sample(bundle)

        self.assertEqual(sample["lineage"]["taskId"], "task-2")
        self.assertEqual(sample["review"]["findingCount"], 1)
        self.assertEqual(sample["usage"]["confidence"], "ATTESTED")
        self.assertEqual(sample["process"]["retryCount"], 1)
        self.assertEqual(sample["attestation"]["overall"], "ATTESTED")

    def test_batch_fails_closed_for_non_object_receipts(self) -> None:
        batch = build_audit_samples([{"status": "PASS"}, "not-an-object"])  # type: ignore[list-item]

        self.assertEqual(batch["status"], "FAIL")
        self.assertEqual(batch["sourceCount"], 2)
        self.assertTrue(batch["blockers"])


if __name__ == "__main__":
    unittest.main()

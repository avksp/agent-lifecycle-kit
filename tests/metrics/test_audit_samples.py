from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import canonical_digest  # noqa: E402
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

        self.assertEqual(
            sample["request"]["promptBytes"],
            len(b"Requirements: do the work\nSecret: sk-abcdefghijklmnopqrstuv"),
        )
        self.assertTrue(sample["request"]["sectionFlags"]["requirements"])
        self.assertNotIn("Requirements: do the work", str(sample))
        self.assertNotIn("private-provider", str(sample))
        self.assertNotIn("sk-abcdefghijklmnopqrstuv", str(sample))
        self.assertFalse(sample["rawPromptStored"])
        self.assertEqual(sample["statisticalProvenance"]["sampleIdentity"], sample["sampleId"])
        self.assertEqual(sample["statisticalProvenance"]["sourceClass"], "UNDECLARED")
        self.assertFalse(sample["statisticalProvenance"]["independenceClaimed"])
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
        self.assertEqual(sample["statisticalProvenance"]["producerIdentityStatus"], "DECLARED")

    def test_statistical_provenance_is_bound_to_current_source(self) -> None:
        sample = build_audit_sample(
            {
                "operationId": "op-stat",
                "runId": "run-stat",
                "sourceClass": "INDEPENDENT_HOLDOUT",
                "derivation": "tracked-fixture",
                "sourceRevision": "source-revision-1",
                "sourceLineageDigest": "a" * 64,
                "producerClass": "independent-reviewer",
                "producerIdentityHash": "b" * 64,
                "status": "PASS",
            }
        )

        provenance = sample["statisticalProvenance"]
        self.assertEqual(provenance["sourceRevision"], "source-revision-1")
        self.assertEqual(provenance["sourceLineageDigest"], "a" * 64)
        self.assertTrue(provenance["independenceClaimed"])

    def test_legacy_sample_without_statistical_provenance_remains_readable(self) -> None:
        sample = build_audit_sample({"operationId": "legacy-op", "status": "PASS"})
        legacy = deepcopy(sample)
        legacy.pop("statisticalProvenance")
        legacy["sampleDigest"] = canonical_digest(
            {key: value for key, value in legacy.items() if key != "sampleDigest"}
        )

        self.assertEqual(validate_audit_sample(legacy)["status"], "PASS")

    def test_provider_like_route_names_are_neutralized(self) -> None:
        for route in ("codex-gpt5-turbo", "openai-general-4", "provider-code-model"):
            with self.subTest(route=route):
                sample = build_audit_sample({"routeClass": route, "status": "PASS"})
                self.assertEqual(sample["request"]["routeClass"], "external-neutral")
                self.assertNotIn(route, str(sample))

    def test_provider_like_review_model_class_is_neutralized(self) -> None:
        sample = build_audit_sample(
            {
                "reviewReceipt": {
                    "schemaVersion": "agent-review-mesh-result.v1",
                    "status": "PASS",
                    "reviewer": {"role": "auditor", "modelClass": "provider-code-model"},
                    "findings": [],
                    "independence": {"status": "INDEPENDENT"},
                }
            }
        )

        self.assertEqual(sample["review"]["modelRouteClass"], "external-neutral")
        self.assertNotIn("provider-code-model", str(sample))

    def test_batch_fails_closed_for_non_object_receipts(self) -> None:
        batch = build_audit_samples([{"status": "PASS"}, "not-an-object"])  # type: ignore[list-item]

        self.assertEqual(batch["status"], "FAIL")
        self.assertEqual(batch["sourceCount"], 2)
        self.assertTrue(batch["blockers"])


if __name__ == "__main__":
    unittest.main()

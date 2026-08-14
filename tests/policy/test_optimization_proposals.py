from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError  # noqa: E402
from agent_lifecycle.metrics.audit_optimization import build_audit_optimization_report  # noqa: E402
from agent_lifecycle.metrics.audit_samples import build_audit_sample  # noqa: E402
from agent_lifecycle.policy.proposals import (  # noqa: E402
    apply_optimization_proposal,
    build_optimization_proposal,
)


class OptimizationProposalTests(unittest.TestCase):
    def test_recommendation_requires_explicit_approval(self) -> None:
        recommendation = _report()["recommendation"]
        proposal = build_optimization_proposal(recommendation)

        self.assertEqual(proposal["status"], "PASS")
        self.assertFalse(proposal["applyAllowed"])
        self.assertIn("optimization-explicit-approval-required", {item["code"] for item in proposal["refusalReasons"]})

    def test_approved_proposal_writes_new_profile_artifact(self) -> None:
        recommendation = _report()["recommendation"]
        proposal = build_optimization_proposal(recommendation, approved=True, target_revision="profile-rev-2")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "audit-optimization-profile.json"
            result = apply_optimization_proposal(proposal, output)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(payload["schemaVersion"], "agent-audit-optimization-applied-profile.v1")
        self.assertTrue(payload["changes"])
        self.assertFalse(payload["productionPromotionClaimed"])

    def test_frozen_plan_and_plan_artifacts_are_never_writable(self) -> None:
        recommendation = _report()["recommendation"]
        proposal = build_optimization_proposal(recommendation, approved=True, frozen_plan=True)

        self.assertFalse(proposal["applyAllowed"])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(LifecycleError):
                apply_optimization_proposal(proposal, Path(directory) / "plan.manifest.json")

    def test_tampered_proposal_digest_is_rejected(self) -> None:
        proposal = build_optimization_proposal(_report()["recommendation"], approved=True)
        proposal["candidateChanges"][0]["after"] = 100000

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(LifecycleError):
                apply_optimization_proposal(proposal, Path(directory) / "profile.json")


def _report() -> dict[str, object]:
    samples = [build_audit_sample(_receipt(index)) for index in range(3)]
    return build_audit_optimization_report(
        samples,
        candidate_profiles=[{
            "profileId": "safe",
            "taskShape": "feature",
            "qualityFloor": "standard",
            "routeClass": "standard",
            "packetTokenLimit": 12000,
            "reviewerCountHint": 2,
            "timeoutSeconds": 900,
            "retryLimit": 1,
            "holdoutTasks": [
                {"taskId": f"task-{index}", "qualityPass": True, "billableTokens": 400, "wallSeconds": 10}
                for index in range(3)
            ],
        }],
        current_profile={"packetTokenLimit": 10000},
    )


def _receipt(index: int) -> dict[str, object]:
    return {
        "operationId": f"operation-{index}",
        "runId": f"run-{index}",
        "packageId": "release-1-70",
        "taskId": f"task-{index}",
        "taskShape": "feature",
        "reviewReceipt": {
            "schemaVersion": "agent-review-mesh-result.v1",
            "status": "PASS",
            "findings": [],
            "independence": {"status": "INDEPENDENT"},
            "reviewer": {"role": "independent-reviewer", "modelClass": "standard"},
        },
        "usageReceipt": {
            "usage": {"inputTokens": 1000, "outputTokens": 500, "billableTokens": 1500, "wallSeconds": 12},
            "attestation": {"status": "ATTESTED"},
        },
        "processReceipt": {
            "resources": {
                "cpuMs": {"value": 120, "availability": "ATTESTED"},
                "peakMemoryMb": {"value": 64, "availability": "ATTESTED"},
                "processCount": {"value": 1, "availability": "ATTESTED"},
            },
            "timing": {"elapsedMs": 12000},
            "retry": {"count": 0},
            "timedOut": False,
        },
        "outcomeReceipt": {"status": "ACCEPTED"},
    }


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from pathlib import Path

from agent_lifecycle.benchmarks.contracts import load_suite, load_task
from agent_lifecycle.benchmarks.oracles import _schema_versions, evaluate_oracle
from agent_lifecycle.contracts import LifecycleError

ROOT = Path(__file__).resolve().parents[2]
SUITE = load_suite(ROOT / "benchmarks/reference-tasks/manifest.json")
DIGEST = "1" * 64


class ReferenceTaskOracleTests(unittest.TestCase):
    def test_all_five_oracles_accept_matching_independent_evidence(self) -> None:
        submissions = {
            "rt01-planning": _submission(
                "rt01-planning",
                {
                    "planValidation": {"schemaVersion": "agent-plan-validation.v1", "status": "FROZEN"},
                    "completenessValidation": {
                        "schemaVersion": "agent-plan-completeness-validation.v1",
                        "status": "PASS",
                        "blockers": [],
                    },
                    "acceptanceValidation": {
                        "schemaVersion": "agent-acceptance-checklist-validation.v1",
                        "status": "PASS",
                        "missingInMarkdown": [],
                        "extraInMarkdown": [],
                        "linkMismatches": [],
                    },
                },
            ),
            "rt02-architecture-review": _submission(
                "rt02-architecture-review",
                {
                    "reviewMeshQuorum": {
                        "schemaVersion": "agent-review-mesh-quorum-receipt.v1",
                        "status": "PASS",
                        "requiredRolesSatisfied": True,
                        "quorumSatisfied": True,
                        "blockingFindingsUnresolved": False,
                        "blockers": [],
                    }
                },
            ),
            "rt03-bug-forensics": _submission(
                "rt03-bug-forensics",
                {
                    "reproductionReceipt": {
                        "schemaVersion": "agent-bug-reproduction-receipt.v1",
                        "status": "PASS",
                        "receiptDigest": DIGEST,
                    },
                    "regressionProof": {
                        "schemaVersion": "agent-regression-proof-receipt.v1",
                        "status": "PASS",
                        "reproductionReceiptDigest": DIGEST,
                        "proofDigest": DIGEST,
                    },
                    "regressionProofValidation": {
                        "schemaVersion": "agent-regression-proof-receipt-validation.v1",
                        "status": "PASS",
                        "proofStatus": "PASS",
                        "proofDigest": DIGEST,
                        "blockers": [],
                    },
                },
            ),
            "rt04-s1-managed-task": _submission(
                "rt04-s1-managed-task",
                {
                    "taskResult": {
                        "schemaVersion": "agent-task-result.v2",
                        "blocker": None,
                        "contractChangeRequest": None,
                        "itemOutcomes": [{"id": "item", "status": "COMPLETE"}],
                        "commands": [{"command": "test", "status": "PASS"}],
                    },
                    "implementationAuditValidation": {
                        "schemaVersion": "agent-implementation-audit-report-validation.v1",
                        "status": "PASS",
                        "verdict": "ACCEPTED",
                        "blockers": [],
                    },
                },
            ),
            "rt05-s2-evidence-task": _submission(
                "rt05-s2-evidence-task",
                {
                    "finalProof": {
                        "schemaVersion": "agent-run-final-proof.v1",
                        "semanticStatus": "READY_FOR_FINALIZATION",
                        "productionPromotionClaimed": False,
                        "acceptedTasks": [{"id": "WS-1"}],
                    },
                    "finalImplementationAuditValidation": {
                        "schemaVersion": "agent-final-implementation-audit-validation.v1",
                        "status": "PASS",
                        "blockers": [],
                    },
                    "proofIntegrityValidation": {
                        "schemaVersion": "agent-proof-integrity-validation.v1",
                        "status": "PASS",
                        "blockers": [],
                    },
                },
            ),
        }
        for task_id, submission in submissions.items():
            with self.subTest(task_id=task_id):
                task = load_task(SUITE, task_id)
                self.assertEqual(evaluate_oracle(task.oracle, submission)["status"], "PASS")

    def test_quorum_oracle_rejects_unresolved_blocking_findings(self) -> None:
        task = load_task(SUITE, "rt02-architecture-review")
        submission = _submission(
            "rt02-architecture-review",
            {
                "reviewMeshQuorum": {
                    "schemaVersion": "agent-review-mesh-quorum-receipt.v1",
                    "status": "PASS",
                    "requiredRolesSatisfied": True,
                    "quorumSatisfied": True,
                    "blockingFindingsUnresolved": True,
                    "blockers": [],
                }
            },
        )

        self.assertEqual(evaluate_oracle(task.oracle, submission)["status"], "FAIL")

    def test_bug_forensics_oracle_rejects_unbound_reproduction(self) -> None:
        task = load_task(SUITE, "rt03-bug-forensics")
        submission = _submission(
            "rt03-bug-forensics",
            {
                "reproductionReceipt": {
                    "schemaVersion": "agent-bug-reproduction-receipt.v1",
                    "status": "PASS",
                    "receiptDigest": DIGEST,
                },
                "regressionProof": {
                    "schemaVersion": "agent-regression-proof-receipt.v1",
                    "status": "PASS",
                    "reproductionReceiptDigest": "2" * 64,
                    "proofDigest": DIGEST,
                },
                "regressionProofValidation": {
                    "schemaVersion": "agent-regression-proof-receipt-validation.v1",
                    "status": "PASS",
                    "proofStatus": "PASS",
                    "proofDigest": DIGEST,
                    "blockers": [],
                },
            },
        )

        self.assertEqual(evaluate_oracle(task.oracle, submission)["status"], "FAIL")

    def test_s1_oracle_rejects_unaccepted_implementation_audit(self) -> None:
        task = load_task(SUITE, "rt04-s1-managed-task")
        submission = _submission(
            "rt04-s1-managed-task",
            {
                "taskResult": {
                    "schemaVersion": "agent-task-result.v2",
                    "blocker": None,
                    "contractChangeRequest": None,
                    "itemOutcomes": [{"id": "item", "status": "COMPLETE"}],
                    "commands": [{"command": "test", "status": "PASS"}],
                },
                "implementationAuditValidation": {
                    "schemaVersion": "agent-implementation-audit-report-validation.v1",
                    "status": "PASS",
                    "verdict": "CHANGES_REQUIRED",
                    "blockers": [],
                },
            },
        )

        self.assertEqual(evaluate_oracle(task.oracle, submission)["status"], "FAIL")

    def test_s2_oracle_rejects_failed_proof_integrity(self) -> None:
        task = load_task(SUITE, "rt05-s2-evidence-task")
        submission = _submission(
            "rt05-s2-evidence-task",
            {
                "finalProof": {
                    "schemaVersion": "agent-run-final-proof.v1",
                    "semanticStatus": "READY_FOR_FINALIZATION",
                    "productionPromotionClaimed": False,
                    "acceptedTasks": [{"id": "WS-1"}],
                },
                "finalImplementationAuditValidation": {
                    "schemaVersion": "agent-final-implementation-audit-validation.v1",
                    "status": "PASS",
                    "blockers": [],
                },
                "proofIntegrityValidation": {
                    "schemaVersion": "agent-proof-integrity-validation.v1",
                    "status": "FAIL",
                    "blockers": [{"code": "proof-chain-invalid"}],
                },
            },
        )

        self.assertEqual(evaluate_oracle(task.oracle, submission)["status"], "FAIL")

    def test_unknown_oracle_type_uses_typed_error(self) -> None:
        with self.assertRaises(LifecycleError) as raised:
            evaluate_oracle({"oracleType": "unknown", "requiredEvidenceSchemas": []}, _submission("task", {}))

        self.assertEqual(raised.exception.code, "reference-oracle-type")

    def test_schema_version_walk_is_iterative_for_deep_internal_values(self) -> None:
        evidence: dict = {"schemaVersion": "deep-evidence.v1"}
        for _ in range(1_500):
            evidence = {"nested": [evidence]}

        self.assertIn("deep-evidence.v1", _schema_versions(evidence))


def _submission(task_id: str, evidence: dict) -> dict:
    return {
        "schemaVersion": "agent-reference-task-submission.v1",
        "taskId": task_id,
        "taskVersion": "1.0.0",
        "accepted": True,
        "evidence": evidence,
        "productionPromotionClaimed": False,
    }


if __name__ == "__main__":
    unittest.main()

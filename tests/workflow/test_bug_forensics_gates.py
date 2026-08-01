from __future__ import annotations

import unittest

from agent_lifecycle.audit.proof_integrity import (
    build_finding_identity,
    build_fix_impact_receipt,
    build_root_cause_evidence,
)
from agent_lifecycle.quality import (
    build_bug_reproduction_receipt,
    build_cross_check_profile,
    build_cross_check_receipt,
    build_failure_classification_receipt,
    build_failure_fingerprint,
    build_hypothesis_ledger,
    build_regression_proof_receipt,
)
from agent_lifecycle.workflow import (
    build_bug_forensics_gate_receipt,
    bug_forensics_activated,
    validate_bug_forensics_gate_receipt,
)


class BugForensicsGateTests(unittest.TestCase):
    def test_regular_task_skips_optional_profile(self) -> None:
        receipt = build_bug_forensics_gate_receipt(task={"id": "WS-01", "taskType": "feature"})

        validation = validate_bug_forensics_gate_receipt(receipt)

        self.assertEqual(receipt["status"], "SKIPPED")
        self.assertFalse(receipt["activated"])
        self.assertEqual(validation["status"], "PASS")

    def test_active_profile_fails_without_reproduction(self) -> None:
        receipt = build_bug_forensics_gate_receipt(task={"id": "BUG-1", "qualityProfile": "bug-forensics"})

        self.assertTrue(bug_forensics_activated({"qualityProfiles": ["bug-forensics"]}))
        self.assertEqual(receipt["status"], "FAIL")
        self.assertIn("bug-forensics-reproduction-missing", {item["code"] for item in receipt["blockers"]})

    def test_active_profile_passes_full_chain_and_reuses_cross_check(self) -> None:
        refs = _refs()
        cross_profile = build_cross_check_profile(budget_cap={"maxInvocations": 1, "maxInputTokens": 2000, "maxOutputTokens": 500, "maxWallSeconds": 60})
        cross_receipt = build_cross_check_receipt(
            profile=cross_profile,
            subject={"taskId": "BUG-1", "blockingCrossCheckRequired": True, "patchDigest": "e" * 64},
            reviewer={"host": "secondary-reviewer", "modelClass": "review"},
            budget_usage={"invocations": 1, "inputTokens": 1500, "outputTokens": 250, "wallSeconds": 30},
            findings=[],
            blocking=True,
            evidence_ids=["EV24-CROSS"],
        )

        receipt = build_bug_forensics_gate_receipt(
            task={"id": "BUG-1", "qualityProfile": "bug-forensics", "blockingCrossCheckRequired": True},
            reproduction_receipt=refs["reproduction"],
            failure_fingerprint=refs["fingerprint"],
            failure_classification=refs["classification"],
            flake_signal={"status": "stable-fail", "runs": 3, "failures": 3},
            hypothesis_ledger=refs["ledger"],
            regression_proof=refs["proof"],
            fix_impact_receipt=refs["fixImpact"],
            cross_check_receipt=cross_receipt,
        )

        validation = validate_bug_forensics_gate_receipt(receipt)

        self.assertEqual(receipt["status"], "PASS")
        self.assertTrue(receipt["chainVerified"])
        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(receipt["evidence"]["crossCheck"]["schemaVersion"], "agent-cross-check-receipt.v1")
        self.assertEqual(receipt["evidence"]["failureClassification"]["schemaVersion"], "agent-failure-classification-receipt.v1")
        self.assertEqual(receipt["evidence"]["flakeSignal"]["status"], "stable-fail")

    def test_security_failure_class_requires_cross_check_for_high_risk_bug(self) -> None:
        refs = _refs()
        classification = build_failure_classification_receipt(
            failure={"logPattern": "security vulnerability token leak"},
            evidence_ids=["EV39-CLASSIFIER"],
        )

        receipt = build_bug_forensics_gate_receipt(
            task={"id": "BUG-1", "qualityProfile": "bug-forensics", "sddTier": "S2", "riskFlags": {"security": True}},
            reproduction_receipt=refs["reproduction"],
            failure_fingerprint=refs["fingerprint"],
            failure_classification=classification,
            hypothesis_ledger=refs["ledger"],
            regression_proof=refs["proof"],
            fix_impact_receipt=refs["fixImpact"],
        )

        self.assertEqual(receipt["status"], "FAIL")
        self.assertIn("bug-forensics-cross-check-missing", {item["code"] for item in receipt["blockers"]})


def _refs() -> dict[str, dict]:
    lineage = {
        "runId": "run-bug",
        "packageId": "release-1-14",
        "planRevision": 3,
        "planDigest": "0" * 64,
        "taskId": "BUG-1",
        "sourceRevision": "source",
    }
    finding = build_finding_identity(
        {
            "category": "api-contract",
            "severity": "HIGH",
            "path": "src/profile.py",
            "function": "get_profile",
            "message": "Missing profile crashes serializer",
        }
    )
    root_cause = build_root_cause_evidence(
        finding_id=finding["findingId"],
        root_cause={"class": "null-edge-case", "summary": "None response crossed API boundary"},
        evidence_ids=["EV24-FINGERPRINT"],
        verifier={"id": "bug-forensics"},
    )
    fix_impact = build_fix_impact_receipt(
        lineage=lineage,
        changed_files=["src/profile.py", "tests/test_profile.py"],
        related_finding_ids=[finding["findingId"]],
        root_cause_digests=[root_cause["rootCauseDigest"]],
        behavior_changes=[{"contract": "missing profile returns 404"}],
        preserved_behaviors=[{"contract": "existing profile response unchanged"}],
        validation_evidence_ids=["EV24-REGRESSION"],
        collateral_damage={"status": "PASS", "checks": ["tests/test_profile.py"]},
        verifier={"id": "bug-forensics"},
    )
    reproduction = build_bug_reproduction_receipt(
        lineage=lineage,
        symptom={"summary": "bug reproduced"},
        reproduction_command=["pytest", "tests/test_profile.py::test_missing_profile"],
        command_status="FAIL",
        artifact_digests=[{"path": "work/bug/repro.log", "sha256": "b" * 64, "bytes": 12}],
    )
    fingerprint = build_failure_fingerprint(
        failure={"exceptionType": "AssertionError", "failingAssertion": "404", "stackTop": "test"},
        affected_symbols=["src/profile.py:get_profile"],
        finding_id=finding["findingId"],
        root_cause_digest=root_cause["rootCauseDigest"],
    )
    classification = build_failure_classification_receipt(
        failure={"exceptionType": "AssertionError", "failingAssertion": "expected HTTP status code 404"},
        failure_fingerprint=fingerprint,
        evidence_ids=["EV39-CLASSIFIER"],
    )
    ledger = build_hypothesis_ledger(
        lineage=lineage,
        hypotheses=[
            {"id": "H1", "status": "REJECTED", "cause": "cache", "check": "disable cache", "result": "failure remains"},
            {"id": "H2", "status": "ACCEPTED", "cause": "None response", "check": "trace response", "result": "confirmed"},
        ],
        minimal_patch={"status": "PASS", "changedFiles": ["src/profile.py"], "suspectScope": ["src/profile.py"], "outsideSuspectScope": [], "justifications": []},
    )
    proof = build_regression_proof_receipt(
        lineage=lineage,
        before={"fingerprintDigest": fingerprint["fingerprintDigest"], "commandStatus": "FAIL", "command": ["pytest"]},
        after={"fingerprintDigest": fingerprint["fingerprintDigest"], "commandStatus": "PASS", "command": ["pytest"]},
        reproduction_receipt=reproduction,
        fix_impact_receipt=fix_impact,
    )
    return {"reproduction": reproduction, "fingerprint": fingerprint, "classification": classification, "ledger": ledger, "proof": proof, "fixImpact": fix_impact}


if __name__ == "__main__":
    unittest.main()

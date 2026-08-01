from __future__ import annotations

import unittest

from agent_lifecycle.audit.proof_integrity import (
    build_finding_identity,
    build_fix_impact_receipt,
    build_root_cause_evidence,
)
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.quality import (
    build_bug_forensics_profile,
    build_bug_reproduction_receipt,
    build_failure_classification_receipt,
    build_failure_fingerprint,
    build_hypothesis_ledger,
    build_regression_proof_receipt,
    validate_bug_forensics_profile,
    validate_bug_reproduction_receipt,
    validate_failure_classification_receipt,
    validate_failure_fingerprint,
    validate_hypothesis_ledger,
    validate_regression_proof_receipt,
)


class BugForensicsProfileTests(unittest.TestCase):
    def test_profile_is_optional_and_resource_capped_without_money(self) -> None:
        profile = build_bug_forensics_profile()

        validation = validate_bug_forensics_profile(profile)

        self.assertEqual(validation["status"], "PASS")
        self.assertFalse(profile["enabledByDefault"])
        self.assertEqual(profile["contextBudget"]["budgetUnits"], "tokens-and-resources")
        self.assertEqual(profile["fixImpactAuthority"]["schemaVersion"], "agent-fix-impact-receipt.v1")
        self.assertEqual(profile["crossCheckPolicy"]["reuseSchemaVersion"], "agent-cross-check-receipt.v1")

    def test_money_budget_fields_are_rejected(self) -> None:
        with self.assertRaises(LifecycleError):
            build_bug_forensics_profile(context_budget={"maxInputTokens": 1000, "maxUsd": 1})

    def test_reproduction_receipt_requires_red_before_modification(self) -> None:
        receipt = build_bug_reproduction_receipt(
            lineage=_lineage(),
            symptom={"summary": "GET /profile crashes for missing profile"},
            reproduction_command=["python", "-m", "pytest", "tests/test_profile.py::test_missing_profile"],
            command_status="FAIL",
            artifact_digests=[_artifact()],
            evidence_ids=["EV24-REPRO"],
        )

        validation = validate_bug_reproduction_receipt(receipt)

        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(validation["status"], "PASS")

        invalid = dict(receipt)
        invalid["beforeModification"] = False
        invalid["receiptDigest"] = "0" * 64
        failed = validate_bug_reproduction_receipt(invalid)
        self.assertEqual(failed["status"], "FAIL")
        self.assertIn("bug-reproduction-not-before-modification", {item["code"] for item in failed["blockers"]})

    def test_failure_fingerprint_links_finding_and_root_cause(self) -> None:
        finding, root_cause, _fix_impact = _proof_integrity_refs()

        fingerprint = build_failure_fingerprint(
            failure={
                "exceptionType": "AssertionError",
                "failingAssertion": "expected missing profile to return 404",
                "stackTop": "tests/test_profile.py::test_missing_profile",
                "logPattern": "profile lookup returned None",
            },
            affected_symbols=["src/profile.py:get_profile"],
            finding_id=finding["findingId"],
            root_cause_digest=root_cause["rootCauseDigest"],
            evidence_ids=["EV24-FINGERPRINT"],
        )

        validation = validate_failure_fingerprint(fingerprint)

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(fingerprint["findingId"], finding["findingId"])
        self.assertEqual(fingerprint["rootCauseDigest"], root_cause["rootCauseDigest"])

    def test_failure_classification_receipt_links_fingerprint(self) -> None:
        _finding, root_cause, _fix_impact = _proof_integrity_refs()
        fingerprint = build_failure_fingerprint(
            failure={
                "exceptionType": "AssertionError",
                "failingAssertion": "expected HTTP status code 404",
                "stackTop": "tests/test_profile.py::test_missing_profile",
            },
            root_cause_digest=root_cause["rootCauseDigest"],
        )

        receipt = build_failure_classification_receipt(
            failure=fingerprint["failure"],
            failure_fingerprint=fingerprint,
            evidence_ids=["EV39-CLASSIFIER"],
        )

        self.assertEqual(receipt["failureClass"], "api-contract")
        self.assertEqual(receipt["failureFingerprintDigest"], fingerprint["fingerprintDigest"])
        self.assertEqual(validate_failure_classification_receipt(receipt)["status"], "PASS")

    def test_hypothesis_ledger_requires_accepted_rejected_and_minimal_patch(self) -> None:
        ledger = build_hypothesis_ledger(
            lineage=_lineage(),
            hypotheses=[
                {"id": "H1", "status": "REJECTED", "cause": "cache stale", "check": "disable cache", "result": "failure remains"},
                {"id": "H2", "status": "ACCEPTED", "cause": "None profile path", "check": "trace repository response", "result": "None reaches serializer"},
            ],
            minimal_patch={
                "status": "PASS",
                "changedFiles": ["src/profile.py", "tests/test_profile.py"],
                "suspectScope": ["src/profile.py", "tests/test_profile.py"],
                "outsideSuspectScope": [],
                "justifications": [],
            },
            evidence_ids=["EV24-HYPOTHESIS"],
        )

        validation = validate_hypothesis_ledger(ledger)

        self.assertEqual(validation["status"], "PASS")
        self.assertIn("suspect-graph", ledger["phase2Deferred"])

        widened = build_hypothesis_ledger(
            lineage=_lineage(),
            hypotheses=ledger["hypotheses"],
            minimal_patch={
                "status": "PASS",
                "changedFiles": ["src/profile.py", "src/unrelated.py"],
                "suspectScope": ["src/profile.py"],
                "outsideSuspectScope": ["src/unrelated.py"],
                "justifications": [],
            },
        )
        failed = validate_hypothesis_ledger(widened)
        self.assertEqual(failed["status"], "FAIL")
        self.assertIn("bug-minimal-patch-justification-missing", {item["code"] for item in failed["blockers"]})

    def test_regression_proof_requires_same_fingerprint_red_then_green(self) -> None:
        _finding, root_cause, fix_impact = _proof_integrity_refs()
        reproduction = build_bug_reproduction_receipt(
            lineage=_lineage(),
            symptom={"summary": "bug reproduced"},
            reproduction_command=["pytest", "tests/test_profile.py::test_missing_profile"],
            command_status="FAIL",
            artifact_digests=[_artifact()],
        )
        fingerprint = build_failure_fingerprint(
            failure={"exceptionType": "AssertionError", "failingAssertion": "404", "stackTop": "test"},
            root_cause_digest=root_cause["rootCauseDigest"],
        )
        before = {"fingerprintDigest": fingerprint["fingerprintDigest"], "commandStatus": "FAIL", "command": ["pytest"]}
        after = {"fingerprintDigest": fingerprint["fingerprintDigest"], "commandStatus": "PASS", "command": ["pytest"]}

        proof = build_regression_proof_receipt(
            lineage=_lineage(),
            before=before,
            after=after,
            reproduction_receipt=reproduction,
            fix_impact_receipt=fix_impact,
            evidence_ids=["EV24-REGRESSION"],
        )

        self.assertEqual(validate_regression_proof_receipt(proof)["status"], "PASS")

        proof["after"] = {"fingerprintDigest": "f" * 64, "commandStatus": "PASS", "command": ["pytest"]}
        proof["proofDigest"] = "0" * 64
        failed = validate_regression_proof_receipt(proof)
        self.assertEqual(failed["status"], "FAIL")
        self.assertIn("regression-proof-same-fingerprint-red-green-missing", {item["code"] for item in failed["blockers"]})


def _lineage() -> dict:
    return {
        "runId": "run-bug",
        "packageId": "release-1-14",
        "planRevision": 3,
        "planDigest": "0" * 64,
        "taskId": "BUG-1",
        "sourceRevision": "source",
    }


def _artifact() -> dict:
    return {"path": "work/bug/reproduction.log", "sha256": "a" * 64, "bytes": 120}


def _proof_integrity_refs() -> tuple[dict, dict, dict]:
    finding = build_finding_identity(
        {
            "category": "api-contract",
            "severity": "MEDIUM",
            "path": "src/profile.py",
            "function": "get_profile",
            "message": "Missing profile crashes serializer",
        }
    )
    root_cause = build_root_cause_evidence(
        finding_id=finding["findingId"],
        root_cause={"class": "null-edge-case", "summary": "repository None result was serialized directly"},
        evidence_ids=["EV24-FINGERPRINT"],
        verifier={"id": "bug-forensics"},
    )
    fix_impact = build_fix_impact_receipt(
        lineage=_lineage(),
        changed_files=["src/profile.py", "tests/test_profile.py"],
        related_finding_ids=[finding["findingId"]],
        root_cause_digests=[root_cause["rootCauseDigest"]],
        behavior_changes=[{"contract": "missing profile returns 404"}],
        preserved_behaviors=[{"contract": "existing profile response remains unchanged"}],
        validation_evidence_ids=["EV24-REGRESSION"],
        collateral_damage={"status": "PASS", "checks": ["tests/test_profile.py"]},
        verifier={"id": "bug-forensics"},
    )
    return finding, root_cause, fix_impact


if __name__ == "__main__":
    unittest.main()

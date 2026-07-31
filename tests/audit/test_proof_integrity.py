from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.audit.proof_integrity import (  # noqa: E402
    build_finding_identity,
    build_fix_impact_receipt,
    build_hash_chain_migration_policy,
    build_proof_integrity_receipt,
    build_receipt_hash_chain,
    build_root_cause_evidence,
    stable_finding_id,
    validate_fix_impact_receipt,
    validate_proof_integrity_receipt,
    validate_receipt_hash_chain,
    validate_root_cause_evidence,
)
from agent_lifecycle.contracts import canonical_digest  # noqa: E402


class ProofIntegrityAuditTests(unittest.TestCase):
    def test_stable_finding_id_survives_line_and_transient_id_changes(self) -> None:
        first = {
            "id": "review-1",
            "category": "api-contract",
            "severity": "MEDIUM",
            "path": "src/service.py",
            "function": "load_user",
            "line": 41,
            "message": "Missing null handling",
        }
        second = {**first, "id": "review-2", "line": 97}

        self.assertEqual(stable_finding_id(first), stable_finding_id(second))

    def test_root_cause_validation_rejects_digest_drift(self) -> None:
        finding = build_finding_identity(_finding())
        evidence = build_root_cause_evidence(
            finding_id=finding["findingId"],
            root_cause=_root_cause(),
            evidence_ids=["EV-ROOT"],
            verifier={"id": "reviewer"},
        )
        evidence["rootCause"]["summary"] = "changed after digest"

        validation = validate_root_cause_evidence(evidence)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("root-cause-digest-mismatch", _codes(validation))

    def test_fix_impact_receipt_links_root_cause_and_collateral_checks(self) -> None:
        finding = build_finding_identity(_finding())
        root_cause = build_root_cause_evidence(
            finding_id=finding["findingId"],
            root_cause=_root_cause(),
            evidence_ids=["EV-ROOT"],
            verifier={"id": "reviewer"},
        )
        receipt = _fix_impact(finding, root_cause)

        validation = validate_fix_impact_receipt(receipt)

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(validation["impactDigest"], receipt["impactDigest"])

    def test_receipt_hash_chain_detects_tampering(self) -> None:
        chain = build_receipt_hash_chain(
            [
                {"path": "final/root-cause.json", "digest": "1" * 64, "schemaVersion": "agent-root-cause-evidence.v1"},
                {"path": "final/fix-impact.json", "digest": "2" * 64, "schemaVersion": "agent-fix-impact-receipt.v1"},
            ],
            chain_id="run-proof",
            lineage=_lineage(),
        )
        self.assertEqual(validate_receipt_hash_chain(chain)["status"], "PASS")

        chain["entries"][1]["artifact"]["digest"] = "3" * 64
        validation = validate_receipt_hash_chain(chain)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("receipt-hash-chain-entry-hash-mismatch", _codes(validation))

    def test_proof_integrity_requires_root_cause_and_fix_impact_for_findings(self) -> None:
        finding = build_finding_identity(_finding())
        root_cause = build_root_cause_evidence(
            finding_id=finding["findingId"],
            root_cause=_root_cause(),
            evidence_ids=["EV-ROOT"],
            verifier={"id": "reviewer"},
        )
        chain = build_receipt_hash_chain(
            [{"path": "final/root-cause.json", "digest": canonical_digest(root_cause)}],
            chain_id="run-proof",
            lineage=_lineage(),
        )
        receipt = build_proof_integrity_receipt(
            lineage=_lineage(),
            findings=[finding],
            root_causes=[root_cause],
            fix_impact_receipts=[],
            hash_chain=chain,
            migration_policy=build_hash_chain_migration_policy(),
            required_evidence_ids=["EV-ROOT"],
            verifier={"id": "final-auditor"},
        )

        validation = validate_proof_integrity_receipt(receipt)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("proof-integrity-fix-impact-missing", _codes(validation))

    def test_proof_integrity_passes_for_complete_evidence_chain(self) -> None:
        finding = build_finding_identity(_finding())
        root_cause = build_root_cause_evidence(
            finding_id=finding["findingId"],
            root_cause=_root_cause(),
            evidence_ids=["EV-ROOT"],
            verifier={"id": "reviewer"},
        )
        fix_impact = _fix_impact(finding, root_cause)
        chain = build_receipt_hash_chain(
            [
                {"path": "final/root-cause.json", "digest": canonical_digest(root_cause)},
                {"path": "final/fix-impact.json", "digest": canonical_digest(fix_impact)},
            ],
            chain_id="run-proof",
            lineage=_lineage(),
        )
        receipt = build_proof_integrity_receipt(
            lineage=_lineage(),
            findings=[finding],
            root_causes=[root_cause],
            fix_impact_receipts=[fix_impact],
            hash_chain=chain,
            migration_policy=build_hash_chain_migration_policy(),
            required_evidence_ids=["EV-ROOT", "EV-FIX"],
            verifier={"id": "final-auditor"},
        )

        validation = validate_proof_integrity_receipt(receipt)

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(validation["findingCount"], 1)
        self.assertEqual(validation["rootCauseCount"], 1)
        self.assertEqual(validation["fixImpactCount"], 1)


def _finding() -> dict:
    return {
        "category": "api-contract",
        "severity": "MEDIUM",
        "path": "src/service.py",
        "function": "load_user",
        "message": "Missing null handling",
    }


def _root_cause() -> dict:
    return {
        "class": "null-edge-case",
        "summary": "load_user assumed the repository always returns a profile.",
        "affectedFunction": "load_user",
    }


def _lineage() -> dict:
    return {
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
    }


def _fix_impact(finding: dict, root_cause: dict) -> dict:
    return build_fix_impact_receipt(
        lineage=_lineage(),
        changed_files=["src/service.py"],
        related_finding_ids=[finding["findingId"]],
        root_cause_digests=[root_cause["rootCauseDigest"]],
        behavior_changes=[{"contract": "load_user returns None for missing profile"}],
        preserved_behaviors=[{"contract": "existing profile payload remains unchanged"}],
        validation_evidence_ids=["EV-REGRESSION"],
        collateral_damage={"status": "PASS", "checks": ["tests/test_service.py::test_existing_profile"]},
        verifier={"id": "reviewer"},
    )


def _codes(validation: dict) -> set[str]:
    codes: set[str] = set()
    for blocker in validation.get("blockers", []):
        if isinstance(blocker, dict) and isinstance(blocker.get("code"), str):
            codes.add(blocker["code"])
            nested = blocker.get("validation")
            if isinstance(nested, dict):
                codes.update(_codes(nested))
    return codes


if __name__ == "__main__":
    unittest.main()

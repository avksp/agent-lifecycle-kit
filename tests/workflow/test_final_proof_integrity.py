from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402

from agent_lifecycle.audit.proof_integrity import (  # noqa: E402
    build_finding_identity,
    build_fix_impact_receipt,
    build_hash_chain_migration_policy,
    build_proof_integrity_receipt,
    build_receipt_hash_chain,
    build_root_cause_evidence,
)


class FinalProofIntegrityTests(unittest.TestCase):
    def test_finalize_run_fails_closed_when_required_receipt_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            _accept_only_task(state_path)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["proofIntegrityRequired"] = True
            state_path.write_text(json.dumps(state), encoding="utf-8")
            audit = _final_audit()
            audit["proofIntegrityRequired"] = True
            write_json_create(root / "final/final-audit.json", audit)

            with self.assertRaises(LifecycleError) as raised:
                finalize_run(
                    state_path,
                    operation_id="finalize-op",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="final/final-audit.json",
                    proof_path="final/proof.json",
                    reason="done",
                )

            self.assertEqual(raised.exception.code, "proof-integrity-receipt-missing")

    def test_finalize_run_embeds_valid_proof_integrity_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            _accept_only_task(state_path)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["proofIntegrityRequired"] = True
            state_path.write_text(json.dumps(state), encoding="utf-8")
            finding, root_cause, fix_impact, receipt = _proof_integrity_receipt()
            audit = _final_audit()
            audit["proofIntegrityRequired"] = True
            audit["proofIntegrityEvidence"] = {
                "required": True,
                "requiredFindingIds": [finding["findingId"]],
                "requiredRootCauseDigests": [root_cause["rootCauseDigest"]],
                "requiredFixImpactDigests": [fix_impact["impactDigest"]],
                "requiredEvidenceIds": ["EV-ROOT", "EV-FIX"],
            }
            write_json_create(root / "final/final-audit.json", audit)
            write_json_create(root / "final/proof-integrity.json", receipt)

            payload = finalize_run(
                state_path,
                operation_id="finalize-op",
                expected_revision=1,
                source_revision="source",
                final_audit_path="final/final-audit.json",
                proof_path="final/proof.json",
                proof_integrity_path="final/proof-integrity.json",
                reason="done",
            )

            self.assertEqual(payload["phase"], "COMPLETE")
            proof = json.loads((root / "final/proof.json").read_text(encoding="utf-8"))
            self.assertEqual(proof["proofIntegrity"]["receipt"]["path"], "final/proof-integrity.json")
            self.assertEqual(proof["proofIntegrity"]["validation"]["status"], "PASS")
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["proofIntegrityReceipt"]["path"], "final/proof-integrity.json")

    def test_finalize_run_rejects_missing_required_finding_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            _accept_only_task(state_path)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["proofIntegrityRequired"] = True
            state_path.write_text(json.dumps(state), encoding="utf-8")
            finding, _root_cause, _fix_impact, receipt = _proof_integrity_receipt()
            receipt["findings"] = []
            receipt["receiptDigest"] = canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"})
            audit = _final_audit()
            audit["proofIntegrityRequired"] = True
            audit["proofIntegrityEvidence"] = {"required": True, "requiredFindingIds": [finding["findingId"]]}
            write_json_create(root / "final/final-audit.json", audit)
            write_json_create(root / "final/proof-integrity.json", receipt)

            with self.assertRaises(LifecycleError) as raised:
                finalize_run(
                    state_path,
                    operation_id="finalize-op",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="final/final-audit.json",
                    proof_path="final/proof.json",
                    proof_integrity_path="final/proof-integrity.json",
                    reason="done",
                )

            self.assertEqual(raised.exception.code, "proof-integrity-validation-failed")


def _accept_only_task(state_path: Path) -> None:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["tasks"][0]["status"] = "ACCEPTED"
    state["tasks"][0]["attempt"] = 1
    state["tasks"][0]["review"] = {"path": "work/WS-01/attempt-1/task-review.json", "sha256": "3" * 64, "bytes": 10}
    state_path.write_text(json.dumps(state), encoding="utf-8")


def _proof_integrity_receipt() -> tuple[dict, dict, dict, dict]:
    lineage = {
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
    }
    finding = build_finding_identity(
        {
            "category": "api-contract",
            "severity": "MEDIUM",
            "path": "src/service.py",
            "function": "load_user",
            "message": "Missing null handling",
        }
    )
    root_cause = build_root_cause_evidence(
        finding_id=finding["findingId"],
        root_cause={"class": "null-edge-case", "summary": "repository response can be absent"},
        evidence_ids=["EV-ROOT"],
        verifier={"id": "reviewer"},
    )
    fix_impact = build_fix_impact_receipt(
        lineage=lineage,
        changed_files=["src/service.py"],
        related_finding_ids=[finding["findingId"]],
        root_cause_digests=[root_cause["rootCauseDigest"]],
        behavior_changes=[{"contract": "missing profile returns None"}],
        preserved_behaviors=[{"contract": "existing profile response remains unchanged"}],
        validation_evidence_ids=["EV-FIX"],
        collateral_damage={"status": "PASS", "checks": ["tests/test_service.py"]},
        verifier={"id": "reviewer"},
    )
    chain = build_receipt_hash_chain(
        [
            {"path": "final/root-cause.json", "digest": canonical_digest(root_cause)},
            {"path": "final/fix-impact.json", "digest": canonical_digest(fix_impact)},
        ],
        chain_id="run-proof",
        lineage=lineage,
    )
    receipt = build_proof_integrity_receipt(
        lineage=lineage,
        findings=[finding],
        root_causes=[root_cause],
        fix_impact_receipts=[fix_impact],
        hash_chain=chain,
        migration_policy=build_hash_chain_migration_policy(),
        required_evidence_ids=["EV-ROOT", "EV-FIX"],
        verifier={"id": "final-auditor"},
    )
    return finding, root_cause, fix_impact, receipt


if __name__ == "__main__":
    unittest.main()

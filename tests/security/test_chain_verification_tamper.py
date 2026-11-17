"""Fail-closed checks for mutated snapshots and incorrect terminal authority."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from agent_lifecycle.audit.chain_verification import verify_chain
from tests.audit.test_chain_verification import AnchoredRunFixture
from tests.contracts.test_operator_signature import inventory
from tests.workflow.test_operator_signature_gates import write


class ChainTamperTests(TestCase):
    def setUp(self) -> None:
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve(strict=True)
        self.fixture = AnchoredRunFixture(self.root, operator_required=True)

    def refusal(self, check: str, code: str, *, status: str = "MISMATCH", exit_code: int = 1) -> None:
        before = inventory(self.root)
        actual = self.fixture.verify()
        self.assertEqual(actual["status"], status, actual)
        self.assertEqual(actual["exitCode"], exit_code, actual)
        self.assertEqual(actual["firstFailure"], {"check": check, "code": code}, actual)
        self.assertEqual(inventory(self.root), before)

    def test_tampered_event_cannot_get_past_external_journal_digest(self):
        journal = self.fixture.repo / self.fixture.bundle["journal"]
        journal.write_bytes(journal.read_bytes().replace(b'"execution-authorized"', b'"other-operation"', 1))
        self.refusal("state-journal", "chain-anchor-journal-mismatch")

    def test_even_anchored_reordered_events_disagree_with_native_ledger(self):
        journal = self.fixture.repo / self.fixture.bundle["journal"]
        lines = journal.read_bytes().splitlines(keepends=True)
        journal.write_bytes(b"".join([lines[1], lines[0], *lines[2:]]))
        self.fixture.rebuild_chain()
        self.fixture.refresh_anchor()
        self.refusal("state-journal", "chain-journal-order-mismatch")

    def test_missing_terminal_proof_is_named_a_required_receipt_mismatch(self):
        (self.fixture.repo / "receipts/proof.json").unlink()
        self.refusal("receipt-chain", "chain-input-missing")

    def test_unpinned_signer_refuses_even_when_the_selection_digests_match(self):
        name = "receipts/final-review.json.operator-signature.json"
        detached = self.fixture.read(name)
        detached["payload"]["signerFingerprint"] = "ed25519:" + "f" * 64
        write(self.fixture.repo / name, detached)
        self.fixture.rebuild_chain()
        self.fixture.refresh_anchor()
        self.refusal("operator-signatures", "chain-operator-signature-mismatch")

    def test_lock_inventory_detects_changed_review_bytes(self):
        name = "plan/plan-review.json"
        changed = self.fixture.read(name)
        changed["reviewId"] = "substitution"
        write(self.fixture.repo / name, changed)
        self.refusal("lock", "chain-lock-file-mismatch")

    def test_reused_operator_proof_fails_phase_and_subject_binding(self):
        name = "receipts/final-review.json.operator-signature.json"
        write(self.fixture.repo / name, self.fixture.read("plan/operator-freeze-signature.json"))
        self.fixture.rebuild_chain()
        self.fixture.refresh_anchor()
        self.refusal("operator-signatures", "chain-operator-signature-mismatch")

    def test_valid_prefix_is_incomplete_under_original_terminal_anchor(self):
        journal = self.fixture.repo / self.fixture.bundle["journal"]
        lines = journal.read_bytes().splitlines(keepends=True)
        journal.write_bytes(b"".join(lines[:-1]))
        self.fixture.rebuild_chain()
        self.refusal("state-journal", "chain-anchor-journal-mismatch")

    def test_unsupported_state_requires_nonzero_not_checked(self):
        state = self.fixture.read(self.fixture.bundle["state"])
        state["schemaVersion"] = "agent-workflow-state.v7"
        write(self.fixture.state_path, state)
        self.fixture.rebuild_chain()
        self.fixture.refresh_anchor()
        self.refusal("state-journal", "chain-state-profile-unsupported", status="NOT_CHECKED")

    def test_hardlinked_file_is_refused_before_hashing(self):
        # Link only synthetic bytes inside the isolated test fixture.
        p = self.fixture.repo / "plan/plan-review.json"
        try:
            os.link(p, p.with_name("alias.json"))
        except OSError as exc:
            self.skipTest(f"Hard links unavailable on test volume: {type(exc).__name__}")
        self.refusal("lock", "chain-input-hardlink")

    def test_missing_verifier_anchor_is_input_error(self):
        self.fixture.anchor.unlink()
        self.refusal("input", "chain-input-missing", status="INVALID_INPUT", exit_code=2)

    def test_verifier_roots_cannot_be_selected_from_bundle_directory(self):
        selected = self.fixture.repo / "trust.json"
        selected.write_bytes(self.fixture.trust.read_bytes())
        before = inventory(self.root)
        actual = verify_chain(
            self.fixture.repo, self.fixture.bundle_name, trust_config_path=selected, anchor_path=self.fixture.anchor
        )
        self.assertEqual(actual["exitCode"], 2, actual)
        self.assertEqual(actual["firstFailure"]["code"], "chain-trust-inside-evidence-root")
        self.assertEqual(inventory(self.root), before)

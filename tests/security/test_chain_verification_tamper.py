"""Fail-closed checks for mutated snapshots and incorrect terminal authority."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from agent_lifecycle.audit import chain_verification
from agent_lifecycle.audit.chain_verification import verify_chain
from agent_lifecycle.contracts.canonical import canonical_bytes
from tests.audit.test_chain_verification import AnchoredRunFixture
from tests.contracts.test_operator_signature import envelope, inventory
from tests.workflow.test_operator_signature_gates import write


class ChainTamperTests(TestCase):
    def setUp(self) -> None:
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve(strict=True)
        self.fixture = AnchoredRunFixture(self.root, operator_required=True, task_bearing=True)

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

    def test_reanchored_prefix_still_disagrees_with_terminal_state(self):
        journal = self.fixture.repo / self.fixture.bundle["journal"]
        journal.write_bytes(b"".join(journal.read_bytes().splitlines(keepends=True)[:-1]))
        self.fixture.rebuild_chain()
        self.fixture.refresh_anchor()
        self.refusal("state-journal", "chain-journal-length-mismatch")

    def test_changed_final_verdict_invalidates_anchored_receipt(self):
        name = "receipts/final-review.json"
        changed = self.fixture.read(name)
        changed["verdict"] = "BLOCKED"
        write(self.fixture.repo / name, changed)
        self.refusal("receipt-chain", "chain-receipt-artifact-mismatch")

    def test_task_retry_without_archived_admission_cannot_pass(self):
        changed = self.fixture.read(self.fixture.bundle["state"])
        changed["tasks"][0]["attempt"] = 2
        write(self.fixture.state_path, changed)
        self.fixture.rebuild_chain()
        self.fixture.refresh_anchor()
        self.refusal("reviewer-signatures", "chain-task-history-unsupported", status="NOT_CHECKED")

    def _reanchor_history(self, events: list[dict]) -> None:
        changed = self.fixture.read(self.fixture.bundle["state"])
        for revision, entry in enumerate(events, 2):
            entry["stateRevision"] = revision
        changed["stateRevision"] = events[-1]["stateRevision"]
        changed["operationLedger"] = {
            entry["operationId"]: {
                key: entry[key] for key in ("stateRevision", "eventType", "recordedAt")
            } for entry in events
        }
        self.fixture.value = changed
        write(self.fixture.state_path, changed)
        (self.fixture.repo / self.fixture.bundle["journal"]).write_bytes(
            b"".join(canonical_bytes(entry) + b"\n" for entry in events)
        )
        self.fixture.rebuild_chain()
        self.fixture.refresh_anchor()

    def _events(self) -> list[dict]:
        return [json.loads(row) for row in
                (self.fixture.repo / self.fixture.bundle["journal"]).read_bytes().splitlines()]

    def test_multi_plan_history_has_no_successful_projection(self):
        events = self._events()
        events.insert(1, {**events[0], "operationId": "second-plan"})
        self._reanchor_history(events)
        self.refusal("state-journal", "chain-plan-history-unsupported", status="NOT_CHECKED")

    def test_repeated_final_outcome_has_no_successful_projection(self):
        events = self._events()
        events.insert(-1, {**events[-2], "operationId": "second-outcome"})
        self._reanchor_history(events)
        self.refusal("reviewer-signatures", "chain-outcome-history-unsupported", status="NOT_CHECKED")

    def test_one_second_observation_that_straddles_key_window_is_not_checked(self):
        terminal = self._events()[-1]
        before = {**self.fixture.value, "stateRevision": terminal["stateRevision"] - 1}
        audit = self.fixture.read("receipts/final-review.json")
        detached = envelope(
            before, "accept", operation_id=terminal["operationId"], subject=audit,
            validFrom=terminal["recordedAt"][:-1] + ".500000Z",
        )
        write(self.fixture.repo / "receipts/final-review.json.operator-signature.json", detached)
        self.fixture.rebuild_chain()
        self.fixture.refresh_anchor()
        self.refusal("operator-signatures", "chain-operator-time-precision", status="NOT_CHECKED")

    def test_advisory_diagnostic_does_not_prove_native_operator_admission(self):
        self.fixture = AnchoredRunFixture(
            self.root / "advisory", operator_required=False, operator_advisory=True,
        )
        self.refusal("operator-signatures", "chain-advisory-operator-not-checked", status="NOT_CHECKED")

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

    def test_repeated_casefolded_selector_is_input_error(self):
        copy = {**self.fixture.bundle, "journal": self.fixture.bundle["lock"].upper()}
        write(self.fixture.repo / self.fixture.bundle_name, copy)
        self.refusal("input", "chain-verification-input-alias", status="INVALID_INPUT", exit_code=2)

    def test_symlinked_review_is_refused(self):
        name = self.fixture.repo / "plan/plan-review.json"
        target = name.with_name("synthetic-review.json")
        target.write_bytes(name.read_bytes())
        name.unlink()
        try:
            name.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"Symbolic links unavailable on test volume: {type(exc).__name__}")
        self.refusal("lock", "authority-input-not-regular")

    def test_nonregular_review_is_refused(self):
        name = self.fixture.repo / "plan/plan-review.json"
        name.unlink()
        name.mkdir()
        self.refusal("lock", "authority-input-not-regular")

    def test_oversized_review_fails_before_loading(self):
        name = self.fixture.repo / "plan/plan-review.json"
        with name.open("wb") as f:
            f.truncate(8 * 1024 * 1024 + 1)
        self.refusal("lock", "chain-input-byte-limit")

    def test_selected_unreadable_receipt_is_mismatch(self):
        original = chain_verification._bounded_file

        def failed(root, path, cap):
            if path.name == "proof.json":
                raise PermissionError("fixture read failure")
            return original(root, path, cap)

        with patch.object(chain_verification, "_bounded_file", side_effect=failed):
            self.refusal("receipt-chain", "chain-input-unreadable")

    def test_selected_bytes_observed_to_drift_cannot_pass(self):
        original = chain_verification._bounded_file
        seen = False

        def changed(root, path, cap):
            nonlocal seen
            data = original(root, path, cap)
            if path.name == "proof.json":
                if seen:
                    return data[:-1]
                seen = True
            return data

        with patch.object(chain_verification, "_bounded_file", side_effect=changed):
            self.refusal("snapshot", "chain-input-changed")

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

"""Fail-closed checks for mutated snapshots and incorrect terminal authority."""

from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from agent_lifecycle.audit import chain_verification
from agent_lifecycle.audit.chain_verification import verify_chain
from agent_lifecycle.cli.main import main
from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest
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
        self.refusal("reviewer-signatures", "chain-input-missing")

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
        self.refusal("reviewer-signatures", "chain-artifact-bytes-mismatch")

    def test_task_retry_without_archived_admission_cannot_pass(self):
        changed = self.fixture.read(self.fixture.bundle["state"])
        changed["tasks"][0]["attempt"] = 2
        write(self.fixture.state_path, changed)
        self.fixture.rebuild_chain()
        self.fixture.refresh_anchor()
        self.refusal("state-journal", "workflow-storage-invalid")

    def _reanchor_history(self, events: list[dict]) -> None:
        changed = self.fixture.read(self.fixture.bundle["state"])
        for revision, entry in enumerate(events, 2):
            entry["stateRevision"] = revision
        changed["stateRevision"] = events[-1]["stateRevision"]
        changed["operationLedger"] = {
            entry["operationId"]: {key: entry[key] for key in ("stateRevision", "eventType", "recordedAt")}
            for entry in events
        }
        self.fixture.value = changed
        write(self.fixture.state_path, changed)
        (self.fixture.repo / self.fixture.bundle["journal"]).write_bytes(
            b"".join(canonical_bytes(entry) + b"\n" for entry in events)
        )
        self.fixture.rebuild_chain()
        self.fixture.refresh_anchor()

    def _events(self) -> list[dict]:
        return [
            json.loads(row) for row in (self.fixture.repo / self.fixture.bundle["journal"]).read_bytes().splitlines()
        ]

    def test_multi_plan_history_has_no_successful_projection(self):
        events = self._events()
        events.insert(1, {**events[0], "operationId": "second-plan"})
        self._reanchor_history(events)
        self.refusal("state-journal", "chain-plan-history-unsupported", status="NOT_CHECKED")

    def test_repeated_final_outcome_has_no_successful_projection(self):
        events = self._events()
        events.insert(-1, {**events[-2], "operationId": "second-outcome"})
        self._reanchor_history(events)
        self.refusal("state-journal", "chain-outcome-history-unsupported", status="NOT_CHECKED")

    def test_replaced_signature_receipt_is_mismatch_even_for_partial_window(self):
        terminal = self._events()[-1]
        before = {**self.fixture.value, "stateRevision": terminal["stateRevision"] - 1}
        audit = self.fixture.read("receipts/final-review.json")
        detached = envelope(
            before,
            "accept",
            operation_id=terminal["operationId"],
            subject=audit,
            validFrom=terminal["recordedAt"][:-1] + ".500000Z",
        )
        write(self.fixture.repo / "receipts/final-review.json.operator-signature.json", detached)
        self.fixture.rebuild_chain()
        self.fixture.refresh_anchor()
        self.refusal("operator-signatures", "chain-operator-signature-mismatch")

    def test_non_object_journal_payload_has_a_named_refusal(self):
        events = self._events()
        events[2]["payload"] = None
        self._reanchor_history(events)
        before = inventory(self.root)
        with redirect_stdout(io.StringIO()) as stdout:
            exit_code = main(
                [
                    "audit",
                    "verify-chain",
                    "--repository-root",
                    str(self.fixture.repo),
                    "--bundle",
                    self.fixture.bundle_name,
                    "--trust-config",
                    str(self.fixture.trust),
                    "--anchor",
                    str(self.fixture.anchor),
                ]
            )
        report = json.loads(stdout.getvalue())
        self.assertEqual((exit_code, report["status"]), (1, "MISMATCH"))
        self.assertEqual(report["firstFailure"], {"check": "state-journal", "code": "chain-journal-payload-invalid"})
        self.assertFalse(report["authorityGranted"])
        self.assertEqual(inventory(self.root), before)

    def test_adoption_and_grant_use_the_same_ordered_journal_clock(self):
        verify_events = chain_verification._events
        for offset in (-1, 0, 1):
            with self.subTest(adoptionSecondsFromGrant=offset):

                def with_observed_adoption(raw, state):
                    events = verify_events(raw, state)
                    grant = datetime.fromisoformat(events[1]["recordedAt"].replace("Z", "+00:00"))
                    observed = (grant + timedelta(seconds=offset)).strftime("%Y-%m-%dT%H:%M:%SZ")
                    events[0] = {**events[0], "recordedAt": observed}
                    return events

                check_window = chain_verification._verify_admission_window

                def with_prior_freeze(receipt, *, latest, earliest=None):
                    if earliest is None and offset == -1:
                        receipt = {"reviewerAdmission": {"observedAt": latest}}
                    return check_window(receipt, latest=latest, earliest=earliest)

                with (
                    patch.object(chain_verification, "_events", side_effect=with_observed_adoption),
                    patch.object(
                        chain_verification, "_verify_admission_window", side_effect=with_prior_freeze
                    ) as admission,
                ):
                    if offset == 1:
                        self.refusal("state-journal", "chain-execution-time-order")
                        self.assertEqual(admission.call_count, 1)
                    else:
                        before = inventory(self.root)
                        result = self.fixture.verify()
                        self.assertEqual(result["status"], "VERIFIED")
                        self.assertEqual(inventory(self.root), before)

    def test_final_event_at_grant_expiry_is_a_named_mismatch(self):
        events = self._events()
        grant = self.fixture.read("receipts/authorization.json")
        expiry = datetime.fromisoformat(grant["expiresAt"])
        events[-1]["recordedAt"] = expiry.strftime("%Y-%m-%dT%H:%M:%SZ")
        self._reanchor_history(events)
        self.refusal("state-journal", "authorization-expired")

    def test_operator_interval_after_observed_second_is_a_mismatch(self):
        terminal = self._events()[-1]
        second = datetime.fromisoformat(terminal["recordedAt"].replace("Z", "+00:00"))
        before = {**self.fixture.value, "stateRevision": terminal["stateRevision"] - 1}
        signature = envelope(
            before,
            "accept",
            operation_id=terminal["operationId"],
            subject=self.fixture.read("receipts/final-review.json"),
            validFrom=(second + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        )
        write(self.fixture.repo / "receipts/final-review.json.operator-signature.json", signature)
        self.fixture.rebuild_chain()
        self.fixture.refresh_anchor()
        self.refusal("operator-signatures", "chain-operator-signature-mismatch")

    def test_optional_audit_claim_in_terminal_proof_only_is_refused(self):
        self.fixture = AnchoredRunFixture(self.root / "untyped", operator_required=False)
        events = self._events()
        proof_path = "receipts/proof.json"
        proof = self.fixture.read(proof_path)
        proof.pop("bodyDigest")
        proof["finalImplementationAudit"] = {}
        proof["bodyDigest"] = canonical_digest(proof)
        write(self.fixture.repo / proof_path, proof)
        proof_identity = dict(self.fixture.value["finalProof"])
        proof_identity.update(bytes=(self.fixture.repo / proof_path).stat().st_size, sha256=canonical_digest(proof))
        self.fixture.value["finalProof"] = proof_identity
        write(self.fixture.state_path, self.fixture.value)
        events[-1]["payload"]["proof"] = proof_identity
        self._reanchor_history(events)
        self.refusal("reviewer-signatures", "chain-final-implementation-mismatch")

    def test_required_typed_final_receipt_missing_is_an_error(self):
        changed = self.fixture.read(self.fixture.bundle["state"])
        changed.pop("finalImplementationAudit")
        write(self.fixture.state_path, changed)
        self.fixture.rebuild_chain()
        self.fixture.refresh_anchor()
        self.refusal("reviewer-signatures", "chain-final-implementation-missing")

    def test_advisory_diagnostic_does_not_prove_native_operator_admission(self):
        self.fixture = AnchoredRunFixture(
            self.root / "advisory",
            operator_required=False,
            operator_advisory=True,
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

    def test_every_admission_window_has_a_named_read_only_refusal(self):
        before = inventory(self.root)
        check = chain_verification._verify_admission_window
        with patch.object(chain_verification, "_verify_admission_window", wraps=check) as probe:
            self.assertEqual(self.fixture.verify()["status"], "VERIFIED")
        events = {event["eventType"]: event["recordedAt"] for event in self._events()}
        task = self.fixture.value["tasks"][0]
        result_time, accept_time = events["task-result-committed"], events["task-accepted"]
        outcome_time, final_time = events["final-audit-outcome-applied"], events["run-finalized"]
        admission_windows = [
            (self.fixture.read("plan/plan.lock.json"), {"latest": events["plan-adopted"]}),
            (task["review"], {"earliest": result_time, "latest": accept_time}),
            (task["implementationAuditReport"], {"earliest": result_time, "latest": accept_time}),
            (self.fixture.value["finalAudit"], {"earliest": accept_time, "latest": outcome_time}),
            (self.fixture.value["finalImplementationAudit"], {"earliest": outcome_time, "latest": final_time}),
        ]
        self.assertEqual([(call.args[0], call.kwargs) for call in probe.call_args_list], admission_windows)

        for selected, phase in enumerate(("state-journal",) + ("reviewer-signatures",) * 4):
            with self.subTest(admission_index=selected):
                index = 0

                def with_invalid_time(receipt, *, earliest=None, latest):
                    nonlocal index
                    if index == selected:
                        later = datetime.fromisoformat(latest.replace("Z", "+00:00")) + timedelta(seconds=1)
                        receipt = {"reviewerAdmission": {"observedAt": later.strftime("%Y-%m-%dT%H:%M:%SZ")}}
                    index += 1
                    return check(receipt, earliest=earliest, latest=latest)

                with patch.object(chain_verification, "_verify_admission_window", side_effect=with_invalid_time):
                    self.refusal(phase, "chain-reviewer-admission-outside-journal-window")
        self.assertEqual(inventory(self.root), before)

    def test_cyclic_explicit_selectors_return_named_cli_input_errors(self):
        cycle = self.root / "cycle"
        try:
            cycle.symlink_to(cycle.name)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symbolic links unavailable on test volume: {type(exc).__name__}")
        before = inventory(self.fixture.repo)
        cases = (
            (cycle, self.fixture.trust, "chain-evidence-root-not-canonical"),
            (self.fixture.repo, cycle, "chain-trust-path-not-canonical"),
        )
        for root, trust, code in cases:
            with self.subTest(code=code), redirect_stdout(io.StringIO()) as stdout:
                exit_code = main(
                    [
                        "audit",
                        "verify-chain",
                        "--repository-root",
                        str(root),
                        "--bundle",
                        self.fixture.bundle_name,
                        "--trust-config",
                        str(trust),
                        "--anchor",
                        str(self.fixture.anchor),
                    ]
                )
                report = json.loads(stdout.getvalue())
                self.assertEqual((exit_code, report["exitCode"], report["status"]), (2, 2, "INVALID_INPUT"))
                self.assertEqual(report["firstFailure"], {"check": "input", "code": code})
                self.assertFalse(report["authorityGranted"])
                self.assertEqual(inventory(self.fixture.repo), before)
                self.assertEqual(os.readlink(cycle), cycle.name)

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

    def test_selected_unreadable_receipt_is_invalid_input(self):
        original = chain_verification._bounded_file

        def failed(root, path, cap):
            if path.name == "proof.json":
                raise PermissionError("fixture read failure")
            return original(root, path, cap)

        with patch.object(chain_verification, "_bounded_file", side_effect=failed):
            self.refusal("reviewer-signatures", "chain-input-unreadable", status="INVALID_INPUT", exit_code=2)

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

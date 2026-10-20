"""Real existing Journal operations and finite owned-effect admission."""

import multiprocessing
import os
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path

from agent_lifecycle.accounting.journal import Journal, RevisionConflict
from agent_lifecycle.adapter_sessions.process_admission import (
    JournalPreparationAdmission,
    preparation_operation_reason,
)
from agent_lifecycle.contracts import LifecycleError
from tests.accounting.test_journal import PROOF, open_scope, operation
from tests.contracts.test_preparation_policy import context_fixture


def preparation_operation(name="op", *, source="d" * 64):
    return replace(operation(name=name), attribution_reason=preparation_operation_reason(
        goal_digest="b" * 64, phase_digest="c" * 64, source_digest=source,
        charged_milliseconds=100, semantic_round=1,
        quantity="RESERVATION_TOKENS",
    ))


def qualified_context(prefix):
    context = context_fixture(prefix["prefixDigest"])
    if prefix["rowCount"] > 1:
        context["progress"].update(status="ADVANCING", verifiedInitial=False)
    return context


def crash_after_durable_preparation_claim(path, marker):
    with Journal(path, PROOF) as journal:
        def fault(stage):
            if stage == "after_commit":
                try:
                    claimed = journal.permit("run", "op").claim_id
                except KeyError:
                    claimed = None
                if claimed is not None:
                    os._exit(27)
        journal.fault_hook = fault
        admission = JournalPreparationAdmission(
            journal, preparation_operation(), qualified_context, clock=lambda: 100,
        )
        admission.invoke(lambda: Path(marker).write_text("effect"),
                         input_digest="b" * 64)


class ProcessAdmissionTests(unittest.TestCase):
    def test_genuine_new_goal_needs_scope_change_and_keeps_prior_exposure(self):
        with tempfile.TemporaryDirectory() as directory:
            with Journal(Path(directory) / "usage.db", PROOF) as journal:
                open_scope(journal)
                first = JournalPreparationAdmission(
                    journal, preparation_operation(), qualified_context, clock=lambda: 100,
                )
                first.invoke(lambda: None, input_digest="b" * 64)
                reason = preparation_operation_reason(
                    goal_digest="e" * 64, phase_digest="f" * 64, source_digest="d" * 64,
                    charged_milliseconds=100, semantic_round=1,
                    quantity="RESERVATION_TOKENS",
                )
                op = replace(preparation_operation("new-goal"), attribution_reason=reason)
                def renamed(prefix):
                    context = qualified_context(prefix)
                    context.update(goalDigest="e" * 64, phaseDigest="f" * 64)
                    context["progress"].update(goalDigest="e" * 64, phaseDigest="f" * 64)
                    return context
                denied = JournalPreparationAdmission(journal, op, renamed, clock=lambda: 100)
                with self.assertRaises(LifecycleError):
                    denied.invoke(lambda: self.fail("rename reset"), input_digest="b" * 64)
                def changed(prefix):
                    context = renamed(prefix)
                    context["progress"].update(status="UNAVAILABLE", verifiedInitial=True)
                    context["scopeChange"] = {
                        "qualified": True, "authorizationDigest": "a" * 64,
                        "newGoalDigest": "e" * 64, "newPhaseDigest": "f" * 64,
                        "allowedPredecessorGoalPhases": [
                            {"goalDigest": "b" * 64, "phaseDigest": "c" * 64},
                        ],
                    }
                    return context
                approved = JournalPreparationAdmission(journal, op, changed, clock=lambda: 100)
                approved.invoke(lambda: None, input_digest="b" * 64)
                self.assertEqual(journal.snapshot("run").active_reservations, 200)

    def test_prefix_overflow_is_typed_and_preserves_zero_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            with Journal(Path(directory) / "usage.db", PROOF) as journal:
                open_scope(journal)
                admission = JournalPreparationAdmission(
                    journal, preparation_operation(), qualified_context,
                    clock=lambda: 100, max_prefix_bytes=1,
                )
                with self.assertRaises(LifecycleError) as caught:
                    admission.invoke(lambda: self.fail("overflow dispatch"),
                                     input_digest="b" * 64)
                self.assertEqual(caught.exception.code, "PREPARATION_HISTORY_UNAVAILABLE")
                self.assertEqual(journal.snapshot("run").journal_revision, 1)

    def test_real_journal_dispatch_once_and_cumulative_renamed_request(self):
        with tempfile.TemporaryDirectory() as directory:
            with Journal(Path(directory) / "usage.db", PROOF) as journal:
                open_scope(journal, protected={"task": 200})
                effects = []
                first = JournalPreparationAdmission(
                    journal, preparation_operation(), qualified_context,
                    clock=lambda: 100,
                )
                self.assertEqual(first.check()["status"], "PASS")
                first.invoke(lambda: effects.append("first"), input_digest="b" * 64)
                with self.assertRaises(LifecycleError):
                    first.invoke(lambda: effects.append("duplicate"),
                                 input_digest="b" * 64)
                for index in range(1, 8):
                    changed = JournalPreparationAdmission(
                        journal, preparation_operation("renamed-" + str(index)),
                        qualified_context, clock=lambda: 100,
                    )
                    changed.invoke(lambda: effects.append("next"),
                                   input_digest="b" * 64)
                with self.assertRaises(LifecycleError) as caught:
                    JournalPreparationAdmission(
                        journal, preparation_operation("another-window"),
                        qualified_context, clock=lambda: 100,
                    ).invoke(lambda: effects.append("overflow"),
                             input_digest="b" * 64)
                self.assertEqual(caught.exception.code, "PREPARATION_BUDGET_EXHAUSTED")
                self.assertEqual(len(effects), 8)
                self.assertEqual(journal.snapshot("run").active_reservations, 800)

    def test_missing_prefix_stall_source_or_chain_has_zero_reserve_effect(self):
        mutations = [
            lambda c: c["progress"].update(journalPrefixDigest="0" * 64),
            lambda c: c["progress"].update(status="STALLED", completedRounds=2,
                                            nonproductiveRounds=2),
            lambda c: c["chain"].update(slots=[]),
            lambda c: c.update(sourceDigest="0" * 64),
            lambda c: c.update(nativeDeadlineAt=99),
            lambda c: c["readiness"]["checks"].update(service="UNAVAILABLE"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            with Journal(Path(directory) / "usage.db", PROOF) as journal:
                open_scope(journal)
                for mutation in mutations:
                    def qualify(prefix):
                        context = qualified_context(prefix)
                        mutation(context)
                        return context
                    admission = JournalPreparationAdmission(
                        journal, preparation_operation(), qualify, clock=lambda: 100,
                    )
                    with self.assertRaises(LifecycleError):
                        admission.invoke(lambda: self.fail("effect started"),
                                         input_digest="b" * 64)
                    self.assertEqual(journal.snapshot("run").journal_revision, 1)

    def test_unknown_effect_keeps_hold_and_cannot_relaunch(self):
        with tempfile.TemporaryDirectory() as directory:
            with Journal(Path(directory) / "usage.db", PROOF) as journal:
                open_scope(journal)
                admission = JournalPreparationAdmission(
                    journal, preparation_operation(), qualified_context,
                    clock=lambda: 100,
                )
                def uncertain():
                    raise TimeoutError("remote delivery unknown")
                with self.assertRaises(TimeoutError):
                    admission.invoke(uncertain, input_digest="b" * 64)
                self.assertEqual(journal.snapshot("run").active_reservations, 100)
                with self.assertRaises(LifecycleError):
                    admission.invoke(lambda: self.fail("duplicate generation"),
                                     input_digest="b" * 64)

    def test_two_separate_connections_compete_for_one_request(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.db"
            with Journal(path, PROOF) as journal:
                open_scope(journal)
            barrier, effects, outcomes = threading.Barrier(2), [], []
            def worker(name):
                with Journal(path, PROOF) as journal:
                    first = True
                    def qualify(prefix):
                        nonlocal first
                        context = qualified_context(prefix)
                        context["limits"]["requests"] = 1
                        if first:
                            first = False
                            barrier.wait(timeout=10)
                        return context
                    admission = JournalPreparationAdmission(
                        journal, preparation_operation(name), qualify,
                        clock=lambda: 100,
                    )
                    try:
                        admission.invoke(lambda: effects.append(name),
                                         input_digest="b" * 64)
                        outcomes.append("DISPATCHED")
                    except RevisionConflict:
                        outcomes.append("REVISION_CONFLICT")
            threads = [threading.Thread(target=worker, args=(str(i),)) for i in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
                self.assertFalse(thread.is_alive())
            self.assertEqual(sorted(outcomes), ["DISPATCHED", "REVISION_CONFLICT"])
            self.assertEqual(len(effects), 1)

    def test_committed_claim_crash_rebuild_preserves_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.db"
            with Journal(path, PROOF) as journal:
                open_scope(journal)
            marker = Path(directory) / "effect.txt"
            process = multiprocessing.get_context("spawn").Process(
                target=crash_after_durable_preparation_claim,
                args=(str(path), str(marker)),
            )
            process.start()
            process.join(timeout=15)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
            self.assertEqual(process.exitcode, 27)
            self.assertFalse(marker.exists())
            with Journal(path, PROOF) as journal:
                recovered = journal.rebuild("run")
                self.assertEqual(recovered.active_reservations, 100)
                self.assertEqual(recovered.gate_status, "INCOMPLETE")
                admission = JournalPreparationAdmission(
                    journal, preparation_operation(), qualified_context,
                    clock=lambda: 100,
                )
                with self.assertRaises(LifecycleError):
                    admission.invoke(lambda: self.fail("unknown replay"),
                                     input_digest="b" * 64)

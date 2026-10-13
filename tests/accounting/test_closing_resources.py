"""D-RESOURCE pure limit witnesses; no transaction or provider admission claim."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from agent_lifecycle.accounting.closing_resource_policy import derive_policy_candidate_data, evaluate_activation_resource_binding
from agent_lifecycle.accounting.contracts import (
    BudgetPolicy,
    BudgetScope,
    EvidenceRef,
    JournalUnavailable,
    OpeningBalance,
    digest,
)
from agent_lifecycle.accounting.journal import Journal
from agent_lifecycle.accounting.workflow_store import _apply
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest
from agent_lifecycle.contracts.closing_resource_schemas import (
    CAP_BINDING_V1,
    CLAIM_REQUEST_V1,
    LIMIT_PROPOSAL_V1,
    OPERATION_BINDING_V1,
    evaluate_claim_headroom,
    evaluate_nested_claim_headroom,
    evaluate_nested_ordinary_headroom,
    evaluate_ordinary_headroom,
    evaluate_own_closeout_headroom,
    validate_cap_binding,
    validate_closing_claim_request,
    validate_closing_operation_binding,
    validate_limit_proposal,
)
from agent_lifecycle.contracts.schemas import get_schema


def _proposal(*, spent: int = 90, additional: int = 20, old: int = 100,
              disposition: str = "SUPERSEDE_BY_CLOSING_POLICY") -> dict:
    return {
        "scope": {"scopeKind": "RUN", "taskId": None},
        "participation": "CLOSING_ENABLED",
        "oldCap": {"kind": "FINITE", "value": old},
        "knownSpentAtAnchor": spent,
        "approvedAdditional": additional,
        "prospectiveCumulativeCeiling": spent + additional,
        "capDisposition": disposition,
        "priorViolationSetDigest": "a" * 64,
    }


def _frame(*, spent: int = 90, protected: int = 0) -> dict:
    return {
        "cumulativeSpent": spent,
        "activeReservations": 0,
        "protectedCloseout": protected,
        "windowSpent": 0,
        "windowReservations": 0,
        "windowProtectedCloseout": protected,
    }


class ClosingResourceTests(unittest.TestCase):
    def test_operation_and_claim_input_shapes_match_locked_resource_contract(self) -> None:
        contract_path = Path(__file__).resolve().parents[2] / 'tasks/release-2-16/cf-d-resource-contract.json'
        definitions = json.loads(contract_path.read_text())['wireContracts']['$defs']
        for schema_id, definition in ((OPERATION_BINDING_V1, 'ClosingOperationBinding'),
                                      (CLAIM_REQUEST_V1, 'ClaimRequest')):
            schema = get_schema(schema_id)
            self.assertEqual({key: schema[key] for key in ('type', 'required', 'properties', 'additionalProperties')},
                             definitions[definition])
        operation_schema = get_schema(OPERATION_BINDING_V1)
        for name in ('ArtifactRef', 'Owner', 'Unit'):
            self.assertEqual(operation_schema['$defs'][name], definitions[name])

        binding = {
            'schemaVersion': OPERATION_BINDING_V1, 'bindingId': 'binding', 'runId': 'run',
            'budgetScopeId': 'scope', 'closingWindowId': 'window', 'policyEffectDigest': 'a' * 64,
            'operationId': 'operation', 'nativeOperationRef': {'path': 'operation.json', 'sha256': 'b' * 64, 'bytes': 1},
            'nativeOperationDigest': 'c' * 64, 'action': 'final-audit',
            'owner': {'scopeKind': 'RUN', 'taskId': None},
            'unit': {'metric': 'reportedTokens', 'unitDefinitionId': 'unit',
                     'definitionDigest': 'd' * 64, 'sourceQualificationDigest': 'e' * 64},
            'upperBound': 10, 'expectedJournalRevision': 1,
            'expectedWorkflowRevision': 2, 'expectedAuthorityEpoch': 3,
            'expectedGuardStateDigest': 'f' * 64,
        }
        self.assertIs(validate_closing_operation_binding(binding), binding)
        for name, bad_value in (('action', []), ('upperBound', True), ('expectedJournalRevision', 2 ** 53),
                                ('nativeOperationDigest', 'A' * 64)):
            invalid = {**binding, name: bad_value}
            with self.subTest(name=name), self.assertRaises(LifecycleError):
                validate_closing_operation_binding(invalid)
        invalid_owner = copy.deepcopy(binding)
        invalid_owner['owner']['taskId'] = 'task'
        with self.assertRaises(LifecycleError):
            validate_closing_operation_binding(invalid_owner)
        with self.assertRaises(LifecycleError):
            validate_closing_operation_binding({**binding, 'callerPass': True})

        claim = {
            'schemaVersion': CLAIM_REQUEST_V1, 'bindingId': 'binding', 'budgetScopeId': 'scope',
            'closingWindowId': 'window', 'operationId': 'operation', 'closingOperationDigest': 'a' * 64,
            'claimId': 'claim', 'expectedJournalRevision': 1, 'expectedWorkflowRevision': 2,
            'expectedAuthorityEpoch': 3,
        }
        self.assertIs(validate_closing_claim_request(claim), claim)
        for name, bad_value in (('claimId', ''), ('expectedAuthorityEpoch', True),
                                ('closingOperationDigest', 'A' * 64)):
            with self.subTest(name=name), self.assertRaises(LifecycleError):
                validate_closing_claim_request({**claim, name: bad_value})
        with self.assertRaises(LifecycleError):
            validate_closing_claim_request({**claim, 'callerPass': True})

    def test_dr01_signed_addition_does_not_include_old_unused_headroom(self) -> None:
        proposal = _proposal()
        self.assertEqual(get_schema(LIMIT_PROPOSAL_V1)["$id"], LIMIT_PROPOSAL_V1)
        self.assertEqual(get_schema(CAP_BINDING_V1)["$id"], CAP_BINDING_V1)
        self.assertIs(validate_limit_proposal(proposal), proposal)
        allowed = evaluate_ordinary_headroom(proposal, _frame(), 20)
        self.assertEqual(allowed["disposition"], "DATA_CANDIDATE")
        self.assertEqual(allowed["cumulativeAfterUpperBound"], 110)
        self.assertIs(allowed["financialAdmission"], False)
        self.assertEqual(evaluate_ordinary_headroom(proposal, _frame(), 21)["disposition"], "REFUSED")

    def test_dr02_prior_overrun_is_not_rewritten_by_new_ceiling(self) -> None:
        proposal = _proposal(spent=120, additional=20)
        before = copy.deepcopy(proposal)
        result = evaluate_ordinary_headroom(proposal, _frame(spent=120), 20)
        self.assertEqual(result["disposition"], "DATA_CANDIDATE")
        self.assertEqual(proposal, before)
        self.assertEqual(proposal["oldCap"]["value"], 100)
        self.assertEqual(proposal["priorViolationSetDigest"], "a" * 64)

    def test_dr04_retained_cap_and_absent_inactive_task_stay_distinct(self) -> None:
        proposal = _proposal(disposition="RETAIN_BINDING")
        self.assertEqual(evaluate_ordinary_headroom(proposal, _frame(), 15)["disposition"], "REFUSED")
        retained = _proposal()
        retained.update(
            scope={"scopeKind": "TASK", "taskId": "task"}, participation="RETAIN_ONLY",
            oldCap={"kind": "ABSENT"}, approvedAdditional=None,
            prospectiveCumulativeCeiling=None, capDisposition="RETAIN_BINDING",
        )
        self.assertIs(validate_limit_proposal(retained), retained)
        self.assertEqual(validate_cap_binding(retained["oldCap"]), {"kind": "ABSENT"})
        with self.assertRaises(LifecycleError):
            evaluate_ordinary_headroom(retained, _frame(), 1)
        retained["participation"] = "CLOSING_ENABLED"
        with self.assertRaises(LifecycleError):
            validate_limit_proposal(retained)

    def test_dr03_task_cap_limits_same_single_run_attribution(self) -> None:
        run = _proposal(spent=90, additional=20)
        task = _proposal(spent=0, additional=5, old=0)
        task["scope"] = {"scopeKind": "TASK", "taskId": "task"}
        result = evaluate_nested_ordinary_headroom(run, _frame(), "task", task, _frame(spent=0), 6)
        self.assertEqual(result["run"]["disposition"], "DATA_CANDIDATE")
        self.assertEqual(result["task"]["disposition"], "REFUSED")
        self.assertEqual(result["disposition"], "REFUSED")
        self.assertIs(result["upperBoundCountedOnce"], True)
        with self.assertRaises(LifecycleError):
            evaluate_nested_ordinary_headroom(run, _frame(), "different", task, _frame(spent=0), 1)
        run_owned = evaluate_nested_ordinary_headroom(run, _frame(), None, None, None, 6)
        self.assertEqual(run_owned["disposition"], "DATA_CANDIDATE")
        self.assertIsNone(run_owned["task"])

    def test_dr06_dr18_missing_boolean_and_overflow_refuse(self) -> None:
        for change in ({"approvedAdditional": None}, {"knownSpentAtAnchor": True},
                       {"prospectiveCumulativeCeiling": 111}):
            proposal = {**_proposal(), **change}
            with self.subTest(change=change), self.assertRaises(LifecycleError):
                validate_limit_proposal(proposal)
        with self.assertRaises(LifecycleError):
            validate_cap_binding({"kind": "ABSENT", "value": 0})
        with self.assertRaises(LifecycleError):
            evaluate_ordinary_headroom(_proposal(), {**_frame(), "activeReservations": (1 << 63) - 1}, 1)

    def test_dr09_closeout_transfers_only_own_protected_window_balance(self) -> None:
        proposal = _proposal()
        frame = {**_frame(protected=14), "windowProtectedCloseout": 10}
        result = evaluate_own_closeout_headroom(proposal, frame, 8, 8, 8)
        self.assertEqual(result["disposition"], "DATA_CANDIDATE")
        self.assertEqual(result["protectedTransfer"], 8)
        self.assertEqual(result["cumulativeAfterTransfer"], 104)
        self.assertEqual(result["windowAfterTransfer"], 10)
        self.assertIs(result["financialAdmission"], False)
        self.assertEqual(evaluate_own_closeout_headroom(proposal, frame, 9, 8, 8)["disposition"], "REFUSED")
        self.assertEqual(evaluate_own_closeout_headroom(proposal, frame, 8, 0, 8)["disposition"], "REFUSED")

    def test_claim_rechecks_existing_reservation_without_double_charge(self) -> None:
        proposal = _proposal(spent=90, additional=10)
        frame = {**_frame(spent=92), "activeReservations": 8,
                 "windowSpent": 2, "windowReservations": 8}
        original = copy.deepcopy(frame)
        result = evaluate_claim_headroom(proposal, frame, 8)
        self.assertEqual(result["disposition"], "DATA_CANDIDATE")
        self.assertEqual(result["currentCumulativeBound"], 100)
        self.assertEqual(result["currentWindowBound"], 10)
        self.assertTrue(result["aggregateReservationCoversUpperBound"])
        self.assertTrue(result["requiresCurrentOperationMembership"])
        self.assertFalse(result["financialAdmission"])
        self.assertEqual(frame, original)
        late = evaluate_claim_headroom(proposal, {**frame, "cumulativeSpent": 93}, 8)
        self.assertEqual(late["disposition"], "REFUSED")
        self.assertEqual(late["currentCumulativeBound"], 101)
        missing = evaluate_claim_headroom(
            proposal, {**frame, "activeReservations": 0, "windowReservations": 0}, 8,
        )
        self.assertEqual(missing["disposition"], "REFUSED")
        self.assertFalse(missing["aggregateReservationCoversUpperBound"])

    def test_claim_respects_retained_cap_and_exact_nested_task(self) -> None:
        retained = _proposal(spent=90, additional=20, old=100, disposition="RETAIN_BINDING")
        frame = {**_frame(spent=95), "activeReservations": 6, "windowSpent": 5,
                 "windowReservations": 6}
        self.assertEqual(evaluate_claim_headroom(retained, frame, 6)["disposition"], "REFUSED")
        run = _proposal(spent=90, additional=20)
        task = {**_proposal(spent=0, additional=10),
                "scope": {"scopeKind": "TASK", "taskId": "task"}}
        run_frame = {**_frame(spent=90), "activeReservations": 10, "windowReservations": 10}
        task_frame = {**_frame(spent=0), "activeReservations": 10, "windowReservations": 10}
        nested = evaluate_nested_claim_headroom(run, run_frame, "task", task, task_frame, 10)
        self.assertEqual(nested["disposition"], "DATA_CANDIDATE")
        self.assertEqual(nested["run"]["currentCumulativeBound"], 100)
        self.assertEqual(nested["task"]["currentCumulativeBound"], 10)
        self.assertTrue(nested["upperBoundCountedOnce"])
        self.assertFalse(nested["financialAdmission"])
        with self.assertRaises(LifecycleError):
            evaluate_nested_claim_headroom(run, run_frame, "other", task, task_frame, 10)
        with self.assertRaises(LifecycleError):
            evaluate_claim_headroom(run, {**run_frame, "activeReservations": None}, 10)
        with self.assertRaises(LifecycleError):
            evaluate_claim_headroom(run, {**run_frame, "cumulativeSpent": (1 << 63) - 1}, 10)


class ClosingResourceCandidateTests(unittest.TestCase):
    @classmethod
    def _activation_inputs(cls):
        from tests.contracts.test_closing_window_schemas import _fixture
        inventory, proposal, before, anchor = cls._inputs()
        request = _fixture()["request"]
        request["scope"].update({key: inventory[key] for key in ("bindingId", "runId", "budgetScopeId", "journalIdentity")})
        request.update(expectedAccountingRevision=7, resourceApprovalDigest=canonical_digest(proposal))
        candidate = derive_policy_candidate_data(inventory, proposal, before, anchor)["candidate"]
        request["policyEffectCandidateDigest"] = canonical_digest(candidate)
        frames = []
        for task in (None, "inactive"):
            # Synthetic pre-activation/window projection, selected separately from candidate bytes.
            frames.append({"scope": {"scopeKind": "RUN" if task is None else "TASK", "taskId": task},
                           "unit": copy.deepcopy(inventory["unit"]), "closingWindowId": "window",
                           "beforePolicy": {"policyId": "policy", "revision": 1, "policyDigest": digest(asdict(before))}, "journalRevision": 7,
                           "cumulativeSpent": 120 if task is None else 0, "activeReservations": 0,
                           "oldCap": {"kind": "FINITE", "value": 100} if task is None else {"kind": "ABSENT"},
                           "currentProtection": 0, "reservationSetDigest": "2" * 64,
                           "violationSetDigest": "4" * 64, "guardSetDigest": canonical_digest([]),
                           "cumulativeCeiling": 140 if task is None else None,
                           "approvedAdditional": 20 if task is None else None,
                           "newGlobalUnspent": 10 if task is None else 0,
                           "newWindowUnspent": 10 if task is None else 0, "retainedOutsideWindow": 0,
                           "windowSpent": 0, "windowReservations": 0, "operationUpperBound": 0})
        return request, inventory, proposal, candidate, before, anchor, frames

    @staticmethod
    def _resource_data_bytes(args):
        policy = asdict(args[4]) if isinstance(args[4], BudgetPolicy) else args[4]
        return canonical_bytes([*args[:4], policy, *args[5:]])

    def _assert_resource_refusal(self, args):
        before = self._resource_data_bytes(args)
        with self.assertRaises(LifecycleError) as caught:
            evaluate_activation_resource_binding(*args)
        self.assertEqual(caught.exception.code, "activation-resource-binding-invalid")
        self.assertEqual(self._resource_data_bytes(args), before)

    def _saved_window_inputs(self, journal, member):
        from tests.accounting.test_journal import PROOF
        from tests.contracts.test_closing_window_schemas import _fixture
        snapshot = journal.snapshot("run")
        before = BudgetPolicy("policy", 1, 1000, {"task": 1000, "other": 1000}, {"task": 7, "other": 4, "": 3}, PROOF)
        inventory, proposal, _, anchor = self._inputs()
        inventory.update(budgetScopeId="run", taskIds=["task", "other"], unit={**inventory["unit"], "unitDefinitionId": "reportedTokens:fixture:v1"})
        owners = {"": snapshot.known_spent, "task": snapshot.tasks["task"]["known_spent"], "other": snapshot.tasks["other"]["known_spent"]}
        anchor.update(journalRevision=snapshot.journal_revision, spent=owners, reservations={key: 0 for key in owners},
                      protected={"": 3, "task": 7, "other": 4}, violationsByOwner={key: "5" * 64 for key in owners})
        proposal.update(budgetScopeId="run", inventoryDigest=canonical_digest(inventory), unit=copy.deepcopy(inventory["unit"]),
                        expectedJournalRevision=snapshot.journal_revision, expectedPolicy={"policyId": "policy", "revision": 1, "policyDigest": digest(asdict(before))})
        limits = [_proposal(spent=owners[""], additional=40, old=1000)]
        limits[0]["priorViolationSetDigest"] = "5" * 64
        for owner in ("task", "other"):
            limits.append({"scope": {"scopeKind": "TASK", "taskId": owner}, "participation": "RETAIN_ONLY",
                           "oldCap": {"kind": "FINITE", "value": 1000}, "knownSpentAtAnchor": owners[owner],
                           "approvedAdditional": None, "prospectiveCumulativeCeiling": None, "capDisposition": "RETAIN_BINDING", "priorViolationSetDigest": "5" * 64})
        proposal["limits"] = limits
        proposal["protectionAllocations"] = [{"owner": {"scopeKind": "RUN", "taskId": None}, "priorUnspent": 3, "retainedAssignedToWindow": 1, "addedForWindow": 6, "retainedOutsideWindow": 2}]
        for owner, amount in (("task", 7), ("other", 4)):
            proposal["protectionAllocations"].append({"owner": {"scopeKind": "TASK", "taskId": owner}, "priorUnspent": amount,
                                                       "retainedAssignedToWindow": 0, "addedForWindow": 0, "retainedOutsideWindow": amount})
        candidate = derive_policy_candidate_data(inventory, proposal, before, anchor)["candidate"]
        request = _fixture()["request"]; request["scope"].update(budgetScopeId="run")
        request.update(expectedAccountingRevision=snapshot.journal_revision, resourceApprovalDigest=canonical_digest(proposal), policyEffectCandidateDigest=canonical_digest(candidate))
        frames = []
        for owner in ("", "task", "other"):
            frames.append({"scope": {"scopeKind": "RUN" if not owner else "TASK", "taskId": owner or None}, "unit": copy.deepcopy(inventory["unit"]),
                           "closingWindowId": "window", "beforePolicy": {"policyId": "policy", "revision": 1, "policyDigest": digest(asdict(before))},
                           "journalRevision": snapshot.journal_revision, "cumulativeSpent": owners[owner], "activeReservations": 0,
                           "oldCap": {"kind": "FINITE", "value": 1000}, "currentProtection": anchor["protected"][owner],
                           "reservationSetDigest": "2" * 64, "violationSetDigest": "4" * 64, "guardSetDigest": canonical_digest([]),
                           "cumulativeCeiling": owners[""] + 40 if not owner else None, "approvedAdditional": 40 if not owner else None,
                           "newGlobalUnspent": 9 if not owner else anchor["protected"][owner], "newWindowUnspent": 7 if not owner else 0,
                           "retainedOutsideWindow": 2 if not owner else anchor["protected"][owner], "windowSpent": 0, "windowReservations": 0, "operationUpperBound": 0})
        args = (request, inventory, proposal, candidate, before, anchor, frames)
        current = {"kind": "SYNTHETIC_WINDOW_DATA_WITH_ORDINARY_FINANCIAL_FACTS", "window": "window", "policy": copy.deepcopy(frames[0]["beforePolicy"]),
                   "memberships": {member: {"owner": "task", "unit": "reportedTokens:fixture:v1"}}, "financialFacts": asdict(snapshot), "frames": frames,
                   "claims": [], "allowances": {"run": 0, "task": 0, "other": 0}, "nonces": [], "dispatchCount": 0}
        retired = copy.deepcopy(current); retired["window"] = "retired"; retired["policy"].update(revision=0, policyDigest="9" * 64)
        for frame in retired["frames"]: frame.update(closingWindowId=retired["window"], beforePolicy=copy.deepcopy(retired["policy"]))
        return args, current, retired

    def test_wr04_activation_resource_binding_and_each_mismatch(self):
        args = self._activation_inputs()
        saved = self._resource_data_bytes(args)
        result = evaluate_activation_resource_binding(*args)
        self.assertIs(result["dataBindingMatched"], True)
        self.assertEqual(result["candidateDigest"], canonical_digest(args[3]))
        self.assertEqual(result["disposition"], "DATA_CANDIDATE")
        self.assertTrue(all(result[key] is False for key in ("sourceAnchorQualified", "nativePolicyPersisted",
                        "nativeActivationGranted", "nativePermissionGranted", "financialAdmission", "nonceConsumed", "dispatchAuthorized")))
        replacements = {"closingWindowId": "retired", "beforePolicy": {"policyId": "foreign", "revision": 0, "policyDigest": "9" * 64}, "scope": {"scopeKind": "TASK", "taskId": "foreign"}, "unit": {}, "journalRevision": 8,
                        "cumulativeSpent": 121, "activeReservations": 1, "oldCap": {"kind": "FINITE", "value": 101},
                        "currentProtection": 1, "reservationSetDigest": "9" * 64, "violationSetDigest": "9" * 64,
                        "guardSetDigest": "9" * 64, "cumulativeCeiling": 141, "approvedAdditional": 21,
                        "newGlobalUnspent": 11, "newWindowUnspent": 11, "retainedOutsideWindow": 1,
                        "windowSpent": 1, "windowReservations": 1, "operationUpperBound": 1}
        for key, value in replacements.items():
            altered = copy.deepcopy(args); altered[6][0][key] = value
            with self.subTest(frame=key): self._assert_resource_refusal(altered)
        for key in ("journalRevision", "windowSpent", "windowReservations", "operationUpperBound", "currentProtection"):
            altered = copy.deepcopy(args); altered[6][0][key] = True
            with self.subTest(boolean=key): self._assert_resource_refusal(altered)
        for frames in (args[6][:1], args[6] + [args[6][0]], [args[6][0], args[6][0]], [None, args[6][1]]):
            altered = list(copy.deepcopy(args)); altered[6] = copy.deepcopy(frames)
            with self.subTest(frameSet=frames): self._assert_resource_refusal(altered)
        for index, key, value in ((0, "expectedAccountingRevision", True), (0, "closingWindowId", "retired"),
                                  (0, "predecessorWindowId", "other"), (2, "inventoryDigest", "9" * 64),
                                  (3, "proposalDigest", "9" * 64)):
            altered = copy.deepcopy(args); altered[index][key] = value
            with self.subTest(document=index, field=key): self._assert_resource_refusal(altered)
        for key in ("bindingId", "runId", "budgetScopeId", "journalIdentity"):
            altered = copy.deepcopy(args); altered[0]["scope"][key] = "other"
            with self.subTest(requestScope=key): self._assert_resource_refusal(altered)
        for index in (0, 1, 2, 3, 5, 6):
            altered = list(copy.deepcopy(args)); altered[index] = None
            with self.subTest(malformedTopLevel=index): self._assert_resource_refusal(altered)
        self.assertEqual(self._resource_data_bytes(args), saved)

    def _ordinary_journal(self, directory):
        from tests.accounting.test_journal import PROOF
        journal = Journal(Path(directory) / "ordinary.sqlite", PROOF)
        journal.open_scope(BudgetScope("run", "run", "reportedTokens:fixture:v1"),
                           BudgetPolicy("policy", 1, 1000, {"task": 1000, "other": 1000},
                                        {"task": 7, "other": 4, "": 3}, PROOF),
                           OpeningBalance("opening", "fixture:source", "reportedTokens:fixture:v1",
                                          {"task": 0, "other": 9}, 2, (), PROOF, PROOF))
        return journal

    def test_local_original_owner_settlement_cancellation_and_refund_data(self):
        from dataclasses import replace
        from tests.accounting.test_journal import PROOF, operation, receipt, open_scope
        pins = {"owner": "task", "unit": "reportedTokens:fixture:v1", "operation": "op"}
        with tempfile.TemporaryDirectory() as directory, self._ordinary_journal(directory) as journal:
            open_scope(journal, "unknown", spent=None, pending=None); unknown = journal.snapshot("unknown")
            op = operation(upper=8); initial = journal.snapshot("run")
            args, current, retired = self._saved_window_inputs(journal, pins["operation"])
            saved = copy.deepcopy((current, retired))
            self.assertEqual((op.task_id, op.unit_definition_id, op.operation_id), (pins["owner"], pins["unit"], pins["operation"]))
            result = evaluate_activation_resource_binding(*args)
            self.assertIs(result["financialAdmission"], False); self.assertEqual(journal.snapshot("run"), initial)
            self.assertEqual(journal.reserve(op), "RESERVED")
            self.assertEqual(journal.snapshot("run").tasks[pins["owner"]]["active_reservations"], 8)
            journal.claim("run", op.operation_id, op.binding_digest, "claim")
            charge = receipt(op, 5); self.assertEqual(charge.unit_definition_id, pins["unit"])
            self.assertEqual(journal.record_settlement(charge), "SETTLED"); settled = journal.snapshot("run")
            self.assertEqual((settled.known_spent - initial.known_spent, settled.tasks["task"]["known_spent"], settled.tasks["task"]["active_reservations"], settled.active_reservations), (5, 5, 0, 0))
            self.assertEqual(journal.record_settlement(charge), "ALREADY_SETTLED"); self.assertEqual(journal.snapshot("run"), settled)
            self.assertEqual(journal.record_settlement(receipt(op, 6)), "CONFLICT")
            conflicted = journal.snapshot("run")
            self.assertEqual((conflicted.known_spent, conflicted.tasks["task"]["known_spent"], conflicted.tasks["task"]["active_reservations"]), (settled.known_spent, 5, 0))
            self.assertIsNone(conflicted.tasks["task"]["spent"])
            with self.assertRaises(ValueError): replace(charge, reported_tokens=True)
            self.assertEqual(journal.snapshot("run"), conflicted); self.assertEqual(journal.snapshot("unknown"), unknown)
            other = conflicted.tasks["other"]
            self.assertEqual({key: other[key] for key in ("known_spent", "active_reservations", "protected_closeout")},
                             {key: initial.tasks["other"][key] for key in ("known_spent", "active_reservations", "protected_closeout")})
            self.assertIsNone(other["spent"]); self.assertEqual(conflicted.protected_closeout, initial.protected_closeout)
            self.assertEqual((current, retired), saved)
        with tempfile.TemporaryDirectory() as directory, self._ordinary_journal(directory) as journal:
            open_scope(journal, "unknown", spent=None, pending=None); unknown = journal.snapshot("unknown")
            op = operation(name="cancel", upper=8); initial = journal.snapshot("run")
            args, current, retired = self._saved_window_inputs(journal, "cancel"); saved = copy.deepcopy((current, retired))
            self.assertEqual((op.task_id, op.unit_definition_id), (pins["owner"], pins["unit"]))
            journal.reserve(op); held = journal.snapshot("run")
            self.assertEqual(held.tasks["task"]["active_reservations"], 8)
            with self.assertRaises(ValueError): journal.cancel_without_dispatch("run", op.operation_id, None)
            self.assertEqual(journal.snapshot("run"), held)
            self.assertEqual(journal.cancel_without_dispatch("run", op.operation_id, PROOF), "CANCELLED"); cancelled = journal.snapshot("run")
            self.assertEqual(journal.cancel_without_dispatch("run", op.operation_id, PROOF), "ALREADY_CANCELLED"); self.assertEqual(journal.snapshot("run"), cancelled)
            self.assertEqual((cancelled.known_spent, cancelled.active_reservations, cancelled.tasks["task"]["known_spent"], cancelled.tasks["task"]["active_reservations"]), (initial.known_spent, 0, 0, 0))
            self.assertEqual(cancelled.tasks["other"], initial.tasks["other"]); self.assertEqual(journal.snapshot("unknown"), unknown)
            self.assertEqual(cancelled.protected_closeout, initial.protected_closeout); self.assertEqual((current, retired), saved)
            self.assertEqual(current["memberships"], {"cancel": {"owner": pins["owner"], "unit": pins["unit"]}})
            self.assertTrue(all(value == 0 for value in current["allowances"].values()))
            newer = copy.deepcopy(current)
            for frame in newer["frames"]: frame["closingWindowId"] = "newer"
            altered = list(args); altered[6] = newer["frames"]; self._assert_resource_refusal(altered)
            self.assertNotIn("new-owner", cancelled.tasks); self.assertEqual(journal.events("new-run"), [])


    def test_local_current_retired_window_data_and_original_late_settlement(self):
        from tests.accounting.test_journal import operation, receipt, open_scope
        pins = {"owner": "task", "unit": "reportedTokens:fixture:v1", "operation": "late-original"}
        with tempfile.TemporaryDirectory() as directory, self._ordinary_journal(directory) as journal:
            open_scope(journal, "unknown", spent=None, pending=None); unknown = journal.snapshot("unknown")
            op = operation(name=pins["operation"], upper=8); initial = journal.snapshot("run")
            args, current, retired = self._saved_window_inputs(journal, pins["operation"])
            saved = copy.deepcopy((current, retired)); source_before = self._resource_data_bytes(args)
            self.assertEqual(current["memberships"], {pins["operation"]: {"owner": pins["owner"], "unit": pins["unit"]}})
            self.assertEqual((op.task_id, op.unit_definition_id), (pins["owner"], pins["unit"]))
            selected = list(args); selected[6] = current["frames"]
            result = evaluate_activation_resource_binding(*selected)
            self.assertEqual(result["disposition"], "DATA_CANDIDATE")
            self.assertTrue(all(result[key] is False for key in ("financialAdmission", "nativePolicyPersisted", "nonceConsumed", "dispatchAuthorized")))
            self.assertEqual(journal.snapshot("run"), initial)
            selected[6] = retired["frames"]; self._assert_resource_refusal(selected)
            for key in ("closingWindowId", "beforePolicy", "scope", "unit", "journalRevision"):
                altered = list(copy.deepcopy(args))
                altered[6][0][key] = copy.deepcopy(retired["frames"][0][key]) if key in ("closingWindowId", "beforePolicy") else {} if key in ("scope", "unit") else 0
                with self.subTest(savedIdentity=key): self._assert_resource_refusal(altered)
            journal.reserve(op); journal.claim("run", op.operation_id, op.binding_digest, "original-claim")
            self.assertEqual(journal.record_settlement(receipt(op, 5)), "SETTLED"); final = journal.snapshot("run")
            self.assertEqual(journal.record_settlement(receipt(op, 5)), "ALREADY_SETTLED"); self.assertEqual(journal.snapshot("run"), final)
            self.assertEqual((final.known_spent - initial.known_spent, final.tasks["task"]["known_spent"], final.tasks["task"]["active_reservations"]), (5, 5, 0))
            self.assertEqual(final.tasks["other"], initial.tasks["other"]); self.assertEqual(final.protected_closeout, initial.protected_closeout)
            self.assertEqual(journal.snapshot("unknown"), unknown); self.assertEqual((current, retired), saved)
            self.assertEqual(self._resource_data_bytes(args), source_before)
            stale = list(copy.deepcopy(args)); stale[5]["journalRevision"] = final.journal_revision
            self._assert_resource_refusal(stale)
            self.assertTrue(all(value == 0 for value in current["allowances"].values())); self.assertEqual(current["claims"], [])
            self.assertEqual((current["nonces"], current["dispatchCount"]), ([], 0)); self.assertNotIn("new-owner", final.tasks)


    @staticmethod
    def _inputs() -> tuple[dict, dict, BudgetPolicy, dict]:
        before = BudgetPolicy("policy", 1, 100, {}, {}, EvidenceRef("old", "a" * 64))
        unit = {"metric": "reportedTokens", "unitDefinitionId": "tokens", "definitionDigest": "a" * 64,
                "sourceQualificationDigest": "b" * 64}
        inventory = {"schemaVersion": "agent-closing-resource-inventory.v1", "bindingId": "binding",
                     "runId": "run", "budgetScopeId": "budget:run", "journalIdentity": "journal",
                     "unit": unit, "taskIds": ["inactive"], "requiredGuardBindings": [],
                     "operationRoutePolicyDigest": "c" * 64, "configurationDigest": "d" * 64,
                     "inventoryProducerQualificationRef": {"path": "inventory.json", "sha256": "e" * 64,
                                                           "bytes": 1}}
        anchor = {"journalRevision": 7, "openingCoverageDigest": "1" * 64,
                  "activeReservationSetDigest": "2" * 64, "protectionSetDigest": "3" * 64,
                  "priorViolationSetDigest": "4" * 64, "spent": {"": 120, "inactive": 0},
                  "reservations": {"": 0, "inactive": 0}, "protected": {"": 0, "inactive": 0},
                  "violationsByOwner": {"": "5" * 64, "inactive": "6" * 64}}
        run_limit = _proposal(spent=120, additional=20)
        run_limit["priorViolationSetDigest"] = anchor["violationsByOwner"][""]
        retained = {"scope": {"scopeKind": "TASK", "taskId": "inactive"},
                    "participation": "RETAIN_ONLY", "oldCap": {"kind": "ABSENT"},
                    "knownSpentAtAnchor": 0, "approvedAdditional": None,
                    "prospectiveCumulativeCeiling": None, "capDisposition": "RETAIN_BINDING",
                    "priorViolationSetDigest": anchor["violationsByOwner"]["inactive"]}
        proposal = {"schemaVersion": "agent-closing-resource-proposal.v1", "bindingId": "binding",
                    "runId": "run", "budgetScopeId": "budget:run", "journalIdentity": "journal",
                    "closingWindowId": "window", "predecessorWindowId": None,
                    "inventoryDigest": canonical_digest(inventory), "unit": unit,
                    "expectedJournalRevision": 7,
                    "expectedPolicy": {"policyId": "policy", "revision": 1,
                                       "policyDigest": digest(asdict(before))},
                    "nextPolicy": {"policyId": "policy", "revision": 2},
                    "openingCoverageDigest": anchor["openingCoverageDigest"],
                    "activeReservationSetDigest": anchor["activeReservationSetDigest"],
                    "protectionSetDigest": anchor["protectionSetDigest"],
                    "priorViolationSetDigest": anchor["priorViolationSetDigest"],
                    "requiredGuards": [], "limits": [run_limit, retained],
                    "protectionAllocations": [
                        {"owner": {"scopeKind": "RUN", "taskId": None}, "priorUnspent": 0,
                         "retainedAssignedToWindow": 0, "addedForWindow": 10,
                         "retainedOutsideWindow": 0},
                        {"owner": {"scopeKind": "TASK", "taskId": "inactive"}, "priorUnspent": 0,
                         "retainedAssignedToWindow": 0, "addedForWindow": 0,
                         "retainedOutsideWindow": 0},
                    ]}
        return inventory, proposal, before, anchor

    def test_absent_retained_task_stays_absent_and_overrun_is_preserved(self) -> None:
        inventory, proposal, before, anchor = self._inputs()
        result = derive_policy_candidate_data(inventory, proposal, before, anchor)
        candidate = result["candidate"]
        self.assertFalse(result["financialAdmission"])
        self.assertFalse(result["sourceAnchorQualified"])
        self.assertFalse(result["nativePolicyPersisted"])
        self.assertEqual(result["nativeAfterPolicy"]["run_cap"], 140)
        self.assertEqual(result["nativeAfterPolicy"]["task_caps"], {})
        self.assertEqual(result["nativeAfterPolicy"]["protected_closeout"], {"": 10})
        self.assertEqual(candidate["limits"][0]["oldExcess"], 20)
        self.assertIsNone(candidate["limits"][1]["oldExcess"])
        self.assertEqual(candidate["limits"][1]["resultingCoreCap"], {"kind": "ABSENT"})
        self.assertEqual(candidate["proposalDigest"], canonical_digest(proposal))
        self.assertEqual(result["candidateDigest"], canonical_digest(candidate))

    def test_closing_policy_event_replays_full_policy_without_clearing_sticky_gate(self) -> None:
        inventory, proposal, before, anchor = self._inputs()
        derived = derive_policy_candidate_data(inventory, proposal, before, anchor)
        candidate = derived["candidate"]
        before_native, after_native = asdict(before), derived["nativeAfterPolicy"]
        effect = {
            "schemaVersion": "agent-closing-resource-effect.v1",
            "candidateDigest": digest(candidate), "proposalDigest": digest(proposal),
            "runId": "run", "budgetScopeId": "budget:run", "closingWindowId": "window",
            "activationOperationId": "activation", "authorityDecisionDigest": "a" * 64,
            "grantDigest": "b" * 64, "beforeJournalRevision": 7, "afterJournalRevision": 8,
            "beforePolicy": candidate["beforePolicy"], "afterPolicy": candidate["afterPolicy"],
        }
        event = {"effect": effect, "candidate": candidate, "proposal": proposal,
                 "nativeBeforePolicy": before_native, "nativeAfterPolicy": after_native}
        original = {"scope": {"run_id": "run", "budget_scope_id": "budget:run"},
                    "policy": before_native, "protected": {}, "qualified": False,
                    "gate": "BOUND_BROKEN", "old_violations": ["retained"]}
        replayed = _apply(copy.deepcopy(original), "CLOSING_POLICY_APPLIED", event, revision=7)
        self.assertEqual(replayed["policy"], after_native)
        self.assertEqual(replayed["protected"], {"": 10})
        self.assertEqual((replayed["gate"], replayed["qualified"], replayed["old_violations"]),
                         ("BOUND_BROKEN", False, ["retained"]))
        for mutation in (
            {**event, "nativeAfterPolicy": {**after_native, "run_cap": 141}},
            {**event, "nativeBeforePolicy": {**before_native, "revision": 0}},
            {**event, "effect": {**effect, "afterJournalRevision": 9}},
            {**event, "proposal": {**proposal, "activeReservationSetDigest": "f" * 64}},
        ):
            with self.subTest(mutation=mutation), self.assertRaises(JournalUnavailable):
                _apply(copy.deepcopy(original), "CLOSING_POLICY_APPLIED", mutation, revision=7)
        with self.assertRaises(JournalUnavailable):
            _apply(copy.deepcopy(original), "CLOSING_POLICY_APPLIED", event, revision=6)
        with self.assertRaises(JournalUnavailable):
            _apply({**original, "gate": "CLOSED"}, "CLOSING_POLICY_APPLIED", event, revision=7)

    def test_internal_policy_event_rebuild_round_trip(self) -> None:
        inventory, proposal, before, anchor = self._inputs()
        inventory["taskIds"] = []
        proposal["inventoryDigest"] = digest(inventory)
        proposal["limits"] = proposal["limits"][:1]
        proposal["protectionAllocations"] = proposal["protectionAllocations"][:1]
        proposal["expectedJournalRevision"] = anchor["journalRevision"] = 1
        for field in ("spent", "reservations", "protected", "violationsByOwner"):
            anchor[field] = {"": anchor[field][""]}
        derived = derive_policy_candidate_data(inventory, proposal, before, anchor)
        candidate = derived["candidate"]
        effect = {
            "schemaVersion": "agent-closing-resource-effect.v1",
            "candidateDigest": digest(candidate), "proposalDigest": digest(proposal),
            "runId": "run", "budgetScopeId": "budget:run", "closingWindowId": "window",
            "activationOperationId": "synthetic-activation", "authorityDecisionDigest": "a" * 64,
            "grantDigest": "b" * 64, "beforeJournalRevision": 1, "afterJournalRevision": 2,
            "beforePolicy": candidate["beforePolicy"], "afterPolicy": candidate["afterPolicy"],
        }
        event = {"effect": effect, "candidate": candidate, "proposal": proposal,
                 "nativeBeforePolicy": asdict(before), "nativeAfterPolicy": derived["nativeAfterPolicy"]}
        evidence = EvidenceRef("synthetic", "a" * 64)
        with tempfile.TemporaryDirectory() as directory, Journal(Path(directory) / "journal.db", evidence) as journal:
            self.assertEqual(journal.open_scope(
                BudgetScope("budget:run", "run", "tokens"), before,
                OpeningBalance("opening", "source", "tokens", {}, 120, (), evidence, evidence),
            ), "OPENED")
            with journal._transaction():
                state, revision = journal._load("budget:run")
                self.assertEqual(revision, 1)
                journal._record("budget:run", state, revision, "CLOSING_POLICY_APPLIED", event)
            self.assertEqual(journal.snapshot("budget:run").journal_revision, 2)
            self.assertEqual(journal.rebuild("budget:run").journal_revision, 2)
            self.assertEqual(journal._load("budget:run")[0]["policy"], derived["nativeAfterPolicy"])

    def test_mutated_source_or_retained_task_entitlement_is_refused(self) -> None:
        inventory, proposal, before, anchor = self._inputs()
        for mutated_proposal, mutated_anchor in (
            (proposal, {**anchor, "spent": {"": 119, "inactive": 0}}),
            ({**proposal, "limits": proposal["limits"][:1]}, anchor),
            ({**proposal, "protectionAllocations": [
                proposal["protectionAllocations"][0],
                {**proposal["protectionAllocations"][1], "addedForWindow": 1},
            ]}, anchor),
            ({**proposal, "limits": [{**proposal["limits"][0], "capDisposition": "RETAIN_BINDING"},
                                   proposal["limits"][1]]}, anchor),
        ):
            with self.subTest(mutated_proposal=mutated_proposal, mutated_anchor=mutated_anchor), \
                    self.assertRaises(LifecycleError):
                derive_policy_candidate_data(inventory, mutated_proposal, before, mutated_anchor)

    def test_run_window_counts_task_protection_once_inside_same_total(self) -> None:
        inventory, proposal, _, anchor = self._inputs()
        before = BudgetPolicy("policy", 1, 100, {"inactive": 0}, {}, EvidenceRef("old", "a" * 64))
        proposal["expectedPolicy"]["policyDigest"] = digest(asdict(before))
        proposal["limits"][1] = {
            **proposal["limits"][1], "participation": "CLOSING_ENABLED",
            "oldCap": {"kind": "FINITE", "value": 0},
            "approvedAdditional": 20, "prospectiveCumulativeCeiling": 20,
            "capDisposition": "SUPERSEDE_BY_CLOSING_POLICY",
        }
        proposal["protectionAllocations"][1]["addedForWindow"] = 15
        with self.assertRaises(LifecycleError):
            derive_policy_candidate_data(inventory, proposal, before, anchor)
        proposal["protectionAllocations"][1]["addedForWindow"] = 10
        result = derive_policy_candidate_data(inventory, proposal, before, anchor)
        self.assertEqual(result["nativeAfterPolicy"]["task_caps"], {"inactive": 20})
        self.assertEqual(result["nativeAfterPolicy"]["protected_closeout"], {"": 10, "inactive": 10})
        self.assertFalse(result["financialAdmission"])

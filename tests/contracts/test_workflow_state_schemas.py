from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.canonical import canonical_digest
from agent_lifecycle.contracts.schemas import get_schema
from agent_lifecycle.contracts.workflow_authority_schemas import RUN_OUTPUT_ANCHOR_V1, validate_run_output_anchor
from agent_lifecycle.contracts.workflow_state_schemas import (
    ADOPTION_INPUT_V1,
    ADOPTION_SELECTION_V1,
    COMMITTED_RESULT_V1,
    PROJECTION_STATUS_V1,
    TRANSITION_REQUEST_V1,
    WORKFLOW_STATE_V4,
    validate_adoption_input,
    validate_adoption_selection,
    validate_committed_result,
    validate_projection_status,
    validate_transition_request,
    validate_workflow_state,
)


def _state() -> dict:
    return {
        "schemaVersion": WORKFLOW_STATE_V4,
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "stateRevision": 1,
        "phase": "RUNNING",
        "eventLog": "events.jsonl",
        "operationLedger": {},
        "tasks": [
            {
                "id": "WS-01",
                "status": "READY",
                "attempt": 0,
                "dependsOn": [],
                "attemptHistory": [],
                "required": True,
            }
        ],
    }


def _a5_policy(requirement: str = "NONE") -> dict:
    policy = {
        "schemaVersion": "agent-a5-limited-policy.v1",
        "mode": "A5_LIMITED",
        "adapterId": "codex",
        "expectationId": "a5:codex",
        "targetVersion": "0.155.1",
        "entrySurface": "ALK_TASK_START",
        "frozenTaskRequirement": requirement,
        "boundaryRecordDigest": "a" * 64,
        "strongAdmissionSupported": False,
    }
    policy["policyDigest"] = canonical_digest(policy)
    return policy


def _marked_state(requirement: str = "NONE") -> dict:
    state = _state()
    state["immutableInput"] = {
        "schemaVersion": "agent-a5-plan-policy.v1",
        "mode": "A5_LIMITED",
        "defaultRequirement": requirement,
        "contractDigest": "b" * 64,
    }
    state["tasks"][0]["immutableInput"] = _a5_policy(requirement)
    return state


def _admission(state: dict) -> dict:
    policy = state["tasks"][0]["immutableInput"]
    decision = {
        "schemaVersion": "agent-a5-limited-decision.v1",
        "subject": {
            "runId": state["runId"],
            "packageId": state["packageId"],
            "taskId": "WS-01",
            "targetAttempt": 1,
            "operationId": "task-start",
            "stateRevision": 1,
            "planDigest": state["planDigest"],
            "sourceRevision": state["sourceRevision"],
        },
        "policyDigest": policy["policyDigest"],
        "boundaryRecordDigest": policy["boundaryRecordDigest"],
        "requestDigest": "c" * 64,
        "effectiveRequirement": "NONE",
        "disposition": "ORDINARY_NO_A5",
        "reason": "NO_STRONG_REQUIREMENT",
        "strongProtectionGranted": False,
        "scope": "ALK_ADMISSION_CLASSIFICATION_ONLY",
    }
    decision["decisionDigest"] = canonical_digest(decision)
    return decision


class WorkflowStateSchemaTests(unittest.TestCase):
    def test_run_output_anchor_matches_governing_wire_contract(self) -> None:
        plan = Path(__file__).resolve().parents[2] / "tasks/release-2-16/cf-d-window-request-contract.json"
        expected = json.loads(plan.read_text())["wireContracts"]["adoptedRunOutputAnchor"]
        self.assertEqual(get_schema(RUN_OUTPUT_ANCHOR_V1), expected)
        anchor = {
            "schemaVersion": RUN_OUTPUT_ANCHOR_V1,
            "bindingDigest": "a" * 64,
            "runId": "run",
            "adoptedStateDigest": "b" * 64,
            "journalIdentity": "journal",
            "storageProtocolVersion": "6",
            "artifactAuthorityRootPath": "/held/root",
            "artifactAuthorityRootIdentity": {"platform": "POSIX", "volumeId": "volume", "fileId": "file"},
            "canonicalStatePath": "work/run/state.json",
            "packageRoot": "/held/root/package",
            "resolvedPackageRootRelativePath": "package",
            "eventLog": "work/run/events.jsonl",
            "runOutputRootRelativePath": "package/.alk-closing/run",
        }
        self.assertIs(validate_run_output_anchor(anchor), anchor)
        for change in (
            {"storageProtocolVersion": "5"},
            {"bindingDigest": "A" * 64},
            {"artifactAuthorityRootIdentity": {"platform": "OTHER", "volumeId": "volume", "fileId": "file"}},
            {"runOutputRootRelativePath": ""},
            {"unexpected": True},
        ):
            with self.subTest(change=change), self.assertRaises(LifecycleError):
                validate_run_output_anchor({**anchor, **change})

    def test_committed_result_and_projection_status_keep_permission_separate(self) -> None:
        ref = {"path": "result.json", "sha256": "a" * 64, "bytes": 10}
        committed = {
            "schemaVersion": COMMITTED_RESULT_V1, "runId": "run", "operationId": "op",
            "requestDigest": "b" * 64, "beforeRevision": 1, "afterRevision": 2,
            "stateDigest": "c" * 64, "eventBundleDigest": "d" * 64,
            "semanticResultRef": ref, "closingWindowId": None, "policyEventId": None,
            "projectionGeneration": 2, "authorityDecisionRef": None,
            "resourcePolicyEffectRef": None, "deadlineDecisionRef": None,
            "clockObservationRef": None, "committedProofEnvelopeRef": None,
        }
        committed["resultDigest"] = canonical_digest(committed)
        self.assertEqual(get_schema(COMMITTED_RESULT_V1)["$id"], COMMITTED_RESULT_V1)
        self.assertIs(validate_committed_result(committed), committed)
        for invalid in (
            {**committed, "afterRevision": 3},
            {**committed, "beforeRevision": True},
            {**committed, "resultDigest": "0" * 64},
            {**committed, "nativePermissionGranted": True},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(LifecycleError):
                validate_committed_result(invalid)
        projection = {
            "schemaVersion": PROJECTION_STATUS_V1, "runId": "run", "workflowRevision": 2,
            "generation": 2, "stateDigest": "c" * 64, "eventBundleDigest": "d" * 64,
            "status": "PENDING", "ackRef": None, "committedProofEnvelopeRef": None,
        }
        self.assertEqual(get_schema(PROJECTION_STATUS_V1)["$id"], PROJECTION_STATUS_V1)
        self.assertIs(validate_projection_status(projection), projection)
        self.assertIs(validate_projection_status({**projection, "status": "ACK", "ackRef": ref})["ackRef"], ref)
        for invalid in (
            {**projection, "status": "ACK"},
            {**projection, "ackRef": ref},
            {**projection, "status": []},
            {**projection, "generation": True},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(LifecycleError):
                validate_projection_status(invalid)

    def test_transition_request_is_closed_data_without_native_permission(self) -> None:
        ref = {"path": "proof.json", "sha256": "a" * 64, "bytes": 10}
        request = {
            "schemaVersion": TRANSITION_REQUEST_V1,
            "binding": {"bindingId": "binding", "expectedBindingDigest": "b" * 64},
            "operationId": "transition-1", "requestDigest": "c" * 64,
            "expectedWorkflowRevision": 3,
            "expectedAccountingRevisions": [{"budgetScopeId": "budget:run", "revision": 5}],
            "action": "activateClosingWindow", "eventType": "closing-window-activated",
            "nextStateRef": ref, "eventBundleRef": ref, "semanticResultRef": ref,
            "authorityContextRef": ref, "activationEffect": None, "preparedProofInputRef": None,
        }
        self.assertEqual(get_schema(TRANSITION_REQUEST_V1)["$id"], TRANSITION_REQUEST_V1)
        self.assertIs(validate_transition_request(request), request)
        variants = [
            {**request, "nativePermissionGranted": True},
            {**request, "expectedWorkflowRevision": True},
            {**request, "requestDigest": "C" * 64},
            {**request, "expectedAccountingRevisions": [
                {"budgetScopeId": "budget:run", "revision": 5},
                {"budgetScopeId": "budget:run", "revision": 6},
            ]},
            {**request, "nextStateRef": {**ref, "bytes": 8_388_609}},
            {**request, "activationEffect": {"closingWindowId": "window"}},
        ]
        for selected in variants:
            with self.subTest(selected=selected), self.assertRaises(LifecycleError) as raised:
                validate_transition_request(copy.deepcopy(selected))
            self.assertEqual(raised.exception.code, "workflow-transition-invalid")

    def test_adoption_wire_shapes_are_closed_and_do_not_qualify_operator(self) -> None:
        ref = {"path": "proof.json", "sha256": "a" * 64, "bytes": 10}
        adoption = {
            "schemaVersion": ADOPTION_INPUT_V1, "operationId": "adopt-1", "bindingRef": ref,
            "legacyStateRef": ref, "legacyEventLogRef": None, "initialSnapshotRef": ref,
            "accountingMode": "EXISTING_QUALIFIED_SCOPE",
        }
        selection = {
            "schemaVersion": ADOPTION_SELECTION_V1,
            "expectedBindingDigest": "b" * 64, "expectedPinDigest": "c" * 64,
            "expectedInitialSnapshotDigest": "d" * 64, "expectedAccountingStateDigest": "e" * 64,
            "expectedAccountingRevision": 4, "expectedJournalIdentity": "journal",
            "expectedBudgetScopeId": "budget:run", "expectedStorageProtocolVersion": "5",
            "expectedWorkflowProtocolVersion": "1", "operatorQualificationRef": ref,
            "quiescenceEvidenceRef": ref, "writerInventoryRef": ref,
        }
        for name, value, validator in (
            (ADOPTION_INPUT_V1, adoption, validate_adoption_input),
            (ADOPTION_SELECTION_V1, selection, validate_adoption_selection),
        ):
            self.assertEqual(get_schema(name)["$id"], name)
            self.assertIs(validator(value), value)
            with self.subTest(name=name), self.assertRaises(LifecycleError):
                validator({**value, "operatorQualified": True})
        for invalid in (
            {**adoption, "accountingMode": "NEW_SCOPE"},
            {**adoption, "legacyEventLogRef": {**ref, "bytes": -1}},
        ):
            with self.assertRaises(LifecycleError):
                validate_adoption_input(invalid)
        for invalid in (
            {**selection, "expectedAccountingRevision": True},
            {**selection, "expectedPinDigest": "A" * 64},
            {**selection, "expectedStorageProtocolVersion": "4"},
        ):
            with self.assertRaises(LifecycleError):
                validate_adoption_selection(invalid)

    def test_v4_schema_is_registered_and_validates(self) -> None:
        self.assertEqual(get_schema(WORKFLOW_STATE_V4)["$id"], WORKFLOW_STATE_V4)
        self.assertEqual(validate_workflow_state(_state())["schemaVersion"], WORKFLOW_STATE_V4)

    def test_unknown_task_status_fails_closed(self) -> None:
        state = _state()
        state["tasks"][0]["status"] = "VALIDATING"
        with self.assertRaises(LifecycleError) as raised:
            validate_workflow_state(state)
        self.assertEqual(raised.exception.code, "invalid-workflow-state")

    def test_final_audit_requires_all_required_tasks(self) -> None:
        state = _state()
        state["phase"] = "FINAL_AUDIT"
        with self.assertRaises(LifecycleError):
            validate_workflow_state(state)

    def test_event_log_rejects_escape_and_platform_aliases(self) -> None:
        for path in (
            "../events.jsonl",
            "./events.jsonl",
            "a/../events.jsonl",
            "C:events.jsonl",
            "events.jsonl:stream",
            "//server/share",
            "a\\events.jsonl",
            "bad\ud800path",
        ):
            state = _state()
            state["eventLog"] = path
            with self.subTest(path=repr(path)), self.assertRaises(LifecycleError) as raised:
                validate_workflow_state(state)
            self.assertEqual(raised.exception.code, "invalid-workflow-state")
            self.assertNotIn(path, raised.exception.message)

    def test_package_root_preserves_parent_anchors_without_granting_containment(self) -> None:
        for root in (".", "..", "../..", "../../project", "project/work"):
            state = _state()
            state["packageRoot"] = root
            with self.subTest(root=root):
                self.assertIs(validate_workflow_state(state), state)

    def test_package_root_rejects_ambiguous_anchors(self) -> None:
        for root in (
            "",
            "/tmp",
            "C:root",
            "a/../b",
            "../",
            "../a:stream",
            "../a\\b",
            ".././a",
            "//server/share",
            "bad\ud800path",
            "../" * 2000,
        ):
            state = _state()
            state["packageRoot"] = root
            with self.subTest(root=repr(root)), self.assertRaises(LifecycleError) as raised:
                validate_workflow_state(state)
            self.assertEqual(raised.exception.code, "invalid-workflow-state")

    def test_marked_state_requires_closed_task_policy(self) -> None:
        state = _marked_state()
        self.assertIs(validate_workflow_state(state), state)
        del state["tasks"][0]["immutableInput"]
        with self.assertRaises(LifecycleError):
            validate_workflow_state(state)
        state = _state()
        state["tasks"][0]["immutableInput"] = _a5_policy()
        with self.assertRaises(LifecycleError):
            validate_workflow_state(state)

    def test_frozen_strong_default_cannot_be_lowered(self) -> None:
        state = _marked_state("STRONG_A5")
        self.assertIs(validate_workflow_state(state), state)
        state["tasks"][0]["immutableInput"] = _a5_policy("NONE")
        with self.assertRaises(LifecycleError):
            validate_workflow_state(state)

    def test_successful_start_binds_original_decision(self) -> None:
        state = _marked_state()
        state["tasks"][0].update(status="RUNNING", attempt=1, immutableInputAdmission=_admission(state))
        self.assertIs(validate_workflow_state(state), state)
        state["tasks"][0]["immutableInputAdmission"]["subject"]["taskId"] = "different"
        with self.assertRaises(LifecycleError):
            validate_workflow_state(state)

    def test_strong_frozen_task_cannot_carry_ordinary_admission(self) -> None:
        state = _marked_state("STRONG_A5")
        state["tasks"][0].update(status="RUNNING", attempt=1, immutableInputAdmission=_admission(state))
        with self.assertRaises(LifecycleError) as raised:
            validate_workflow_state(state)
        self.assertEqual(raised.exception.code, "a5-context-invalid")

    def test_strong_frozen_task_cannot_be_forged_as_accepted(self) -> None:
        state = _marked_state("STRONG_A5")
        state["tasks"][0].update(status="ACCEPTED", attempt=1)
        with self.assertRaises(LifecycleError) as raised:
            validate_workflow_state(state)
        self.assertEqual(raised.exception.code, "a5-context-invalid")

    def test_admission_keeps_actual_attempt(self) -> None:
        state = _marked_state()
        state["tasks"][0].update(status="RUNNING", attempt=2, immutableInputAdmission=_admission(state))
        with self.assertRaises(LifecycleError) as raised:
            validate_workflow_state(state)
        self.assertEqual(raised.exception.code, "a5-context-invalid")

    def test_legacy_adoption_retains_no_fabricated_admission(self) -> None:
        state = _marked_state()
        state["tasks"][0].update(status="ACCEPTED", attempt=1)
        policy = state["tasks"][0]["immutableInput"]
        binding = {
            "schemaVersion": "agent-a5-adoption-binding.v1",
            "runId": state["runId"],
            "taskId": "WS-01",
            "actualAttempt": 1,
            "originalPlanDigest": "d" * 64,
            "currentPlanDigest": state["planDigest"],
            "originalPolicyDigest": None,
            "currentPolicyDigest": policy["policyDigest"],
            "originalDecisionDigest": None,
            "compatibilityReceiptDigest": "e" * 64,
            "classification": "PRESERVED_LEGACY_NO_A5",
            "strongProtectionGranted": False,
        }
        binding["bindingDigest"] = canonical_digest(binding)
        state["tasks"][0]["immutableInputAdoption"] = binding
        self.assertIs(validate_workflow_state(state), state)
        state["tasks"][0]["immutableInputAdmission"] = _admission(state)
        with self.assertRaises(LifecycleError):
            validate_workflow_state(state)


if __name__ == "__main__":
    unittest.main()

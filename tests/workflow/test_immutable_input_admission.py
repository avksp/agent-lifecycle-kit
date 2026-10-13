"""Frozen policy checks and real public task-start denial before mutation."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.canonical import canonical_bytes
from agent_lifecycle.contracts.immutable_input_schemas import validate_a5_boundary_registry
from agent_lifecycle.planning.task_compatibility import build_task_plan_compatibility_receipt
from agent_lifecycle.workflow.immutable_input import (
    evaluate_task_admission,
    is_unadopted_ordinary_context,
    require_task_consumer_admission,
)
from agent_lifecycle.workflow.task_start import start_task
from agent_lifecycle.workflow.task_transitions import accept_task, commit_task_result
from tests.contracts import test_immutable_input_schemas as fixture
from tests.workflow import helpers
from tests.workflow import test_plan_adoption as adoption

ROOT = Path(__file__).resolve().parents[2]


def marked(requirement="NONE"):
    registry = json.loads((ROOT / "profiles/immutable-input-adapter-capabilities.v1.json").read_text())
    record = registry["records"][0]
    policy = fixture.policy()
    policy.update({key: record[key] for key in ("adapterId", "expectationId", "targetVersion", "boundaryRecordDigest")})
    policy["frozenTaskRequirement"] = requirement
    fixture.sealed(policy, "policyDigest")
    plan = {"schemaVersion": "agent-a5-plan-policy.v1", "mode": "A5_LIMITED", "defaultRequirement": requirement, "contractDigest": "a" * 64}
    task = {"id": "task", "immutableInput": policy}
    manifest = {"immutableInput": plan, "workstreams": [task]}
    state = {"immutableInput": copy.deepcopy(plan)}
    return manifest, state, copy.deepcopy(task), registry


def accepted_marked_fixture(root):
    state_path = helpers._write_state(root, phase="BLOCKED", blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"})
    plan, policy, registry = adoption._a5_policies()
    manifest = adoption._write_authority_bundle(root, global_fields={"immutableInput": plan}, task_fields={"immutableInput": policy})
    boundary = root / "profiles/immutable-input-adapter-capabilities.v1.json"
    boundary.parent.mkdir()
    boundary.write_text(json.dumps(registry))
    adoption._adopt_authority_bundle(state_path, manifest)
    helpers.start_execution(state_path, operation_id="run", expected_revision=2, source_revision="source-2", reason="test")
    start_task(state_path, task_id="WS-01", operation_id="ordinary", expected_revision=3, source_revision="source-2", reason="test")
    state = json.loads(state_path.read_text())
    # Accepted status is a controlled unit fixture, not a claimed public acceptance.
    state["tasks"][0]["status"] = "ACCEPTED"
    state["tasks"][0]["usageTotals"] = {"tokensIn": 101, "tokensOut": 37, "billableTokens": 138, "elapsedSeconds": 13}
    state_path.write_bytes(canonical_bytes(state) + b"\n")
    return state_path, plan, policy


def accepted_unmarked_fixture(root, *, pre_execution_repeat=False):
    state_path = helpers._write_state(root, phase="BLOCKED", blocker={
        "code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"})
    manifest = adoption._write_authority_bundle(root)
    adoption._adopt_authority_bundle(state_path, manifest)
    if pre_execution_repeat:
        adoption.adoption_module.adopt_plan(state_path, manifest_path=manifest, operation_id="unstarted-repeat",
            expected_revision=2, source_revision="source-2", reset_tasks=False,
            preserve_accepted_compatible=False, start_mode="auto-after-freeze", authorized_by="test")
    revision = json.loads(state_path.read_text())["stateRevision"]
    helpers.start_execution(state_path, operation_id="legacy-run", expected_revision=revision,
        source_revision="source-2", reason="test")
    start_task(state_path, task_id="WS-01", operation_id="legacy-start", expected_revision=revision + 1,
        source_revision="source-2", reason="test")
    state = json.loads(state_path.read_text())
    # Accepted status is a unit fixture; the unmarked native start is real.
    state["tasks"][0]["status"] = "ACCEPTED"
    state["tasks"][0]["usageTotals"] = {"billableTokens": 138}
    state_path.write_bytes(canonical_bytes(state) + b"\n")
    plan, policy, registry = adoption._a5_policies()
    boundary = root / "profiles/immutable-input-adapter-capabilities.v1.json"
    boundary.parent.mkdir()
    boundary.write_text(json.dumps(registry))
    return state_path, plan, policy


def successor_fixture(root, plan, policy, revision, *, task_id="WS-01", marked_input=True):
    manifest_path = root / "plans/package/plan.manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["planRevision"] = revision
    if marked_input:
        manifest["immutableInput"] = copy.deepcopy(plan)
        manifest["workstreams"][0]["immutableInput"] = copy.deepcopy(policy)
    else:
        manifest.pop("immutableInput", None)
        manifest["workstreams"][0].pop("immutableInput", None)
    manifest["workstreams"][0]["id"] = task_id
    manifest_path.write_bytes(canonical_bytes(manifest) + b"\n")
    digest = canonical_digest(manifest)
    (root / manifest["package"]["planArtifactRoot"] / "plan.lock.json").write_bytes(canonical_bytes({"schemaVersion": "agent-plan-lock.v1", "planRevision": revision, "manifestHash": digest}) + b"\n")
    index_path = root / "plans/package/workflow/task-packets/index.json"
    index = json.loads(index_path.read_text())
    index["manifestDigest"] = digest
    index["packets"][0]["taskId"] = task_id
    index_path.write_bytes(canonical_bytes(index) + b"\n")
    return manifest_path


class A5TaskAdmissionTests(unittest.TestCase):
    def test_unstarted_same_plan_snapshot_does_not_hide_accepted_legacy_attempt(self):
        from agent_lifecycle.workflow.plan_adoption import adopt_plan

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, plan, policy = accepted_unmarked_fixture(root, pre_execution_repeat=True)
            original_plan = json.loads(state_path.read_text())["planDigest"]
            for revision, marked_input in ((3, False), (4, True)):
                manifest = successor_fixture(root, plan, policy, revision, marked_input=marked_input)
                state = json.loads(state_path.read_text())
                adopt_plan(state_path, manifest_path=manifest, operation_id="preserve-" + str(revision),
                    expected_revision=state["stateRevision"], source_revision="source-2", reset_tasks=True,
                    preserve_accepted_compatible=True, start_mode="auto-after-freeze", authorized_by="test")
            task = json.loads(state_path.read_text())["tasks"][0]
            self.assertEqual(task["status"], "ACCEPTED")
            self.assertEqual(task["immutableInputAdoption"]["originalPlanDigest"], original_plan)
            self.assertEqual(task["usageTotals"]["billableTokens"], 138)

    def test_marked_legacy_binding_still_requires_intermediate_native_history(self):
        from agent_lifecycle.workflow.events import event_log_path
        from agent_lifecycle.workflow.plan_adoption import adopt_plan

        for missing in ("operation", "event", "receipt", "snapshot"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state_path, plan, policy = accepted_unmarked_fixture(root)
                for revision, marked_input in ((3, False), (4, True)):
                    manifest = successor_fixture(root, plan, policy, revision, marked_input=marked_input)
                    state = json.loads(state_path.read_text())
                    adopt_plan(state_path, manifest_path=manifest, operation_id="history-" + str(revision),
                        expected_revision=state["stateRevision"], source_revision="source-2", reset_tasks=True,
                        preserve_accepted_compatible=True, start_mode="auto-after-freeze", authorized_by="test")
                state = json.loads(state_path.read_text())
                if missing == "operation":
                    del state["operationLedger"]["history-3"]
                elif missing == "receipt":
                    snapshot = next(s for s in state["priorSnapshots"] if s["planRevision"] == 3)
                    del snapshot["tasks"][0]["planCompatibilityReceipt"]
                elif missing == "snapshot":
                    state["priorSnapshots"] = [s for s in state["priorSnapshots"] if s["planRevision"] != 3]
                else:
                    journal = event_log_path(state_path, state)
                    events = [json.loads(line) for line in journal.read_bytes().splitlines()]
                    journal.write_bytes(b"".join(canonical_bytes(event) + b"\n" for event in events
                        if event.get("operationId") != "history-3"))
                state_path.write_bytes(canonical_bytes(state) + b"\n")
                manifest = successor_fixture(root, plan, policy, 5)
                before = adoption._tree_bytes(root)
                with patch.object(adoption.adoption_module, "commit_state") as commit, self.assertRaises(LifecycleError) as raised:
                    adopt_plan(state_path, manifest_path=manifest, operation_id="missing-intermediate-" + missing,
                        expected_revision=state["stateRevision"], source_revision="source-2", reset_tasks=True,
                        preserve_accepted_compatible=True, start_mode="auto-after-freeze", authorized_by="test")
                self.assertEqual(raised.exception.code, "a5-context-invalid")
                commit.assert_not_called()
                self.assertEqual(adoption._tree_bytes(root), before)

    def test_unmarked_adoption_chain_preserves_true_start_plan_and_requires_original_proof(self):
        from agent_lifecycle.workflow.events import event_log_path
        from agent_lifecycle.workflow.plan_adoption import adopt_plan

        for missing in (None, "start", "operation", "compatibility-operation"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state_path, plan, policy = accepted_unmarked_fixture(root)
                original_plan = json.loads(state_path.read_text())["planDigest"]
                for revision in (3, 4):
                    manifest = successor_fixture(root, plan, policy, revision, marked_input=False)
                    state = json.loads(state_path.read_text())
                    adopt_plan(state_path, manifest_path=manifest, operation_id="unmarked-" + str(revision),
                        expected_revision=state["stateRevision"], source_revision="source-2", reset_tasks=True,
                        preserve_accepted_compatible=True, start_mode="auto-after-freeze", authorized_by="test")
                    self.assertNotIn("immutableInputAdoption", json.loads(state_path.read_text())["tasks"][0])
                state = json.loads(state_path.read_text())
                if missing in ("operation", "compatibility-operation"):
                    del state["operationLedger"]["legacy-start" if missing == "operation" else "unmarked-3"]
                    state_path.write_bytes(canonical_bytes(state) + b"\n")
                elif missing == "start":
                    journal = event_log_path(state_path, state)
                    events = [json.loads(line) for line in journal.read_bytes().splitlines()]
                    journal.write_bytes(b"".join(canonical_bytes(event) + b"\n" for event in events
                        if event.get("eventType") != "task-started"))
                for revision in (5, 6):
                    manifest = successor_fixture(root, plan, policy, revision)
                    state = json.loads(state_path.read_text())
                    if missing is not None:
                        before = adoption._tree_bytes(root)
                        with patch.object(adoption.adoption_module, "commit_state") as commit, self.assertRaises(LifecycleError) as raised:
                            adopt_plan(state_path, manifest_path=manifest, operation_id="marked-" + str(revision),
                                expected_revision=state["stateRevision"], source_revision="source-2", reset_tasks=True,
                                preserve_accepted_compatible=True, start_mode="auto-after-freeze", authorized_by="test")
                        self.assertEqual(raised.exception.code, "a5-context-invalid")
                        commit.assert_not_called()
                        self.assertEqual(adoption._tree_bytes(root), before)
                        break
                    adopt_plan(state_path, manifest_path=manifest, operation_id="marked-" + str(revision),
                        expected_revision=state["stateRevision"], source_revision="source-2", reset_tasks=True,
                        preserve_accepted_compatible=True, start_mode="auto-after-freeze", authorized_by="test")
                    task = json.loads(state_path.read_text())["tasks"][0]
                    self.assertEqual(task["status"], "ACCEPTED")
                    self.assertEqual(task["immutableInputAdoption"]["originalPlanDigest"], original_plan)
                    self.assertEqual(task["immutableInputAdoption"]["classification"], "PRESERVED_LEGACY_NO_A5")
                    self.assertNotIn("immutableInputAdmission", task)
                    self.assertEqual(task["usageTotals"]["billableTokens"], 138)

    def test_real_unmarked_start_can_be_preserved_twice_and_requires_its_native_operation(self):
        from agent_lifecycle.workflow.plan_adoption import adopt_plan

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, plan, policy = accepted_unmarked_fixture(root)
            state = json.loads(state_path.read_text())
            original_plan = state["planDigest"]
            for revision in (3, 4):
                manifest = successor_fixture(root, plan, policy, revision)
                before = json.loads(state_path.read_text())
                adopt_plan(state_path, manifest_path=manifest, operation_id="legacy-adopt-" + str(revision),
                    expected_revision=before["stateRevision"], source_revision="source-2", reset_tasks=True,
                    preserve_accepted_compatible=True, start_mode="auto-after-freeze", authorized_by="test")
                state = json.loads(state_path.read_text())
                task = state["tasks"][0]
                self.assertEqual(task["status"], "ACCEPTED")
                self.assertNotIn("immutableInputAdmission", task)
                self.assertEqual(task["immutableInputAdoption"]["classification"], "PRESERVED_LEGACY_NO_A5")
                self.assertEqual(task["immutableInputAdoption"]["originalPlanDigest"], original_plan)
                self.assertEqual(task["usageTotals"]["billableTokens"], 138)
            del state["operationLedger"]["legacy-start"]
            state_path.write_bytes(canonical_bytes(state) + b"\n")
            manifest = successor_fixture(root, plan, policy, 5)
            before = adoption._tree_bytes(root)
            with self.assertRaises(LifecycleError) as raised:
                adopt_plan(state_path, manifest_path=manifest, operation_id="missing-legacy-operation",
                    expected_revision=state["stateRevision"], source_revision="source-2", reset_tasks=True,
                    preserve_accepted_compatible=True, start_mode="auto-after-freeze", authorized_by="test")
            self.assertEqual(raised.exception.code, "a5-context-invalid")
            self.assertEqual(adoption._tree_bytes(root), before)

    def test_first_legacy_preservation_requires_start_and_operation(self):
        from agent_lifecycle.workflow.plan_adoption import adopt_plan

        for missing in ("start", "operation"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state_path, plan, policy = accepted_unmarked_fixture(root)
                state = json.loads(state_path.read_text())
                if missing == "operation":
                    del state["operationLedger"]["legacy-start"]
                    state_path.write_bytes(canonical_bytes(state) + b"\n")
                else:
                    from agent_lifecycle.workflow.events import event_log_path
                    journal = event_log_path(state_path, state)
                    events = [json.loads(line) for line in journal.read_bytes().splitlines()]
                    journal.write_bytes(b"".join(canonical_bytes(event) + b"\n" for event in events
                        if event.get("eventType") != "task-started"))
                manifest = successor_fixture(root, plan, policy, 3)
                before = adoption._tree_bytes(root)
                with patch.object(adoption.adoption_module, "commit_state") as commit, self.assertRaises(LifecycleError) as raised:
                    adopt_plan(state_path, manifest_path=manifest, operation_id="missing-first-legacy-" + missing,
                        expected_revision=4, source_revision="source-2", reset_tasks=True,
                        preserve_accepted_compatible=True, start_mode="auto-after-freeze", authorized_by="test")
                self.assertEqual(raised.exception.code, "a5-context-invalid")
                commit.assert_not_called()
                self.assertEqual(adoption._tree_bytes(root), before)

    def test_unknown_usage_survives_incompatibility_revisions_and_task_reintroduction(self):
        from agent_lifecycle.workflow.plan_adoption import adopt_plan

        for missing in (False, True):
            with self.subTest(telemetry="absent" if missing else "null"), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state_path, plan, policy = accepted_marked_fixture(root)
                state = json.loads(state_path.read_text())
                if missing:
                    del state["tasks"][0]["usageTotals"]
                else:
                    state["tasks"][0]["usageTotals"] = None
                original = copy.deepcopy(state["tasks"][0])
                state_path.write_bytes(canonical_bytes(state) + b"\n")
                changed = copy.deepcopy(policy)
                changed["entrySurface"] = "ALK_MANAGED_TASK_LAUNCH"
                fixture.sealed(changed, "policyDigest")
                for revision, task_id in ((3, "WS-01"), (4, "WS-01"), (5, "WS-02"), (6, "WS-01")):
                    manifest = successor_fixture(root, plan, changed, revision, task_id=task_id)
                    before = json.loads(state_path.read_text())
                    adopt_plan(state_path, manifest_path=manifest, operation_id="unknown-" + str(revision),
                        expected_revision=before["stateRevision"], source_revision="source-2", reset_tasks=True,
                        preserve_accepted_compatible=revision == 3, start_mode="auto-after-freeze", authorized_by="test")
                    current = json.loads(state_path.read_text())
                    self.assertEqual(current["phase"], "BLOCKED")
                    hold = current["unresolvedPlanIncompatibilities"][0]
                    self.assertEqual(hold["taskId"], "WS-01")
                    self.assertEqual(hold["financialObligations"], original)
                    if missing:
                        self.assertNotIn("cumulativeUsageTotals", hold)
                    else:
                        self.assertIsNone(hold["cumulativeUsageTotals"])
                    if task_id == "WS-01":
                        task = current["tasks"][0]
                        self.assertEqual(task["priorFinancialObligations"], original)
                        if missing:
                            self.assertNotIn("usageTotals", task)
                        else:
                            self.assertIsNone(task["usageTotals"])
                    all_bytes = adoption._tree_bytes(root)
                    with self.assertRaises(LifecycleError):
                        start_task(state_path, task_id=task_id, operation_id="unknown-start-" + str(revision),
                            expected_revision=current["stateRevision"], source_revision="source-2", reason="test")
                    self.assertEqual(adoption._tree_bytes(root), all_bytes)

    def test_marked_original_cannot_become_legacy_after_admission_removal_and_binding_reseal(self):
        from agent_lifecycle.workflow.plan_adoption import adopt_plan

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, plan, policy = accepted_marked_fixture(root)
            manifest = successor_fixture(root, plan, policy, 3)
            adopt_plan(state_path, manifest_path=manifest, operation_id="compatible", expected_revision=4,
                source_revision="source-2", reset_tasks=True, preserve_accepted_compatible=True,
                start_mode="auto-after-freeze", authorized_by="test")
            state = json.loads(state_path.read_text())
            task = state["tasks"][0]
            original_receipt = copy.deepcopy(task["planCompatibilityReceipt"])
            del task["immutableInputAdmission"]
            binding = task["immutableInputAdoption"]
            binding.update(classification="PRESERVED_LEGACY_NO_A5", originalPolicyDigest=None, originalDecisionDigest=None)
            fixture.sealed(binding, "bindingDigest")
            state_path.write_bytes(canonical_bytes(state) + b"\n")
            manifest = successor_fixture(root, plan, policy, 4)
            before = adoption._tree_bytes(root)
            with patch.object(adoption.adoption_module, "commit_state") as commit, self.assertRaises(LifecycleError) as raised:
                adopt_plan(state_path, manifest_path=manifest, operation_id="forged-legacy", expected_revision=5,
                    source_revision="source-2", reset_tasks=True, preserve_accepted_compatible=True,
                    start_mode="auto-after-freeze", authorized_by="test")
            self.assertEqual(raised.exception.code, "a5-context-invalid")
            commit.assert_not_called()
            self.assertEqual(adoption._tree_bytes(root), before)
            self.assertEqual(json.loads(state_path.read_text())["tasks"][0]["planCompatibilityReceipt"], original_receipt)

    def test_incompatibility_hold_and_cost_survive_another_adoption(self):
        from agent_lifecycle.workflow.plan_adoption import adopt_plan

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, plan, policy = accepted_marked_fixture(root)
            original = json.loads(state_path.read_text())["tasks"][0]
            changed = copy.deepcopy(policy)
            changed["entrySurface"] = "ALK_MANAGED_TASK_LAUNCH"
            fixture.sealed(changed, "policyDigest")
            for revision in (3, 4, 5):
                manifest = successor_fixture(root, plan, changed, revision)
                before = json.loads(state_path.read_text())
                adopt_plan(state_path, manifest_path=manifest, operation_id="held-" + str(revision),
                    expected_revision=before["stateRevision"], source_revision="source-2", reset_tasks=True,
                    preserve_accepted_compatible=revision != 5, start_mode="auto-after-freeze", authorized_by="test")
                current = json.loads(state_path.read_text())
                self.assertEqual(current["phase"], "BLOCKED")
                self.assertEqual(current["tasks"][0]["usageTotals"], original["usageTotals"])
                self.assertEqual(current["tasks"][0]["priorFinancialObligations"], original)
                self.assertEqual(len(current["unresolvedPlanIncompatibilities"]), 1)
                self.assertIs(current["unresolvedPlanIncompatibilities"][0]["automaticRetryAuthorized"], False)
                all_bytes = adoption._tree_bytes(root)
                with self.assertRaises(LifecycleError):
                    start_task(state_path, task_id="WS-01", operation_id="automatic-" + str(revision),
                        expected_revision=current["stateRevision"], source_revision="source-2", reason="test")
                self.assertEqual(adoption._tree_bytes(root), all_bytes)

    def test_public_repeated_adoption_receipts_retain_existing_identity_and_original_native_start(self):
        from agent_lifecycle.planning.task_compatibility import validate_task_plan_compatibility_receipt
        from agent_lifecycle.workflow.plan_adoption import adopt_plan

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, plan, policy = accepted_marked_fixture(root)
            original = json.loads(state_path.read_text())["tasks"][0]["immutableInputAdmission"]
            for revision in (3, 4):
                manifest = successor_fixture(root, plan, policy, revision)
                before = json.loads(state_path.read_text())
                adopt_plan(state_path, manifest_path=manifest, operation_id="adopt-" + str(revision),
                    expected_revision=before["stateRevision"], source_revision="source-2", reset_tasks=True,
                    preserve_accepted_compatible=True, start_mode="auto-after-freeze", authorized_by="test")
                current = json.loads(state_path.read_text())
                task = current["tasks"][0]
                self.assertEqual(task["status"], "ACCEPTED")
                self.assertEqual(task["immutableInputAdmission"], original)
                receipt = task["planCompatibilityReceipt"]
                self.assertEqual(set(receipt["currentPlan"]), {"runId", "packageId", "planRevision", "planDigest", "sourceRevision"})
                self.assertEqual(validate_task_plan_compatibility_receipt(receipt, state=current, task=task)["status"], "PASS")
                self.assertEqual(task["immutableInputAdoption"]["compatibilityReceiptDigest"], receipt["receiptDigest"])
                self.assertEqual(task["usageTotals"]["billableTokens"], 138)

    def test_public_adoption_cannot_reclassify_stripped_previous_marked_plan_as_legacy(self):
        from agent_lifecycle.workflow.plan_adoption import adopt_plan

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, plan, policy = accepted_marked_fixture(root)
            state = json.loads(state_path.read_text())
            del state["immutableInput"]
            del state["tasks"][0]["immutableInput"]
            del state["tasks"][0]["immutableInputAdmission"]
            state_path.write_bytes(canonical_bytes(state) + b"\n")
            manifest = successor_fixture(root, plan, policy, 3)
            before = adoption._tree_bytes(root)
            with patch.object(adoption.adoption_module, "commit_state") as commit, self.assertRaises(LifecycleError) as raised:
                adopt_plan(state_path, manifest_path=manifest, operation_id="stripped-preserve", expected_revision=4,
                    source_revision="source-2", reset_tasks=True, preserve_accepted_compatible=True,
                    start_mode="auto-after-freeze", authorized_by="test")
            self.assertEqual(raised.exception.code, "a5-context-invalid")
            commit.assert_not_called()
            self.assertEqual(adoption._tree_bytes(root), before)

    def test_public_repeated_adoption_rejects_missing_or_resealed_invalid_previous_receipt(self):
        from agent_lifecycle.workflow.plan_adoption import adopt_plan

        for alteration in ("missing", "resealed-invalid"):
            with self.subTest(alteration=alteration), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state_path, plan, policy = accepted_marked_fixture(root)
                manifest = successor_fixture(root, plan, policy, 3)
                adopt_plan(state_path, manifest_path=manifest, operation_id="compatible", expected_revision=4,
                    source_revision="source-2", reset_tasks=True, preserve_accepted_compatible=True,
                    start_mode="auto-after-freeze", authorized_by="test")
                state = json.loads(state_path.read_text())
                task = state["tasks"][0]
                if alteration == "missing":
                    del task["planCompatibilityReceipt"]
                else:
                    receipt = task["planCompatibilityReceipt"]
                    receipt["status"] = "FAIL"
                    receipt["receiptDigest"] = canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"})
                    binding = task["immutableInputAdoption"]
                    binding["compatibilityReceiptDigest"] = receipt["receiptDigest"]
                    fixture.sealed(binding, "bindingDigest")
                state_path.write_bytes(canonical_bytes(state) + b"\n")
                manifest = successor_fixture(root, plan, policy, 4)
                before = adoption._tree_bytes(root)
                with patch.object(adoption.adoption_module, "commit_state") as commit, self.assertRaises(LifecycleError) as raised:
                    adopt_plan(state_path, manifest_path=manifest, operation_id="invalid-repeat", expected_revision=5,
                        source_revision="source-2", reset_tasks=True, preserve_accepted_compatible=True,
                        start_mode="auto-after-freeze", authorized_by="test")
                self.assertEqual(raised.exception.code, "a5-context-invalid")
                commit.assert_not_called()
                self.assertEqual(adoption._tree_bytes(root), before)

    def test_incompatible_adoption_archives_original_task_and_cost_and_blocks_automatic_continuation(self):
        from agent_lifecycle.workflow.plan_adoption import adopt_plan

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, plan, policy = accepted_marked_fixture(root)
            original = json.loads(state_path.read_text())["tasks"][0]
            changed = copy.deepcopy(policy)
            changed["entrySurface"] = "ALK_MANAGED_TASK_LAUNCH"
            fixture.sealed(changed, "policyDigest")
            manifest = successor_fixture(root, plan, changed, 3)
            adopt_plan(state_path, manifest_path=manifest, operation_id="incompatible", expected_revision=4,
                source_revision="source-2", reset_tasks=True, preserve_accepted_compatible=True,
                start_mode="auto-after-freeze", authorized_by="test")
            current = json.loads(state_path.read_text())
            self.assertEqual(current["phase"], "BLOCKED")
            self.assertEqual(current["priorSnapshots"][-1]["tasks"][0], original)
            self.assertEqual(current["tasks"][0]["usageTotals"], original["usageTotals"])
            self.assertIs(current["tasks"][0]["planIncompatibility"]["automaticRetryAuthorized"], False)
            before = adoption._tree_bytes(root)
            with self.assertRaises(LifecycleError):
                start_task(state_path, task_id="WS-01", operation_id="automatic-retry", expected_revision=current["stateRevision"], source_revision="source-2", reason="test")
            self.assertEqual(adoption._tree_bytes(root), before)

    def test_known_unadopted_ordinary_start_needs_no_fictional_plan_and_strong_still_refuses(self):
        for request in (None, {"schemaVersion": "agent-a5-invocation-request.v1", "requestedProtection": "NONE"}):
            with self.subTest(request=request), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state_path = helpers._write_state(root, phase="RUNNING")
                ordinary = start_task(state_path, task_id="WS-01", operation_id="ordinary", expected_revision=1, source_revision="source", reason="test", immutable_input_request=request)
                self.assertEqual(ordinary["tasks"][0]["status"], "RUNNING")
                stored = json.loads(state_path.read_text())
                self.assertNotIn("immutableInputAdmission", stored["tasks"][0])
                self.assertFalse((root / "plans").exists())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = helpers._write_state(root, phase="RUNNING")
            before = adoption._tree_bytes(root)
            with patch("agent_lifecycle.workflow.task_start.clear_task_risk_profile") as helper, self.assertRaises(LifecycleError) as raised:
                start_task(state_path, task_id="WS-01", operation_id="strong", expected_revision=1, source_revision="source", reason="test", immutable_input_request={"schemaVersion": "agent-a5-invocation-request.v1", "requestedProtection": "STRONG_A5"})
            self.assertEqual(raised.exception.code, "a5-strong-unproven")
            helper.assert_not_called()
            self.assertEqual(adoption._tree_bytes(root), before)

    def test_missing_or_partial_adopted_context_never_becomes_unadopted_ordinary(self):
        for marker in ({"manifestPath": ""}, {"packetSet": {}}, {"immutableInput": {}}, {"immutableInputAdmission": {}}):
            state = {"runId": "run"}
            task = {"id": "task"}
            (task if "immutableInputAdmission" in marker else state).update(marker)
            with self.subTest(marker=marker), self.assertRaises(LifecycleError) as raised:
                is_unadopted_ordinary_context(state, task)
            self.assertEqual(raised.exception.code, "a5-context-invalid")
        with self.assertRaises(LifecycleError):
            is_unadopted_ordinary_context({}, {}, {"schemaVersion": "agent-a5-invocation-request.v1", "requestedProtection": "NONE", "extra": True})

    def test_consumer_keeps_original_start_across_later_operation_and_rejects_missing_or_replayed_admission(self):
        manifest, state, task, registry = marked()
        original_subject = fixture.subject()
        state.update(runId=original_subject["runId"], packageId=original_subject["packageId"],
                     planDigest=original_subject["planDigest"], sourceRevision=original_subject["sourceRevision"])
        task.update(id=original_subject["taskId"], attempt=original_subject["targetAttempt"], status="RUNNING")
        manifest["workstreams"][0]["id"] = task["id"]
        decision = evaluate_task_admission(manifest, state, task, original_subject, registry=registry)
        task["immutableInputAdmission"] = decision
        consumer = {**original_subject, "operationId": "different-consumer", "stateRevision": original_subject["stateRevision"] + 4}
        before = copy.deepcopy((state, task, decision))
        require_task_consumer_admission(manifest, state, task, consumer, registry=registry, trusted_original_admission=decision)
        self.assertEqual((state, task, decision), before)
        for alteration in ("missing", "wrong-package", "wrong-source", "wrong-attempt", "future-revision", "positive"):
            changed = copy.deepcopy(task)
            if alteration == "missing":
                del changed["immutableInputAdmission"]
            else:
                admission = changed["immutableInputAdmission"]
                if alteration == "positive":
                    admission["strongProtectionGranted"] = True
                else:
                    field, value = {
                        "wrong-package": ("packageId", "different"),
                        "wrong-source": ("sourceRevision", "different"),
                        "wrong-attempt": ("targetAttempt", task["attempt"] + 1),
                        "future-revision": ("stateRevision", consumer["stateRevision"]),
                    }[alteration]
                    admission["subject"][field] = value
                fixture.sealed(admission, "decisionDigest")
            with self.subTest(alteration=alteration), self.assertRaises(LifecycleError) as raised:
                require_task_consumer_admission(manifest, state, changed, consumer, registry=registry, trusted_original_admission=decision)
            self.assertEqual(raised.exception.code, "a5-context-invalid")

    def test_consumer_adoption_joins_original_decision_and_current_compatibility(self):
        from agent_lifecycle.workflow.immutable_input import adoption_binding

        manifest, state, task, registry = marked()
        subject = fixture.subject()
        state.update(runId=subject["runId"], packageId=subject["packageId"],
                     planDigest=subject["planDigest"], sourceRevision=subject["sourceRevision"])
        task.update(id=subject["taskId"], attempt=subject["targetAttempt"], status="ACCEPTED")
        manifest["workstreams"][0]["id"] = task["id"]
        task["immutableInputAdmission"] = evaluate_task_admission(manifest, state, task, subject, registry=registry)
        current = {**state, "planDigest": "b" * 64}
        original = copy.deepcopy(task["immutableInputAdmission"])
        identity = {key: current.get(key) for key in ("runId", "packageId", "planRevision", "planDigest", "sourceRevision")}
        compatibility = build_task_plan_compatibility_receipt(previous_state=state, current_plan=identity, previous_task=task, current_task=task)
        binding = adoption_binding(state, task, task, current, compatibility, trusted_original_admission=original)
        task.update(immutableInputAdoption=binding, planCompatibilityReceipt=compatibility)
        consumer = {**subject, "planDigest": current["planDigest"], "operationId": "adopted-consumer", "stateRevision": subject["stateRevision"] + 8}
        before = copy.deepcopy(task)
        require_task_consumer_admission(manifest, current, task, consumer, registry=registry, trusted_original_admission=original)
        self.assertEqual(task, before)
        for alteration in ("digest-only", "status", "current-source", "contract", "artifacts"):
            changed = copy.deepcopy(task)
            receipt = changed["planCompatibilityReceipt"]
            if alteration == "digest-only":
                changed["planCompatibilityReceipt"] = {"receiptDigest": receipt["receiptDigest"]}
            else:
                if alteration == "status":
                    receipt["status"] = "FAIL"
                elif alteration == "current-source":
                    receipt["currentPlan"]["sourceRevision"] = "forged-source"
                elif alteration == "contract":
                    receipt["taskContract"]["currentDigest"] = "d" * 64
                else:
                    receipt["acceptedArtifacts"]["result"] = {"path": "missing.json", "sha256": "d" * 64, "bytes": 42}
                receipt["receiptDigest"] = canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"})
                changed["immutableInputAdoption"]["compatibilityReceiptDigest"] = receipt["receiptDigest"]
                fixture.sealed(changed["immutableInputAdoption"], "bindingDigest")
            with self.subTest(alteration=alteration), self.assertRaises(LifecycleError) as raised:
                require_task_consumer_admission(manifest, current, changed, consumer, registry=registry, trusted_original_admission=original)
            self.assertEqual(raised.exception.code, "a5-context-invalid")

    def test_public_consumers_reject_stripped_frozen_policy_before_downstream_gates(self):
        for consumer, alteration in ((c, a) for c in ("result", "acceptance") for a in ("strip", "source", "operation", "revision", "package")):
            with self.subTest(consumer=consumer, alteration=alteration), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state_path = helpers._write_state(root, phase="BLOCKED", blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"})
                plan, policy, registry = adoption._a5_policies()
                manifest = adoption._write_authority_bundle(root, global_fields={"immutableInput": plan}, task_fields={"immutableInput": policy})
                boundary = root / "profiles/immutable-input-adapter-capabilities.v1.json"
                boundary.parent.mkdir()
                boundary.write_text(json.dumps(registry))
                adoption._adopt_authority_bundle(state_path, manifest)
                helpers.start_execution(state_path, operation_id="run", expected_revision=2, source_revision="source-2", reason="test")
                start_task(state_path, task_id="WS-01", operation_id="ordinary", expected_revision=3, source_revision="source-2", reason="test")
                state = json.loads(state_path.read_text())
                task = state["tasks"][0]
                if alteration == "strip":
                    del state["immutableInput"]
                    del task["immutableInput"]
                    del task["immutableInputAdmission"]
                else:
                    decision = task["immutableInputAdmission"]
                    field, value = {"source": ("sourceRevision", "rewritten-source"),
                                    "operation": ("operationId", "run"), "revision": ("stateRevision", 2),
                                    "package": ("packageId", "different")}[alteration]
                    decision["subject"][field] = value
                    request = {"schemaVersion": "agent-a5-limited-request.v1", "subject": decision["subject"],
                               "requestedProtection": "NONE", "expectedPolicyDigest": decision["policyDigest"],
                               "expectedBoundaryRecordDigest": decision["boundaryRecordDigest"]}
                    decision["requestDigest"] = canonical_digest(request)
                    fixture.sealed(decision, "decisionDigest")
                if consumer == "acceptance":
                    task["status"] = "VERIFYING"
                    if state["schemaVersion"] != "agent-workflow-state.v4":
                        state["phase"] = "STEP_REVIEW"
                state_path.write_bytes(canonical_bytes(state) + b"\n")
                before = adoption._tree_bytes(root)
                with patch("agent_lifecycle.workflow.task_transitions.validate_controller_gates", side_effect=AssertionError("invalid A5 must stop before downstream gates")) as gates, patch("agent_lifecycle.workflow.task_transitions.commit_state") as commit:
                    with self.assertRaises(LifecycleError) as raised:
                        if consumer == "result":
                            commit_task_result(state_path, task_id="WS-01", operation_id="consume-result", expected_revision=4, source_revision="source-2", result_path="unused.json", reason="test")
                        else:
                            accept_task(state_path, task_id="WS-01", operation_id="consume-review", expected_revision=4, review_path="unused.json", reason="test")
                    self.assertEqual(raised.exception.code, "a5-context-invalid")
                    gates.assert_not_called()
                    commit.assert_not_called()
                self.assertEqual(adoption._tree_bytes(root), before)

    def test_twelve_route_registry_is_negative_and_complete(self):
        _, _, _, registry = marked()
        checked = validate_a5_boundary_registry(registry)
        self.assertEqual(len(checked["records"]), 12)
        self.assertTrue(all(item["strongCapability"] == "UNPROVEN" and item["strongAdmissionSupported"] is False for item in checked["records"]))

    def test_marked_ordinary_decision_binds_exact_attempt_without_mutation(self):
        manifest, state, task, registry = marked()
        before = copy.deepcopy((manifest, state, task, registry))
        decision = evaluate_task_admission(manifest, state, task, fixture.subject(), registry=registry)
        self.assertEqual(decision["subject"], fixture.subject())
        self.assertEqual(decision["disposition"], "ORDINARY_NO_A5")
        self.assertIs(decision["strongProtectionGranted"], False)
        self.assertEqual((manifest, state, task, registry), before)

    def test_frozen_strong_cannot_be_lowered_by_none_or_omission(self):
        manifest, state, task, registry = marked("STRONG_A5")
        for request in (None, {"schemaVersion": "agent-a5-invocation-request.v1", "requestedProtection": "NONE"}):
            with self.subTest(request=request), self.assertRaises(LifecycleError) as raised:
                evaluate_task_admission(manifest, state, task, fixture.subject(), request, registry=registry)
            self.assertEqual(raised.exception.code, "a5-strong-unproven")

    def test_missing_marked_state_and_changed_boundary_refuse(self):
        manifest, state, task, registry = marked()
        with self.assertRaises(LifecycleError):
            evaluate_task_admission(manifest, {}, task, fixture.subject(), registry=registry)
        registry["records"][0]["strongAdmissionSupported"] = True
        with self.assertRaises(LifecycleError):
            evaluate_task_admission(manifest, state, task, fixture.subject(), registry=registry)

    def test_real_public_denial_keeps_state_events_and_helpers_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = helpers._write_state(root, phase="BLOCKED", blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"})
            manifest = adoption._write_authority_bundle(root)
            adoption._adopt_authority_bundle(state_path, manifest)
            helpers.start_execution(state_path, operation_id="run", expected_revision=2, source_revision="source-2", reason="test")
            before = adoption._tree_bytes(root)
            with patch("agent_lifecycle.workflow.task_start.clear_task_risk_profile") as helper, self.assertRaises(LifecycleError) as raised:
                start_task(state_path, task_id="WS-01", operation_id="denied", expected_revision=3, source_revision="source-2", reason="test", immutable_input_request={"schemaVersion": "agent-a5-invocation-request.v1", "requestedProtection": "STRONG_A5"})
            self.assertEqual(raised.exception.code, "a5-strong-unproven")
            helper.assert_not_called()
            self.assertEqual(adoption._tree_bytes(root), before)
            ordinary = start_task(state_path, task_id="WS-01", operation_id="ordinary", expected_revision=3, source_revision="source-2", reason="test")
            self.assertEqual(ordinary["tasks"][0]["status"], "RUNNING")

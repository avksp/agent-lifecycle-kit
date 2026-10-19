from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
try:
    from .helpers import *  # noqa: F403
except ImportError:
    from helpers import (
        LifecycleError,
        _write_plan_bundle,
        _write_state,
        adopt_plan,
        canonical_digest,
        start_execution,
        start_task,
    )

from agent_lifecycle.contracts import canonical_bytes  # noqa: E402
from agent_lifecycle.freeze.package_integrity import build_plan_lock_v2, verify_plan_package_integrity  # noqa: E402
from agent_lifecycle.planning.validation import validate_plan_manifest  # noqa: E402
from agent_lifecycle.workflow import plan_adoption as adoption_module  # noqa: E402
from agent_lifecycle.workflow import run_workflow_step  # noqa: E402
from agent_lifecycle.workflow.immutable_input import adoption_binding, policies_compatible_for_adoption  # noqa: E402
from tests.contracts import test_immutable_input_schemas as a5_fixture  # noqa: E402

try:
    from tests.planning.test_completeness import _manifest as _canonical_manifest
except ImportError:
    from planning.test_completeness import _manifest as _canonical_manifest


def _write_authority_bundle(root, *, kind="legacy", global_fields=None, task_fields=None):
    """Bind declarations to real locks and packet indexes before adoption."""
    _write_plan_bundle(root)
    manifest_path = root / "plans/package/plan.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plan_root = root / manifest["package"]["planArtifactRoot"]
    if kind != "legacy":
        manifest["schemaVersion"] = "agent-plan-manifest.v1"
    if kind.startswith("integrity"):
        canonical = _canonical_manifest()
        for field in (
            "packageIntegrity",
            "specification",
            "acceptance",
            "validation",
            "budgets",
            "contextLimits",
            "finalAuditGates",
            "releaseTarget",
            "forbiddenWrites",
        ):
            manifest[field] = canonical[field]
        manifest["workstreams"][0]["acceptanceIds"] = ["AC-01", "AC-02"]
        manifest["workstreams"][0]["evidenceIds"] = ["EV-01", "EV-02"]
        if kind == "integrity-s0":
            manifest["specification"]["tier"] = "S0"
        manifest_path = plan_root / "plan.manifest.json"
        manifest["planFiles"] = sorted(
            [
                manifest_path.relative_to(root).as_posix(),
                manifest["planReview"]["report"],
            ]
        )
        manifest["packageIntegrity"]["allowedUnlistedFiles"] = ["plan.lock.json"]
    manifest.update(global_fields or {})
    manifest["workstreams"][0].update(task_fields or {})
    manifest_path.write_bytes(canonical_bytes(manifest) + b"\n")
    digest = canonical_digest(manifest)
    lock = (
        build_plan_lock_v2(manifest, repository_root=root)
        if kind.startswith("integrity")
        else {"schemaVersion": "agent-plan-lock.v1", "planRevision": 2, "manifestHash": digest}
    )
    (plan_root / "plan.lock.json").write_bytes(canonical_bytes(lock) + b"\n")
    index_path = root / "plans/package/workflow/task-packets/index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["manifestDigest"] = digest
    index_path.write_bytes(canonical_bytes(index) + b"\n")
    validate_plan_manifest(manifest, require_completeness=kind.startswith("integrity"))
    verification = verify_plan_package_integrity(manifest, lock, repository_root=root)
    assert verification["status"] == "PASS"
    assert verification["filesystemVerified"] == kind.startswith("integrity")
    return manifest_path


def _adopt_authority_bundle(state_path, manifest_path, *, preserve=False):
    return adopt_plan(
        state_path,
        manifest_path=manifest_path,
        operation_id="adopt-authority",
        expected_revision=1,
        source_revision="source-2",
        reset_tasks=True,
        preserve_accepted_compatible=preserve,
        start_mode="auto-after-freeze",
        authorized_by="tester",
    )


def _tree_bytes(root):
    return {
        entry.relative_to(root).as_posix(): entry.read_bytes() if entry.is_file() else None for entry in root.rglob("*")
    }


def _a5_policies():
    registry = json.loads((ROOT / 'profiles/immutable-input-adapter-capabilities.v1.json').read_text())
    row = next(item for item in registry['records'] if item['adapterId'] == 'codex')
    policy = a5_fixture.policy()
    policy.update({key: row[key] for key in ('adapterId', 'expectationId', 'targetVersion', 'boundaryRecordDigest')})
    policy['frozenTaskRequirement'] = 'NONE'
    a5_fixture.sealed(policy, 'policyDigest')
    plan = {'schemaVersion': 'agent-a5-plan-policy.v1', 'mode': 'A5_LIMITED',
            'defaultRequirement': 'NONE', 'contractDigest': 'a' * 64}
    return plan, policy, registry


class A5PlanAdoptionTests(unittest.TestCase):
    def test_same_digest_repeat_adoption_refuses_without_changing_any_runtime_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase='BLOCKED', blocker={'code':'plan-drift','reason':'x','resumePhase':'RUNNING'})
            plan, policy, registry = _a5_policies()
            manifest = _write_authority_bundle(root, global_fields={'immutableInput':plan}, task_fields={'immutableInput':policy})
            target = root / 'profiles/immutable-input-adapter-capabilities.v1.json'
            target.parent.mkdir()
            target.write_text(json.dumps(registry))
            _adopt_authority_bundle(state_path, manifest)
            start_execution(state_path, operation_id='run', expected_revision=2, source_revision='source-2', reason='test')
            start_task(state_path, task_id='WS-01', operation_id='ordinary', expected_revision=3, source_revision='source-2', reason='test')
            before = _tree_bytes(root)
            original = json.loads(state_path.read_text())
            self.assertEqual(original['tasks'][0]['attempt'], 1)
            self.assertIn('immutableInputAdmission', original['tasks'][0])
            for reset, code in ((True, 'same-plan-reset'), (False, 'reset-required')):
                with self.subTest(reset=reset), patch.object(adoption_module, '_build_tasks') as helper, patch.object(adoption_module, 'commit_state') as commit:
                    with self.assertRaises(LifecycleError) as raised:
                        adopt_plan(state_path, manifest_path=manifest, operation_id='repeat-'+str(reset),
                            expected_revision=4, source_revision='source-2', reset_tasks=reset,
                            start_mode='auto-after-freeze', authorized_by='tester')
                    self.assertEqual(raised.exception.code, code)
                    helper.assert_not_called()
                    commit.assert_not_called()
                    self.assertEqual(_tree_bytes(root), before)
                    self.assertEqual(json.loads(state_path.read_text()), original)

    def test_public_adoption_materializes_policies_before_real_ordinary_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase='BLOCKED', blocker={'code': 'plan-drift', 'reason': 'x', 'resumePhase': 'RUNNING'})
            plan, policy, registry = _a5_policies()
            manifest = _write_authority_bundle(root, global_fields={'immutableInput': plan}, task_fields={'immutableInput': policy})
            target = root / 'profiles/immutable-input-adapter-capabilities.v1.json'
            target.parent.mkdir()
            target.write_text(json.dumps(registry))
            _adopt_authority_bundle(state_path, manifest)
            stored = json.loads(state_path.read_text())
            self.assertEqual(stored['immutableInput'], plan)
            self.assertEqual(stored['tasks'][0]['immutableInput'], policy)
            start_execution(state_path, operation_id='run', expected_revision=2, source_revision='source-2', reason='test')
            start_task(state_path, task_id='WS-01', operation_id='ordinary', expected_revision=3, source_revision='source-2', reason='test')
            decision = json.loads(state_path.read_text())['tasks'][0]['immutableInputAdmission']
            self.assertEqual(decision['subject']['stateRevision'], 3)
            self.assertEqual(decision['policyDigest'], policy['policyDigest'])
            self.assertFalse(decision['strongProtectionGranted'])

    def test_repeated_adoption_keeps_first_execution_decision_and_plan(self):
        import copy

        from agent_lifecycle.workflow.immutable_input import evaluate_task_admission
        plan, policy, registry = _a5_policies()
        subject = a5_fixture.subject()
        old = {'id': subject['taskId'], 'status': 'ACCEPTED', 'attempt': subject['targetAttempt'], 'immutableInput': policy}
        decision = evaluate_task_admission({'immutableInput': plan, 'workstreams': [old]}, {'immutableInput': plan}, old, subject, registry=registry)
        old['immutableInputAdmission'] = decision
        previous = {'runId': subject['runId'], 'packageId': subject['packageId'], 'planRevision': 1,
                    'planDigest': subject['planDigest'], 'sourceRevision': subject['sourceRevision'],
                    'immutableInput': plan, 'tasks': [old]}
        original = copy.deepcopy(decision)
        for revision, digest in ((2, 'b' * 64), (3, 'c' * 64)):
            fresh = {k: copy.deepcopy(v) for k,v in old.items() if k not in ('immutableInputAdmission', 'immutableInputAdoption', 'planCompatibilityReceipt')}
            fresh.update(status='READY', attempt=0)
            current = {**{k: previous[k] for k in ('runId','packageId','sourceRevision')}, 'planRevision': revision,
                       'planDigest': digest, 'immutableInput': plan}
            carried = adoption_module._preserve_accepted_tasks(previous, [fresh], current_plan=current,
                current_plan_policy=plan, original_admissions={subject['taskId']: original})[0]
            self.assertEqual(carried['status'], 'ACCEPTED')
            self.assertEqual(carried['immutableInputAdmission'], original)
            binding = carried['immutableInputAdoption']
            self.assertEqual(binding['originalPlanDigest'], subject['planDigest'])
            self.assertEqual(binding['currentPlanDigest'], digest)
            self.assertEqual(binding['originalDecisionDigest'], original['decisionDigest'])
            self.assertEqual(binding['compatibilityReceiptDigest'], carried['planCompatibilityReceipt']['receiptDigest'])
            self.assertFalse(binding['strongProtectionGranted'])
            previous = {**current, 'tasks': [carried]}
            old = carried

    def test_policy_change_and_strong_default_cannot_preserve_acceptance(self):
        import copy
        plan, policy, _ = _a5_policies()
        accepted = {'id': 'task', 'immutableInput': policy}
        changed = copy.deepcopy(policy)
        changed['entrySurface'] = 'ALK_MANAGED_TASK_LAUNCH'
        a5_fixture.sealed(changed, 'policyDigest')
        self.assertFalse(policies_compatible_for_adoption(accepted, {'id': 'task', 'immutableInput': changed},
            previous_plan_policy=plan, current_plan_policy=plan))
        self.assertFalse(policies_compatible_for_adoption(accepted, accepted, previous_plan_policy=plan,
            current_plan_policy={**plan, 'defaultRequirement': 'STRONG_A5'}))
        self.assertFalse(policies_compatible_for_adoption(accepted, {'id': 'task'}, previous_plan_policy=plan, current_plan_policy=None))

    def test_legacy_none_upgrade_and_repeated_binding_keep_original_history(self):
        import copy
        plan, policy, _ = _a5_policies()
        previous = {'runId': 'run', 'planDigest': 'a' * 64}
        old = {'id': 'task', 'attempt': 2}
        current = {'id': 'task', 'immutableInput': policy}
        self.assertTrue(policies_compatible_for_adoption(old, current, previous_plan_policy=None, current_plan_policy=plan))
        from agent_lifecycle.planning.task_compatibility import build_task_plan_compatibility_receipt
        next_state = {**previous, 'planDigest': 'b' * 64}
        identity = {key: next_state.get(key) for key in ('runId','packageId','planRevision','planDigest','sourceRevision')}
        first_receipt = build_task_plan_compatibility_receipt(previous_state=previous, current_plan=identity,
            previous_task=old, current_task=current)
        first = adoption_binding(previous, old, current, next_state, first_receipt)
        self.assertEqual(first['classification'], 'PRESERVED_LEGACY_NO_A5')
        self.assertIsNone(first['originalDecisionDigest'])
        adopted = {**old, **copy.deepcopy(current), 'immutableInputAdoption': first, 'planCompatibilityReceipt': first_receipt}
        final_state = {**previous, 'planDigest': 'c' * 64}
        final_identity = {key: final_state.get(key) for key in ('runId','packageId','planRevision','planDigest','sourceRevision')}
        second_receipt = build_task_plan_compatibility_receipt(previous_state=next_state, current_plan=final_identity,
            previous_task=adopted, current_task=current)
        second = adoption_binding(next_state, adopted, current, final_state, second_receipt)
        self.assertEqual(second['originalPlanDigest'], 'a' * 64)
        tampered = copy.deepcopy(adopted)
        tampered['immutableInputAdoption']['actualAttempt'] = 3
        a5_fixture.sealed(tampered['immutableInputAdoption'], 'bindingDigest')
        with self.assertRaises(LifecycleError):
            adoption_binding(next_state, tampered, current, final_state, second_receipt)


def _assert_authority_rejection(test, root, state_path, manifest_path, code, *, preserve=False):
    journal = root / "events.jsonl"
    if not journal.exists():
        journal.write_bytes(b'{"schemaVersion":"agent-workflow-event.v1","stateRevision":1,"operationId":"prior-fixture"}\n')
    before = _tree_bytes(root)
    with (
        patch("agent_lifecycle.workflow.plan_adoption._packet_set") as packet_set,
        patch("agent_lifecycle.workflow.plan_adoption._build_tasks") as build_tasks,
        patch("agent_lifecycle.workflow.plan_adoption._preserve_accepted_tasks") as preserve_tasks,
        test.assertRaises(LifecycleError) as raised,
    ):
        _adopt_authority_bundle(state_path, manifest_path, preserve=preserve)
    test.assertEqual(raised.exception.code, code)
    packet_set.assert_not_called()
    build_tasks.assert_not_called()
    preserve_tasks.assert_not_called()
    test.assertEqual(_tree_bytes(root), before)
    return raised.exception


class WorkflowPlanAdoptionTests(unittest.TestCase):
    def test_legal_authority_adopts_with_legacy_and_integrity_locks(self) -> None:
        for kind in ("legacy", "canonical-v1", "integrity", "integrity-s0"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state_path = _write_state(root, phase="READY")
                manifest_path = _write_authority_bundle(
                    root,
                    kind=kind,
                    global_fields={
                        "readOnly": ["docs"],
                        "forbiddenWrites": [".git"],
                        "leadOwned": [{"path": "coordination"}],
                    },
                    task_fields={
                        "readOnly": ["references"],
                        "forbiddenWrites": ["private"],
                        "leadOwned": [{"path": "receipts"}],
                    },
                )
                payload = _adopt_authority_bundle(state_path, manifest_path)
                self.assertEqual(payload["phase"], "READY")
                self.assertEqual(payload["planRevision"], 2)

    def test_missing_case_semantics_reject_all_protected_declaration_categories(self) -> None:
        for kind in ("legacy", "canonical-v1", "integrity", "integrity-s0"):
            for scope in ("global", "task"):
                for field in ("readOnly", "forbiddenWrites", "leadOwned"):
                    with self.subTest(kind=kind, scope=scope, field=field), tempfile.TemporaryDirectory() as tmp:
                        root = Path(tmp)
                        state_path = _write_state(root, phase="READY")
                        protected = [{"path": "Protected"}] if field == "leadOwned" else ["Protected"]
                        global_fields = {field: protected} if scope == "global" else {}
                        task_fields = {"writes": ["protected/output"]}
                        if scope == "task":
                            task_fields[field] = protected
                        manifest_path = _write_authority_bundle(
                            root,
                            kind=kind,
                            global_fields=global_fields,
                            task_fields=task_fields,
                        )
                        error = _assert_authority_rejection(
                            self,
                            root,
                            state_path,
                            manifest_path,
                            "filesystem-policy-unavailable",
                        )
                        self.assertEqual(error.message, "missing names have unknown alias semantics")

    def test_protected_aliases_follow_native_filesystem_semantics(self) -> None:
        for kind in ("legacy", "integrity"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "Protected").mkdir()
                aliases = (root / "protected").exists()
                if not aliases:
                    (root / "protected").mkdir()
                state_path = _write_state(root, phase="READY")
                manifest_path = _write_authority_bundle(
                    root,
                    kind=kind,
                    global_fields={"readOnly": ["Protected"]},
                    task_fields={"writes": ["protected/output"]},
                )
                if aliases:
                    error = _assert_authority_rejection(
                        self,
                        root,
                        state_path,
                        manifest_path,
                        "ambiguous-authority-path",
                    )
                    self.assertEqual(error.message, "filesystem aliases have conflicting ownership")
                else:
                    self.assertEqual(_adopt_authority_bundle(state_path, manifest_path)["phase"], "READY")

    def test_global_legacy_write_authority_is_checked_before_preserving_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="READY")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0].update({"status": "ACCEPTED", "attempt": 1})
            state_path.write_text(json.dumps(state), encoding="utf-8")
            manifest_path = _write_authority_bundle(
                root,
                global_fields={"writes": ["protected/output"], "readOnly": ["Protected"]},
            )
            _assert_authority_rejection(
                self,
                root,
                state_path,
                manifest_path,
                "filesystem-policy-unavailable",
                preserve=True,
            )

    def test_alias_policy_failure_precedes_accepted_task_preservation(self) -> None:
        for kind in ("legacy", "integrity"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state_path = _write_state(root, phase="READY")
                state = json.loads(state_path.read_text(encoding="utf-8"))
                state["tasks"][0].update({"status": "ACCEPTED", "attempt": 1})
                state_path.write_text(json.dumps(state), encoding="utf-8")
                manifest_path = _write_authority_bundle(root, kind=kind, global_fields={"readOnly": ["SRC"]})
                # Deterministic alias branch complements the native filesystem test.
                with patch("agent_lifecycle.contracts.ownership_paths._same_filesystem_name", return_value=True):
                    _assert_authority_rejection(
                        self,
                        root,
                        state_path,
                        manifest_path,
                        "ambiguous-authority-path",
                        preserve=True,
                    )

    def test_run_and_adoption_share_traceability_completeness_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(
                root,
                phase="BLOCKED",
                blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"},
            )
            manifest = _canonical_manifest()
            manifest["workstreams"][0]["acceptanceIds"] = ["AC-02"]
            manifest_path = root / "plan.manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            before_state = state_path.read_bytes()

            run_receipt = run_workflow_step(
                state_path=state_path,
                manifest_path=manifest_path,
                operation_id="run-incomplete-plan",
                expected_revision=1,
                source_revision="source",
            )
            run_failure = next(
                blocker for blocker in run_receipt["blockers"] if blocker["code"] == "plan-completeness-failed"
            )

            with self.assertRaises(LifecycleError) as raised:
                adopt_plan(
                    state_path,
                    manifest_path=manifest_path,
                    operation_id="adopt-incomplete-plan",
                    expected_revision=1,
                    source_revision="source-2",
                    reset_tasks=True,
                    start_mode="auto-after-freeze",
                    authorized_by="tester",
                )

            run_codes = {item["code"] for item in run_failure["context"]["validation"]["blockers"]}
            adoption_codes = {item["code"] for item in raised.exception.details["validation"]["blockers"]}
            self.assertEqual(raised.exception.code, "plan-completeness-failed")
            self.assertEqual(run_codes, adoption_codes)
            self.assertEqual(run_codes, {"traceability-owner-count"})
            self.assertEqual(state_path.read_bytes(), before_state)

    def test_adopt_plan_rejects_unknown_authority_before_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(
                root, phase="BLOCKED", blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"}
            )
            _write_plan_bundle(root)
            manifest_path = root / "plans/package/plan.manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["schemaVersion"] = "agent-plan-manifest.v1"
            manifest["integrationSeams"] = ["controller"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            before = state_path.read_bytes()

            with self.assertRaises(LifecycleError) as raised:
                adopt_plan(
                    state_path,
                    manifest_path=manifest_path,
                    operation_id="adopt-invalid-op",
                    expected_revision=1,
                    source_revision="source-2",
                    reset_tasks=True,
                    start_mode="auto-after-freeze",
                    authorized_by="tester",
                )

            self.assertEqual(raised.exception.code, "plan-manifest-contract-failed")
            self.assertEqual(state_path.read_bytes(), before)

    def test_adopt_plan_resets_changed_plan_and_starts_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(
                root, phase="BLOCKED", blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"}
            )
            _write_plan_bundle(root, include_model_route=True)
            payload = adopt_plan(
                state_path,
                manifest_path=root / "plans/package/plan.manifest.json",
                operation_id="adopt-op",
                expected_revision=1,
                source_revision="source-2",
                reset_tasks=True,
                start_mode="auto-after-freeze",
                authorized_by="tester",
            )
            self.assertEqual(payload["phase"], "READY")
            self.assertEqual(payload["planRevision"], 2)
            self.assertEqual(payload["nextAction"]["type"], "start-execution")
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            task = next(item for item in stored["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "READY")
            self.assertEqual(task["modelRoute"]["modelClass"], "standard-code")

            payload = start_execution(
                state_path,
                operation_id="run-op",
                expected_revision=2,
                source_revision="source-2",
                reason="go",
            )
            self.assertEqual(payload["phase"], "RUNNING")
            self.assertEqual(payload["nextAction"]["taskIds"], ["WS-01"])

            payload = start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=3,
                source_revision="source-2",
                reason="launch",
            )
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            task = next(item for item in stored["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["attemptModelRoute"]["modelClass"], "standard-code")

    def test_adopt_plan_accepts_plan_lock_review_identity_without_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(
                root, phase="BLOCKED", blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"}
            )
            _write_plan_bundle(root, include_plan_review_report=False)

            payload = adopt_plan(
                state_path,
                manifest_path=root / "plans/package/plan.manifest.json",
                operation_id="adopt-op",
                expected_revision=1,
                source_revision="source-2",
                reset_tasks=True,
                start_mode="auto-after-freeze",
                authorized_by="tester",
            )

            self.assertEqual(payload["phase"], "READY")
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["lastPlanReview"]["surface"], "plan-lock")
            self.assertEqual(stored["lastPlanReview"]["reviewId"], "plan-review-r02")

    def test_adopt_plan_preserves_compatible_accepted_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(
                root, phase="BLOCKED", blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"}
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["status"] = "ACCEPTED"
            state["tasks"][0]["attempt"] = 3
            state["tasks"][0]["attemptHistoryStart"] = 3
            state["tasks"][0]["result"] = {
                "path": "work/WS-01/attempt-3/task-result.json",
                "sha256": "2" * 64,
                "bytes": 10,
            }
            state["tasks"][0]["review"] = {
                "path": "work/WS-01/attempt-3/task-review.json",
                "sha256": "3" * 64,
                "bytes": 10,
            }
            state["tasks"][0]["implementationAuditReport"] = {
                "path": "work/WS-01/attempt-3/implementation-audit.json",
                "sha256": "4" * 64,
                "bytes": 10,
                "taskId": "WS-01",
                "attempt": 3,
                "verdict": "ACCEPTED",
                "reportDigest": "5" * 64,
            }
            state_path.write_text(json.dumps(state), encoding="utf-8")
            _write_plan_bundle(root)

            payload = adopt_plan(
                state_path,
                manifest_path=root / "plans/package/plan.manifest.json",
                operation_id="adopt-op",
                expected_revision=1,
                source_revision="source-2",
                reset_tasks=True,
                preserve_accepted_compatible=True,
                start_mode="auto-after-freeze",
                authorized_by="tester",
            )

            task = next(item for item in payload["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "ACCEPTED")
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            stored_task = next(item for item in stored["tasks"] if item["id"] == "WS-01")
            self.assertEqual(stored_task["adoptedFromPlanRevision"], 1)
            self.assertEqual(stored_task["attemptHistoryStart"], 3)
            for field in ("result", "review", "implementationAuditReport"):
                self.assertEqual(stored_task[field], state["tasks"][0][field])
            self.assertEqual(stored["priorSnapshots"][-1]["taskSummary"]["WS-01"], "ACCEPTED")
            receipt = stored_task["planCompatibilityReceipt"]
            self.assertEqual(receipt["schemaVersion"], "agent-task-plan-compatibility-receipt.v1")
            self.assertEqual(receipt["previousPlan"]["planRevision"], 1)
            self.assertEqual(receipt["currentPlan"]["planRevision"], 2)
            self.assertEqual(receipt["acceptedArtifacts"]["implementationAuditReport"]["sha256"], "4" * 64)
            self.assertEqual(payload["phase"], "READY")

            payload = start_execution(
                state_path,
                operation_id="resume-accepted",
                expected_revision=2,
                source_revision="source-2",
                reason="finish the preserved accepted task",
            )
            self.assertEqual(payload["phase"], "FINAL_AUDIT")

    def test_adopt_plan_preserve_unlocks_new_dependents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(
                root, phase="BLOCKED", blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"}
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["status"] = "ACCEPTED"
            state["tasks"][0]["attempt"] = 1
            state_path.write_text(json.dumps(state), encoding="utf-8")
            _write_plan_bundle(root, include_dependent=True)

            payload = adopt_plan(
                state_path,
                manifest_path=root / "plans/package/plan.manifest.json",
                operation_id="adopt-op",
                expected_revision=1,
                source_revision="source-2",
                reset_tasks=True,
                preserve_accepted_compatible=True,
                start_mode="auto-after-freeze",
                authorized_by="tester",
            )

            task = next(item for item in payload["tasks"] if item["id"] == "WS-02")
            self.assertEqual(task["status"], "READY")

    def test_preserved_v4_acceptance_reaches_final_proof_after_authorization(self) -> None:
        from agent_lifecycle.contracts import write_json_create
        from agent_lifecycle.workflow import apply_final_audit_outcome, authorize_execution, finalize_run
        from agent_lifecycle.workflow.artifacts import artifact_identity
        from tests.workflow.test_authorization import _receipt

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="FINAL_AUDIT")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state.update(schemaVersion="agent-workflow-state.v4", packageRoot=".", operationLedger={})
            task = state["tasks"][0]
            task.update(status="ACCEPTED", attempt=1, attemptHistoryStart=1, attemptHistory=[])
            accepted_files = {}
            for field, value in (
                ("result", {"schemaVersion": "agent-task-result.v2", "changedFiles": []}),
                ("review", {"schemaVersion": "agent-task-review.v2", "verdict": "ACCEPTED"}),
            ):
                path = task["artifactPaths"][field].replace("{attempt}", "1")
                write_json_create(root / path, value)
                task[field] = artifact_identity(root, path, value)
                accepted_files[path] = (root / path).read_bytes()
            state_path.write_text(json.dumps(state), encoding="utf-8")
            _write_plan_bundle(root)
            adopted = adopt_plan(
                state_path,
                manifest_path=root / "plans/package/plan.manifest.json",
                operation_id="adopt-preserved-v4",
                expected_revision=1,
                source_revision="source-2",
                reset_tasks=True,
                preserve_accepted_compatible=True,
                start_mode="approval-required",
                authorized_by="tester",
            )
            self.assertEqual(adopted["phase"], "AWAITING_AUTHORIZATION")
            before = state_path.read_bytes()
            with self.assertRaises(LifecycleError) as raised:
                start_execution(
                    state_path, operation_id="before-approval", expected_revision=2,
                    source_revision="source-2", reason="must require fresh approval",
                )
            self.assertEqual(raised.exception.code, "invalid-phase")
            self.assertEqual(state_path.read_bytes(), before)
            adopted_state = json.loads(before)
            write_json_create(root / "authorization.json", _receipt(adopted_state))
            authorize_execution(
                state_path, operation_id="authorize-resume", expected_revision=2,
                source_revision="source-2", receipt_path="authorization.json", reason="fresh authority",
            )
            started = start_execution(
                state_path, operation_id="start-preserved-v4", expected_revision=3,
                source_revision="source-2", reason="finalize unchanged acceptance",
            )
            self.assertEqual(started["phase"], "FINAL_AUDIT")
            self.assertEqual(started["nextAction"]["type"], "final-audit-outcome")
            current = json.loads(state_path.read_text(encoding="utf-8"))
            for field in ("status", "attempt", "result", "review", "planCompatibilityReceipt"):
                self.assertEqual(current["tasks"][0][field], adopted_state["tasks"][0][field])
            lineage = {key: current[key] for key in (
                "runId", "packageId", "planRevision", "planDigest", "sourceRevision",
            )}
            verifier = {"id": "final-auditor", "independent": True}
            audit = {
                "schemaVersion": "agent-run-final-audit.v1", **lineage,
                "status": "PASS", "verdict": "ACCEPTED", "semanticStatus": "READY_FOR_FINALIZATION",
                "verifier": verifier, "productionPromotionClaimed": False, "findings": [],
                "notAcceptedTasks": [], "missingReleaseEvidence": [],
                "completionSignal": {
                    "schemaVersion": "agent-completion-signal.v1", **lineage,
                    "status": "PASS", "evidenceIds": ["EV-FINAL"], "verifier": verifier,
                },
            }
            write_json_create(root / "final/final-audit.json", audit)
            apply_final_audit_outcome(
                state_path, operation_id="accept-final", expected_revision=4,
                source_revision="source-2", final_audit_path="final/final-audit.json",
                verdict="ACCEPTED", reason="independent final acceptance",
            )
            finished = finalize_run(
                state_path, operation_id="finalize-preserved", expected_revision=5,
                source_revision="source-2", final_audit_path="final/final-audit.json",
                proof_path="final/proof.json", reason="complete without repeating the task",
            )
            self.assertEqual(finished["phase"], "COMPLETE")
            self.assertTrue((root / "final/proof.json").is_file())
            for path, content in accepted_files.items():
                self.assertEqual((root / path).read_bytes(), content)

    def test_start_accepted_tasks_still_requires_authority(self) -> None:
        cases = (
            ("READY", "approval-required", False, "source", "authorization-required"),
            ("READY", "approval-required", True, "different-source", "source-revision-mismatch"),
            ("READY", "plan-only", True, "source", "plan-only-not-executable"),
        )
        for phase, mode, granted, source, code in cases:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as tmp:
                state_path = _write_state(Path(tmp), phase=phase)
                state = json.loads(state_path.read_text(encoding="utf-8"))
                state["tasks"][0]["status"] = "ACCEPTED"
                state["startMode"] = mode
                state["authorization"]["granted"] = granted
                state_path.write_text(json.dumps(state), encoding="utf-8")
                before = state_path.read_bytes()
                with self.assertRaises(LifecycleError) as raised:
                    start_execution(
                        state_path, operation_id="invalid-start", expected_revision=1,
                        source_revision=source, reason="must preserve authority checks",
                    )
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(state_path.read_bytes(), before)

    def test_start_phase_depends_on_nonempty_required_task_set(self) -> None:
        cases = (
            ([], "RUNNING"),
            ([(False, "ACCEPTED")], "RUNNING"),
            ([(True, "ACCEPTED"), (True, "READY")], "RUNNING"),
            ([(True, "ACCEPTED"), (False, "READY")], "FINAL_AUDIT"),
        )
        for task_states, expected in cases:
            with self.subTest(tasks=task_states), tempfile.TemporaryDirectory() as tmp:
                state_path = _write_state(Path(tmp), phase="READY")
                state = json.loads(state_path.read_text(encoding="utf-8"))
                template = state["tasks"][0]
                state["tasks"] = [
                    {**template, "id": f"WS-{i}", "required": required, "status": task_status}
                    for i, (required, task_status) in enumerate(task_states)
                ]
                state_path.write_text(json.dumps(state), encoding="utf-8")
                started = start_execution(
                    state_path, operation_id="select-phase", expected_revision=1,
                    source_revision="source", reason="select the next required work",
                )
                self.assertEqual(started["phase"], expected)

    def test_adopt_plan_copies_completion_check_to_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(
                root, phase="BLOCKED", blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"}
            )
            _write_plan_bundle(root, include_completion_check=True)

            adopt_plan(
                state_path,
                manifest_path=root / "plans/package/plan.manifest.json",
                operation_id="adopt-op",
                expected_revision=1,
                source_revision="source-2",
                reset_tasks=True,
                start_mode="auto-after-freeze",
                authorized_by="tester",
            )

            stored = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["completionCheck"]["checkId"], "done-check")
            self.assertEqual(
                stored["completionCheckValidation"]["schemaVersion"], "agent-completion-check-validation.v1"
            )
            self.assertEqual(stored["completionCheck"]["receiptPath"], "final/completion-check-receipt.json")


if __name__ == "__main__":
    unittest.main()


class R1054ProtectionTests(unittest.TestCase):
    def test_adoption_retains_task_protections_and_runtime_precedence(self):
        from agent_lifecycle.workflow.task_transitions import _validate_task_write_scope
        for kind in ('legacy','integrity'):
            with self.subTest(lock=kind),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);state_path=_write_state(root,phase='READY')
                fields={'readOnly':['references'],'forbiddenWrites':['controller/protected'],'leadOwned':[{'path':'receipts'}]}
                manifest=_write_authority_bundle(root,kind=kind,global_fields={'leadOwned':[{'path':'controller'}]},task_fields=fields)
                _adopt_authority_bundle(state_path,manifest);state=json.loads(state_path.read_text());task=state['tasks'][0]
                for field,value in fields.items():self.assertEqual(task.get(field),value)
                before=json.loads(json.dumps(state))
                for path,category in (('controller/protected/output','forbidden'),('references/input','read-only')):
                    with self.subTest(path=path),self.assertRaises(LifecycleError) as caught:_validate_task_write_scope(state,task,{'changedFiles':[path]})
                    self.assertEqual(caught.exception.code,'task-ownership-violation');self.assertEqual(caught.exception.details['ownership']['blockers'][0]['category'],category)
                self.assertEqual(_validate_task_write_scope(state,task,{'changedFiles':['receipts/evidence']})['entries'][0]['category'],'lead-owned')
                self.assertEqual(state,before)

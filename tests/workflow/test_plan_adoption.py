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
from agent_lifecycle.workflow import run_workflow_step  # noqa: E402

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


def _assert_authority_rejection(test, root, state_path, manifest_path, code, *, preserve=False):
    journal = root / "events.jsonl"
    if not journal.exists():
        journal.write_bytes(b'{"schemaVersion":"agent-workflow-event.v1","stateRevision":1}\n')
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

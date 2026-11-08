"""Actual producers and native adoption on isolated UNIT_ONLY fixtures."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from agent_lifecycle.accounting.declared_source_route import canonical_source_bytes, prepare_project_opening
from agent_lifecycle.adapter_sessions import launch_preflight, stage_launch
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.declared_source_schemas import DATA_LIMIT, validate_project_head
from agent_lifecycle.workflow import start_task
from agent_lifecycle.workflow.limited_usage import current_source_snapshot
from agent_lifecycle.workflow.source_usage_prepare import prepare_source_admission, prepare_source_receipt
from tests.accounting.test_generic_source_usage import GenericFixture, minimal_nonempty_carry_at_size, write_data
from tests.adapter_sessions.test_stage_launch import select
from tests.cli.test_model_setup import run_cli
from tests.workflow.test_stage_binding_adoption import adopt, prepare


def canonical_generic_run(root: Path) -> GenericFixture:
    """Real v4 initialization/adoption/authorization; reviews are synthetic UNIT_ONLY."""
    from agent_lifecycle.compiler.task_packets import compile_task_packets
    from agent_lifecycle.freeze.package_integrity import build_plan_lock_v2
    from agent_lifecycle.workflow import adopt_plan, authorize_execution, initialize_workflow_state, start_execution
    from tests.workflow.test_authorization import _receipt

    f = GenericFixture(root, git_backed=True, two_tasks=True, probe_only=True)
    # Runtime/private fixture inputs are outside the tracked source contribution.
    (root / ".git/info/exclude").write_text(
        ".alk/\n.codex/\ninput/\nnative.state.json\nnative.events.jsonl\nauthorization.json\n"
    )
    f.manifest["orchestration"] = {
        "maxParallelTasks": 1,
        "maxTaskAttempts": 1,
        "maxTaskWallSeconds": 600,
        "maxRunWallSeconds": 3600,
        "maxToolCallsPerTask": 1000,
    }
    f.manifest["releaseTarget"] = {"targetVersion": "1.0.0"}
    f.manifest["specification"]["requirements"] = [
        {"id": "R-1", "description": "UNIT_ONLY probe"},
        {"id": "R-2", "description": "UNIT_ONLY managed contribution"},
    ]
    f.manifest["acceptance"]["criteria"] = [
        {"id": "AC-1", "requirementIds": ["R-1"], "evidenceIds": ["EV-1"]},
        {"id": "AC-2", "requirementIds": ["R-2"], "evidenceIds": ["EV-2"]},
    ]
    f.manifest["finalAuditGates"] = ["[AC-1|EV-1] UNIT_ONLY probe", "[AC-2|EV-2] UNIT_ONLY managed contribution"]
    f.manifest["acceptance"]["evidence"] = [
        {"id": "EV-1", "artifactPath": "work/EV-1.unit.json", "description": "Declared UNIT_ONLY probe API evidence"},
        {"id": "EV-2", "artifactPath": "work/EV-2.unit.json", "description": "Declared UNIT_ONLY managed API evidence"},
    ]
    for index, row in enumerate(f.manifest["workstreams"], 1):
        row.update(
            reviewer="reviewer",
            plannedItems=[f"R-{index}"],
            writes=["src/" + row["id"] + ".py"],
            acceptanceIds=[f"AC-{index}"],
            evidenceIds=[f"EV-{index}"],
            artifactPaths={
                "result": f"work/{row['id']}/attempt-{{attempt}}/task-result.json",
                "review": f"work/{row['id']}/attempt-{{attempt}}/task-review.json",
            },
        )
    review_path = "tasks/strategy/unit-plan-review.json"
    f.manifest["planFiles"] = sorted([*f.manifest["planFiles"], review_path])
    f.manifest["planReview"] = {
        "required": True,
        "report": review_path,
        "reviewedRevision": 1,
        "verdict": "READY_TO_FREEZE",
    }
    review = {
        "schemaVersion": "agent-plan-review.v1",
        "reviewId": "UNIT_ONLY-plan",
        "reviewer": {"id": "unit-reviewer", "runId": "unit", "surface": "unit", "independent": True},
        "packageId": "package",
        "planRevision": 1,
        "reviewedPlanHash": canonical_digest(f.manifest),
        "fullReview": True,
        "verdict": "READY_TO_FREEZE",
        "findings": [],
    }
    write_data(root, review_path, review)
    write_data(root, "tasks/strategy/plan.manifest.json", f.manifest)
    write_data(root, "tasks/strategy/plan.lock.json", build_plan_lock_v2(f.manifest, repository_root=root))
    f.state_path = root / "native.state.json"
    initialize_workflow_state(f.state_path, run_id="run", package_id="package", event_log="native.events.jsonl")
    try:
        compile_task_packets(f.manifest_path, repository_root=root, write=True)
    except LifecycleError as error:
        raise AssertionError({"code": error.code, "details": error.details}) from error
    adopt_plan(
        f.state_path,
        manifest_path=f.manifest_path,
        operation_id="adopt-unit",
        expected_revision=1,
        source_revision=f.revision,
        reset_tasks=False,
        start_mode="approval-required",
    )
    state = json.loads(f.state_path.read_text())
    write_data(root, "authorization.json", _receipt(state))
    authorize_execution(
        f.state_path,
        operation_id="authorize-unit",
        expected_revision=state["stateRevision"],
        source_revision=f.revision,
        receipt_path="authorization.json",
        reason="UNIT_ONLY",
    )
    state = json.loads(f.state_path.read_text())
    start_execution(
        f.state_path,
        operation_id="run-unit",
        expected_revision=state["stateRevision"],
        source_revision=f.revision,
        reason="UNIT_ONLY",
    )
    return f


def canonical_complete_task(f: GenericFixture, task_id: str, operation: str, *, probe: bool) -> dict:
    from agent_lifecycle.audit.implementation import build_implementation_audit_report
    from agent_lifecycle.changesets import capture_task_change_set
    from agent_lifecycle.workflow import apply_task_review_outcome, commit_task_result
    from agent_lifecycle.workflow.artifacts import artifact_path
    from tests.workflow.helpers import _result, _review
    from tests.workflow.test_task_transitions import _strategy_start_inputs

    state = json.loads(f.state_path.read_text())
    output = f.root / ("work/strategy-" + task_id + ".json")
    prepared = prepare(
        f.root,
        f.state_path,
        output,
        f.profile,
        task_id=task_id,
        operation_id=operation,
        source_revision=f.revision,
        binding_id="primary",
    )
    assert prepared["status"] == "READY", prepared
    start_task(
        f.state_path,
        task_id=task_id,
        operation_id=operation,
        expected_revision=state["stateRevision"],
        source_revision=f.revision,
        strategy_path=output.relative_to(f.root).as_posix(),
        strategy_inputs={**_strategy_start_inputs(), "hostProfilePath": ".alk/host-launch/host.json"},
        reason="UNIT_ONLY",
    )
    state = json.loads(f.state_path.read_text())
    task = next(row for row in state["tasks"] if row["id"] == task_id)
    args = {**authority_args(f), "task_id": task_id, "operation_id": operation}
    head = f.context().source.read_current()["headSha256"]
    window = "work/source/windows/" + task_id + ".json"
    prepare_source_admission(**args, expected_head_sha256=head, out=window)
    if probe:
        argv = [
            "model",
            "availability",
            "--project-profile",
            ".alk/project-profile.json",
            "--probe",
            "--binding",
            "primary",
            "--state",
            str(f.state_path),
            "--manifest",
            str(f.manifest_path),
            "--lock",
            str(f.manifest_path.with_name("plan.lock.json")),
            "--task",
            task_id,
            "--operation-id",
            operation,
            "--expected-revision",
            str(state["stateRevision"]),
            "--source-revision",
            f.revision,
            "--authorization-receipt",
            str(f.root / "authorization.json"),
            "--max-invocations",
            "1",
            "--max-wall-seconds",
            "30",
            "--max-output-bytes",
            "4096",
        ]
        runner = Mock(
            return_value={
                "status": "PASS",
                "processStarted": True,
                "exitCode": 0,
                "stdoutTail": (
                    '{"type":"item.completed","item":{"type":"agent_message","text":"UNIT_ONLY response"}}\n'
                    '{"type":"turn.completed"}\n'
                ),
            }
        )
        runner.return_value["stdout"] = runner.return_value["stdoutTail"]
        with patch("agent_lifecycle.adapter_sessions.launcher.run_process", runner):
            code, launched = run_cli(f.root, argv)
        assert code == 0 and launched["status"] == "PASS", launched
        runner.assert_called_once()
        code, repeated = run_cli(f.root, argv)
        assert code != 0 and repeated["code"] == "model-probe-already-attempted", repeated
    else:
        launched = prepare(
            f.root,
            f.state_path,
            output,
            f.profile,
            task_id=task_id,
            operation_id=operation,
            source_revision=f.revision,
            binding_id="primary",
            launch=True,
            strategy_out_path=None,
        )
        assert launched["hostLaunchStarted"], launched
        assert canonical_digest("UNIT_ONLY managed response") in json.dumps(launched), launched
    frozen_task = next(row for row in f.manifest["workstreams"] if row["id"] == task_id)
    planned_item = frozen_task["plannedItems"][0]
    evidence = capture_task_change_set(f.root, baseline=f.revision, write_paths=task["writes"])
    result = _result(attempt=1)
    result.update(
        taskId=task_id,
        sourceRevision=f.revision,
        planDigest=state["planDigest"],
        taskPacketHash=task["packet"]["sha256"],
        changedFiles=evidence["changedFiles"],
        changeSet={
            "schemaVersion": "agent-task-change-set-claim.v1",
            **{key: evidence[key] for key in ("provider", "baselineSha", "fileSetHash", "diffHash", "snapshotHash")},
        },
        itemOutcomes=[
            {
                "plannedItemId": planned_item,
                "status": "COMPLETE",
                "changedFiles": evidence["changedFiles"],
                "commandIds": [],
            }
        ],
    )
    result_path = artifact_path(task, "result", 1)
    usage_path = str(Path(result_path).with_name("usage.json"))
    write_data(f.root, result_path, result)
    prepare_source_receipt(**args, window=window, out=usage_path)
    commit_task_result(
        f.state_path,
        task_id=task_id,
        operation_id="result-" + task_id,
        expected_revision=state["stateRevision"],
        source_revision=f.revision,
        result_path=result_path,
        model_usage_receipt_path=usage_path,
        reason="UNIT_ONLY",
    )
    state = json.loads(f.state_path.read_text())
    review = _review(attempt=1, result_hash=canonical_digest(result), plan_digest=state["planDigest"])
    review.update(
        taskId=task_id,
        taskPacketHash=task["packet"]["sha256"],
        itemReviews=[{"plannedItemId": planned_item, "verdict": "ACCEPTED", "findingIds": []}],
        acceptanceChecks=[
            {
                "acceptanceId": frozen_task["acceptanceIds"][0],
                "status": "PASS",
                "evidenceIds": frozen_task["evidenceIds"],
                "findingIds": [],
            }
        ],
    )
    review_path = artifact_path(task, "review", 1)
    write_data(f.root, review_path, review)
    evidence_entry = next(
        row for row in f.manifest["acceptance"]["evidence"] if row["id"] == frozen_task["evidenceIds"][0]
    )
    usage = json.loads((f.root / usage_path).read_text())
    write_data(
        f.root,
        evidence_entry["artifactPath"],
        {
            "schemaVersion": "unit-only-declared-source-evidence.v1",
            "evidenceId": evidence_entry["id"],
            "taskId": task_id,
            "sourceRevision": f.revision,
            "planDigest": state["planDigest"],
            "transport": "MOCKED_UNIT_ONLY",
            "liveModelQualification": "UNAVAILABLE",
            "nativeResultDigest": canonical_digest(result),
            "usageReceiptDigest": canonical_digest(usage),
            "originalAdmissionRef": usage["currentAdmissionRef"],
            "actualTokens": None,
            "actualUSD": None,
        },
    )
    report = build_implementation_audit_report(
        manifest_path=f.manifest_path,
        state_path=f.state_path,
        task_id=task_id,
        result_path=result_path,
        review_path=review_path,
        evidence_paths=[evidence_entry["artifactPath"]],
    )
    assert report["status"] == "PASS", report["blockers"]
    audit_path = str(Path(result_path).with_name("implementation-audit.json"))
    write_data(f.root, audit_path, report)
    apply_task_review_outcome(
        f.state_path,
        task_id=task_id,
        operation_id="accept-" + task_id,
        expected_revision=state["stateRevision"],
        source_revision=f.revision,
        review_path=review_path,
        implementation_audit_path=audit_path,
        reason="UNIT_ONLY",
    )
    return json.loads((f.root / usage_path).read_text())


def authority_args(f: GenericFixture) -> dict:
    state = json.loads(f.state_path.read_text())
    return dict(
        state_path=f.state_path,
        manifest_path=f.manifest_path,
        lock_path=f.manifest_path.with_name("plan.lock.json"),
        task_id="WS-01",
        operation_id="start-strategy",
        expected_revision=state["stateRevision"],
        source_revision=state["sourceRevision"],
        actor_id="worker",
    )


class SourceUsagePrepareTests(unittest.TestCase):
    def test_canonical_v4_two_task_probe_managed_result_acceptance_and_finalization_unit_only(self) -> None:
        from agent_lifecycle.workflow import apply_final_audit_outcome, finalize_run
        from tests.workflow.helpers import _final_audit

        with tempfile.TemporaryDirectory() as tmp:
            f = canonical_generic_run(Path(tmp).resolve())
            for path in (f.root / ".alk/host-launch").glob("availability-*.json"):
                path.unlink()
            original_state = json.loads(f.state_path.read_text())
            first = canonical_complete_task(f, "WS-01", "probe-unit", probe=True)
            managed_stdout = (
                json.dumps(
                    {"type": "item.completed", "item": {"type": "agent_message", "text": "UNIT_ONLY managed response"}}
                )
                + "\n"
                + json.dumps({"type": "turn.completed"})
                + "\n"
            )
            runner = Mock(
                return_value={
                    "status": "PASS",
                    "processStarted": True,
                    "exitCode": 0,
                    "stdout": managed_stdout,
                    "stdoutTail": managed_stdout,
                }
            )
            with patch("agent_lifecycle.adapter_sessions.launcher.run_process", runner):
                second = canonical_complete_task(f, "WS-02", "managed-unit", probe=False)
            runner.assert_called_once()
            self.assertNotEqual(first["currentAdmissionRef"], second["currentAdmissionRef"])
            state = json.loads(f.state_path.read_text())
            self.assertEqual(state["phase"], "FINAL_AUDIT")
            self.assertTrue(all(task["status"] == "ACCEPTED" for task in state["tasks"]))
            self.assertEqual(state["runStartedAt"], original_state["runStartedAt"])
            self.assertEqual(state["runDeadlineAt"], original_state["runDeadlineAt"])
            audit = _final_audit()
            audit.update(runId=state["runId"], packageId=state["packageId"], sourceRevision=state["sourceRevision"])
            audit["planDigest"] = state["planDigest"]
            audit["completionSignal"].update(planDigest=state["planDigest"], sourceRevision=f.revision)
            write_data(f.root, "work/final-unit-audit.json", audit)
            apply_final_audit_outcome(
                f.state_path,
                operation_id="final-unit-outcome",
                expected_revision=state["stateRevision"],
                source_revision=f.revision,
                final_audit_path="work/final-unit-audit.json",
                verdict="ACCEPTED",
                reason="synthetic UNIT_ONLY review",
            )
            state = json.loads(f.state_path.read_text())
            finalize_run(
                f.state_path,
                operation_id="final-unit",
                expected_revision=state["stateRevision"],
                source_revision=f.revision,
                final_audit_path="work/final-unit-audit.json",
                proof_path="work/final-unit-proof.json",
                reason="UNIT_ONLY",
            )
            proof = json.loads((f.root / "work/final-unit-proof.json").read_text())
            self.assertEqual(proof["usageAssurance"]["guarantee"], "LIMITED_DECLARED_SOURCE_ACCOUNTING")
            self.assertIsNone(proof["usageAssurance"]["actualTokens"])
            self.assertEqual(json.loads(f.state_path.read_text())["phase"], "COMPLETE")

    def test_actual_producers_use_full_persisted_hold_and_immutable_original_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = GenericFixture(Path(tmp))
            f.start()
            context = f.context()
            head = context.source.read_current()["headSha256"]
            window = "work/source/windows/unit-window.json"
            before_state = f.state_path.read_bytes()
            admission = prepare_source_admission(**authority_args(f), expected_head_sha256=head, out=window)
            repeated = prepare_source_admission(**authority_args(f), expected_head_sha256=head, out=window)
            self.assertEqual(repeated["windowRef"], admission["windowRef"])
            held = json.loads((f.root / window).read_text())
            task = json.loads(before_state)["tasks"][0]
            self.assertEqual(
                held["declaredTokenHold"], task["attemptExecutionStrategy"]["resourceCaps"]["maxBillableTokens"]
            )
            self.assertEqual(admission["financialClosure"], "OPEN_UNAVAILABLE")
            original = (f.root / window).read_bytes()
            usage_path = "work/WS-01/attempt-1/model-usage.json"
            result = prepare_source_receipt(**authority_args(f), window=window, out=usage_path)
            usage = json.loads((f.root / usage_path).read_text())
            self.assertEqual(usage["attestation"], {"source": "alk-declared", "status": "UNAVAILABLE"})
            self.assertTrue(all(value is None for value in usage["usage"].values()))
            self.assertEqual((f.root / usage_path).read_bytes(), canonical_source_bytes(usage))
            self.assertEqual((f.root / window).read_bytes(), original)
            self.assertEqual(f.state_path.read_bytes(), before_state)
            self.assertFalse(result["executionAuthorized"])
            with self.assertRaises(FileExistsError):
                prepare_source_receipt(**authority_args(f), window=window, out=usage_path)

    def test_public_cli_opening_requires_explicit_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = GenericFixture(Path(tmp))
            code, result = run_cli(
                f.root,
                [
                    "workflow",
                    "source-usage-prepare",
                    "--phase",
                    "opening",
                    "--input",
                    "input/carry.json",
                    "--owner-bindings",
                    "input/owners.json",
                    "--opening-out",
                    "other-inputs",
                    "--out",
                    "other-source",
                ],
            )
            self.assertEqual(code, 0, result)
            self.assertEqual(result["status"], "SOURCE_DATA_ONLY")
            self.assertFalse(result["executionAuthorized"])

    def test_admission_receipt_refuse_foreign_native_subject_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = GenericFixture(Path(tmp))
            f.start()
            head = f.context().source.read_current()["headSha256"]
            for overrides in (
                {"actor_id": "foreign"},
                {"operation_id": "foreign"},
                {"source_revision": "foreign"},
                {"expected_revision": 1},
                {"task_id": "foreign"},
            ):
                before = (f.root / "work/source/HEAD.json").read_bytes()
                with self.subTest(overrides=overrides), self.assertRaises(LifecycleError):
                    prepare_source_admission(
                        **{**authority_args(f), **overrides},
                        expected_head_sha256=head,
                        out="work/source/windows/refused.json",
                    )
                self.assertEqual((f.root / "work/source/HEAD.json").read_bytes(), before)
            window = "work/source/windows/original.json"
            prepare_source_admission(**authority_args(f), expected_head_sha256=head, out=window)
            with self.assertRaises(LifecycleError):
                prepare_source_receipt(
                    **authority_args(f),
                    window="work/source/windows/foreign.json",
                    out="work/WS-01/attempt-1/refused-usage.json",
                )

    def test_probe_bootstrap_canonical_strategy_risk_and_both_managed_rechecks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = GenericFixture(Path(tmp), probe_only=True)
            for path in (f.root / ".alk/host-launch").glob("availability-*.json"):
                path.unlink()
            before = f.state_path.read_bytes()
            prepared = prepare(f.root, f.state_path, f.strategy_path, f.profile, binding_id="primary")
            self.assertEqual(prepared["status"], "READY", prepared)
            self.assertEqual(before, f.state_path.read_bytes())
            # The explicit diagnostic projection supplies checked inputs, never native adoption.
            state = json.loads(before)
            selected = select(f.root, f.profile, state=state, task_id="WS-01", explicit_probe=True)
            risk = stage_launch.derive_binding_risk(
                selected,
                root=f.root,
                state_path=f.state_path,
                manifest_path=f.manifest_path,
                task_id="WS-01",
                operation_id="start-strategy",
                source_revision="source",
            )
            write_data(f.root, "work/probe-risk.json", risk)
            with self.assertRaises(LifecycleError) as risk_only:
                start_task(
                    f.state_path,
                    task_id="WS-01",
                    operation_id="start-strategy",
                    expected_revision=1,
                    source_revision="source",
                    risk_profile_path="work/probe-risk.json",
                    reason="UNIT_ONLY",
                )
            self.assertEqual(risk_only.exception.code, "scoped-usage-strategy-required")
            adopt(f.state_path, f.strategy_path, risk_profile_path="work/probe-risk.json")
            state = json.loads(f.state_path.read_text())
            selected = select(f.root, f.profile, state=state, task_id="WS-01", explicit_probe=True)
            sealed = stage_launch.seal_stage_launch(
                selected, state_path=f.state_path, task_id="WS-01", source_revision="source"
            )
            self.assertEqual(sealed["neutralBinding"], state["tasks"][0]["attemptExecutionStrategy"]["stageBinding"])
            risk = stage_launch.derive_binding_risk(
                sealed,
                root=f.root,
                state_path=f.state_path,
                manifest_path=f.manifest_path,
                task_id="WS-01",
                operation_id="start-strategy",
                source_revision="source",
            )
            runner = Mock(return_value={"status": "PASS", "processStarted": True, "exitCode": 0})
            original_validator = launch_preflight.validate_task_risk_profile
            with (
                patch.object(stage_launch, "capture_git_worktree_identity", return_value={"head": "source"}),
                patch.object(launch_preflight, "validate_task_risk_profile", wraps=original_validator) as validations,
            ):
                launched = launch_preflight.launch_from_local_profile(
                    profile_path=selected["inspected"]["launchPath"],
                    operation="managedTask",
                    adapter_id="codex",
                    project_root=f.root,
                    explicit_launch=True,
                    state_path=f.state_path,
                    manifest_path=f.manifest_path,
                    lock_path=f.manifest_path.with_name("plan.lock.json"),
                    task_id="WS-01",
                    operation_id="start-strategy",
                    source_revision="source",
                    risk_profile=risk,
                    process_runner=runner,
                    stage_binding=sealed,
                )
            self.assertEqual(launched["status"], "PASS", launched)
            self.assertEqual(validations.call_count, 2)
            self.assertTrue(all(call.kwargs["repository_root"] == f.root for call in validations.call_args_list))
            runner.assert_called_once()
            ordinary = {**sealed, "explicitProbe": False}
            with (
                patch.object(stage_launch, "capture_git_worktree_identity", return_value={"head": "source"}),
                self.assertRaises(LifecycleError) as refused,
            ):
                stage_launch.verify_stage_sink(type("Context", (), {"root": f.root})(), ordinary)
            self.assertEqual(refused.exception.code, "stage-binding-probe-only")

    def test_each_actual_managed_risk_recheck_refuses_missing_source_root(self) -> None:
        for sink in (1, 2):
            with self.subTest(sink=sink), tempfile.TemporaryDirectory() as tmp:
                f = GenericFixture(Path(tmp))
                f.start()
                state = json.loads(f.state_path.read_text())
                selected = select(f.root, f.profile, state=state, task_id="WS-01")
                sealed = stage_launch.seal_stage_launch(
                    selected, state_path=f.state_path, task_id="WS-01", source_revision="source"
                )
                risk = stage_launch.derive_binding_risk(
                    sealed,
                    root=f.root,
                    state_path=f.state_path,
                    manifest_path=f.manifest_path,
                    task_id="WS-01",
                    operation_id="start-strategy",
                    source_revision="source",
                )
                original = launch_preflight.validate_task_risk_profile
                calls = 0

                def missing_context(
                    *args: object, sink_index: int = sink, checked=original, **kwargs: object
                ) -> object:
                    nonlocal calls
                    calls += 1
                    if calls == sink_index:
                        kwargs.pop("repository_root", None)
                    return checked(*args, **kwargs)

                runner = Mock()
                with (
                    patch.object(stage_launch, "capture_git_worktree_identity", return_value={"head": "source"}),
                    patch.object(launch_preflight, "validate_task_risk_profile", side_effect=missing_context),
                ):
                    launched = launch_preflight.launch_from_local_profile(
                        profile_path=selected["inspected"]["launchPath"],
                        operation="managedTask",
                        adapter_id="codex",
                        project_root=f.root,
                        explicit_launch=True,
                        state_path=f.state_path,
                        manifest_path=f.manifest_path,
                        lock_path=f.manifest_path.with_name("plan.lock.json"),
                        task_id="WS-01",
                        operation_id="start-strategy",
                        source_revision="source",
                        risk_profile=risk,
                        process_runner=runner,
                        stage_binding=sealed,
                    )
                self.assertEqual(launched["status"], "BLOCKED", launched)
                self.assertEqual(calls, sink)
                runner.assert_not_called()

    def test_first_probe_exception_requires_frozen_boolean_and_explicit_readonly_preparation(self) -> None:
        for mutation in ("nonboolean", "ordinary", "no-binding", "launch", "wrong-revision", "forged-state"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                f = GenericFixture(Path(tmp), probe_only=True)
                for path in (f.root / ".alk/host-launch").glob("availability-*.json"):
                    path.unlink()
                overrides: dict[str, Any] = {"binding_id": "primary"}
                if mutation in {"nonboolean", "ordinary"}:
                    f.manifest["workstreams"][0]["executionPolicy"]["availabilityProbeOnly"] = (
                        "true" if mutation == "nonboolean" else False
                    )
                    f.refreeze()
                elif mutation == "no-binding":
                    overrides = {}
                elif mutation == "launch":
                    overrides["launch"] = True
                elif mutation == "wrong-revision":
                    overrides["expected_revision"] = 99
                else:
                    state = json.loads(f.state_path.read_text())
                    state["tasks"][0]["executionPolicy"]["availabilityProbeOnly"] = True
                    f.manifest["workstreams"][0]["executionPolicy"]["availabilityProbeOnly"] = False
                    f.refreeze()
                    write_data(f.root, f.state_path.name, {**state, "planDigest": canonical_digest(f.manifest)})
                with self.assertRaises(LifecycleError):
                    prepare(f.root, f.state_path, f.strategy_path, f.profile, **overrides)
                self.assertFalse(f.strategy_path.exists())

    def test_normal_producer_valid_head_wrapper_remains_observable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            f = GenericFixture(root)
            identifier = "p" + "x" * 127
            carry = minimal_nonempty_carry_at_size(f.carry, 64000)
            head = json.loads((root / f.policy["openingRef"]["path"]).read_text())
            predicted = {
                **head,
                "unknownIntervals": carry["unknownIntervals"],
                "sequence": 1,
                "previousHeadSha256": "0" * 64,
                "openingHeadSha256": "0" * 64,
                "windows": [{"path": "windows/" + identifier + ".json", "sha256": "0" * 64, "bytes": 1000}],
            }
            target = 64000 + 65500 - len(canonical_bytes(predicted))
            assert target <= DATA_LIMIT - 1, {"requiredCarrySize": target}
            carry = minimal_nonempty_carry_at_size(f.carry, target)
            write_data(root, "input/large-carry.json", carry)
            opened = prepare_project_opening(
                root,
                carry_path="input/large-carry.json",
                owner_bindings_path="input/owners.json",
                opening_out="tasks/strategy/large-inputs",
                source_root="work/large-source",
            )
            f.policy.update(
                openingRef=opened["openingRef"],
                sourceAuthoringRegistryRef=opened["sourceAuthoringRegistryRef"],
                financialSource=opened["financialSource"],
            )
            f.manifest["planFiles"] = sorted(
                set(f.manifest["planFiles"])
                | {
                    p.relative_to(root).as_posix()
                    for p in (root / "tasks/strategy/large-inputs").rglob("*")
                    if p.is_file()
                }
            )
            f.refreeze()
            f.start()
            context = f.context()
            current = context.source.read_current()
            state = json.loads(f.state_path.read_text())
            result: dict[str, Any]
            try:
                prepare_source_admission(
                    state_path=f.state_path,
                    manifest_path=f.manifest_path,
                    lock_path=f.manifest_path.with_name("plan.lock.json"),
                    task_id="WS-01",
                    operation_id="start-strategy",
                    expected_revision=state["stateRevision"],
                    source_revision=f.revision,
                    actor_id="worker",
                    expected_head_sha256=current["headSha256"],
                    out="work/large-source/windows/" + identifier + ".json",
                )
            except LifecycleError as error:
                result = {"actual": "REFUSED", "code": error.code, "message": str(error)}
            else:
                result = {"actual": "SUCCEEDED"}
            path = root / "work/large-source/HEAD.json"
            raw = path.read_bytes()
            head = validate_project_head(json.loads(raw))
            pending = path.with_suffix(".pending.json")
            result.update(
                carryCanonicalBytes=target,
                windowIdBytes=len(identifier),
                headBytes=len(raw),
                headCanonicalBytes=len(canonical_bytes(head)),
                committedSequence=head["sequence"],
                pendingExists=pending.exists(),
                pendingBytes=pending.stat().st_size if pending.exists() else None,
                headChanged=hashlib.sha256(raw).hexdigest() != current["headSha256"],
            )
            self.assertEqual(result["actual"], "SUCCEEDED", result)
            self.assertLessEqual(len(raw), DATA_LIMIT)
            self.assertEqual(result["committedSequence"], 1)
            self.assertFalse(pending.exists())
            self.assertEqual(context.source.read_current()["head"]["sequence"], 1)
            registry = current_source_snapshot(context)
            self.assertGreater(len(registry["projectionBytes"]), DATA_LIMIT)
            self.assertLessEqual(len(registry["projectionBytes"]), context.inputs["registryByteLimit"])
            # Wrapper capacity does not expand the enclosed authority data bound.
            path.write_bytes(raw + b" " * (DATA_LIMIT + 1 - len(raw)))
            with self.assertRaises(LifecycleError) as oversized:
                context.source.read_current()
            self.assertEqual(oversized.exception.code, "authority-input-too-large")

    def test_final_rendered_probe_cwd_is_rechecked_before_mocked_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = GenericFixture(Path(tmp).resolve(), probe_only=True)
            f.start()
            state = json.loads(f.state_path.read_text())
            selected = select(f.root, f.profile, state=state, task_id="WS-01", explicit_probe=True)
            sealed = stage_launch.seal_stage_launch(
                selected, state_path=f.state_path, task_id="WS-01", source_revision=f.revision
            )
            risk = stage_launch.derive_binding_risk(
                sealed,
                root=f.root,
                state_path=f.state_path,
                manifest_path=f.manifest_path,
                task_id="WS-01",
                operation_id="start-strategy",
                source_revision=f.revision,
            )
            renderer = launch_preflight.render_local_launch_argv
            runner = Mock(return_value={"status": "PASS", "processStarted": True, "exitCode": 0})

            def foreign_argv(*args: Any, **kwargs: Any) -> list[str]:
                return [*renderer(*args, **kwargs), "--cd=/outside"]

            with (
                patch.object(stage_launch, "capture_git_worktree_identity", return_value={"head": f.revision}),
                patch.object(launch_preflight, "render_local_launch_argv", side_effect=foreign_argv),
            ):
                result = launch_preflight.launch_from_local_profile(
                    profile_path=selected["inspected"]["launchPath"],
                    operation="managedTask",
                    adapter_id="codex",
                    project_root=f.root,
                    explicit_launch=True,
                    state_path=f.state_path,
                    manifest_path=f.manifest_path,
                    lock_path=f.manifest_path.with_name("plan.lock.json"),
                    task_id="WS-01",
                    operation_id="start-strategy",
                    source_revision=f.revision,
                    risk_profile=risk,
                    process_runner=runner,
                    stage_binding=sealed,
                )
            self.assertEqual(result["status"], "BLOCKED", result)
            self.assertIn("model-probe-containment-required", json.dumps(result))
            runner.assert_not_called()

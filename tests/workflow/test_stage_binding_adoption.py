"""Native strategy adoption proof; host transport observations are UNIT_ONLY."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agent_lifecycle.adapter_sessions import launch_preflight, stage_launch
from agent_lifecycle.adapter_sessions.unified_start import start_lifecycle
from agent_lifecycle.cli import main
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.freeze.package_integrity import build_plan_lock_v2
from agent_lifecycle.model_routing.availability import build_probe_observation
from agent_lifecycle.model_routing.stage_bindings import validate_neutral_stage_binding
from agent_lifecycle.workflow import start_task
from tests.adapter_sessions.test_stage_launch import select, write_fixture
from tests.workflow.test_task_transitions import _strategy_start_inputs, _write_strategy_start_bundle


def fixture(root: Path) -> tuple[Path, Path, dict, dict]:
    state_path, _, _ = _write_strategy_start_bundle(root)
    profile, entry, _ = write_fixture(root)
    inspected = stage_launch.inspect_binding(root, entry)
    observation = build_probe_observation(
        availability=inspected["availability"],
        auth_revision_digest=inspected["authRevisionDigest"],
        launch={"status": "PASS", "hostLaunchStarted": True, "receiptDigest": "f" * 64},
        model_response={
            "status": "PASS",
            "responseDigest": "d" * 64,
            "terminalDigest": "e" * 64,
            "backendIdentityAttested": False,
        },
        now=int(stage_launch.time.time()),
        lineage={"test": "UNIT_ONLY"},
    )
    (root / ".alk/host-launch" / ("availability-" + canonical_digest(entry) + ".json")).write_text(
        json.dumps(observation)
    )
    state = json.loads(state_path.read_text())
    manifest_path = root / "tasks/strategy/plan.manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.update(
        planFiles=["tasks/strategy/plan.manifest.json"],
        packageIntegrity={
            "required": True,
            "lockSchemaVersion": "agent-plan-lock.v2",
            "inventorySource": "planFiles",
            "undeclaredTopLevelFiles": "reject",
        },
        validation={"commands": ["python -m unittest"]},
        budgets={"maxInvocations": 3},
        contextLimits={"targetTokens": 1024},
        forbiddenWrites=[".git"],
        finalAuditGates=["[AC-1|EV-1] UNIT_ONLY independent receipt"],
    )
    manifest_path.write_text(json.dumps(manifest))
    (root / "tasks/strategy/plan.lock.json").write_text(json.dumps(build_plan_lock_v2(manifest, repository_root=root)))
    state["planDigest"] = canonical_digest(manifest)
    state["runDeadlineAt"] = "2099-01-01T00:00:00Z"
    state["budgets"]["maxToolCallsPerTask"] = 1000
    state_path.write_text(json.dumps(state))
    return state_path, root / "work/stage-strategy.json", profile, entry


def prepare(root: Path, state_path: Path, output: Path, profile: dict, **overrides: object) -> dict:
    arguments = {
        "adapter_id": "codex",
        "mode": "implement",
        "task_file": root / "tasks/strategy/plan.manifest.json",
        "state_path": state_path,
        "lock_path": root / "tasks/strategy/plan.lock.json",
        "task_id": "WS-01",
        "operation_id": "start-strategy",
        "expected_revision": json.loads(state_path.read_text())["stateRevision"],
        "source_revision": "source",
        "descriptor_path": root / "adapters/codex/adapter.descriptor.json",
        "project_profile": profile,
        "project_profile_path": root / ".alk/project-profile.json",
        "project_root": root,
        "strategy_out_path": output,
        "stage": "implementation",
    }
    return start_lifecycle(**{**arguments, **overrides})


def adopt(state_path: Path, output: Path, **overrides: object) -> dict:
    inputs = {**_strategy_start_inputs(), "hostProfilePath": ".alk/host-launch/host.json"}
    arguments = {
        "task_id": "WS-01",
        "operation_id": "start-strategy",
        "expected_revision": 1,
        "source_revision": "source",
        "strategy_path": output.relative_to(state_path.parent).as_posix(),
        "strategy_inputs": inputs,
        "reason": "UNIT_ONLY exact stage binding adoption",
    }
    return start_task(state_path, **{**arguments, **overrides})


class StageBindingAdoptionTests(unittest.TestCase):
    def test_actual_cli_preparation_normalized_profile_and_subsequent_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            state_path, output, _, _ = fixture(root)
            before = state_path.read_bytes()
            argv = [
                "start",
                "--mode",
                "implement",
                "--file",
                "tasks/strategy/plan.manifest.json",
                "--state",
                state_path.relative_to(root).as_posix(),
                "--lock",
                "tasks/strategy/plan.lock.json",
                "--task",
                "WS-01",
                "--operation-id",
                "start-strategy",
                "--expected-revision",
                "1",
                "--source-revision",
                "source",
                "--descriptor",
                "adapters/codex/adapter.descriptor.json",
                "--stage",
                "implementation",
                "--project-profile",
                ".alk/project-profile.json",
                "--strategy-out",
                output.relative_to(root).as_posix(),
            ]
            previous = Path.cwd()
            try:
                os.chdir(root)
                stream = io.StringIO()
                with contextlib.redirect_stdout(stream):
                    code = main(argv)
                self.assertEqual(code, 0, stream.getvalue())
                self.assertEqual(state_path.read_bytes(), before)
                adopt(state_path, output)
                native = json.loads(state_path.read_text())
                runner = Mock(return_value={"status": "PASS", "processStarted": True, "exitCode": 0})
                launch_argv = argv[:-2]
                launch_argv[launch_argv.index("--expected-revision") + 1] = str(native["stateRevision"])
                with (
                    patch("agent_lifecycle.adapter_sessions.launcher.run_process", runner),
                    patch.object(stage_launch, "capture_git_worktree_identity", return_value={"head": "source"}),
                    contextlib.redirect_stdout(io.StringIO()) as launched,
                ):
                    launch_code = main([*launch_argv, "--launch"])
                payload = json.loads(launched.getvalue())
                self.assertEqual(launch_code, 0, payload)
                self.assertTrue(payload["hostLaunchStarted"], payload)
                self.assertTrue(payload["modelCallsStarted"])
                runner.assert_called_once()
                dispositions = list((root / ".alk/host-launch").glob("dispatch-*-result.json"))
                self.assertEqual(json.loads(dispositions[0].read_text())["disposition"], "SUCCEEDED")
            finally:
                os.chdir(previous)

    def test_public_prepare_native_adopt_and_same_binding_ordinary_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, output, profile, _ = fixture(root)
            before = state_path.read_bytes()
            prepared = prepare(root, state_path, output, profile)
            self.assertEqual(prepared["status"], "READY")
            self.assertFalse(prepared["hostLaunchStarted"])
            self.assertEqual(state_path.read_bytes(), before)
            strategy = json.loads(output.read_text())
            neutral = validate_neutral_stage_binding(strategy["stageBinding"])
            self.assertNotIn("private-model", json.dumps(neutral))
            self.assertNotIn("high", json.dumps(neutral))
            adopt(state_path, output)
            state = json.loads(state_path.read_text())
            task = state["tasks"][0]
            self.assertEqual(task["executionStrategy"]["stageBinding"], neutral)
            self.assertEqual(task["attemptExecutionStrategy"]["stageBinding"], neutral)
            selected = select(root, profile, state=state, task_id="WS-01")
            self.assertEqual(selected["neutralBinding"], neutral)
            sealed = stage_launch.seal_stage_launch(
                selected, state_path=state_path, task_id="WS-01", source_revision="source"
            )
            risk = stage_launch.derive_binding_risk(
                sealed,
                root=root,
                state_path=state_path,
                manifest_path=root / "tasks/strategy/plan.manifest.json",
                task_id="WS-01",
                operation_id="start-strategy",
                source_revision="source",
            )
            runner = Mock(
                return_value={
                    "status": "PASS",
                    "processStarted": True,
                    "exitCode": 0,
                    "stdoutTail": '{"status":"UNIT_ONLY"}',
                }
            )
            with patch.object(stage_launch, "capture_git_worktree_identity", return_value={"head": "source"}):
                launched = launch_preflight.launch_from_local_profile(
                    profile_path=selected["inspected"]["launchPath"],
                    operation="managedTask",
                    adapter_id="codex",
                    project_root=root,
                    explicit_launch=True,
                    state_path=state_path,
                    manifest_path=root / "tasks/strategy/plan.manifest.json",
                    lock_path=root / "tasks/strategy/plan.lock.json",
                    task_id="WS-01",
                    operation_id="start-strategy",
                    source_revision="source",
                    risk_profile=risk,
                    process_runner=runner,
                    stage_binding=sealed,
                )
            self.assertEqual(launched["status"], "PASS", launched)
            runner.assert_called_once()
            self.assertEqual(runner.call_args.args[0].count("--model"), 1)
            self.assertEqual(runner.call_args.args[0].count("--config"), 1)

    def test_missing_adoption_prepares_without_dispatch_or_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, output, profile, _ = fixture(root)
            before = state_path.read_bytes()
            with patch("agent_lifecycle.adapter_sessions.unified_start.launch_from_local_profile") as runner:
                result = prepare(root, state_path, output, profile, launch=True)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["blockers"][0]["code"], "stage-binding-adoption-required")
            self.assertEqual(state_path.read_bytes(), before)
            runner.assert_not_called()

    def test_unknown_dispatch_is_persistent_across_independent_cli_invocations(self) -> None:
        for first_result in (
            RuntimeError("lost observation after possible start"),
            {"status": "FAIL", "processStarted": True, "timedOut": True},
        ):
            with self.subTest(result=type(first_result).__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state_path, output, profile, _ = fixture(root)
                prepare(root, state_path, output, profile)
                adopt(state_path, output)
                state = json.loads(state_path.read_text())
                before = state_path.read_bytes()
                selected = select(root, profile, state=state, task_id="WS-01")
                sealed = stage_launch.seal_stage_launch(
                    selected, state_path=state_path, task_id="WS-01", source_revision="source"
                )
                risk = stage_launch.derive_binding_risk(
                    sealed,
                    root=root,
                    state_path=state_path,
                    manifest_path=root / "tasks/strategy/plan.manifest.json",
                    task_id="WS-01",
                    operation_id="start-strategy",
                    source_revision="source",
                )
                arguments = {
                    "profile_path": selected["inspected"]["launchPath"],
                    "operation": "managedTask",
                    "adapter_id": "codex",
                    "project_root": root,
                    "explicit_launch": True,
                    "state_path": state_path,
                    "manifest_path": root / "tasks/strategy/plan.manifest.json",
                    "lock_path": root / "tasks/strategy/plan.lock.json",
                    "task_id": "WS-01",
                    "operation_id": "start-strategy",
                    "source_revision": "source",
                    "risk_profile": risk,
                }
                first = (
                    Mock(side_effect=first_result)
                    if isinstance(first_result, Exception)
                    else Mock(return_value=first_result)
                )
                with patch.object(stage_launch, "capture_git_worktree_identity", return_value={"head": "source"}):
                    if isinstance(first_result, Exception):
                        with self.assertRaises(LifecycleError):
                            launch_preflight.launch_from_local_profile(
                                **arguments, process_runner=first, stage_binding=sealed
                            )
                    else:
                        launch_preflight.launch_from_local_profile(
                            **arguments, process_runner=first, stage_binding=sealed
                        )
                    new_selection = select(root, profile, state=state, task_id="WS-01")
                    new_sealed = stage_launch.seal_stage_launch(
                        new_selection, state_path=state_path, task_id="WS-01", source_revision="source"
                    )
                    second = Mock(return_value={"status": "PASS", "processStarted": True})
                    result = launch_preflight.launch_from_local_profile(
                        **arguments, process_runner=second, stage_binding=new_sealed
                    )
                self.assertEqual(result["status"], "BLOCKED")
                self.assertEqual(result["blockers"][0]["code"], "stage-binding-dispatch-reconcile")
                first.assert_called_once()
                second.assert_not_called()
                self.assertEqual(state_path.read_bytes(), before)
                markers = list((root / ".alk/host-launch").glob("dispatch-*.json"))
                self.assertEqual(len(markers), 1)
                self.assertEqual(json.loads(markers[0].read_text())["disposition"], "PENDING")

    def test_proven_no_start_has_explicit_disposition_without_retry_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, output, profile, _ = fixture(root)
            prepare(root, state_path, output, profile)
            adopt(state_path, output)
            state = json.loads(state_path.read_text())
            selected = select(root, profile, state=state, task_id="WS-01")
            sealed = stage_launch.seal_stage_launch(
                selected, state_path=state_path, task_id="WS-01", source_revision="source"
            )
            context = type("LocalContext", (), {"root": root})()
            sealed["invocationDigest"] = "a" * 64
            marker = stage_launch._claim_dispatch_observation(context, sealed, state, state["tasks"][0])
            stage_launch._record_dispatch_disposition(context, marker, {"status": "FAIL", "processStarted": False})
            disposition = json.loads(marker.with_name(marker.stem + "-result.json").read_text())
            self.assertEqual(disposition["disposition"], "PROVEN_NO_START")
            self.assertFalse(disposition["retryAuthorized"])

    def test_native_refuses_tamper_drift_membership_source_and_revision_without_writes(self) -> None:
        mutations = (
            "projection",
            "non-member",
            "parameter",
            "launch",
            "qualification",
            "project",
            "source",
            "revision",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state_path, output, profile, entry = fixture(root)
                prepare(root, state_path, output, profile)
                overrides = {}
                if mutation in {"projection", "non-member"}:
                    strategy = json.loads(output.read_text())
                    key = "parameterDigest" if mutation == "projection" else "selectedBindingDigest"
                    strategy["stageBinding"][key] = "0" * 64
                    strategy["adoptionBinding"]["stageBindingDigest"] = canonical_digest(strategy["stageBinding"])
                    strategy["strategyDigest"] = canonical_digest(
                        {key: value for key, value in strategy.items() if key != "strategyDigest"}
                    )
                    output.write_text(json.dumps(strategy))
                elif mutation == "project":
                    profile["stages"]["implementation"]["executionBindingRefs"] = ["outside-list"]
                    (root / ".alk/project-profile.json").write_text(json.dumps(profile))
                elif mutation in {"source", "revision"}:
                    overrides["source_revision" if mutation == "source" else "expected_revision"] = (
                        "wrong-source" if mutation == "source" else 2
                    )
                else:
                    ref = (
                        entry["parameterSupport"]["evidence"]
                        if mutation == "parameter"
                        else entry["launchProfile"]
                        if mutation == "launch"
                        else entry["qualificationEvidence"]
                    )
                    (root / ref["path"]).write_text("{}")
                before = state_path.read_bytes()
                event_before = (root / "events.jsonl").read_bytes() if (root / "events.jsonl").exists() else None
                with self.assertRaises(LifecycleError):
                    adopt(state_path, output, **overrides)
                self.assertEqual(state_path.read_bytes(), before)
                self.assertEqual(
                    (root / "events.jsonl").read_bytes() if (root / "events.jsonl").exists() else None, event_before
                )

    def test_native_legacy_strategy_omits_stage_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, output, strategy = _write_strategy_start_bundle(root)
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-strategy",
                expected_revision=1,
                source_revision="source",
                strategy_path=output,
                strategy_inputs=_strategy_start_inputs(),
                reason="legacy",
            )
            self.assertNotIn("stageBinding", strategy)
            task = json.loads(state_path.read_text())["tasks"][0]
            self.assertNotIn("stageBinding", task["attemptExecutionStrategy"])

    def test_post_adoption_change_and_late_fallback_refuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, output, profile, entry = fixture(root)
            prepare(root, state_path, output, profile)
            adopt(state_path, output)
            state = json.loads(state_path.read_text())
            raw = (root / ".alk/host-launch/registry.json").read_bytes()
            registry = json.loads(raw)
            reserve = copy.deepcopy(entry)
            reserve["hostParameters"]["reasoningEffort"] = "none"
            registry["bindings"]["reserve"] = reserve
            (root / ".alk/host-launch/registry.json").write_text(json.dumps(registry))
            profile["stages"]["implementation"]["executionBindingRefs"].append("reserve")
            (root / ".alk/project-profile.json").write_text(json.dumps(profile))
            before = state_path.read_bytes()
            with self.assertRaises(LifecycleError):
                select(root, profile, state=state, task_id="WS-01", binding_id="reserve")
            with self.assertRaises(LifecycleError):
                select(root, profile, state=state, task_id="WS-01")
            self.assertEqual(state_path.read_bytes(), before)

    def test_pre_adoption_ordered_fallback_stops_at_first_usable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, profile, entry = fixture(root)
            registry_path = root / ".alk/host-launch/registry.json"
            registry = json.loads(registry_path.read_text())
            launch = json.loads((root / entry["launchProfile"]["path"]).read_text())
            launch["executable"] = "/definitely-not-installed/codex"
            raw = json.dumps(launch).encode()
            (root / ".alk/host-launch/unavailable.json").write_bytes(raw)
            missing = copy.deepcopy(entry)
            missing["launchProfile"] = {
                "path": ".alk/host-launch/unavailable.json",
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            registry["bindings"].update(missing=missing, third=copy.deepcopy(entry))
            registry_path.write_text(json.dumps(registry))
            profile["stages"]["implementation"]["executionBindingRefs"] = ["missing", "primary", "third"]
            (root / ".alk/project-profile.json").write_text(json.dumps(profile))
            with patch.object(stage_launch, "inspect_binding", wraps=stage_launch.inspect_binding) as inspect:
                selected = select(root, profile)
            self.assertEqual(selected["bindingId"], "primary")
            self.assertEqual(inspect.call_count, 2)
            self.assertEqual(len(selected["alternatives"]), 1)

    def test_adopted_managed_projection_refuses_identity_drift_without_new_attempt(self) -> None:
        """Current adoption is consumed read-only, including native v3 metadata."""
        from agent_lifecycle.adapter_sessions.start_routing import resolve_managed_execution_strategy
        from tests.accounting.test_generic_source_usage import GenericFixture

        with tempfile.TemporaryDirectory() as directory:
            f = GenericFixture(Path(directory).resolve())
            f.start()
            state = json.loads(f.state_path.read_text())
            strategy_path = f.root / state["tasks"][0]["attemptExecutionStrategy"]["path"]
            strategy = json.loads(strategy_path.read_text())
            arguments = dict(
                adapter_id="codex",
                state_path=f.state_path,
                manifest_path=f.manifest_path,
                lock_path=f.manifest_path.with_name("plan.lock.json"),
                task_id="WS-01",
                operation_id="start-strategy",
                expected_revision=state["stateRevision"],
                source_revision=state["sourceRevision"],
                requested_risk=strategy["adoptionBinding"]["policyInputs"]["requestedRisk"],
                descriptor_path=f.root / "adapters/codex/adapter.descriptor.json",
                host_model_profile_path=f.root / ".alk/host-launch/host.json",
                project_profile_path=f.root / ".alk/project-profile.json",
            )
            before_state = f.state_path.read_bytes()
            before_events = (f.root / "events.jsonl").read_bytes()
            with patch(
                "agent_lifecycle.adapter_sessions.start_routing.next_available_attempt",
                side_effect=AssertionError("active launch must not allocate another attempt"),
            ):
                projected = resolve_managed_execution_strategy(**arguments)
                self.assertEqual(projected["strategy"]["strategyDigest"], strategy["strategyDigest"])
                self.assertEqual(projected["strategy"]["lineage"]["targetAttempt"], 1)
                for change in (
                    {"operation_id": "foreign"},
                    {"source_revision": "foreign"},
                    {"expected_revision": 99},
                    {"stage_binding": {}},
                ):
                    with self.subTest(change=change), self.assertRaises(LifecycleError):
                        resolve_managed_execution_strategy(**{**arguments, **change})
                wrong_annotation = copy.deepcopy(state)
                wrong_annotation["tasks"][0]["attemptModelRoute"]["attempt"] = 2
                f.state_path.write_text(json.dumps(wrong_annotation))
                with self.assertRaises(LifecycleError):
                    resolve_managed_execution_strategy(**arguments)
                f.state_path.write_bytes(before_state)
                original_strategy = strategy_path.read_bytes()
                altered = copy.deepcopy(strategy)
                altered["stageBinding"]["parameterDigest"] = "0" * 64
                strategy_path.write_text(json.dumps(altered))
                with self.assertRaises(LifecycleError):
                    resolve_managed_execution_strategy(**arguments)
                strategy_path.write_bytes(original_strategy)
            self.assertEqual(f.state_path.read_bytes(), before_state)
            self.assertEqual((f.root / "events.jsonl").read_bytes(), before_events)

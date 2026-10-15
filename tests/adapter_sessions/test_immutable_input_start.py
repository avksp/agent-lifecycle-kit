"""Non-authorizing context cannot be replayed for changed actual inputs."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent_lifecycle.adapter_sessions import launch_preflight
from agent_lifecycle.adapter_sessions.immutable_input import current_managed_invocation, validate_current_invocation
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from tests.contracts import test_immutable_input_schemas as fixture
from tests.workflow import helpers
from tests.workflow import test_plan_adoption as adoption
from tests.workflow import test_risk_execution_gate as risk

ROOT = Path(__file__).resolve().parents[2]


def managed_fixture(root):
    state_path = helpers._write_state(root, phase="BLOCKED", blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"})
    manifest_path = adoption._write_authority_bundle(root)
    adoption._adopt_authority_bundle(state_path, manifest_path)
    helpers.start_execution(state_path, operation_id="run", expected_revision=2, source_revision="source-2", reason="test")
    state = json.loads(state_path.read_text())
    profile = risk._risk_profile(operation_id="ordinary")
    profile.update(runId=state["runId"], packageId=state["packageId"], planRevision=state["planRevision"],
                   planDigest=state["planDigest"], sourceRevision=state["sourceRevision"])
    fixture.sealed(profile, "profileDigest")
    path = root / "work/risk.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(profile) + b"\n")
    helpers.start_task(state_path, task_id="WS-01", operation_id="ordinary", expected_revision=3,
                       source_revision="source-2", reason="test", risk_profile_path="work/risk.json")
    context = SimpleNamespace(root=root, runner=Mock(return_value={"status": "FAIL", "processStarted": False, "blockers": []}),
                              profile_adapter="codex", profile_digest="b" * 64, profile={},
                              env={}, env_receipt={}, timeout_seconds=5)
    args = dict(session_id="session", state_path=state_path, manifest_path=manifest_path,
                lock_path=root / json.loads(manifest_path.read_text())["package"]["planArtifactRoot"] / "plan.lock.json", task_id="WS-01", operation_id="ordinary",
                source_revision="source-2", risk_profile=profile, qualification_receipt=None, host_identity={})
    current = current_managed_invocation(project_root=root, profile=context.profile, profile_digest=context.profile_digest,
        adapter_id=context.profile_adapter, request=None, **{k:v for k,v in args.items() if k not in {"qualification_receipt", "host_identity"}})
    return context, args, current


class A5ManagedSinkTests(unittest.TestCase):
    def test_direct_missing_context_and_strong_refuse_before_renderer_and_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            launch, args, _current = managed_fixture(Path(tmp))
            for request in (None, {"schemaVersion": "agent-a5-invocation-request.v1", "requestedProtection": "STRONG_A5"}):
                with self.subTest(request=request), patch.object(launch_preflight, "render_local_launch_argv") as render:
                    before = adoption._tree_bytes(launch.root)
                    result = launch_preflight._run_managed_process(launch, **args, immutable_input_request=request)
                    self.assertEqual(result["status"], "BLOCKED")
                    self.assertFalse(result["hostLaunchStarted"])
                    self.assertEqual(result["argv"], [])
                    self.assertEqual(adoption._tree_bytes(launch.root), before)
                    render.assert_not_called()
                    launch.runner.assert_not_called()

    def test_current_ordinary_binding_preserves_physical_no_start_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            launch, args, current = managed_fixture(Path(tmp))
            with patch.object(launch_preflight, "render_local_launch_argv", return_value=["python"]):
                result = launch_preflight._run_managed_process(launch, **args, immutable_input_context=current)
            self.assertEqual(result["status"], "FAIL")
            self.assertFalse(result["hostLaunchStarted"])
            launch.runner.assert_called_once()

    def test_actual_state_change_invalidates_old_context_before_argv(self):
        with tempfile.TemporaryDirectory() as tmp:
            launch, args, current = managed_fixture(Path(tmp))
            state = json.loads(args["state_path"].read_text())
            state["stateRevision"] += 1
            args["state_path"].write_text(json.dumps(state))
            with patch.object(launch_preflight, "render_local_launch_argv") as render:
                result = launch_preflight._run_managed_process(launch, **args, immutable_input_context=current)
                self.assertEqual(result["blockers"][0]["code"], "a5-context-invalid")
                render.assert_not_called()
                launch.runner.assert_not_called()

    def test_frozen_strong_cannot_be_lowered_by_omitted_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            launch, args, current = managed_fixture(Path(tmp))
            manifest = json.loads(args["manifest_path"].read_text())
            state = json.loads(args["state_path"].read_text())
            policy = fixture.policy()
            registry = json.loads((ROOT / "profiles/immutable-input-adapter-capabilities.v1.json").read_text())
            record = next(row for row in registry["records"] if row["adapterId"] == "codex")
            policy.update({k:record[k] for k in ("adapterId", "expectationId", "targetVersion", "boundaryRecordDigest")})
            policy["frozenTaskRequirement"] = "STRONG_A5"
            fixture.sealed(policy, "policyDigest")
            plan = {"schemaVersion": "agent-a5-plan-policy.v1", "mode": "A5_LIMITED", "defaultRequirement": "STRONG_A5", "contractDigest": "a" * 64}
            manifest["immutableInput"] = plan
            manifest["workstreams"][0]["immutableInput"] = policy
            state["immutableInput"] = plan
            state["tasks"][0]["immutableInput"] = policy
            state["planDigest"] = canonical_digest(manifest)
            args["manifest_path"].write_text(json.dumps(manifest))
            args["state_path"].write_text(json.dumps(state))
            lock = json.loads(args["lock_path"].read_text())
            lock["manifestHash"] = state["planDigest"]
            args["lock_path"].write_text(json.dumps(lock))
            target = launch.root / "profiles/immutable-input-adapter-capabilities.v1.json"
            target.parent.mkdir()
            target.write_text(json.dumps(registry))
            with patch.object(launch_preflight, "render_local_launch_argv") as render:
                result = launch_preflight._run_managed_process(launch, **args, immutable_input_context=current)
                self.assertEqual(result["blockers"][0]["code"], "a5-strong-unproven")
                render.assert_not_called()
                launch.runner.assert_not_called()

    def test_exact_sink_refuses_unbound_call_before_claim_cleanup_and_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            launch, args, _current = managed_fixture(Path(tmp))
            prepared = {"operationId": "ordinary", "verifyBeforeStart": Mock()}
            with patch.object(launch_preflight, "claim_attempt_start") as claim, patch.object(launch_preflight, "cleanup_prestart_raw") as cleanup:
                result = launch_preflight._run_exact_managed_process(launch, prepared=prepared, audit={},
                    session_id="session", risk_profile=args["risk_profile"], host_identity={}, operation_id="ordinary")
                self.assertEqual(result["blockers"][0]["code"], "a5-context-invalid")
                prepared["verifyBeforeStart"].assert_not_called()
                claim.assert_not_called()
                cleanup.assert_not_called()
                launch.runner.assert_not_called()


def context():
    request = {"schemaVersion": "agent-a5-invocation-request.v1", "requestedProtection": "NONE"}
    return fixture.sealed({
        "schemaVersion": "agent-a5-invocation-context.v1", "invocationId": "invocation",
        "operation": "PLANNING_TASK", "origin": "EXPLICIT_PLANNING_CALL",
        "workflowSubject": None, "frozenAuthorityRefs": [], "adapterId": "codex",
        "sessionId": "session", "requestedProtection": "NONE", "expectedProtection": "NONE",
        "policyDigest": None, "boundaryRecordDigest": None,
        "normalizedRequestDigest": canonical_digest(request), "taskInputDigest": "a" * 64,
        "profileDigest": "b" * 64, "strongProtectionGranted": False,
    }, "contextDigest"), request


class A5CurrentInvocationTests(unittest.TestCase):
    def test_current_ordinary_context_retains_no_protection_claim(self):
        value, request = context()
        checked = validate_current_invocation(value, request, current_context=copy.deepcopy(value))
        self.assertIs(checked["strongProtectionGranted"], False)

    def test_resealed_context_cannot_authorize_changed_actual_input(self):
        value, request = context()
        current = copy.deepcopy(value)
        current["taskInputDigest"] = "c" * 64
        fixture.sealed(current, "contextDigest")
        with self.assertRaises(LifecycleError) as raised:
            validate_current_invocation(value, request, current_context=current)
        self.assertEqual(raised.exception.code, "a5-context-invalid")

    def test_task_bearing_version_relabel_is_refused(self):
        value, request = context()
        value.update(operation="VERSION_PREFLIGHT", origin="VERSION_ONLY_PREFLIGHT")
        fixture.sealed(value, "contextDigest")
        with self.assertRaises(LifecycleError):
            validate_current_invocation(value, request, current_context=value)

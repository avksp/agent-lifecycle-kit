"""A5 refusal at real planning and qualification sinks, before callbacks/stdin."""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agent_lifecycle.adapter_sessions import launch_execution, launch_preflight, planning_launch, unified_start
from agent_lifecycle.adapter_sessions.immutable_input import (
    normalize_invocation_request,
    planning_invocation_context,
    require_no_strong_protection,
)
from agent_lifecycle.adapter_sessions.qualification import load_shipped_launch_profile
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from tests.adapter_sessions import test_unified_start_planning_launch as start_fixture

ROOT = Path(__file__).resolve().parents[2]
STRONG = {"schemaVersion": "agent-a5-invocation-request.v1", "requestedProtection": "STRONG_A5"}


def planning_arguments():
    return dict(adapter_id="codex", session_id="session", requested_mode="plan", task_text="private input",
                input_source="text", argv=[sys.executable, "-c", "raise SystemExit(99)"], env=dict(os.environ),
                timeout_seconds=5, advisory=None, process_cwd=ROOT, profile_digest="b" * 64)


class A5PlanningSinkTests(unittest.TestCase):
    def test_all_twelve_strong_routes_refuse_before_envelope_and_process(self):
        routes = json.loads((ROOT / "profiles/immutable-input-adapter-capabilities.v1.json").read_text())["records"]
        for row in routes:
            args = planning_arguments()
            args["adapter_id"] = row["adapterId"]
            with self.subTest(adapter=row["adapterId"]), patch.object(planning_launch, "build_planning_envelope") as envelope, patch.object(planning_launch, "run_process") as process:
                result = planning_launch.run_planning_launch(**args, explicit_launch=True, immutable_input_request=STRONG)
                self.assertEqual(result["blockers"][0]["code"], "a5-strong-unproven")
                self.assertEqual(result["processCalls"], 0)
                self.assertIsNone(result["result"])
                self.assertIsNone(result["usageEvidence"]["inputTokens"])
                envelope.assert_not_called()
                process.assert_not_called()

    def test_unbound_direct_sink_refuses_before_envelope(self):
        with patch.object(planning_launch, "build_planning_envelope") as envelope, patch.object(planning_launch, "run_process") as process:
            result = planning_launch.run_planning_launch(**planning_arguments())
            self.assertEqual(result["blockers"][0]["code"], "a5-context-invalid")
            envelope.assert_not_called()
            process.assert_not_called()

    def test_resealed_stale_actual_input_and_transport_refuse(self):
        args = planning_arguments()
        context = planning_invocation_context(**args, request=None)
        for field, replacement in (("task_text", "different"), ("requested_mode", "review"),
                                   ("argv", ["different"]), ("profile_digest", "c" * 64),
                                   ("process_cwd", ROOT.parent), ("env", {"PATH": "different"})):
            changed = {**args, field: replacement}
            with self.subTest(field=field), patch.object(planning_launch, "run_process") as process:
                result = planning_launch.run_planning_launch(**changed, immutable_input_context=context)
                self.assertEqual(result["blockers"][0]["code"], "a5-context-invalid")
                process.assert_not_called()

    def test_explicit_ordinary_path_delivers_exact_private_stdin_once(self):
        args = planning_arguments()
        payload = {"schemaVersion": "agent-planning-result.v1", "status": "REVIEW_REQUIRED",
                   "summary": "ordinary plan", "requirements": ["R"], "workstreams": ["WS"],
                   "evidenceRoutes": ["EV"], "implementationAuthorized": False, "productionPromotionClaimed": False}
        script = "import json,sys; v=json.load(sys.stdin); assert v['task']['untrustedText']=='private input'; print(" + repr(json.dumps(payload)) + ")"
        args["argv"] = [sys.executable, "-c", script]
        result = planning_launch.run_planning_launch(**args, explicit_launch=True)
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertEqual(result["processCalls"], 1)
        self.assertFalse(result["implementationAuthorized"])
        self.assertNotIn("private input", json.dumps(result))

    def test_local_planning_refuses_before_identity_qualification_and_capture(self):
        from types import SimpleNamespace
        context = SimpleNamespace(profile_adapter="codex", profile_digest="b" * 64, profile={},
                                  root=ROOT, env={}, timeout_seconds=5)
        with patch.object(launch_preflight, "_identity") as identity, patch.object(launch_preflight, "require_planning_qualification_receipt") as qualification, patch.object(launch_preflight, "capture_git_worktree_identity") as capture:
            result = launch_preflight._planning_task(context, session_id="session", explicit_launch=True,
                requested_mode="plan", task_text="private input", input_source="text", advisory=None,
                immutable_input_request=STRONG)
            self.assertEqual(result["blockers"][0]["code"], "a5-strong-unproven")
            identity.assert_not_called()
            qualification.assert_not_called()
            capture.assert_not_called()


class A5QualificationSinkTests(unittest.TestCase):
    def test_strong_and_stale_budget_refuse_before_both_callbacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            profile_path = root / ".alk/host-launch/gemini-cli.json"
            profile_path.parent.mkdir(parents=True)
            profile_path.write_text(json.dumps(load_shipped_launch_profile("gemini-cli", repository_root=ROOT)))
            capture, runner = Mock(return_value={"identityDigest": "same"}), Mock()
            args = dict(profile_path=profile_path, project_root=root, approval_digest="ordinary-diagnostic",
                        max_wall_seconds=10, model_token_budget=100, capture_identity=capture, planning_runner=runner,
                        process_env={"HOME": tmp, "PATH": os.environ.get("PATH", "")})
            result = launch_execution.run_planning_qualification_candidate(**args, immutable_input_request=STRONG)
            self.assertEqual(result["blockers"][0]["code"], "a5-strong-unproven")
            capture.assert_not_called()
            runner.assert_not_called()
            self.assertIsNone(result["usageEvidence"]["inputTokens"])
            receipt = {"status": "REVIEW_REQUIRED", "blockers": [], "hostLaunchStarted": True,
                       "modelCallsStarted": True, "receiptDigest": "x", "usageEvidence": {
                           "confidence": "ATTESTED", "inputTokens": 1, "outputTokens": 1}}
            runner.return_value = receipt
            ordinary = launch_execution.run_planning_qualification_candidate(**args)
            self.assertEqual(ordinary["status"], "PASS")
            bound = runner.call_args.kwargs["immutable_input_context"]
            self.assertEqual(bound["operation"], "PLANNING_QUALIFICATION")
            self.assertFalse(bound["strongProtectionGranted"])
            capture.reset_mock()
            runner.reset_mock()
            changed = {**args, "model_token_budget": 101}
            rejected = launch_execution.run_planning_qualification_candidate(**changed, immutable_input_context=bound)
            self.assertEqual(rejected["blockers"][0]["code"], "a5-context-invalid")
            capture.assert_not_called()
            runner.assert_not_called()


class A5PublicStartTests(unittest.TestCase):
    def test_twelve_strong_requests_refuse_direct_project_and_resume_before_intake(self):
        routes = json.loads((ROOT / "profiles/immutable-input-adapter-capabilities.v1.json").read_text())["records"]
        for row in routes:
            for extra in ({"task_text": "private", "launch": True},
                          {"task_text": "private", "project_profile": {"unresolved": True}},
                          {"resume_session_id": "session"}):
                with self.subTest(adapter=row["adapterId"], path=extra), patch.object(unified_start, "start_adapter_task") as intake, patch.object(unified_start, "create_planning_session") as session, patch.object(unified_start, "launch_from_local_profile") as launch, patch.object(unified_start, "build_effective_project_profile") as project:
                    receipt = unified_start.start_lifecycle(adapter_id=row["adapterId"], immutable_input_request=STRONG, **extra)
                    self.assertEqual(receipt["blockers"][0]["code"], "a5-strong-unproven")
                    self.assertFalse(receipt["hostLaunchStarted"])
                    intake.assert_not_called()
                    session.assert_not_called()
                    launch.assert_not_called()
                    project.assert_not_called()

    def test_ordinary_request_reaches_finish_in_direct_and_project_branches(self):
        request = {"schemaVersion": "agent-a5-invocation-request.v1", "requestedProtection": "NONE"}
        for profile in (None, {"fixture": True}):
            with self.subTest(project=profile is not None), patch.object(unified_start, "start_adapter_task", return_value=start_fixture._intake_receipt("inspect")), patch.object(unified_start, "build_effective_project_profile", return_value={"defaultAdapter": "codex", "defaultMode": "plan", "defaultRisk": "auto"}), patch.object(unified_start, "_build_guided_action_receipt", side_effect=lambda base, **_kwargs: base), patch.object(unified_start, "_finish_start", wraps=unified_start._finish_start) as finish:
                result = unified_start.start_lifecycle(adapter_id="codex", mode="plan", task_text="inspect",
                                                       project_profile=profile, immutable_input_request=request)
                self.assertEqual(result["status"], "REVIEW_REQUIRED")
                self.assertEqual(finish.call_args.kwargs["immutable_input_request"], request)
                self.assertFalse(result["hostLaunchStarted"])

    def test_planning_context_is_built_before_running_transition_from_real_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            profile_path = root / ".alk/host-launch/gemini-cli.json"
            profile_path.parent.mkdir(parents=True)
            profile_path.write_text(json.dumps(load_shipped_launch_profile("gemini-cli", repository_root=ROOT)))
            old_cwd = Path.cwd()
            try:
                os.chdir(root)
                events = []
                original_transition = unified_start.transition_planning_session
                def transition(**kwargs):
                    events.append(kwargs["new_state"])
                    return original_transition(**kwargs)
                def launch(**kwargs):
                    self.assertEqual(events, ["PLANNING_RUNNING"])
                    context = kwargs["immutable_input_context"]
                    self.assertEqual(context["operation"], "PLANNING_TASK")
                    self.assertEqual(context["adapterId"], "gemini-cli")
                    self.assertEqual(context["normalizedRequestDigest"], canonical_digest(kwargs["immutable_input_request"]))
                    self.assertFalse(context["strongProtectionGranted"])
                    return start_fixture._planning_receipt(result_summary="ordinary plan")
                with patch.object(unified_start, "start_adapter_task", return_value=start_fixture._intake_receipt("inspect")), patch.object(unified_start, "transition_planning_session", side_effect=transition), patch.object(unified_start, "launch_from_local_profile", side_effect=launch) as runner:
                    result = unified_start.start_lifecycle(adapter_id="gemini-cli", mode="plan", task_text="inspect",
                        launch=True, session_root=root / "sessions", host_launch_profile_path=profile_path)
                    self.assertEqual(result["status"], "REVIEW_REQUIRED")
                    runner.assert_called_once()
                    self.assertEqual(events, ["PLANNING_RUNNING", "REVIEW_REQUIRED"])
            finally:
                os.chdir(old_cwd)



class A5InvocationRequestTests(unittest.TestCase):
    def test_strong_is_not_retried_as_none(self):
        request = {"schemaVersion": "agent-a5-invocation-request.v1", "requestedProtection": "STRONG_A5"}
        before = copy.deepcopy(request)
        with self.assertRaises(LifecycleError) as raised:
            require_no_strong_protection(request, expected_protection="NONE")
        self.assertEqual(raised.exception.code, "a5-strong-unproven")
        self.assertEqual(request, before)

    def test_omission_cannot_lower_expected_strong(self):
        with self.assertRaises(LifecycleError) as raised:
            require_no_strong_protection(None, expected_protection="STRONG_A5")
        self.assertEqual(raised.exception.code, "a5-strong-unproven")

    def test_malformed_requests_and_unresolved_expectations_are_contract_errors(self):
        for value in ([], {}, True, {"schemaVersion": "agent-a5-invocation-request.v1", "requestedProtection": "NONE", "allow": True}):
            with self.subTest(value=value), self.assertRaises(LifecycleError):
                normalize_invocation_request(value)
        for expected in (None, [], {}, "unknown"):
            with self.subTest(expected=expected), self.assertRaises(LifecycleError):
                require_no_strong_protection(None, expected_protection=expected)

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent_lifecycle.adapter_sessions import launch_preflight
from agent_lifecycle.adapter_sessions.immutable_input import current_managed_invocation
from agent_lifecycle.adapter_sessions.local_launch_profile import (
    build_executable_identity,
    load_local_launch_profile,
    render_local_launch_argv,
    validate_local_launch_profile,
)
from agent_lifecycle.adapter_sessions.process import run_process
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.schemas import get_schema
from tests.adapter_sessions import test_immutable_input_start as a5_fixture

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/adapter_sessions/fixtures/local_launch_profiles"


class LocalLaunchProfileTests(unittest.TestCase):
    def test_managed_receipt_uses_observed_no_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = _launch_context(Path(tmp), Mock(return_value={
                'status': 'FAIL', 'processStarted': False, 'blockers': []}))
            with patch.object(launch_preflight, 'render_local_launch_argv', return_value=['python']):
                receipt = _generic_launch(context)
        self.assertFalse(receipt['hostLaunchStarted'])
        self.assertEqual(receipt['status'], 'FAIL')

    def test_managed_receipt_refuses_unobserved_or_contradictory_start(self) -> None:
        results = [
            {'status': 'FAIL'}, {'status': 'FAIL', 'processStarted': 0},
            {'status': 'PASS', 'processStarted': False},
            {'status': 'FAIL', 'processStarted': False, 'startedFailure': True},
            {'status': 'FAIL', 'processStarted': False, 'processReceipt': {'pid': 1}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for result in results:
                with self.subTest(result=result), patch.object(
                        launch_preflight, 'render_local_launch_argv', return_value=['python']):
                    with self.assertRaises(LifecycleError) as raised:
                        _generic_launch(_launch_context(Path(tmp), Mock(return_value=result)))
                    self.assertEqual(raised.exception.code, 'local-launch-start-uncertain')
                    self.assertEqual(raised.exception.details['costStatus'], 'UNAVAILABLE')

    def test_managed_runner_exception_retains_start_uncertainty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
                launch_preflight, 'render_local_launch_argv', return_value=['python']):
            with self.assertRaises(LifecycleError) as raised:
                _generic_launch(_launch_context(Path(tmp), Mock(side_effect=OSError('possible post-spawn failure'))))
        self.assertEqual(raised.exception.code, 'local-launch-start-uncertain')

    def test_exact_post_start_exception_preserves_raw_and_uncertain_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / 'raw-input.json'
            raw.write_bytes(b'private input')
            prepared = _prepared_launch(root)
            context = _launch_context(root, Mock(side_effect=RuntimeError('post-start observation failed')))
            with patch.object(launch_preflight, 'verify_fresh_task_gate'), patch.object(
                    launch_preflight, 'claim_attempt_start'), patch.object(
                    launch_preflight, 'record_uncertain_attempt') as uncertain, patch.object(
                    launch_preflight, 'cleanup_prestart_raw') as cleanup:
                with self.assertRaises(LifecycleError) as raised:
                    _exact_launch(context, prepared, time.monotonic_ns() + 5_000_000_000)
            self.assertEqual(raised.exception.code, 'codex-exact-start-uncertain')
            uncertain.assert_called_once()
            cleanup.assert_not_called()
            self.assertEqual(raw.read_bytes(), b'private input')

    def test_original_deadline_uses_earlier_run_or_attempt_without_rounding_up(self) -> None:
        observed = datetime(2026, 10, 5, tzinfo=timezone.utc)
        for run_left, attempt_left in [(1.25, 9.0), (9.0, 1.25)]:
            state = {'runDeadlineAt': (observed + timedelta(seconds=run_left)).isoformat()}
            task = {'attemptDeadlineAt': (observed + timedelta(seconds=attempt_left)).isoformat()}
            with self.subTest(run=run_left), patch.object(launch_preflight.time, 'monotonic_ns', return_value=100), patch.object(
                    launch_preflight, 'datetime') as wall:
                wall.now.return_value = observed
                wall.fromisoformat.side_effect = datetime.fromisoformat
                self.assertEqual(launch_preflight._original_attempt_deadline(state, task), 1_250_000_100)

    def test_original_deadline_refuses_missing_stale_or_non_utc_authority(self) -> None:
        future = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
        for deadline in [None, 'invalid', '2020-01-01T00:00:00Z', '2099-01-01T00:00:00', '2099-01-01T00:00:00+03:00']:
            with self.subTest(deadline=deadline), self.assertRaises(LifecycleError) as raised:
                launch_preflight._original_attempt_deadline(
                    {'runDeadlineAt': deadline}, {'attemptDeadlineAt': future})
            self.assertEqual(raised.exception.code, 'codex-exact-deadline-unavailable')

    def test_late_exact_child_cannot_extend_original_attempt_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = []
            def observed_runner(*args, **kwargs):
                self.assertEqual(kwargs['absolute_deadline_monotonic_ns'], deadline)
                result = run_process(*args, cleanup_grace_seconds=0.05, **kwargs)
                results.append(result)
                return result
            context = _launch_context(root, observed_runner)
            prepared = _prepared_launch(root)
            prepared['argv'] = [sys.executable, '-c', 'import sys,time;sys.stdin.read();time.sleep(3)']
            bound = _bound_launch_context(context, root)
            end = (datetime.now(timezone.utc) + timedelta(seconds=0.3)).isoformat()
            deadline = launch_preflight._original_attempt_deadline(
                {'runDeadlineAt': end}, {'attemptDeadlineAt': end})
            started = time.monotonic()
            with patch.object(launch_preflight, 'verify_fresh_task_gate'), patch.object(
                    launch_preflight, 'claim_attempt_start'), patch.object(
                    launch_preflight, 'publish_attempt_result', return_value={'status': 'FAIL'}):
                receipt = _exact_launch(context, prepared, deadline, bound=bound)
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertTrue(receipt['hostLaunchStarted'])
            self.assertTrue(receipt['timedOut'])
            self.assertEqual(results[0]['deadlineMonotonicNs'], deadline)

    def test_expired_exact_deadline_refuses_before_claim_and_spawn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = Mock()
            with patch.object(launch_preflight, 'verify_fresh_task_gate'), patch.object(
                    launch_preflight, 'claim_attempt_start') as claim, patch.object(
                    launch_preflight, 'cleanup_prestart_raw'), patch.object(
                    launch_preflight, 'record_proven_no_start'):
                receipt = _exact_launch(_launch_context(root, runner), _prepared_launch(root), time.monotonic_ns() - 1)
            self.assertFalse(receipt['hostLaunchStarted'])
            runner.assert_not_called()
            claim.assert_not_called()

    def test_exact_observed_popen_no_start_remains_no_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepared = _prepared_launch(root)
            prepared['argv'] = [str(root / 'absent-executable')]
            with patch.object(launch_preflight, 'verify_fresh_task_gate'), patch.object(
                    launch_preflight, 'claim_attempt_start'), patch.object(
                    launch_preflight, 'cleanup_prestart_raw') as cleanup, patch.object(
                    launch_preflight, 'record_proven_no_start') as no_start, patch.object(
                    launch_preflight, 'record_uncertain_attempt') as uncertain:
                receipt = _exact_launch(_launch_context(root, run_process), prepared, time.monotonic_ns() + 5_000_000_000)
            self.assertFalse(receipt['hostLaunchStarted'])
            self.assertFalse(receipt['modelCallsStarted'])
            self.assertEqual(receipt['exactPrompt']['terminalStatus'], 'NOT_STARTED')
            cleanup.assert_called_once()
            no_start.assert_called_once()
            uncertain.assert_not_called()

    def test_exact_preflight_cleanup_cannot_convert_existing_dispatch_to_no_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'attempt-result-dispatched.json').write_bytes(b'possible child start')
            prepared = _prepared_launch(root)
            prepared['verifyBeforeStart'] = Mock(side_effect=LifecycleError('stale-input', 'changed'))
            runner = Mock()
            with patch.object(launch_preflight, 'cleanup_prestart_raw') as cleanup:
                with self.assertRaises(LifecycleError) as raised:
                    _exact_launch(_launch_context(root, runner), prepared, time.monotonic_ns() + 5_000_000_000)
            self.assertEqual(raised.exception.code, 'codex-exact-start-uncertain')
            runner.assert_not_called()
            cleanup.assert_not_called()

    def test_blocked_preflight_preserves_uncertain_cleanup_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
                launch_preflight, 'cleanup_no_start', side_effect=LifecycleError('codex-exact-start-uncertain', 'possible start')):
            with self.assertRaises(LifecycleError) as raised:
                launch_preflight._no_start_cleanup_blockers(Path(tmp), Path(tmp) / 'input.json', [{'code': 'blocked'}])
        self.assertEqual(raised.exception.code, 'codex-exact-start-uncertain')

    def test_managed_task_forwards_original_deadline_before_prompt_preparation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = datetime.now(timezone.utc)
            context = _launch_context(root, run_process)
            context.profile['executable'] = sys.executable
            context, args, _ = _bound_launch_context(context, root)
            state = json.loads(args['state_path'].read_text())
            task = state['tasks'][0]
            task['attemptDeadlineAt'] = (now + timedelta(seconds=30)).isoformat()
            state['runDeadlineAt'] = (now + timedelta(seconds=60)).isoformat()
            args['state_path'].write_text(json.dumps(state))
            sentinel = {'status': 'fixture'}
            boundary = time.monotonic_ns()
            def prepare(**kwargs):
                self.assertEqual(kwargs['state'], state)
                self.assertEqual(kwargs['task'], task)
                self.assertIs(kwargs['task'], kwargs['state']['tasks'][0])
                time.sleep(0.01)
                return {'intentPath': root / 'intent.json'}
            with patch.object(launch_preflight, '_managed_launch_blockers', return_value=[]), patch.object(
                    launch_preflight, '_identity', return_value={'status': 'PASS', 'executableContentSha256': 'a' * 64}), patch.object(
                    launch_preflight, 'prepare_exact_prompt', side_effect=prepare), patch.object(
                    launch_preflight, 'require_bootstrap_audit', return_value={'auditSha256': 'b' * 64}), patch.object(
                    launch_preflight, '_run_exact_managed_process', return_value=sentinel) as runner:
                result = launch_preflight._managed_task(context, session_id='session', explicit_launch=True,
                    state_path=args['state_path'], manifest_path=args['manifest_path'], lock_path=args['lock_path'],
                    task_id=args['task_id'], operation_id=args['operation_id'], source_revision=args['source_revision'], risk_profile=args['risk_profile'],
                    route_id=launch_preflight.CODEX_EXACT_ROUTE, requested_claim=launch_preflight.CODEX_SCOPED_CLAIM,
                    input_request=root / 'input.json')
            self.assertIs(result, sentinel)
            forwarded = runner.call_args.kwargs['absolute_deadline_monotonic_ns']
            self.assertIs(type(forwarded), int)
            self.assertLessEqual(forwarded, boundary + 30_000_000_000)
            self.assertGreater(forwarded, boundary + 29_000_000_000)

    def test_valid_profile_passes_and_public_schemas_are_registered(self) -> None:
        profile = _fixture("valid.json")

        validation = validate_local_launch_profile(profile)

        self.assertEqual(validation["status"], "PASS", validation["blockers"])
        self.assertEqual(len(validation["profileDigest"]), 64)
        for schema_id in (
            "agent-local-host-launch-profile.v1",
            "agent-local-host-launch-profile-validation.v1",
            "agent-local-host-launch-profile-receipt.v1",
            "agent-local-host-launch-probe-receipt.v1",
        ):
            self.assertEqual(get_schema(schema_id)["$id"], schema_id)

    def test_invalid_fixtures_fail_closed(self) -> None:
        expected = {
            "path-escape.json": "local-launch-profile-executable",
            "shell-command.json": "local-launch-profile-shell-executable",
            "unknown-placeholder.json": "local-launch-profile-placeholder",
            "env-wildcard.json": "local-launch-profile-env-pattern",
        }
        for name, code in expected.items():
            with self.subTest(name=name):
                validation = validate_local_launch_profile(_fixture(name))
                self.assertEqual(validation["status"], "FAIL")
                self.assertIn(code, {item["code"] for item in validation["blockers"]})

    def test_loader_requires_ignored_local_root_and_rejects_outside_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local = root / ".alk/host-launch/codex.json"
            local.parent.mkdir(parents=True)
            local.write_text(json.dumps(_fixture("valid.json")), encoding="utf-8")
            outside = root / "codex.json"
            outside.write_text(json.dumps(_fixture("valid.json")), encoding="utf-8")

            relative, profile, validation = load_local_launch_profile(local, project_root=root)
            self.assertEqual(relative.as_posix(), ".alk/host-launch/codex.json")
            self.assertEqual(profile["adapterId"], "codex")
            self.assertEqual(validation["status"], "PASS")
            with self.assertRaises(LifecycleError) as raised:
                load_local_launch_profile(outside, project_root=root)

        self.assertEqual(raised.exception.code, "local-launch-profile-path-outside-root")

    def test_loader_rejects_symlinked_local_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside"
            outside.mkdir()
            profile = outside / "codex.json"
            profile.write_text(json.dumps(_fixture("valid.json")), encoding="utf-8")
            (root / ".alk").mkdir()
            (root / ".alk/host-launch").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(LifecycleError) as raised:
                load_local_launch_profile(root / ".alk/host-launch/codex.json", project_root=root)

        self.assertEqual(raised.exception.code, "local-launch-profile-path-invalid")

    def test_version_probe_is_read_only_and_bare_executable_requires_path(self) -> None:
        profile = _fixture("valid.json")
        profile["versionProbeArgs"] = ["run", "task.md"]
        validation = validate_local_launch_profile(profile)
        self.assertIn("local-launch-profile-version-probe", {item["code"] for item in validation["blockers"]})

        profile = _fixture("valid.json")
        profile["env"]["allow"] = ["HOME"]
        validation = validate_local_launch_profile(profile)
        self.assertIn("local-launch-profile-path-env-required", {item["code"] for item in validation["blockers"]})

    def test_renderer_accepts_only_whole_token_frozen_placeholders(self) -> None:
        profile = _fixture("valid.json")
        profile["argvTemplate"] = ["--state", "{state_path}", "--task", "{task_id}"]

        argv = render_local_launch_argv(profile, {"state_path": "work/state.json", "task_id": "WS-01"})

        self.assertEqual(argv, ["codex", "--state", "work/state.json", "--task", "WS-01"])
        profile["argvTemplate"] = ["prefix-{task_id}"]
        validation = validate_local_launch_profile(profile)
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("local-launch-profile-placeholder-shape", {item["code"] for item in validation["blockers"]})

    def test_executable_identity_is_content_bound_and_path_free(self) -> None:
        profile = _fixture("valid.json")
        profile["executable"] = sys.executable
        profile_digest = validate_local_launch_profile(profile)["profileDigest"]

        identity = build_executable_identity(profile, profile_digest=profile_digest)

        self.assertEqual(identity["status"], "PASS")
        self.assertEqual(identity["trustClass"], "OPERATOR_OWNED_UNVERIFIED")
        self.assertEqual(len(identity["resolvedPathSha256"]), 64)
        self.assertEqual(len(identity["executableContentSha256"]), 64)
        self.assertNotIn(str(Path(sys.executable).parent), json.dumps(identity))


def _launch_context(root: Path, runner) -> SimpleNamespace:
    return SimpleNamespace(root=root, runner=runner, timeout_seconds=5.0,
        profile_adapter='codex', profile={}, profile_digest='profile', env={}, env_receipt={})


def _generic_launch(context) -> dict:
    with tempfile.TemporaryDirectory(dir=context.root) as tmp:
        actual, args, invocation = _bound_launch_context(context, Path(tmp).resolve())
        return launch_preflight._run_managed_process(actual, **args, immutable_input_context=invocation)


def _bound_launch_context(context, root):
    actual, args, _ = a5_fixture.managed_fixture(root)
    actual.runner = context.runner
    actual.profile = context.profile
    actual.profile_digest = canonical_digest(actual.profile)
    actual.timeout_seconds = context.timeout_seconds
    actual.env = context.env
    actual.env_receipt = context.env_receipt
    invocation = current_managed_invocation(project_root=root, profile=actual.profile,
        profile_digest=actual.profile_digest, adapter_id=actual.profile_adapter, request=None,
        **{k:v for k,v in args.items() if k not in {'qualification_receipt','host_identity'}})
    return actual, args, invocation


def _prepared_launch(root: Path) -> dict:
    return {'verifyBeforeStart': lambda: None, 'intentPath': root / 'intent.json',
        'startReceiptPath': root / 'process-start.json', 'inputReceiptPath': root / 'process-input.json',
        'runId': 'run', 'taskId': 'task', 'attemptId': '1', 'argv': ['python'],
        'codexHome': str(root), 'stdinText': 'bounded input',
        'onStarted': lambda event: None, 'onInput': lambda event: None,
        'sealedSha256': 'a' * 64, 'finalPromptSha256': 'b' * 64, 'fitReceiptDigest': 'c' * 64}


def _exact_launch(context, prepared, deadline, *, bound=None) -> dict:
    actual, args, invocation = bound if bound is not None else _bound_launch_context(context, context.root)
    prepared['taskId'] = args['task_id']
    prepared['operationId'] = args['operation_id']
    inputs = {k:v for k,v in args.items() if k in {'state_path','manifest_path','lock_path','task_id','operation_id','source_revision'}}
    return launch_preflight._run_exact_managed_process(actual, prepared=prepared,
        audit={'auditSha256': 'd' * 64}, session_id=args['session_id'], risk_profile=args['risk_profile'],
        host_identity={}, operation_id=args['operation_id'], absolute_deadline_monotonic_ns=deadline,
        immutable_input_context=invocation, immutable_input_inputs=inputs)


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()


class R1054OwnedCleanupTests(unittest.TestCase):
    def test_owned_second_a5_refusal_cleans_no_start_but_never_uncertain_dispatch(self):
        for dispatched in (False,True):
            with self.subTest(dispatched=dispatched), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);context=_launch_context(root,run_process);context.profile['executable']=sys.executable
                context,args,current=_bound_launch_context(context,root);state=json.loads(args['state_path'].read_text());now=datetime.now(timezone.utc)
                state['tasks'][0]['attemptDeadlineAt']=(now+timedelta(seconds=30)).isoformat();state['runDeadlineAt']=(now+timedelta(seconds=60)).isoformat();args['state_path'].write_text(json.dumps(state))
                prepared=_prepared_launch(root);raw=root/'sealed.raw';raw.write_bytes(b'owned private input');prepared['startReceiptPath'].write_text('{"stdinStatus":"PENDING"}')
                if dispatched:prepared['startReceiptPath'].with_name('attempt-result-dispatched.json').write_text('{"status":"START_UNCERTAIN"}')
                def cleanup(*a,**kw):self.assertTrue(kw['proven_no_start']);raw.unlink()
                def record(*a):prepared['startReceiptPath'].write_text('{"stdinStatus":"NO_START"}')
                with patch.object(launch_preflight,'_managed_launch_blockers',return_value=[]),patch.object(launch_preflight,'_identity',return_value={'status':'PASS','executableContentSha256':'a'*64}),patch.object(launch_preflight,'current_managed_invocation',side_effect=[current,LifecycleError('a5-context-invalid','sink changed')]),patch.object(launch_preflight,'validate_current_invocation'),patch.object(launch_preflight,'prepare_exact_prompt',return_value=prepared),patch.object(launch_preflight,'require_bootstrap_audit',return_value={'auditSha256':'b'*64}),patch.object(launch_preflight,'cleanup_prestart_raw',side_effect=cleanup) as clean,patch.object(launch_preflight,'record_proven_no_start',side_effect=record) as no_start:
                    call=lambda:launch_preflight._managed_task(context,session_id='session',explicit_launch=True,state_path=args['state_path'],manifest_path=args['manifest_path'],lock_path=args['lock_path'],task_id=args['task_id'],operation_id=args['operation_id'],source_revision=args['source_revision'],risk_profile=args['risk_profile'],route_id=launch_preflight.CODEX_EXACT_ROUTE,requested_claim=launch_preflight.CODEX_SCOPED_CLAIM,input_request=root/'input.json')
                    if dispatched:
                        with self.assertRaises(LifecycleError) as caught:call()
                        self.assertEqual(caught.exception.code,'codex-exact-start-uncertain');clean.assert_not_called();no_start.assert_not_called();self.assertTrue(raw.exists())
                    else:
                        result=call();self.assertEqual(result['status'],'BLOCKED');self.assertFalse(result['hostLaunchStarted']);self.assertIs(type(result),dict);clean.assert_called_once();no_start.assert_called_once();self.assertFalse(raw.exists());self.assertEqual(json.loads(prepared['startReceiptPath'].read_text())['stdinStatus'],'NO_START')

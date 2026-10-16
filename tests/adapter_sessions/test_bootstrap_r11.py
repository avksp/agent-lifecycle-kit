from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent_lifecycle.adapter_sessions import bootstrap_r11
from agent_lifecycle.adapter_sessions import source_review_inputs
from agent_lifecycle.adapter_sessions import codex_exact_prompt as exact
from agent_lifecycle.adapter_sessions import codex_prompt_preparation as preparation
from agent_lifecycle.adapter_sessions import launch_preflight
from agent_lifecycle.adapter_sessions.bootstrap_r11 import (
    publish_attempt_result, read_attempt_result, reserve_attempt_result,
)
from agent_lifecycle.adapter_sessions.codex_exact_prompt import _write_exclusive
from agent_lifecycle.contracts import LifecycleError, canonical_bytes
from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.adapter_sessions.process import run_process



def _current_disabled_r11_binding():
    """Only a verified installed ordinary/disabled plan can retire old positives.

    This Release2.16 fixture has no applicability decision for another route.
    Unknown, missing, inconsistent or enabled authority fails instead of skips.
    """
    from agent_lifecycle.freeze import verify_plan_package_integrity
    root = Path(__file__).resolve().parents[2]
    plan = root / 'tasks/release-2-16'
    manifest_raw = (plan / 'plan.manifest.json').read_bytes()
    lock_raw = (plan / 'plan.lock.json').read_bytes()
    manifest, lock = json.loads(manifest_raw), json.loads(lock_raw)
    verify_plan_package_integrity(manifest, lock, repository_root=root)
    route = json.loads((plan / 'route-bootstrap-contract.json').read_bytes())
    delivery = manifest['runtimePolicy']['reviewDelivery']
    if (manifest['status'] != 'FROZEN' or manifest['package']['id'] != 'release-2-16'
            or {**delivery, 'ordinaryWorkflowAdmissionContract':
                'tasks/release-2-16/ordinary-release-contract-r88.md'} != route['auditJoin']['delivery']
            or delivery.get('mode') != 'ORDINARY_INDEPENDENT_SOURCE_AUDIT'
            or delivery.get('experimentalR11') != 'DISABLED'):
        raise AssertionError('No approved test applicability decision for this authority/route')
    return {'planDigest': canonical_digest(manifest), 'lockSha256': hashlib.sha256(lock_raw).hexdigest()}


def _retired_r11_positive(method):
    """Keep old assertions available; never report a retired positive as PASS."""
    from functools import wraps
    @wraps(method)
    def observed(self):
        binding = _current_disabled_r11_binding()
        self.skipTest('NOT_RUN_BY_APPLICABILITY: valid frozen ordinary/R11=DISABLED; '
                      'legacy positive retained; plan=' + binding['planDigest'] + '; lock=' + binding['lockSha256'])
    return observed


@contextmanager
def bound_current_invocation_fixture(root, *, task_id="task", operation_id="op",
                                     source_revision="revision", state_path=None,
                                     manifest_path=None, lock_path=None):
    """Isolate terminal/route tests from A5 authority; real sink shape guards remain.

    This local fixture never proves a host route or production invocation. Its
    mocked A5 boundary checks exact inputs and context identity; dedicated A5
    tests cover the actual validator. Original downstream assertions stay real.
    """
    inputs = {"state_path": state_path or root / "state.fixture.json",
              "manifest_path": manifest_path or root / "tasks/release-2-16/plan.manifest.json",
              "lock_path": lock_path or root / "tasks/release-2-16/plan.lock.json",
              "task_id": task_id, "operation_id": operation_id, "source_revision": source_revision}
    invocation = {"testOnly": True, "protection": "NONE", "operationId": operation_id,
                  "requestDigest": canonical_digest(None)}

    def current(**kwargs):
        launch_preflight.require_no_strong_protection(kwargs["request"], expected_protection="NONE")
        if kwargs["project_root"] != root or kwargs["adapter_id"] != "codex":
            raise AssertionError("local fixture invocation differs")
        if any(kwargs[key] != value for key, value in inputs.items()):
            raise AssertionError("local fixture inputs differ")
        return {**invocation, "requestDigest": canonical_digest(kwargs["request"])}

    def validate(bound, request, *, current_context):
        launch_preflight.require_no_strong_protection(request, expected_protection="NONE")
        expected = {**invocation, "requestDigest": canonical_digest(request)}
        if bound != expected or current_context != expected:
            raise AssertionError("local fixture context differs")

    with patch.object(launch_preflight, "current_managed_invocation", side_effect=current), patch.object(
            launch_preflight, "validate_current_invocation", side_effect=validate):
        yield {"immutable_input_context": invocation, "immutable_input_inputs": inputs}


@unittest.skipUnless(os.name == 'posix', 'durable directory fixture uses POSIX descriptors')
class AttemptResultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.path = self.root / 'work/release-2-16/evidence/codex-exact-prompt/run/task/1/prelaunch-intent.json'
        self.intent = {'schemaVersion': 'alk-codex-prelaunch-intent.v1',
                       'runId': 'run', 'taskId': 'task', 'attemptId': '1', 'operationId': 'op',
                       'routeId': 'codex-exact-prompt-v1', 'requestedClaim': 'ALK_CONTROLLED_OUTBOUND_INPUT_FIT',
                       'planDigest': 'a' * 64, 'lockDigest': 'b' * 64, 'sourceRevision': 'revision',
                       'requestSha256': 'c' * 64, 'finalPromptSha256': 'd' * 64,
                       'commandIdentityHash': 'e' * 64, 'plannedStdinBytes': 12, 'hostLaunchStarted': False}
        _write_exclusive(self.path, canonical_bytes(self.intent), root=self.root)
        self.result = {'processStarted': True, 'status': 'FAIL', 'exitCode': -15,
                       'timedOut': True, 'cancelled': False,
                       'startObservation': {'processIdentityHash': 'f' * 64},
                       'deadlineMonotonicNs': 1000000000, 'cleanup': {'status': 'PASS'},
                       'observerDisposition': 'CALLBACK_PENDING'}

    def reserve(self) -> None:
        reserve_attempt_result(self.root, intent_path=self.path)

    def publish(self) -> dict:
        return publish_attempt_result(self.root, intent_path=self.path, process_result=self.result)

    def read(self) -> dict:
        return read_attempt_result(self.root, intent_path=self.path)

    def observations(self) -> None:
        identity = {key: self.intent[key] for key in ('runId', 'taskId', 'attemptId', 'finalPromptSha256')}
        start = {**identity, 'schemaVersion': 'alk-codex-process-start.v1',
                 'hostLaunchStarted': True, 'stdinStatus': 'PENDING',
                 'commandIdentityHash': self.intent['commandIdentityHash'], 'processIdentityHash': 'f' * 64}
        delivered = {**identity, 'schemaVersion': 'alk-codex-process-input.v1', 'status': 'COMPLETE',
                     'closeSucceeded': True, 'processIdentityHash': 'f' * 64,
                     'acceptedBytes': 12, 'acceptedSha256': self.intent['finalPromptSha256']}
        start_raw, input_raw = canonical_bytes(start), canonical_bytes(delivered)
        transport = {**identity, 'schemaVersion': 'alk-codex-os-pipe-transport.v1',
                     'status': 'OS_PIPE_ACCEPTED', 'processStartSha256': hashlib.sha256(start_raw).hexdigest(),
                     'processInputSha256': hashlib.sha256(input_raw).hexdigest()}
        for name, raw in [('process-start.json', start_raw), ('process-input.json', input_raw),
                          ('transport-equivalence.json', canonical_bytes(transport))]:
            _write_exclusive(self.path.with_name(name), raw, root=self.root)

    def test_reservation_precedes_publication_and_cannot_be_reused(self) -> None:
        with self.assertRaises(FileNotFoundError):
            self.publish()
        self.reserve()
        with self.assertRaises(LifecycleError):
            self.reserve()
        self.assertFalse(self.path.with_name('attempt-result-terminal.json').exists())

    def test_missing_terminal_is_uncertain_not_no_start(self) -> None:
        self.reserve()
        with self.assertRaises(LifecycleError) as caught:
            self.read()
        self.assertEqual(caught.exception.code, 'r11-result-start-uncertain')

    def test_late_observations_do_not_promote_failed_attempt(self) -> None:
        self.reserve()
        first = self.publish()
        raw = self.path.with_name('attempt-result-terminal.json').read_bytes()
        self.observations()
        self.assertEqual(self.read(), first)
        self.assertEqual(first['status'], 'FAIL')
        self.assertEqual(first['costStatus'], 'UNAVAILABLE')
        self.assertFalse(first['retryAuthorized'])
        self.assertEqual(self.path.with_name('attempt-result-terminal.json').read_bytes(), raw)

    def test_terminal_failure_cannot_be_overwritten_by_success(self) -> None:
        self.reserve()
        self.publish()
        self.observations()
        self.result.update(status='PASS', exitCode=0, timedOut=False)
        with self.assertRaises(LifecycleError) as caught:
            self.publish()
        self.assertEqual(caught.exception.code, 'r11-result-terminal-conflict')
        self.assertEqual(self.read()['status'], 'FAIL')

    def test_positive_result_requires_transport_and_detects_later_change(self) -> None:
        self.reserve()
        self.result.update(status='PASS', exitCode=0, timedOut=False)
        with self.assertRaises(FileNotFoundError):
            self.publish()
        self.observations()
        self.assertEqual(self.publish()['status'], 'PASS')
        self.assertEqual(self.read()['status'], 'PASS')
        path = self.path.with_name('process-input.json')
        value = json.loads(path.read_bytes())
        value['acceptedBytes'] = 0
        path.write_bytes(canonical_bytes(value))
        with self.assertRaises(LifecycleError) as caught:
            self.read()
        self.assertEqual(caught.exception.code, 'r11-result-positive-join')

    def test_failed_directory_sync_leaves_visible_terminal_unauthorized(self) -> None:
        self.reserve()
        from agent_lifecycle.adapter_sessions import attempt_authority
        original_sync = attempt_authority._sync_directory
        calls = []

        def fail_terminal_sync(path: Path) -> None:
            calls.append(path)
            if len(calls) == 2:
                raise OSError('injected durability failure after link')
            original_sync(path)

        with patch.object(attempt_authority, '_sync_directory', fail_terminal_sync):
            with self.assertRaises(OSError):
                self.publish()
        self.assertTrue(self.path.with_name('attempt-result-terminal.json').exists())
        self.assertTrue(self.path.with_name('attempt-result-terminal.pending.json').exists())
        with self.assertRaises(LifecycleError) as caught:
            self.read()
        self.assertEqual(caught.exception.code, 'r11-result-start-uncertain')

    def test_changed_intent_cannot_rebind_reserved_attempt(self) -> None:
        self.reserve()
        self.intent['lockDigest'] = '9' * 64
        self.path.write_bytes(canonical_bytes(self.intent))
        with self.assertRaises(LifecycleError) as caught:
            self.publish()
        self.assertEqual(caught.exception.code, 'r11-result-identity')

    def test_concurrent_publishers_cannot_overwrite_each_other(self) -> None:
        self.reserve()
        barrier = threading.Barrier(2)
        published = []
        refused = []

        def publish(status: str) -> None:
            barrier.wait(timeout=2)
            try:
                result = publish_attempt_result(self.root, intent_path=self.path,
                                                process_result={**self.result, 'status': status})
                published.append(result)
            except (OSError, LifecycleError) as exc:
                refused.append(exc)

        workers = [threading.Thread(target=publish, args=(status,)) for status in ('FAIL', 'BLOCKED')]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(2)
            self.assertFalse(worker.is_alive())
        self.assertEqual(len(published), 1)
        self.assertEqual(len(refused), 1)
        self.assertEqual(self.read(), published[0])

    def test_no_start_result_does_not_create_started_terminal(self) -> None:
        self.reserve()
        self.result['processStarted'] = False
        with self.assertRaises(LifecycleError) as caught:
            self.publish()
        self.assertEqual(caught.exception.code, 'r11-result-start-unproven')
        self.assertFalse(self.path.with_name('attempt-result-terminal.json').exists())

    def test_cross_attempt_path_and_symlink_are_refused(self) -> None:
        other = self.path.parent.parent / '2/prelaunch-intent.json'
        _write_exclusive(other, canonical_bytes(self.intent), root=self.root)
        with self.assertRaises(LifecycleError):
            reserve_attempt_result(self.root, intent_path=other)
        self.reserve()
        self.path.with_name('attempt-result-terminal.json').symlink_to(self.path)
        with self.assertRaises(LifecycleError):
            self.publish()


@unittest.skipUnless(os.name == 'posix', 'managed-child fixture uses POSIX descriptors')
class PreparedAttemptIntegrationTests(unittest.TestCase):
    """Real prepared callbacks and local Python child; host fit is a fixture."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        source = Path(__file__).parents[2]
        for name in bootstrap_r11._SOURCES:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
        self.manifest = {'status': 'FROZEN', 'planRevision': 69}
        self.manifest_path = self.root / 'tasks/release-2-16/plan.manifest.json'
        self.manifest_path.parent.mkdir(parents=True)
        self.manifest_path.write_bytes(canonical_bytes(self.manifest))
        self.lock = self.manifest_path.with_name('plan.lock.json')
        self.lock.write_bytes(b'{"fixture":true}')
        from agent_lifecycle.adapter_sessions.attempt_authority import _invocation_namespace
        namespace = _invocation_namespace('run', 'task', '1', 'op')
        self.evidence = self.root / 'work/release-2-16/evidence/codex-exact-prompt' / namespace
        self.home = self.root / 'work/release-2-16/runtime-private/codex-exact-prompt' / namespace / 'codex-home'
        exact._private_dir(self.home, boundary=self.root)
        config = self.home / 'config.toml'
        config.write_text('model="fixture"\n')
        config.chmod(0o400)
        snapshot_digest = exact._snapshot_digest(self.home, root=self.root)
        config_manifest = b'{"fixture":"config"}'
        _write_exclusive(self.evidence / 'config-snapshot-manifest.json', config_manifest, root=self.root)
        self.binary = self.root / 'bin/codex'
        self.binary.parent.mkdir()
        self.binary.write_text('#!' + sys.executable + '\nimport sys\nsys.stdin.buffer.read()\n')
        self.binary.chmod(0o700)
        selected = {'selected': []}
        model_input = {'renderedEnvelope': {}, 'selectedSource': [], 'instruction': 'fixture', 'schema': {}}
        final_sha = hashlib.sha256(canonical_bytes(model_input)).hexdigest()
        self.final_sha = final_sha
        packet = {'plan': {'planDigest': canonical_digest(self.manifest)}, 'task': {'id': 'task'}}
        packet_path = self.root / 'work/release-2-16/packet.json'
        packet_path.write_bytes(canonical_bytes(packet))
        contract = self.manifest_path.with_name('alk-input-fit-contract.json')
        contract.write_bytes(canonical_bytes({'commonEnvelope': {'reservedOutputEstimatedTokens': 3072}}))
        profile = self.root / 'profiles/small-context-profile.v1.json'
        profile.parent.mkdir()
        profile.write_bytes(b'{}')
        self.request = {'routeId': exact.ROUTE_ID, 'requestedClaim': exact.CLAIM,
                        'runId': 'run', 'taskId': 'task', 'operationId': 'op', 'sourceRevision': 'revision',
                        'planDigest': canonical_digest(self.manifest),
                        'lockDigest': hashlib.sha256(self.lock.read_bytes()).hexdigest(),
                        'packetPath': 'work/release-2-16/packet.json',
                        'packetSha256': hashlib.sha256(packet_path.read_bytes()).hexdigest(),
                        'role': 'worker', 'selection': selected, 'summary': {}, 'selectedSource': [],
                        'instruction': 'fixture', 'schema': {}}
        fixtures = {
            'assess_local_input_fit': {'status': 'PASS_ALK_COMPONENTS_ONLY', 'checks': [{'status': 'PASS'}],
                                      'inputComponentDigests': {'fullAlkModelInput': final_sha},
                                      'receiptDigest': 'f' * 64},
            'render_context': {'envelope': {}},
            '_selected_host_evidence': ('fixture', str(self.home), snapshot_digest, {},
                                       {'rawSha256': 'a' * 64, 'items': []},
                                       hashlib.sha256(config_manifest).hexdigest()),
            '_selected_binary_path': self.binary,
            'create_prestart_raw_inventory': (self.root / 'inventory', self.root / 'pending', 'b' * 64),
            'verify_prestart_raw_inventory': 'b' * 64,
            '_recheck_active_workflow_state': None, '_recheck_alk_fit_sources': None,
            '_require_fresh_catalog': None,
        }
        for name, value in fixtures.items():
            self.patches.enter_context(patch.object(preparation, name, return_value=value))
        staged = exact.stage_input_request(self.root, 'request', self.request)
        self.prepared = exact.prepare_exact_prompt(
            project_root=self.root, input_request=staged, route_id=exact.ROUTE_ID,
            requested_claim=exact.CLAIM, state={'runId': 'run', 'sourceRevision': 'revision'},
            task={'id': 'task', 'attempt': 1, 'status': 'RUNNING'}, manifest=self.manifest,
            lock_path=self.lock, source_revision='revision', operation_id='op',
            executable_identity={'status': 'PASS', 'executableContentSha256': 'c' * 64},
            executable=str(self.binary), process_env=dict(os.environ), manifest_path=self.manifest_path)
        # This fixture exercises native attempt terminals; fresh bootstrap proof
        # is tested separately with the ordinary task-bound metadata gate.
        bootstrap_gate = patch.object(launch_preflight, 'verify_fresh_task_gate')
        self.bootstrap_gate = bootstrap_gate.start()
        self.addCleanup(bootstrap_gate.stop)
        self.outcomes = []

        def runner(*args, **kwargs):
            result = run_process(*args, **kwargs, cleanup_grace_seconds=0.1)
            self.outcomes.append(result)
            return result

        # One original monotonic deadline per fixture; reused launches never renew it.
        self.absolute_deadline_monotonic_ns = time.monotonic_ns() + 5_000_000_000
        self.context = launch_preflight._LaunchContext(
            root=self.root, relative=Path('profiles/local.fixture.json'), runner=runner,
            timeout_seconds=2, profile={'executable': str(self.binary)}, profile_adapter='codex',
            env=dict(os.environ), env_receipt={}, profile_digest='fixture', shipped_digest=None)
        self.immutable_bindings = self.patches.enter_context(bound_current_invocation_fixture(
            self.root, manifest_path=self.manifest_path, lock_path=self.lock))

    def launch(self) -> dict:
        return launch_preflight._run_exact_managed_process(
            self.context, prepared=self.prepared, audit={'auditSha256': 'a' * 64},
            session_id='fixture', risk_profile={'profileDigest': 'risk'},
            host_identity={'status': 'PASS'}, operation_id='op',
            absolute_deadline_monotonic_ns=self.absolute_deadline_monotonic_ns, **self.immutable_bindings)

    def test_fresh_bootstrap_refusal_prevents_native_dispatch(self) -> None:
        self.bootstrap_gate.side_effect = LifecycleError('r11-native-stale', 'fresh evidence changed')
        result = self.launch()
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertFalse(result['hostLaunchStarted'])
        self.assertEqual(self.outcomes, [])
        self.assertFalse(self.prepared['intentPath'].with_name('attempt-result-dispatched.json').exists())
        self.bootstrap_gate.assert_called_once()

    def test_success_is_joined_to_reserved_terminal_and_current_sources(self) -> None:
        self.assertTrue((self.evidence / 'attempt-result-reservation.json').exists())
        result = self.launch()
        self.assertEqual(result['status'], 'PASS', result)
        self.assertEqual(result['exactPrompt']['terminalStatus'], 'PASS')
        terminal_path = self.evidence / 'attempt-result-terminal.json'
        self.assertEqual(result['exactPrompt']['terminalResultSha256'], hashlib.sha256(terminal_path.read_bytes()).hexdigest())
        exact.reconcile_prelaunch_intents(self.root)
        intent = json.loads(self.prepared['intentPath'].read_bytes())
        changed = self.root / bootstrap_r11._SOURCES[0]
        changed.write_bytes(changed.read_bytes() + b'\n# changed\n')
        self.assertFalse(exact._complete_started_input(self.root, self.evidence, intent))
        with self.assertRaises(LifecycleError):
            exact.reconcile_prelaunch_intents(self.root)

    def exercise_late_prepared_receipts(self) -> None:
        from agent_lifecycle.adapter_sessions import process as process_module
        entered = threading.Event()
        child_exited = threading.Event()
        children = []
        original_popen = process_module.subprocess.Popen

        def capture_child(*args, **kwargs):
            child = original_popen(*args, **kwargs)
            children.append(child)
            return child
        release = threading.Event()
        finished = threading.Event()
        original_replace = preparation._replace_reserved
        callback = self.prepared['onInput']

        def delay_input(path, record, *, root):
            if path.name == 'process-input.json':
                entered.set()
                release.wait(10)
            original_replace(path, record, root=root)

        def observed_callback(event):
            try:
                # Observe the zero child exit before deliberately holding its
                # receipt past the original deadline.
                self.assertEqual(children[0].wait(timeout=2), 0)
                child_exited.set()
                callback(event)
            finally:
                finished.set()

        self.prepared['onInput'] = observed_callback
        self.context = replace(self.context, timeout_seconds=3)
        with patch.object(process_module.subprocess, 'Popen', side_effect=capture_child), \
                patch.object(preparation, '_replace_reserved', delay_input):
            try:
                result = self.launch()
                self.assertTrue(child_exited.is_set())
                self.assertTrue(entered.is_set())
                self.assertEqual(result['status'], 'FAIL', result)
                self.assertEqual(result['exactPrompt']['terminalStatus'], 'FAIL')
                self.assertEqual(result['exactPrompt']['costStatus'], 'UNAVAILABLE')
                self.assertEqual(self.outcomes[0]['cleanup']['status'], 'PASS')
                self.assertEqual(self.outcomes[0]['exitCode'], 0)
                terminal_path = self.evidence / 'attempt-result-terminal.json'
                before = terminal_path.read_bytes()
            finally:
                release.set()
                self.assertTrue(finished.wait(2))
        self.assertEqual(terminal_path.read_bytes(), before)
        self.assertTrue((self.evidence / 'transport-equivalence.json').exists())
        terminal = read_attempt_result(self.root, intent_path=self.prepared['intentPath'])
        self.assertEqual(terminal['status'], 'FAIL')
        self.assertFalse(terminal['retryAuthorized'])
        with self.assertRaises(LifecycleError) as caught:
            exact.reconcile_prelaunch_intents(self.root)
        self.assertEqual(caught.exception.code, 'codex-exact-terminal-retry-required')
        self.assertTrue(self.prepared['sealedRequest'].exists())

    def exercise_terminal_publication_failure(self) -> None:
        with patch.object(launch_preflight, 'publish_attempt_result', side_effect=OSError('disk failure')):
            result = self.launch()
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['exactPrompt']['terminalStatus'], 'START_UNCERTAIN')
        self.assertIsNone(result['exactPrompt']['terminalResultSha256'])
        self.assertEqual(result['exactPrompt']['costStatus'], 'UNAVAILABLE')
        self.assertTrue(self.prepared['sealedRequest'].exists())
        with self.assertRaises(LifecycleError):
            exact.reconcile_prelaunch_intents(self.root)

    def test_reusing_prepared_attempt_neither_restarts_nor_deletes_raw(self) -> None:
        result = self.launch()
        self.assertEqual(result['status'], 'PASS')
        terminal_before = (self.evidence / 'attempt-result-terminal.json').read_bytes()
        with self.assertRaises(LifecycleError) as caught:
            self.launch()
        self.assertEqual(caught.exception.code, 'codex-exact-start-uncertain')
        self.assertEqual((self.evidence / 'attempt-result-terminal.json').read_bytes(), terminal_before)
        self.assertEqual(len(self.outcomes), 1)
        self.assertTrue(self.prepared['sealedRequest'].exists())

    def test_uncertain_runner_does_not_claim_no_start_or_remove_raw(self) -> None:
        self.context = replace(self.context, runner=lambda *args, **kwargs: {})
        with self.assertRaises(LifecycleError) as caught:
            self.launch()
        self.assertEqual(caught.exception.code, 'codex-exact-start-uncertain')
        self.assertTrue(self.prepared['sealedRequest'].exists())
        self.assertFalse((self.evidence / 'proven-no-start.json').exists())
        with self.assertRaises(LifecycleError):
            read_attempt_result(self.root, intent_path=self.prepared['intentPath'])

    def test_same_prepared_attempt_cannot_dispatch_concurrently(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        first = []
        runner = self.context.runner

        def blocked_runner(*args, **kwargs):
            entered.set()
            release.wait(3)
            return runner(*args, **kwargs)

        self.context = replace(self.context, runner=blocked_runner)
        worker = threading.Thread(target=lambda: first.append(self.launch()))
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            with self.assertRaises(LifecycleError) as caught:
                self.launch()
            self.assertEqual(caught.exception.code, 'codex-exact-start-uncertain')
            self.assertTrue(self.prepared['sealedRequest'].exists())
            self.assertFalse((self.evidence / 'proven-no-start.json').exists())
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(first[0]['status'], 'PASS', first)
        self.assertEqual(len(self.outcomes), 1)

    def test_known_runner_no_start_remains_a_separate_proof(self) -> None:
        self.context = replace(self.context, runner=lambda *args, **kwargs: {
            'processStarted': False, 'status': 'FAIL', 'blockers': []})
        result = self.launch()
        self.assertFalse(result['hostLaunchStarted'])
        self.assertEqual(result['exactPrompt']['terminalStatus'], 'NOT_STARTED')
        self.assertEqual(result['exactPrompt']['costStatus'], 'NOT_STARTED')
        self.assertTrue((self.evidence / 'proven-no-start.json').exists())
        self.assertFalse((self.evidence / 'attempt-result-terminal.json').exists())
        self.assertFalse(self.prepared['sealedRequest'].exists())
        exact.reconcile_prelaunch_intents(self.root)

    def test_changed_manifest_after_result_cannot_authorize_positive_join(self) -> None:
        result = self.launch()
        self.assertEqual(result['status'], 'PASS')
        self.manifest_path.write_bytes(canonical_bytes({**self.manifest, 'planRevision': 70}))
        with self.assertRaises(LifecycleError) as caught:
            bootstrap_r11.require_positive_attempt_result(self.root, intent_path=self.prepared['intentPath'])
        self.assertEqual(caught.exception.code, 'r11-result-authority-stale')


if __name__ == '__main__':
    unittest.main()


_R11_ROOT = Path(__file__).parents[2]
_R11_REAL_SRC = _R11_ROOT / 'src'
_R11_SCHEMA = (_R11_ROOT / 'tasks/release-2-16/historical-r69q/REVIEWER-BODY-v5-R11.schema.json').read_bytes()

def _r11_sha(raw):
    return hashlib.sha256(raw).hexdigest()

class _R11BodyFixture(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.schema_path = self.root / 'tasks/release-2-16/REVIEWER-BODY-v5-R11.schema.json'
        self.schema_path.parent.mkdir(parents=True)
        self.schema_path.write_bytes(_R11_SCHEMA)
        self.source = b'def entry():\n    return 1\n'
        self.sources = {('CURRENT', 'src/example.py'): self.source}
        self.rows = bootstrap_r11._r11_coverage_rows(self.sources, {('CURRENT', 'src/example.py'): [(0, len(self.source))]})
        self.shared = {'currentSubjectSha256': 'a' * 64, 'parentSubjectSha256': 'b' * 64}
        self.subject = {**self.shared, 'shardId': 'r11-01', 'shardInventorySha256': 'c' * 64, 'coveredPathRangeSha256': canonical_digest(self.rows)}
        self.request = bootstrap_r11._r11_shard_request(root=self.root, sources=self.sources, rows=self.rows, shared=self.shared, calls=[], schema=json.loads(_R11_SCHEMA), shard_id='r11-01', inventory_sha='c' * 64, thread_id='thread', request_id=1)
        self.body = {'schemaVersion': 'alk-route-bootstrap-reviewer-body.v5-r11', 'subjectSha256': canonical_digest(self.subject), 'verdict': 'PASS', 'phase': 'PRE_WS01', 'rb11RuntimeStatus': 'NOT_RUN', 'coverageComplete': True, 'reviewText': 'NO_CURRENT_FINDINGS', 'findings': [], **self.subject, 'inheritedCoverageAccepted': True, 'interactionScopeComplete': True, 'closedParentFindingIds': ['RB-OBSERVER-TIMEOUT-01']}

    def read(self, body_raw):
        return {'thread': {'id': 'thread', 'turns': [{'id': 'turn', 'status': 'completed', 'items': [{'id': 'input', 'type': 'userMessage', 'content': json.loads(self.request)['params']['input']}, {'id': 'reason', 'type': 'reasoning', 'summary': []}, {'id': 'output', 'type': 'agentMessage', 'phase': 'final_answer', 'text': body_raw.decode()}]}]}}

class _R11TransportFixture(_R11BodyFixture):

    def setUp(self):
        super().setUp()
        self.binding = {'operationId': 'op', 'shardId': 'r11-01', 'threadId': 'thread', 'binarySha256': 'd' * 64, 'transportSourceSha256': 'e' * 64}
        self.body_raw = canonical_bytes(self.body)

    def build(self):
        records = []

        def add(kind, **values):
            records.append({'sequence': len(records), 'monotonicNs': 100 + len(records), 'kind': kind, **values})

        def send(raw):
            ident = json.loads(raw)['id']
            add('REQUEST_SAVED', raw=raw.decode())
            middle = len(raw) // 2
            for left, right in [(0, middle), (middle, len(raw))]:
                add('WRITE_ACCEPTED', requestId=ident, offset=left, acceptedBytes=right - left, chunkSha256=_r11_sha(raw[left:right]), prefixSha256=_r11_sha(raw[:right]))
            add('FLUSHED', requestId=ident, requestBytes=len(raw), requestSha256=_r11_sha(raw))

        def receive(message):
            add('RECEIVED', rawHex=canonical_bytes(message).hex())

        def notice(method, params):
            receive({'method': method, 'params': params})
        add('SESSION', binding=self.binding)
        send(self.request)
        start = {'id': 'turn', 'status': 'inProgress', 'items': [], 'error': None}
        receive({'id': 1, 'result': {'turn': start}})
        notice('turn/started', {'threadId': 'thread', 'turn': start})
        for item in self.read(self.body_raw)['thread']['turns'][0]['items']:
            notice('item/started', {'threadId': 'thread', 'turnId': 'turn', 'item': item})
            if item['type'] == 'agentMessage':
                notice('item/agentMessage/delta', {'threadId': 'thread', 'turnId': 'turn', 'itemId': item['id'], 'delta': '...'})
            notice('item/completed', {'threadId': 'thread', 'turnId': 'turn', 'item': item})
        notice('turn/completed', {'threadId': 'thread', 'turn': {'id': 'turn', 'status': 'completed', 'error': None, 'items': [self.read(self.body_raw)['thread']['turns'][0]['items'][-1]]}})
        for ident in [2, 3]:
            send(canonical_bytes({'id': ident, 'method': 'thread/read', 'params': {'threadId': 'thread', 'includeTurns': True}}) + b'\n')
            receive({'id': ident, 'result': self.read(self.body_raw)})
        return records

def _r11_funding():
    self = SimpleNamespace()
    self.opening = {'costStatus': 'UNAVAILABLE', 'actualTokens': None, 'unknownHoldsIncludingThisWindow': 1000, 'ledgerLowerBoundIncludingThisHold': 1100}
    self.admission = {'status': 'ADMITTED_PREAPPROVED_BY_USER', 'bootstrapAdmissionId': 'fixture-window', 'implementationOriginAdmissionId': 'r166-pre-ws01-route-bootstrap', 'tokenCap': 300000, 'protectedCloseoutTokens': 100000, 'workAllocation': 200000, 'costOpeningSha256': _r11_sha(canonical_bytes(self.opening)), 'priorUnknownHolds': 1000, 'priorAccountedExposureLowerBound': 1100, 'admittedUnknownHolds': 301000, 'admittedExposureLowerBound': 301100, 'maxToolRequests': 40, 'maxTargetedValidationCommands': 2, 'maxElapsedSeconds': 1800, 'maxModelReviewStarts': 1, 'maxNativeLaunches': 0, 'paidResponsesApi': False, 'externalMessages': False, 'costStatus': 'UNAVAILABLE', 'actualModelTokens': None}
    self.cost = {'bootstrapAdmissionId': 'fixture-window', 'implementationOriginAdmissionId': 'r166-pre-ws01-route-bootstrap', 'windowCap': 300000, 'admissionSha256': _r11_sha(canonical_bytes(self.admission)), 'priorUnknownHolds': 1000, 'priorAccountedExposureLowerBound': 1100, 'heldUnknownTokens': 301000, 'accountedExposureLowerBound': 301100, 'costStatus': 'UNAVAILABLE', 'actualModelTokens': None}
    return self




def _r11_role_request_fixture(self, *, padding='', shared_operation='shared-op'):
    temporary = tempfile.TemporaryDirectory()
    self.addCleanup(temporary.cleanup)
    root = Path(temporary.name)
    shutil.copytree(Path(__file__).parents[2] / 'tasks/release-2-16', root / 'tasks/release-2-16')
    authority = bootstrap_r11._r11_role_authority(root)
    shared = {'fixtureOnly': True, 'parentReviewRaw': '{"verdict":"FAIL"}\n', 'padding': padding}
    literal = 'def call(cb):\n    return cb("ё")\n'
    extent = {'version': 'CURRENT', 'path': 'src/fixture.py', 'start': 0,
              'end': len(literal.encode()), 'sha256': hashlib.sha256(literal.encode()).hexdigest()}
    scopes = ['COLLECTOR_FIRST_NATIVE', 'OBSERVER_TERMINAL']
    source = {'sourceContent': [{'extent': extent, 'content': literal}],
              'callProjection': [{'path': extent['path'], 'allCallsOnLines': [2]}],
              'staticPairAssignment': [], 'requiredIntegrationScopes': scopes,
              'integrationClosureContent': {scope: 'Fixture parent finding and exact predicate for ' + scope for scope in scopes}}
    base = {key: 'a' * 64 for key in authority['schemas']['base']['properties']}
    base.update(schemaVersion='alk-r11-role-base.v1', reviewId='fixture-review',
                planLockSha256=authority['lockSha256'], limits=authority['contract']['limits'],
                claimScope='LIMITED_ALK_INPUT_PROCEDURAL_REVIEW', sharedExposureSha256=canonical_digest(shared))
    empty = canonical_digest([])
    inventory = {'schemaVersion': 'alk-r11-role-inventory.v1', 'reviewId': base['reviewId'],
                 'baseSha256': canonical_digest(base), 'roles': [
                     {'roleId': 'shared-01', 'roleKind': 'SHARED', 'operationId': shared_operation,
                      'exposureSha256': canonical_digest(shared), 'sourceRangeSha256': empty,
                      'callProjectionSha256': empty, 'staticPairAssignmentSha256': empty,
                      'requiredIntegrationScopes': []},
                     {'roleId': 'source-01', 'roleKind': 'SOURCE', 'operationId': 'source-op',
                      'exposureSha256': canonical_digest(source), 'sourceRangeSha256': canonical_digest([extent]),
                      'callProjectionSha256': canonical_digest(source['callProjection']),
                      'staticPairAssignmentSha256': empty, 'requiredIntegrationScopes': scopes}]}
    slot = {'tokenCap': 360000, 'protectedCloseoutTokens': 100000, 'maxModelStarts': 1,
            'maxElapsedSeconds': 1800, 'maxToolRequests': 40, 'maxTargetedValidationCommands': 2,
            'workTokens': 260000}
    funding = {'schemaVersion': 'alk-r11-role-funding.v1', 'reviewId': base['reviewId'],
               'baseSha256': canonical_digest(base), 'roleInventorySha256': canonical_digest(inventory),
               'priorHeadSha256': 'b' * 64, 'priorUnknownHolds': 300000, 'priorExposureLowerBound': 400000,
               'reusedFirstHold': None, 'admittedAtUtc': '2026-09-28T00:00:00Z',
               'absoluteDeadlineUtc': '2026-09-28T16:30:00Z', 'tokenCap': 720000,
               'protectedCloseoutTokens': 200000, 'admittedUnknownHolds': 1020000,
               'admittedExposureLowerBound': 1120000,
               'slots': [{**slot, 'roleId': role['roleId']} for role in inventory['roles']]}
    return root, authority, base, inventory, funding, shared, source


@contextmanager
def _r11_completed_role_fixture(self):
    # Real request serialization/body validation/private assignment I/O;
    # source reconstruction, financial prefix and per-role producer boundaries
    # are controlled. No installed host, full graph or native qualification.
    from datetime import datetime,timedelta,timezone
    m=bootstrap_r11
    root,authority,base,inventory,funding,shared_exposure,source=_r11_role_request_fixture(self)
    root=root.resolve();review=base['reviewId'];directory=m._r11_review_directory(root,review)
    source_template=copy.deepcopy(inventory['roles'][1]);inventory['roles']=inventory['roles'][:1]
    exposures={'shared-01':canonical_bytes(shared_exposure)}
    for number,scopes in enumerate([['COLLECTOR_FIRST_NATIVE'],['OBSERVER_TERMINAL'],[]],1):
        role_id=f'source-{number:02d}';exposure=copy.deepcopy(source)
        exposure['requiredIntegrationScopes']=scopes
        exposure['integrationClosureContent']={name:source['integrationClosureContent'][name] for name in scopes}
        exposures[role_id]=canonical_bytes(exposure)
        inventory['roles'].append({**source_template,'roleId':role_id,'operationId':'op-'+role_id,
            'requiredIntegrationScopes':scopes,'exposureSha256':canonical_digest(exposure)})
    now=datetime.now(timezone.utc)
    funding.update(roleInventorySha256=canonical_digest(inventory),tokenCap=1440000,protectedCloseoutTokens=400000,
        admittedUnknownHolds=1740000,admittedExposureLowerBound=1840000,
        admittedAtUtc=(now-timedelta(minutes=1)).isoformat(),absoluteDeadlineUtc=(now+timedelta(hours=1)).isoformat(),
        slots=[{**funding['slots'][0],'roleId':r['roleId']} for r in inventory['roles']])
    identity=m._r11_role_identity(authority=authority,base_raw=canonical_bytes(base),inventory_raw=canonical_bytes(inventory),funding_raw=canonical_bytes(funding))
    basis={'identity':identity,'schemas':authority['schemas'],'openingOrigin':{'fixture':'opening'}}
    catalog={'selected':{'catalogWindowTokens':1000000},'evidenceSha256':'c'*64}
    fit={'completeEnvelopeFit':True,'sourceFreshnessQualified':True,'catalogEvidenceSha256':catalog['evidenceSha256'],'coordinatorHeadSha256':'d'*64}
    rebuilt={'candidate':{'status':'ROLE_RECONSTRUCTION_UNQUALIFIED',
        'roleBasis':{'baseRaw':canonical_bytes(base),'roleInventoryRaw':canonical_bytes(inventory),'roleExposureRaw':exposures},
        'sourceBasisSubject':{'parentVerdict':'FAIL','callExpansionSha256':'e'*64},'sourceProjection':{'coverageUnionSha256':'f'*64}}}
    cost={'fundingAdmitted':True,'rolePrefixesAnchored':True,'allRolesSettled':True,'unreservedRoleIds':[],
          'reservations':[],'settlements':[],'fundingOrigin':{'currentHeadSha256':'d'*64},'costStatus':'UNAVAILABLE','actualModelTokens':None}
    sealed={};producers={};body_raws={};accepted=None
    with patch.object(m,'_r11_role_authority',new=lambda root:copy.deepcopy(authority)):
        for index,role in enumerate(inventory['roles']):
            role_id=role['roleId'];binding={'operationId':role['operationId'],'shardId':role_id,'threadId':'thread-'+role_id,
                'binarySha256':'a'*64,'transportSourceSha256':'b'*64}
            candidate=m._r11_role_request_candidate(root,base_raw=canonical_bytes(base),inventory_raw=canonical_bytes(inventory),funding_raw=canonical_bytes(funding),
                role_id=role_id,exposure_raw=exposures[role_id],thread_id=binding['threadId'],model_context_window=1000000,
                shared_evidence_raw=None if accepted is None else accepted['evidenceRaw'],shared_body_raw=None if accepted is None else accepted['bodyRaw'])
            sealed[role_id]={**candidate,'seal':{'schemaVersion':'alk-r11-role-request-seal.v2-origin','binding':binding},'sealSha256':canonical_digest(binding)}
            subject=candidate['subject'];body={'schemaVersion':'alk-route-bootstrap-reviewer-body.v6-r11','verdict':'PASS',
                'phase':'PRE_WS01','rb11RuntimeStatus':'NOT_RUN','subjectSha256':canonical_digest(subject),
                **{k:subject[k] for k in ('baseSha256','roleInventorySha256','fundingBatchSha256','roleId','roleKind','exposureSha256','sharedEvidenceSha256')},
                'sharedContentSeenByThisRole':index==0,'assignedContentComplete':True,'inheritedCoverageAccepted':True,'interactionScopeComplete':True,
                'approvedIntegrationScopes':role['requiredIntegrationScopes'],'closedParentFindingIds':[],'findings':[],'reviewText':'NO_CURRENT_FINDINGS'}
            raw=canonical_bytes(body);body_raws[role_id]=raw;m._write(root,root/m._R11_REVIEW_ROOT/'shards'/role_id/'review-body.raw',body)
            reservation={'roleId':role_id,'binding':binding,'requestSha256':candidate['requestSha256'],'subjectSha256':canonical_digest(subject),
                'sharedEvidenceSha256':subject['sharedEvidenceSha256']}
            settled={'binding':binding,'reservationSha256':canonical_digest(reservation),'worker':{'state':'WORKER_PROCESS_FINISHED','evidenceSha256':{'terminal.json':'1'*64}}}
            cost['reservations'].append(reservation);cost['settlements'].append(settled)
            match={'subjectSha256':canonical_digest(subject),'bodySha256':hashlib.sha256(raw).hexdigest(),'requestSha256':candidate['requestSha256'],
                'roleId':role_id,'roleKind':role['roleKind'],'threadId':binding['threadId'],'approvedIntegrationScopes':role['requiredIntegrationScopes'],'closedParentFindingIds':[]}
            producer={'producerQualified':True,'binding':binding,'requestSha256':candidate['requestSha256'],
                'costReservationSha256':canonical_digest(reservation),'costSettlementSha256':canonical_digest(settled),
                'workerEvidenceSha256':canonical_digest(settled['worker']['evidenceSha256']), 'transport':{'transport':{'bodyReadMatch':match}},'firstNativeBootstrapEligible':False}
            producers[role_id]=producer
            if index==0:
                receipt={key:'2'*64 for key in authority['schemas']['sharedEvidence']['properties']}
                receipt.update(schemaVersion='alk-r11-shared-evidence.v1',status='SHARED_ACCEPTED',reviewId=review,
                    **{key:identity[key] for key in ('baseSha256','roleInventorySha256','fundingBatchSha256')},
                    subjectSha256=canonical_digest(subject),bodyRawSha256=hashlib.sha256(raw).hexdigest(),binding=binding,firstNativeBootstrapEligible=False)
                accepted={'sharedEvidenceAccepted':True,'evidenceRaw':canonical_bytes(receipt),'receipt':receipt,'bodyRaw':raw,'producer':producer}
        with ExitStack() as stack:
            for name,value in [('_r11_review_cost_basis',basis),('read_source_review_cost',cost),('read_source_review_catalog',catalog),
                ('read_source_review_envelope_fit',fit),('reconstruct_source_review',rebuilt),('collect_source_review_shared',accepted)]:
                stack.enter_context(patch.object(m,name,new=lambda *a,_value=value,**kw:copy.deepcopy(_value)))
            stack.enter_context(patch.object(m,'read_source_review_request',new=lambda *a,role_id,**kw:copy.deepcopy(sealed[role_id])))
            stack.enter_context(patch.object(m,'collect_source_review_producer',new=lambda *a,shard_id,**kw:copy.deepcopy(producers[shard_id])))
            yield SimpleNamespace(root=root,authority=authority,base=base,inventory=inventory,funding=funding,shared_exposure=shared_exposure,source=source,review=review,directory=directory,exposures=exposures,identity=identity,basis=basis,catalog=catalog,fit=fit,rebuilt=rebuilt,cost=cost,sealed=sealed,producers=producers,body_raws=body_raws,accepted=accepted)
    self.assertEqual(m._r11_role_authority(root),authority)


@contextmanager
def _r11_v6_composite_fixture(self,root,authority,basis,cost,fit,sealed):
    # Actual v6 all-role composition/publication/read/install and private
    # inventory. The existing assignment fixture controls source/catalog,
    # funding and individual producers; coordinator ancestry is also captured.
    # No host/model/native process or complete live financial proof.
    m=bootstrap_r11;identity=basis['identity'];review=identity['base']['reviewId'];directory=m._r11_review_directory(root,review)
    role_ids=[row['roleId'] for row in identity['inventory']['roles']]
    opening='3'*64;original='d'*64;later='4'*64
    basis['openingOrigin']['coordinatorHeadSha256']=opening
    steps=[{'headSha256':canonical_digest([role,kind]),'recordPath':role+'/'+kind+'.json'} for role in role_ids for kind in ('reservation','settlement')]
    cost.update(costChainSha256='5'*64,prefixSha256={'fixture-prefix':'6'*64},declaredUnknownHoldsAtFunding=identity['funding']['admittedUnknownHolds'],
        currentCoordinatorUnknownHolds=identity['funding']['admittedUnknownHolds'])
    cost['fundingOrigin']['costPrefix']={'steps':steps}
    chain=[original]+[row['headSha256'] for row in reversed(steps)]+[opening]
    holds={name:identity['funding']['admittedUnknownHolds'] for name in chain}
    extra={}
    def head(*a,ancestor_head_sha256=None,**kw):
        current=cost['fundingOrigin']['currentHeadSha256'];anchor=ancestor_head_sha256 or current
        if anchor not in chain:raise LifecycleError('r11-opening-ancestry','fixture ancestor absent')
        return {'headSha256':current,'ancestryHeadSha256s':chain[:chain.index(anchor)+1],
            'ancestor':{'headSha256':anchor,'head':{'unknownHolds':holds[anchor]}},**extra}
    for name,key in [('role-base.json','base'),('role-inventory.json','inventory'),('role-funding.json','funding')]:m._write(root,directory/name,identity[key])
    for name in ['role-envelope-fit.json','role-preparation.json','cost-opening.json','cost-opening-origin.json','role-funding-origin.json']:
        m._write(root,directory/name,{'fixtureBoundary':name})
    for name in ['catalog','support','role-prefix-receipts']:
        m._write(root,directory/name/'fixture.json',{'fixtureBoundary':name})
    for index,role in enumerate(role_ids):
        for prefix in ['worker-','thread-preparation-']:m._write(root,directory/(prefix+role+'.json'),{'fixtureBoundary':prefix+role})
        m._write(root,directory/'role-operations'/role/'start.json',{'fixtureBoundary':role})
        m._write(root,directory/'role-cost'/role/'reservation.json',cost['reservations'][index])
        m._write(root,directory/'role-cost'/role/'settlement.json',cost['settlements'][index])
        m._r11_write_role_request_files(root,directory/'role-requests'/role,{'request.jsonl':sealed[role]['requestRaw'],
            'seal.json':canonical_bytes(sealed[role]['seal']),'subject.json':canonical_bytes(sealed[role]['subject'])})
        m._write(root,root/m._R11_REVIEW_ROOT/'shards'/('metadata-'+role)/'fixture.json',{'fixtureBoundary':'metadata'})
    with patch.object(m,'read_coordinator_cost_head',new=head):
        yield SimpleNamespace(identity=identity,review=review,directory=directory,role_ids=role_ids,opening=opening,original=original,later=later,steps=steps,chain=chain,holds=holds,head=head,extra=extra)


@contextmanager
def _r11_fresh_metadata_fixture(self,f,c):
    """Real composite/fresh/collector joins; controlled ledger/catalog/process.

    No actual host/model process. The simulated supervisor writes raw metadata
    records that the real collector reopens; worker exit provenance is captured.
    """
    import time
    from datetime import datetime,timedelta,timezone
    from agent_lifecycle.contracts.process_execution_schemas import command_identity_hash,process_identity_hash
    m=bootstrap_r11;root=f.root;responses={};sent=[];workers={}
    for name in m._SOURCES:
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((_R11_ROOT/name).read_bytes())
    for name in m._R11_VALIDATION_ROOTS:(root/name).mkdir(parents=True,exist_ok=True)
    f.catalog.update(binaryPath='/fixture/codex');f.catalog['selected'].update(binarySha256='a'*64,model='fixture-model')
    for role,sealed in f.sealed.items():
        request=json.loads(sealed['requestRaw']);thread=sealed['seal']['binding']['threadId'];turn='turn-'+role
        body=(root/m._R11_REVIEW_ROOT/'shards'/role/'review-body.raw').read_bytes()
        response={'thread':{'id':thread,'turns':[{'id':turn,'status':'completed','error':None,'items':[
            {'id':'input','type':'userMessage','content':request['params']['input']},
            {'id':'output','type':'agentMessage','phase':'final_answer','text':body.decode()}]}]}}
        responses[thread]=response
        f.producers[role]['transport']['transport']['bodyReadMatch'].update(turnId=turn,
            stableProjectionSha256=canonical_digest(exact._single_turn_projection(response,thread_id=thread,turn_id=turn,request=request)))
    cost_path=f.directory/'support/cost.json'
    m._write(root,cost_path,{'costStatus':'UNAVAILABLE','heldUnknownTokens':f.cost['currentCoordinatorUnknownHolds'],'actualModelTokens':None})
    m.finalize_source_review_assignment(root,review_id=f.review,role_delivery=True)
    receipt=m.publish_source_review_composite(root,review_id=f.review);m.install_source_review_composite(root,review_id=f.review)
    state=root/'workflow-state.json';state.write_bytes(canonical_bytes({'runId':'run','sourceRevision':'revision','tasks':[{'id':'task','status':'RUNNING','attempt':1}]}))
    intent_path=root/m._ROOT/'run/task/1/prelaunch-intent.json'
    intent={'schemaVersion':'alk-codex-prelaunch-intent.v1','runId':'run','taskId':'task','attemptId':'1','operationId':'native-op',
        'routeId':exact.ROUTE_ID,'requestedClaim':exact.CLAIM,'sourceRevision':'revision','planDigest':f.authority['planDigest'],'lockDigest':f.authority['lockSha256'],
        'requestSha256':'c'*64,'finalPromptSha256':'d'*64,'commandIdentityHash':'e'*64,'binarySha256':'a'*64,'plannedStdinBytes':12,'hostLaunchStarted':False,
        **m.capture_attempt_authority(root,lock_path=root/'tasks/release-2-16/plan.lock.json')}
    m._write(root,intent_path,intent);m.reserve_attempt_result(root,intent_path=intent_path)
    task=m._r11_native_task(root,intent_path,state);key=canonical_digest({k:intent[k] for k in ('runId','taskId','attemptId')})[:56]
    binding={'operationId':'r11-fresh/'+key,'shardId':'fresh-'+key,'threadId':'FIRST_NATIVE_READ_ONLY',
        'binarySha256':'a'*64,'transportSourceSha256':hashlib.sha256((root/m._R11_FIXED_WORKER).read_bytes()).hexdigest()}
    now=datetime.now(timezone.utc);mono=time.monotonic_ns();timeout=120
    operation={'schemaVersion':'alk-r11-fresh-operation.v1','reviewId':f.review,'taskSha256':canonical_digest(task),'compositeSha256':canonical_digest(receipt),
        'binding':binding,'timeoutSeconds':timeout,'startedAtUtc':now.isoformat(),'absoluteDeadlineUtc':(now+timedelta(seconds=timeout)).isoformat(),
        'startedMonotonicNs':mono,'deadlineMonotonicNs':mono+timeout*1_000_000_000,'modelRequestsAuthorized':0,'retryAuthorized':False}
    current='f'*64;held=c.holds[c.original]+40000;c.chain.insert(0,current);c.holds[current]=held
    f.cost.update(currentCoordinatorUnknownHolds=held);f.cost['fundingOrigin']['currentHeadSha256']=current;f.fit['coordinatorHeadSha256']=current
    source={'status':'ADMITTED_PREAPPROVED_BY_USER','modelRequestCount':0,'freshMetadataOperation':operation,'tokenCap':40000,'unknownHoldsIncludingThisWindow':held}
    c.extra.update(source=source,head={'sourcePath':m._R11_COORDINATOR_BASE+'/r999-fixture-metadata/admission.json','sourceSha256':canonical_digest(source),'unknownHolds':held})
    def supervisor(project_root,**kw):
        path=kw['instruction_path'];value,requests=m._r11_read_fresh_input(root,path)
        self.assertEqual(kw['absolute_deadline_monotonic_ns'],operation['deadlineMonotonicNs'])
        groups=[('SESSION',canonical_bytes(binding))]
        class Wire:
            buffer=b''
            def send_bootstrap(self,row):
                sent.append(copy.deepcopy(row));raw=canonical_bytes(row)+b'\n'
                groups.extend([('SEND_PENDING',raw),('WRITE_ACCEPTED',raw),('FLUSHED',canonical_bytes({'sha256':hashlib.sha256(raw).hexdigest()}))])
            def bootstrap_reply(self,ident,thread):
                response=responses[thread] if thread else {'userAgent':'fixture'}
                groups.append(('RECEIVED_CHUNK',canonical_bytes({'id':ident,'result':response})+b'\n'));return copy.deepcopy(response)
        start=time.monotonic_ns();exchange=m._r11_fresh_exchange(Wire(),value,requests);finish=time.monotonic_ns();pid=os.getpid()
        argv=[str(Path(sys.executable).resolve(strict=True)),'-B',str(root/m._R11_FIXED_WORKER),str(path)]
        env={**os.environ,'PYTHONPATH':str(root/'src'),'PYTHONDONTWRITEBYTECODE':'1','PYTHONUNBUFFERED':'1'}
        reservation={'schemaVersion':'alk-r11-worker-reservation.v1','binding':binding,'workerPath':m._R11_FIXED_WORKER,
            'instructionPath':path.relative_to(root).as_posix(),'argv':argv,'commandIdentityHash':command_identity_hash(argv),
            'environmentSha256':canonical_digest(env),'sourceSha256':m._r11_worker_sources(root,root/m._R11_FIXED_WORKER,path),
            'timeoutSeconds':timeout,'heldUnknownTokens':held,'costStatus':'UNAVAILABLE','actualModelTokens':None,'retryAuthorized':False,
            'absoluteDeadlineMonotonicNs':operation['deadlineMonotonicNs']}
        worker={'status':'WORKER_PROCESS_FINISHED','finishedMonotonicNs':finish};workers.update(worker)
        result={'startedMonotonicNs':start,'absoluteDeadlineMonotonicNs':operation['deadlineMonotonicNs'],'deadlineMonotonicNs':operation['deadlineMonotonicNs'],
            'cleanup':{'mode':'posix-session'},'processReceipt':{'processIdentityHash':process_identity_hash(pid=pid,started_ns=start)}}
        directory=m._r11_worker_directory(root,binding);base=directory.parent
        for name,value in [('reservation.json',reservation),('process-result.json',result),('terminal.json',worker)]:m._write(root,directory/name,value)
        m._write(root,base/'host-process/launch.json',{'binding':binding,'argv':[f.catalog['binaryPath'],'app-server','--listen','stdio://'],
            'supervisorPid':pid,'processGroupId':pid,'model':f.catalog['selected']['model'],'state':'START_UNCERTAIN','retryAuthorized':False})
        m._write(root,base/'host-process/finished.json',{**exchange,'hostPid':pid+1,'hostExitCode':0,'supervisorPid':pid,'processGroupId':pid,'binarySha256':binding['binarySha256']})
        m._write(root,base/'host-wire/exchange.json',exchange);sequence=0
        for kind,raw in groups:
            for offset in range(0,len(raw),32768):
                m._write(root,base/'host-wire'/f'{sequence:08d}.json',{'sequence':sequence,'monotonicNs':start,'kind':kind,'offset':offset,'bytes':len(raw),'rawHex':raw[offset:offset+32768].hex()});sequence+=1
        return worker
    with patch.object(m,'__file__',str(root/m._R11_FIXED_WORKER)),patch.object(m,'_supervise_source_review_worker',new=supervisor), \
         patch.object(m,'read_source_review_worker',new=lambda *a,**kw:copy.deepcopy(workers)):
        yield SimpleNamespace(root=root,intent_path=intent_path,state=state,receipt=receipt,binding=binding,held=held,cost_path=cost_path,sent=sent,
            args={'intent_path':intent_path,'state_path':state,'plan_digest':intent['planDigest'],'lock_sha256':intent['lockDigest'],'selected_binary_sha256':intent['binarySha256']})


class R11BootstrapTests(unittest.TestCase):
    @_retired_r11_positive
    def test_parent_fail_and_all_shards_join_only_after_exact_closure(self) -> None:
        m=bootstrap_r11
        for close_parent in (False,True):
            with _r11_completed_role_fixture(self) as f, _r11_v6_composite_fixture(self,f.root,f.authority,f.basis,f.cost,f.fit,f.sealed) as c:
                parent_before=f.shared_exposure['parentReviewRaw'];self.assertEqual(json.loads(parent_before)['verdict'],'FAIL')
                last=f.cost['settlements'].pop()
                with self.subTest(parentClosure='incomplete-role-denies-assignment',close_parent=close_parent),self.assertRaises(LifecycleError):
                    m.finalize_source_review_assignment(f.root,review_id=f.review,role_delivery=True)
                self.assertFalse((f.directory/'assignment.json').exists());f.cost['settlements'].append(last)
                m.finalize_source_review_assignment(f.root,review_id=f.review,role_delivery=True)
                body=f.root/m._R11_REVIEW_ROOT/'shards/source-02/review-body.raw';original=body.read_bytes()
                if not close_parent:
                    changed=json.loads(original);changed['approvedIntegrationScopes']=[];body.write_bytes(canonical_bytes(changed))
                receipt=m.publish_source_review_composite(f.root,review_id=f.review)
                with self.subTest(parentClosure='all-roles-and-both-primary-approvals-required',close_parent=close_parent):
                    self.assertEqual(receipt['collectorStatus'],'VERIFIED' if close_parent else 'DENY');self.assertFalse(receipt['firstNativeBootstrapEligible'])
                    terminal=json.loads((f.directory/'collector/qualification.json').read_bytes())
                    self.assertEqual(terminal['heldUnknownTokens'],f.funding['admittedUnknownHolds']);self.assertIsNone(terminal['actualModelTokens'])
                    self.assertEqual(f.shared_exposure['parentReviewRaw'],parent_before)
                    if close_parent:
                        self.assertEqual(receipt['closedParentFindingIds'],['RB-OBSERVER-TIMEOUT-01']);self.assertEqual(receipt['parentVerdict'],'FAIL')
                        assignment=json.loads((f.directory/'assignment.json').read_bytes());self.assertEqual([r['roleId'] for r in assignment['roles']],c.role_ids)
                        self.assertEqual(len(assignment['roles']),4);self.assertEqual(m.read_source_review_composite(f.root,review_id=f.review),receipt)
                    else:
                        self.assertEqual(receipt['unknownHoldsReleased'],0)
                        self.assertEqual(m.read_source_review_composite(f.root,review_id=f.review),receipt)
                if close_parent:
                    body.unlink()
                    with self.subTest(parentClosure='earlier-role-proof-removed'),self.assertRaises((LifecycleError,OSError)):
                        m.read_source_review_composite(f.root,review_id=f.review)
                else:
                    body.write_bytes(original)
                    with self.subTest(parentClosure='late-proof-cannot-upgrade-refusal'):
                        self.assertEqual(m.read_source_review_composite(f.root,review_id=f.review),receipt)
                        with self.assertRaises(FileExistsError):m.publish_source_review_composite(f.root,review_id=f.review)
                        with self.assertRaises(LifecycleError):m.install_source_review_composite(f.root,review_id=f.review)

    @unittest.skip(
        "Historical R11 protocol assertion replaced by ordinary snapshot/cost cases in ORDINARY-AUDIT-CASES.json"
    )
    def test_first_native_fresh_reread_refuses_changed_source_or_cost(self) -> None:
        m=bootstrap_r11
        with _r11_completed_role_fixture(self) as f, _r11_v6_composite_fixture(self,f.root,f.authority,f.basis,f.cost,f.fit,f.sealed) as c, \
             _r11_fresh_metadata_fixture(self,f,c) as current:
            audit=exact.require_bootstrap_audit(f.root,**current.args)
            with self.subTest(freshMigration='real-installed-composite-raw-all-role-metadata-and-current-gate'):
                self.assertTrue(audit['firstNativeBootstrapEligible']);self.assertFalse(m.read_source_review_composite(f.root,review_id=f.review)['firstNativeBootstrapEligible'])
                self.assertEqual([q['method'] for q in current.sent],['initialize','initialized']+['thread/read']*4)
                self.assertEqual([q['params']['threadId'] for q in current.sent if q['method']=='thread/read'],[f.sealed[r]['seal']['binding']['threadId'] for r in c.role_ids])
                m.verify_source_review_fresh_gate(f.root,audit=audit,intent_path=current.intent_path)
                self.assertEqual(audit['heldUnknownTokens'],current.held);self.assertEqual(audit['costStatus'],'UNAVAILABLE')
                self.assertIsNone(audit['actualModelTokens']);self.assertEqual(audit['modelRequestsSent'],0)
            paths={'source':f.root/m._R11_FIXED_WORKER,'cost':current.cost_path}
            for mutation,path in paths.items():
                original=path.read_bytes()
                try:
                    if mutation=='source':path.write_bytes(original+b'\n# changed after fresh read\n')
                    else:
                        changed=json.loads(original);changed['heldUnknownTokens']=0;path.write_bytes(canonical_bytes(changed))
                    with self.subTest(freshMigration='post-gate-change',mutation=mutation),self.assertRaises(LifecycleError):
                        m.verify_source_review_fresh_gate(f.root,audit=audit,intent_path=current.intent_path)
                finally:path.write_bytes(original)
            with self.subTest(freshMigration='no-native-consumption-or-extra-model-request'):
                self.assertFalse(current.intent_path.with_name('attempt-result-dispatched.json').exists())
                self.assertEqual(len(current.sent),6)



# Regression for implicit package/submodule source dependency ownership.
_R411_PACKAGE = 'src/agent_lifecycle/graph_fixture/__init__.py'
_R411_CHILD = 'src/agent_lifecycle/graph_fixture/child.py'
_R411_ENTRY = 'src/agent_lifecycle/entry.py'

class ImplicitSubmoduleDependencyTests(unittest.TestCase):
    def collect(self, *, package='"""package"""\n', child='def first():\n return 1\ndef second():\n return 2\n',
                entry='from agent_lifecycle.graph_fixture import child\ndef consume(value):\n return value\ndef run():\n return consume(child)\n', extra=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = {_R411_PACKAGE: package, _R411_ENTRY: entry, 'src/agent_lifecycle/__init__.py': '"""root"""\n'}
            if child is not None:
                data[_R411_CHILD] = child
            data.update(extra or {})
            for name, content in data.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            raw = (root / _R411_ENTRY).read_bytes()
            partition = {'partitionSha256': 'a' * 64, 'rows': [{'path': _R411_ENTRY, 'partition': 'C',
                'beforeExists': False, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}]}
            with patch.object(source_review_inputs, 'collect_source_partition', return_value=partition), patch.object(
                    source_review_inputs, '_r11_source_inputs', return_value=({'requiredIntegrationSelectors': {}}, {}, {})):
                deps = bootstrap_r11.collect_source_dependencies(root, partition=partition,
                    parent_inventory=b'fixture', parent_selection=b'fixture', parent_sources={})
            sources = {('CURRENT', row['path']): (root / row['path']).read_bytes() for row in deps['files']}
            pairs = bootstrap_r11._r11_interaction_requirements(sources, deps)
            return deps, sources, pairs

    def test_implicit_module_preserves_caller_to_every_child_unit(self):
        deps, sources, pairs = self.collect()
        self.assertIn([_R411_ENTRY, 'run', _R411_CHILD, '*'], deps['edges'])
        self.assertIn([_R411_ENTRY, 'run', _R411_PACKAGE, '@header'], deps['edges'])
        self.assertFalse(any(edge[0:2] == [_R411_PACKAGE, 'child'] or edge[2:4] == [_R411_PACKAGE, 'child'] for edge in deps['edges']))
        caller = bootstrap_r11._r11_python_index(sources['CURRENT', _R411_ENTRY], _R411_ENTRY)['bindings']['run']
        targets = bootstrap_r11._r11_python_index(sources['CURRENT', _R411_CHILD], _R411_CHILD)['units']
        for unit in targets:
            self.assertTrue(any(bootstrap_r11._r11_coverage_contains(pair, ('CURRENT', _R411_ENTRY), [(caller['start'], caller['end'])])
                and bootstrap_r11._r11_coverage_contains(pair, ('CURRENT', _R411_CHILD), [(unit['start'], unit['end'])]) for pair in pairs))
        self.assertFalse(deps['dependencyClosureComplete'])
        self.assertFalse(deps['firstNativeBootstrapEligible'])

    def test_explicit_binding_keeps_static_owner(self):
        deps, _, _ = self.collect(package='child = 42\n')
        self.assertIn([_R411_ENTRY, 'run', _R411_PACKAGE, 'child'], deps['edges'])
        self.assertNotIn(_R411_CHILD, [row['path'] for row in deps['files']])

    def test_explicit_reexport_keeps_its_real_import_owner(self):
        target = 'src/agent_lifecycle/graph_fixture/other.py'
        deps, _, _ = self.collect(package='from .other import value as child\n', extra={target: 'value = 7\n'})
        self.assertIn([_R411_ENTRY, 'run', _R411_PACKAGE, 'child'], deps['edges'])
        self.assertIn([_R411_PACKAGE, 'child', target, 'value'], deps['edges'])
        self.assertNotIn(_R411_CHILD, [row['path'] for row in deps['files']])

    def test_package_submodule_and_local_alias_are_resolved(self):
        subpkg = 'src/agent_lifecycle/graph_fixture/child/__init__.py'
        deps, _, _ = self.collect(child=None, extra={subpkg: 'def child_value():\n return 3\n'},
            entry='def run():\n from agent_lifecycle.graph_fixture import child as local\n return local\n')
        self.assertIn([_R411_ENTRY, 'run', subpkg, '*'], deps['edges'])
        self.assertIn([_R411_ENTRY, 'run', _R411_PACKAGE, '@header'], deps['edges'])

    def test_relative_implicit_import_is_resolved(self):
        deps, _, _ = self.collect(entry='from .graph_fixture import child as local\ndef run():\n return local\n')
        self.assertIn([_R411_ENTRY, 'run', _R411_CHILD, '*'], deps['edges'])

    def test_missing_ambiguous_and_dynamic_targets_refuse(self):
        variants = [
            {'child': None},
            {'extra': {'src/agent_lifecycle/graph_fixture/child/__init__.py': '"""ambiguous"""\n'}},
            {'package': 'def __getattr__(name):\n return object()\n'},
        ]
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaises(LifecycleError):
                self.collect(**variant)

    def _check_module_file_metadata(self):
        entries=[
            'import agent_lifecycle.graph_fixture.child as module\ndef run():\n return module.__file__\n',
            'from agent_lifecycle.graph_fixture import child as module\ndef run():\n return module.__file__\n',
        ]
        for number,entry in enumerate(entries):
            with self.subTest(moduleMetadata='whole-namespace-and-every-pair',importForm=number):
                deps,sources,pairs=self.collect(entry=entry)
                self.assertIn([_R411_ENTRY,'run',_R411_CHILD,'*'],deps['edges'])
                self.assertFalse(any('__file__' in (r[1],r[3]) for r in deps['edges']))
                caller=bootstrap_r11._r11_python_index(sources['CURRENT',_R411_ENTRY],_R411_ENTRY)['bindings']['run']
                for unit in bootstrap_r11._r11_python_index(sources['CURRENT',_R411_CHILD],_R411_CHILD)['units']:
                    self.assertTrue(any(bootstrap_r11._r11_coverage_contains(pair,('CURRENT',_R411_ENTRY),[(caller['start'],caller['end'])])
                        and bootstrap_r11._r11_coverage_contains(pair,('CURRENT',_R411_CHILD),[(unit['start'],unit['end'])]) for pair in pairs))
                self.assertFalse(deps['dependencyClosureComplete']);self.assertFalse(deps['firstNativeBootstrapEligible'])
        with self.subTest(moduleMetadata='explicit-assignment-keeps-physical-owner'):
            deps,_,_=self.collect(entry=entries[0],child="__file__ = 'overridden'\ndef untouched():\n return 1\n")
            self.assertIn([_R411_ENTRY,'run',_R411_CHILD,'__file__'],deps['edges'])
            self.assertNotIn([_R411_ENTRY,'run',_R411_CHILD,'*'],deps['edges'])
        with self.subTest(moduleMetadata='reexport-keeps-import-and-target-owner'):
            target='src/agent_lifecycle/graph_fixture/other.py'
            deps,_,_=self.collect(entry=entries[0],child='from .other import marker as __file__\n',extra={target:"marker = 'other'\n"})
            self.assertIn([_R411_ENTRY,'run',_R411_CHILD,'__file__'],deps['edges'])
            self.assertIn([_R411_CHILD,'__file__',target,'marker'],deps['edges'])
            self.assertNotIn([_R411_ENTRY,'run',_R411_CHILD,'*'],deps['edges'])
        with self.subTest(moduleMetadata='arbitrary-missing-name-still-refuses'):
            with self.assertRaises(LifecycleError) as failure:self.collect(entry=entries[0].replace('__file__','__unknown__'))
            self.assertEqual(failure.exception.code,'r11-dependency-selector')
        with self.subTest(moduleMetadata='import-effects-and-dynamic-logic-are-source-not-executed'):
            child="raise RuntimeError('must not execute')\ndef __getattr__(name):\n return object()\ndef marker():\n return 1\n"
            deps,sources,pairs=self.collect(entry=entries[0],child=child)
            self.assertIn([_R411_ENTRY,'run',_R411_CHILD,'*'],deps['edges'])
            row=next(r for r in deps['files'] if r['path']==_R411_CHILD)
            self.assertEqual(bootstrap_r11._r11_ranges([(r['start'],r['end']) for r in row['ranges']]),[(0,len(child.encode()))])
            self.assertTrue(deps['callsRequiringInteractionReview']);self.assertFalse(deps['dependencyClosureComplete'])
        with self.subTest(moduleMetadata='empty-module-does-not-invent-a-definition'):
            deps,_,_=self.collect(entry=entries[0],child='')
            self.assertIn([_R411_ENTRY,'run',_R411_CHILD,'*'],deps['edges'])
            row=next(r for r in deps['files'] if r['path']==_R411_CHILD)
            self.assertEqual(row['bytes'],0);self.assertEqual(row['ranges'],[])

    def test_direct_module_and_physical_imports_stay_supported(self):
        self._check_module_file_metadata()
        deps, _, pairs = self.collect(entry='import agent_lifecycle.graph_fixture.child as module\ndef run():\n return module\n')
        self.assertIn([_R411_ENTRY, 'run', _R411_CHILD, '*'], deps['edges'])
        self.assertTrue(pairs)


class RoleProjectionContractTests(unittest.TestCase):
    """Role-local proofs only; host/content/funding/composite gates remain separate."""

    def _check_generic_role_schema_values(self):
        strict = bootstrap_r11._r11_role_schema_matches
        cases = [
            (True, {'type': 'integer', 'enum': [1]}, False),
            (1, {'type': 'integer', 'enum': [1]}, True),
            (1.0, {'type': 'integer'}, False),
            ('a' * 64 + '\n', {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}, False),
            ('a' * 64, {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}, True),
            ('ё' * 129, {'type': 'string', 'maxLength': 256}, False),
            ('ё' * 128, {'type': 'string', 'maxLength': 256}, True),
            ('2028-02-29T12:00:00Z', {'type': 'string', 'format': 'date-time'}, True),
            ('2026-02-29T12:00:00Z', {'type': 'string', 'format': 'date-time'}, False),
            ('2028-02-29T12:00:00+03:00', {'type': 'string', 'format': 'date-time'}, False),
            ('20280229T120000Z', {'type': 'string', 'format': 'date-time'}, False),
            ({}, {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}, True),
            ({'extra': 1}, {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}, False),
            ({}, {'type': 'object', 'properties': {'id': {'type': 'string'}}, 'required': ['id'], 'additionalProperties': False}, False),
            ('a', {'type': 'string', 'unimplementedConstraint': True}, False),
        ]
        for value, schema, expected in cases:
            with self.subTest(value=value, schema=schema):
                self.assertIs(strict(value, schema), expected)

    def _check_literal_role_source_fixture(self):
        # Full literal code survives rendering, including non-ASCII bytes.
        # Complete AST units and canonical extents are independently checked.
        path = 'src/agent_lifecycle/role_fixture.py'
        raw = 'def first():\n    return "ёж"\n\ndef second():\n    return first()\n'.encode()
        key = ('CURRENT', path)
        sources = {key: raw}
        rows = bootstrap_r11._r11_coverage_rows(sources, {key: [(0, len(raw))]})
        parts = bootstrap_r11._r11_role_source_content(sources, rows)
        self.assertEqual(parts, [{'extent': rows[0], 'content': raw.decode()}])
        self.assertEqual(parts[0]['content'].encode(), raw)
        partial = bootstrap_r11._r11_coverage_rows(sources, {key: [(0, raw.index(b'    return'))]})
        split_utf8 = bootstrap_r11._r11_coverage_rows(sources, {key: [(0, raw.index('ё'.encode()) + 1)]})
        bad_hash = copy.deepcopy(rows); bad_hash[0]['sha256'] = '0' * 64
        foreign = copy.deepcopy(rows); foreign[0]['path'] = 'src/foreign.py'
        bad_version = copy.deepcopy(rows); bad_version[0]['version'] = []
        negative = copy.deepcopy(rows); negative[0]['start'] = -1
        for variant in (rows + rows, partial, split_utf8, bad_hash, foreign, bad_version, negative):
            with self.subTest(sourceMutation=variant):
                with self.assertRaises(LifecycleError):
                    bootstrap_r11._r11_role_source_content(sources, variant)
        data = {('CURRENT', 'policy/role.json'): b'{"role":1}\n'}
        partial_data = bootstrap_r11._r11_coverage_rows(data, {next(iter(data)): [(0, 2)]})
        with self.assertRaises(LifecycleError):
            bootstrap_r11._r11_role_source_content(data, partial_data)

        return parts, rows

    def test_generic_role_schema_and_literal_extents_remain_unconditional(self):
        self._check_generic_role_schema_values()
        self._check_literal_role_source_fixture()

    @_retired_r11_positive
    def test_shared_source_role_exposure_is_exact(self):
        self._check_role_reconstruction()
        # Real locked package and raw schema reads, with isolated copies for
        # corruption cases. No coordinator work archive or host fixture needed.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = root / 'tasks/release-2-16'
            shutil.copytree(Path(__file__).parents[2] / 'tasks/release-2-16', plan)
            authority = bootstrap_r11._r11_role_authority(root)
            self.assertEqual(authority['status'], 'ROLE_AUTHORITY_MATCHED')
            self.assertFalse(authority['firstNativeBootstrapEligible'])
            self.assertEqual(len(authority['schemas']), 10)
            schemas = authority['schemas']
            self._check_role_material_authority(root, authority)
            for name in ('r69q-role-contract.json', 'REVIEWER-BODY-v6-R11.schema.json'):
                with self.subTest(authorityMutation=name):
                    path = plan / name
                    raw = path.read_bytes()
                    try:
                        path.write_bytes(raw + b' ')
                        with self.assertRaises(LifecycleError):
                            bootstrap_r11._r11_role_authority(root)
                    finally:
                        path.write_bytes(raw)

            # Contract value boundaries: unknown keywords cannot quietly weaken
            # a validator; bool cannot pass integer1; string caps count UTF-8.
            strict = bootstrap_r11._r11_role_schema_matches
            cases = [
                (720000, schemas['fundingBatch']['properties']['tokenCap'], True),
                (720001, schemas['fundingBatch']['properties']['tokenCap'], False),
                (11880001, schemas['fundingBatch']['properties']['tokenCap'], False),
                (['OBSERVER_TERMINAL', 'OBSERVER_TERMINAL'], schemas['roleSubject']['properties']['requiredIntegrationScopes'], False),
                (None, schemas['roleSubject']['properties']['sharedEvidenceSha256'], True),
                ([], schemas['reviewerBody']['properties']['closedParentFindingIds'], True),
                (['RB-OBSERVER-TIMEOUT-01'], schemas['reviewerBody']['properties']['closedParentFindingIds'], False),
            ]
            for value, schema, expected in cases:
                with self.subTest(value=value, schema=schema):
                    self.assertIs(strict(value, schema), expected)

            parts, rows = self._check_literal_role_source_fixture()

            subject = {'schemaVersion': 'alk-r11-role-subject.v1', 'reviewId': 'review-local',
                       'baseSha256': 'a' * 64, 'roleInventorySha256': 'b' * 64,
                       'fundingBatchSha256': 'c' * 64, 'slotSha256': 'd' * 64,
                       'roleId': 'source-01', 'roleKind': 'SOURCE',
                       'exposureSha256': canonical_digest(parts),
                       'sourceRangeSha256': canonical_digest(rows),
                       'callProjectionSha256': canonical_digest([]),
                       'staticPairAssignmentSha256': canonical_digest([]),
                       'requiredIntegrationScopes': [], 'sharedEvidenceSha256': 'e' * 64,
                       'phase': 'PRE_WS01', 'rb11RuntimeStatus': 'NOT_RUN'}
            def body_for(expected):
                value = {key: expected[key] for key in ('baseSha256', 'roleInventorySha256',
                         'fundingBatchSha256', 'roleId', 'roleKind', 'exposureSha256', 'sharedEvidenceSha256')}
                return {'schemaVersion': 'alk-route-bootstrap-reviewer-body.v6-r11',
                        **value, 'subjectSha256': canonical_digest(expected), 'verdict': 'PASS',
                        'phase': 'PRE_WS01', 'rb11RuntimeStatus': 'NOT_RUN',
                        'sharedContentSeenByThisRole': expected['roleKind'] == 'SHARED',
                        'assignedContentComplete': True, 'inheritedCoverageAccepted': True,
                        'interactionScopeComplete': True, 'reviewText': 'NO_CURRENT_FINDINGS',
                        'findings': [], 'approvedIntegrationScopes': expected['requiredIntegrationScopes'],
                        'closedParentFindingIds': []}
            body = body_for(subject)
            matched = bootstrap_r11._r11_role_body(canonical_bytes(body), subject=subject, schemas=schemas)
            self.assertEqual(matched['status'], 'ROLE_BODY_MATCHED_UNQUALIFIED')
            self.assertFalse(matched['sharedEvidenceAccepted'])
            self.assertFalse(matched['firstNativeBootstrapEligible'])
            self.assertEqual(matched['closedParentFindingIds'], [])
            mutations = {
                'extra': {'unseenSupport': True}, 'falseSharedExposure': {'sharedContentSeenByThisRole': True},
                'foreignBase': {'baseSha256': 'f' * 64}, 'foreignRole': {'roleId': 'source-02'},
                'closureEscalation': {'closedParentFindingIds': ['RB-OBSERVER-TIMEOUT-01']},
                'scopeEscalation': {'approvedIntegrationScopes': ['OBSERVER_TERMINAL']},
                'incomplete': {'assignedContentComplete': False}, 'nonBoolean': {'assignedContentComplete': 1},
                'failed': {'verdict': 'FAIL'}, 'proseInsteadOfClean': {'reviewText': 'Looks fine.'},
                'extraNewline': {'reviewText': 'NO_CURRENT_FINDINGS\n\n'},
                'rawFinding': {'reviewText': 'NO_CURRENT_FINDINGS\n[P2] omitted defect'},
                'missingShared': {'sharedEvidenceSha256': None},
            }
            for name, delta in mutations.items():
                with self.subTest(bodyMutation=name):
                    with self.assertRaises(LifecycleError):
                        bootstrap_r11._r11_role_body(canonical_bytes({**body, **delta}), subject=subject, schemas=schemas)
            duplicate = canonical_bytes(body)[:-1] + b',"verdict":"PASS"}'
            with self.assertRaises(LifecycleError):
                bootstrap_r11._r11_role_body(duplicate, subject=subject, schemas=schemas)
            missing = dict(body); missing.pop('fundingBatchSha256')
            with self.assertRaises(LifecycleError):
                bootstrap_r11._r11_role_body(canonical_bytes(missing), subject=subject, schemas=schemas)
            missing_shared_subject = {**subject, 'sharedEvidenceSha256': None}
            with self.assertRaises(LifecycleError):
                bootstrap_r11._r11_role_body(canonical_bytes(body_for(missing_shared_subject)),
                                            subject=missing_shared_subject, schemas=schemas)
            for scopes in (['OBSERVER_TERMINAL'], ['COLLECTOR_FIRST_NATIVE', 'OBSERVER_TERMINAL']):
                primary = {**subject, 'requiredIntegrationScopes': scopes}
                receipt = bootstrap_r11._r11_role_body(canonical_bytes(body_for(primary)), subject=primary, schemas=schemas)
                self.assertEqual(receipt['approvedIntegrationScopes'], scopes)
                self.assertEqual(receipt['closedParentFindingIds'], [])
                self.assertFalse(receipt['firstNativeBootstrapEligible'])
            shared = {**subject, 'roleId': 'shared-01', 'roleKind': 'SHARED', 'sharedEvidenceSha256': None,
                      'sourceRangeSha256': canonical_digest([])}
            shared_body = body_for(shared)
            result = bootstrap_r11._r11_role_body(canonical_bytes(shared_body), subject=shared, schemas=schemas)
            self.assertFalse(result['sharedEvidenceAccepted'])
            for variant in ({**shared, 'sharedEvidenceSha256': 'e' * 64},
                            {**shared, 'requiredIntegrationScopes': ['OBSERVER_TERMINAL']},
                            {**shared, 'roleId': 'source-01'},
                            {**shared, 'sourceRangeSha256': 'f' * 64},
                            {**shared, 'callProjectionSha256': 'f' * 64},
                            {**shared, 'staticPairAssignmentSha256': 'f' * 64}):
                with self.subTest(sharedMutation=variant), self.assertRaises(LifecycleError):
                    bootstrap_r11._r11_role_body(canonical_bytes(body_for(variant)), subject=variant, schemas=schemas)
            oversized = canonical_bytes(shared_body)
            oversized += b' ' * (4097 - len(oversized))
            with self.assertRaises(LifecycleError):
                bootstrap_r11._r11_role_body(oversized, subject=shared, schemas=schemas)

    def test_grouped_calls_expand_all_calls_on_lines(self):
        name = 'src/call_fixture.py'
        raw = ('# UTF-8 before AST columns: ё\n'
               'def local(x):\n    return x\n'
               'def caller(cb):\n'
               '    ё = "значение"; return cb(local(cb(1))) + cb(1)\n'
               'def later(cb):\n    return cb(2)\n').encode()
        sources = {('CURRENT', name): raw, ('PARENT', name): raw}
        original = [[name, 'caller', 5, 'cb'], [name, 'later', 7, 'cb']]
        index = bootstrap_r11._r11_role_call_index(sources, {'callsRequiringInteractionReview': original})
        unit = bootstrap_r11._r11_python_index(raw, name)['bindings']['caller']
        selected = {('CURRENT', name): [(unit['start'], unit['end'])]}
        expected = [{'path': name, 'allCallsOnLines': [5]}]
        result = bootstrap_r11._r11_role_project_calls(index, selected, supplied=expected)
        self.assertEqual(result['originalTuples'], original[:1])
        # One deduplicated graph tuple expands to three cb calls plus the static
        # local call on that same source line. Original UTF-8 offsets are bytes.
        self.assertEqual(len(result['allAstCalls']), 4)
        self.assertEqual(sorted(row['callee'] for row in result['allAstCalls']), ['cb', 'cb', 'cb', 'local'])
        actual_slices = [raw[row['start']:row['end']] for row in result['allAstCalls']]
        self.assertEqual(actual_slices, [b'cb(local(cb(1)))', b'local(cb(1))', b'cb(1)', b'cb(1)'])
        for row, content in zip(result['allAstCalls'], actual_slices):
            self.assertEqual(row['sha256'], hashlib.sha256(content).hexdigest())
        self.assertFalse(result['firstNativeBootstrapEligible'])
        with self.subTest(kind='parent-only-does-not-claim-current-calls'):
            parent = bootstrap_r11._r11_role_project_calls(index, {('PARENT', name): [(0, len(raw))]}, supplied=[])
            self.assertEqual(parent['originalTuples'], [])
        with self.subTest(kind='all-selected-owners'):
            whole = bootstrap_r11._r11_role_project_calls(index, {('CURRENT', name): [(0, len(raw))]})
            self.assertEqual(whole['groups'], [{'path': name, 'allCallsOnLines': [5, 7]}])
            self.assertEqual(whole['originalTuples'], original)
            self.assertEqual(len(whole['allAstCalls']), 5)
        variants = [[], expected * 2, [{'path': name, 'allCallsOnLines': []}],
                    [{'path': name, 'allCallsOnLines': [5, 5]}],
                    [{'path': name, 'allCallsOnLines': [7]}],
                    [{'path': name, 'allCallsOnLines': [5, 7]}],
                    [{'path': name, 'allCallsOnLines': [0]}],
                    [{'path': name, 'allCallsOnLines': [4]}],
                    [{'path': name, 'allCallsOnLines': [True]}],
                    [{'path': name, 'allCallsOnLines': [5.0]}],
                    [{'path': name, 'allCallsOnLines': [5], 'extra': True}],
                    [{'path': 'src/foreign.py', 'allCallsOnLines': [5]}]]
        for supplied in variants:
            with self.subTest(invalidGroups=supplied), self.assertRaises(LifecycleError):
                bootstrap_r11._r11_role_project_calls(index, selected, supplied=supplied)
        with self.subTest(kind='partial-caller'), self.assertRaises(LifecycleError):
            bootstrap_r11._r11_role_project_calls(index, {('CURRENT', name): [(unit['start'] + 1, unit['end'])]})
        bad_graphs = [original[::-1], original + original[:1], [[name, 'caller', 5, 'missing']],
                      [[name, 'local', 5, 'cb']], [[name, 'caller', 4, 'cb']],
                      [[name, 'caller', True, 'cb']], [['src/foreign.py', 'caller', 5, 'cb']],
                      [[name, 'caller', 5]], [[name, '*', 5, 'cb']]]
        for graph in bad_graphs:
            with self.subTest(invalidOriginal=graph), self.assertRaises(LifecycleError):
                bootstrap_r11._r11_role_call_index(sources, {'callsRequiringInteractionReview': graph})
        # Header/assignment aliases and decorators are real callers too. The
        # same physical call may have several graph identities, all retained.
        other_name = 'src/header_fixture.py'
        other = b'x = y = factory()\n@decorate(factory())\ndef wrapped():\n    return x\n'
        graph = sorted([[other_name, '@header', 1, 'factory'], [other_name, 'x', 1, 'factory'],
                        [other_name, 'y', 1, 'factory'], [other_name, 'wrapped', 2, 'factory'],
                        [other_name, 'wrapped', 2, 'decorate']])
        other_index = bootstrap_r11._r11_role_call_index({('CURRENT', other_name): other},
                                                        {'callsRequiringInteractionReview': graph})
        expanded = bootstrap_r11._r11_role_project_calls(other_index, {('CURRENT', other_name): [(0, len(other))]})
        self.assertEqual(expanded['originalTuples'], graph)
        self.assertEqual(len(expanded['allAstCalls']), 3)
        self.assertEqual(expanded['groups'], [{'path': other_name, 'allCallsOnLines': [1, 2]}])

    def test_static_pairs_and_both_integration_scopes_are_complete(self):
        self._check_shared_coverage_core()
        # Real production source owners make the scope check exercise new helper
        # inclusion. Only the small caller/callee graph is a synthetic fixture;
        # no mock substitutes for source, scope or coverage verification.
        root = Path(__file__).parents[2]
        prefix = 'src/agent_lifecycle/adapter_sessions/'
        core = {('CURRENT', prefix + name): (root / (prefix + name)).read_bytes() for name in
                ('bootstrap_r11.py', 'process.py', 'codex_exact_prompt.py', 'launch_preflight.py')}
        with self.assertRaises(LifecycleError) as refused:
            bootstrap_r11._r11_required_interaction_scopes(core)
        self.assertEqual(refused.exception.code, 'r11-shard-interaction')
        # Disclosed archival monolith, AST data only: these complete provider
        # bodies retain their bytes but use a conceptual historical namespace.
        # This does not prove current source closure; it is never executed.
        import inspect
        import importlib
        refs = []
        for namespace_file in ('bootstrap_r11.py', 'process.py', 'codex_exact_prompt.py', 'launch_preflight.py'):
            namespace = importlib.import_module('agent_lifecycle.adapter_sessions.' + namespace_file[:-3])
            chosen = {}
            for alias, value in vars(namespace).items():
                provider_name = getattr(value, '__module__', '')
                name = getattr(value, '__name__', '')
                if not (inspect.isfunction(value) or inspect.isclass(value)) or not provider_name.startswith('agent_lifecycle.'):
                    continue
                # Resolve duplicate imported names through this namespace's
                # actual final binding, never by an oracle-generated stub.
                if name in vars(namespace) and vars(namespace)[name] is not value:
                    continue
                if name in chosen:
                    continue
                provider = Path(inspect.getsourcefile(value)).resolve()
                if not provider.is_relative_to(root / 'src'):
                    raise AssertionError('Conceptual fixture source escaped this checkout')
                unit_lines, first = inspect.getsourcelines(value)
                raw = ''.join(unit_lines).encode()
                actual = b''.join(provider.read_bytes().splitlines(keepends=True)[first-1:first-1+len(unit_lines)])
                self.assertEqual(raw, actual)
                chosen[name] = raw
                refs.append({'namespace': namespace_file, 'symbol': name,
                             'path': provider.relative_to(root).as_posix(), 'firstLine': first,
                             'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
            # Include complete private provider units too: ordinary facades
            # intentionally do not re-export every former monolithic helper.
            import ast
            patterns = {'bootstrap_r11.py': ['source_review_*.py'],
                        'process.py': ['process*.py'],
                        'codex_exact_prompt.py': ['codex_*.py', 'ordinary_*.py'],
                        'launch_preflight.py': ['launch*.py', 'managed_process.py']}
            providers = {p for pattern in patterns[namespace_file] for p in (root / prefix).glob(pattern)}
            if namespace_file == 'bootstrap_r11.py':
                providers.update((root / 'src/agent_lifecycle/accounting').glob('declared_ledger*.py'))
            for provider in sorted(providers):
                raw_lines = provider.read_bytes().splitlines(keepends=True)
                for unit in ast.parse(b''.join(raw_lines)).body:
                    if not isinstance(unit, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        continue
                    if unit.name in chosen:
                        continue
                    first = min([unit.lineno] + [d.lineno for d in unit.decorator_list])
                    raw = b''.join(raw_lines[first-1:unit.end_lineno])
                    chosen[unit.name] = raw
                    refs.append({'namespace': namespace_file, 'symbol': unit.name,
                                 'path': provider.relative_to(root).as_posix(), 'firstLine': first,
                                 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
            core[('CURRENT', prefix + namespace_file)] = b'\n\n'.join(chosen.values())
        self._legacy_ast_provenance = {'kind': 'CONCEPTUAL_ARCHIVAL_NAMESPACE_COMPLETE_AST_UNITS_ONLY',
                                       'importedOrExecuted': False, 'currentSourceClosureProof': False,
                                       'providerUnitRefs': refs}
        a, b = ('CURRENT', 'src/caller_fixture.py'), ('CURRENT', 'src/target_fixture.py')
        old = ('PARENT', 'src/caller_fixture.py')
        document = ('CURRENT', 'src/fixture.txt')
        sources = {**core, document: b'Literal non-Python source.\n', a: b'def caller(cb):\n    return cb()\n',
                   b: b'def target():\n    return 1\n', old: b'def caller(cb):\n    return cb(0)\n'}
        full = {key: [(0, len(raw))] for key, raw in sources.items()}
        rows = lambda chosen: bootstrap_r11._r11_coverage_rows(sources, {key: full[key] for key in chosen})
        roles = [rows(core), rows([a]), rows([b]), rows([a, b]), rows([old, document])]
        graph = {'edges': [[a[1], 'caller', b[1], 'target']],
                 'callsRequiringInteractionReview': [[a[1], 'caller', 2, 'cb']]}
        primaries = {'OBSERVER_TERMINAL': 'source-01', 'COLLECTOR_FIRST_NATIVE': 'source-01'}
        project = lambda rr=roles, ss=primaries, **kw: bootstrap_r11._r11_role_source_projection(
            sources, full, graph, rr, ss, **kw)
        result = project()
        self.assertFalse(result['dependencyClosureComplete'])
        self.assertFalse(result['firstNativeBootstrapEligible'])
        self.assertEqual(result['coverageUnionSha256'], canonical_digest(rows(sources)))
        self.assertEqual(result['roles'][0]['requiredIntegrationScopes'], sorted(primaries))
        self.assertTrue(all(role['requiredIntegrationScopes'] == [] for role in result['roles'][1:]))
        self.assertEqual(result['roles'][3]['staticPairAssignment'], [rows([a, b])])
        self.assertTrue(all(not result['roles'][i]['staticPairAssignment'] for i in (0, 1, 2, 4)))
        self.assertEqual(result['roles'][1]['callProjection'], [{'path': a[1], 'allCallsOnLines': [2]}])
        self.assertEqual(result['roles'][4]['callProjection'], [])
        self.assertEqual(project(supplied=copy.deepcopy(result)), result)
        # Both primaries may be distinct, but each needs the entire assigned
        # scope. Duplicate raw overlap alone grants no third approval.
        overlapping = [rows(core), rows(core), rows([a, b, old, document])]
        separate = project(overlapping, {'OBSERVER_TERMINAL': 'source-01', 'COLLECTOR_FIRST_NATIVE': 'source-02'})
        self.assertEqual(separate['roles'][0]['requiredIntegrationScopes'], ['OBSERVER_TERMINAL'])
        self.assertEqual(separate['roles'][1]['requiredIntegrationScopes'], ['COLLECTOR_FIRST_NATIVE'])
        with self.subTest(kind='32-source-roles-accepted'):
            many = [rows(sources)] + [rows([a])] * 31
            self.assertEqual(len(project(many)['roles']), 32)
        bad_roles = {
            'static-pair-split': roles[:3] + roles[4:],
            'missing-parent-bytes': roles[:-1],
            'empty-role': roles + [[]],
            'zero-roles': [],
            '33-roles': [rows(sources)] + [rows([a])] * 32,
            'both-scopes-split-across-files': [rows([key]) for key in core] + [rows([a, b, old, document])],
        }
        altered = copy.deepcopy(roles); altered[1][0]['sha256'] = '0' * 64
        bad_roles['stale-source'] = altered
        altered = copy.deepcopy(roles); altered[1].append(dict(altered[1][0]))
        bad_roles['duplicate-extent'] = altered
        # Full global union is insufficient when even one newly participating
        # helper is removed from its primary and assigned to an ordinary role.
        bootstrap_key = ('CURRENT', prefix + 'bootstrap_r11.py')
        helper = bootstrap_r11._r11_python_index(sources[bootstrap_key], bootstrap_key[1])['bindings']['_r11_role_project_calls']
        split = copy.deepcopy(full)
        split[bootstrap_key] = [(0, helper['start']), (helper['end'], len(sources[bootstrap_key]))]
        bad_roles['new-helper-separated-from-primary'] = [bootstrap_r11._r11_coverage_rows(sources, split),
            bootstrap_r11._r11_coverage_rows(sources, {bootstrap_key: [(helper['start'], helper['end'])]})]
        for name, rr in bad_roles.items():
            with self.subTest(refusal=name), self.assertRaises(LifecycleError):
                project(rr)
        for scopes in ({}, {'OBSERVER_TERMINAL': 'source-01'},
                       {**primaries, 'OTHER': 'source-01'},
                       {**primaries, 'OBSERVER_TERMINAL': 'source-02'},
                       {**primaries, 'COLLECTOR_FIRST_NATIVE': 'source-06'},
                       {**primaries, 'OBSERVER_TERMINAL': ['source-01', 'source-02']}):
            with self.subTest(invalidPrimaries=scopes), self.assertRaises(LifecycleError):
                project(ss=scopes)
        mutations = []
        for field in ('sourceRanges', 'callProjection'):
            value = copy.deepcopy(result); value['roles'][1][field] = []; mutations.append(value)
        value = copy.deepcopy(result); value['roles'][3]['staticPairAssignment'] = []; mutations.append(value)
        value = copy.deepcopy(result); value['roles'][2]['requiredIntegrationScopes'] = ['OBSERVER_TERMINAL']; mutations.append(value)
        value = copy.deepcopy(result); value['roles'][0]['requiredIntegrationScopes'].pop(); mutations.append(value)
        value = copy.deepcopy(result); value['roles'][1]['roleId'] = 'source-32'; mutations.append(value)
        value = copy.deepcopy(result); value['firstNativeBootstrapEligible'] = True; mutations.append(value)
        for i, value in enumerate(mutations):
            with self.subTest(tamperedAssignment=i), self.assertRaises(LifecycleError):
                project(supplied=value)
        # New helpers cannot escape the mandatory first-native integration role.
        scope = bootstrap_r11._r11_required_interaction_scopes(sources)['COLLECTOR_FIRST_NATIVE']
        key = ('CURRENT', prefix + 'bootstrap_r11.py')
        index = bootstrap_r11._r11_python_index(sources[key], key[1])
        for helper in ('_r11_role_call_index', '_r11_role_project_calls', '_r11_role_source_projection'):
            unit = index['bindings'][helper]
            self.assertTrue(bootstrap_r11._r11_coverage_contains(scope, key, [(unit['start'], unit['end'])]))

    def _role_request_fixture(self, *, padding='', shared_operation='shared-op'):
        return _r11_role_request_fixture(self,padding=padding,shared_operation=shared_operation)

    def _check_completed_role_assignment(self, *, section=None):
        from datetime import datetime, timedelta

        m=bootstrap_r11
        with _r11_completed_role_fixture(self) as fixture:
            root,authority,base,inventory,funding,shared_exposure,source,review,directory,exposures,identity,basis,catalog,fit,rebuilt,cost,sealed,producers,body_raws,accepted = (fixture.root,fixture.authority,fixture.base,fixture.inventory,fixture.funding,fixture.shared_exposure,fixture.source,fixture.review,fixture.directory,fixture.exposures,fixture.identity,fixture.basis,fixture.catalog,fixture.fit,fixture.rebuilt,fixture.cost,fixture.sealed,fixture.producers,fixture.body_raws,fixture.accepted)
            def collect(**kw):return m._r11_completed_assignment(root,review,role_delivery=True,**kw)
            if section in ('fresh','fresh-worker'):
                self._check_fresh_role_gate(root,authority,basis,cost,fit,sealed,producers,catalog,only_worker=section=='fresh-worker')
            if section=='composite':
                self._check_v6_composite(root,authority,basis,cost,fit,sealed)
            if section in (None,'assignment'):
                with self.subTest(allRoles='reconstruct-and-publish-exact-four-role-assignment'):
                    result=collect(with_evidence=True);assignment=result['assignment']
                    self.assertEqual([row['roleId'] for row in assignment['roles']],['shared-01','source-01','source-02','source-03'])
                    self.assertEqual(assignment['sharedEvidenceSha256'],hashlib.sha256(accepted['evidenceRaw']).hexdigest())
                    self.assertEqual([row['evidenceSha256'] for row in assignment['roles']],[canonical_digest(v) for v in result['roleEvidence']])
                    self.assertFalse(result['firstNativeBootstrapEligible']);self.assertIsNone(result['actualModelTokens'])
                    self.assertEqual(m.finalize_source_review_assignment(root,review_id=review,role_delivery=True),assignment)
                    published=m.collect_source_review_qualified_evidence(root,review_id=review,role_delivery=True)
                    self.assertEqual(published['assignmentSha256'],canonical_digest(assignment));self.assertTrue(published['producerQualified'])
                    self.assertFalse(published['firstNativeBootstrapEligible']);self.assertFalse(published['hostContextQualified'])
                for kind in ('missing-settlement','failed-worker','extra-role','reversed-settlements','unfinished-role','unanchored'):
                    changed=copy.deepcopy(cost)
                    if kind=='missing-settlement':changed['settlements'].pop()
                    if kind=='failed-worker':changed['settlements'][2]['worker']['state']='WORKER_FAILED'
                    if kind=='extra-role':changed['reservations'].append(copy.deepcopy(changed['reservations'][-1]))
                    if kind=='reversed-settlements':changed['settlements'].reverse()
                    if kind=='unfinished-role':changed['unreservedRoleIds']=['source-03']
                    if kind=='unanchored':changed['rolePrefixesAnchored']=False
                    with self.subTest(allRoles=kind),patch.object(m,'read_source_review_cost',new=lambda *a,**kw:changed),self.assertRaises(LifecycleError):collect()
                for key in ('baseRaw','roleInventoryRaw'):
                    changed=copy.deepcopy(rebuilt);changed['candidate']['roleBasis'][key]+=b' '
                    with self.subTest(allRoles='changed-reconstructed-'+key),patch.object(m,'reconstruct_source_review',new=lambda *a,**kw:changed),self.assertRaises(LifecycleError):collect()
                for kind in ('legacy-seal','wrong-request','foreign-operation'):
                    old=sealed['source-02'];changed=copy.deepcopy(old)
                    if kind=='legacy-seal':changed['seal']['schemaVersion']='alk-r11-role-request-seal.v1'
                    if kind=='wrong-request':changed['requestRaw']+=b' '
                    if kind=='foreign-operation':changed['seal']['binding']['operationId']='foreign'
                    sealed['source-02']=changed
                    try:
                        with self.subTest(allRoles=kind),self.assertRaises(LifecycleError):collect()
                    finally:sealed['source-02']=old
                path=directory/'assignment.json';saved=path.read_bytes()
                for kind in ('extra-field','omitted-role','mixed-v5-role','changed-evidence'):
                    changed=json.loads(saved)
                    if kind=='extra-field':changed['trustMe']=True
                    if kind=='omitted-role':changed['roles'].pop()
                    if kind=='mixed-v5-role':changed['roles'][1]['roleId']='r11-01'
                    if kind=='changed-evidence':changed['roles'][1]['evidenceSha256']='0'*64
                    path.write_bytes(canonical_bytes(changed))
                    try:
                        with self.subTest(allRoles='published-'+kind),self.assertRaises(LifecycleError):m.collect_source_review_evidence(root,review_id=review,role_delivery=True)
                    finally:path.write_bytes(saved)
                for entry,kwargs in [(m._r11_completed_assignment,{}),(m.finalize_source_review_assignment,{'review_id':review}),
                                     (m.collect_source_review_evidence,{'review_id':review}),(m.collect_source_review_qualified_evidence,{'review_id':review})]:
                    with self.subTest(allRoles='legacy-mode-refuses',entry=entry.__name__),self.assertRaises(LifecycleError):
                        entry(root,review,**kwargs) if not kwargs else entry(root,**kwargs)
                for target in ('producer','ledger','shared'):
                    count=[0]
                    def drift(*a,**kw):
                        count[0]+=1
                        if target=='producer':
                            value=copy.deepcopy(producers[kw['shard_id']])
                            if count[0]>4:value['lateChange']=True
                        elif target=='ledger':
                            value=copy.deepcopy(cost)
                            if count[0]>1:value['fundingOrigin']['currentHeadSha256']='0'*64
                        else:
                            value=copy.deepcopy(accepted)
                            if count[0]>1:value['bodyRaw']+=b' '
                        return value
                    name={'producer':'collect_source_review_producer','ledger':'read_source_review_cost','shared':'collect_source_review_shared'}[target]
                    with self.subTest(allRoles='late-'+target+'-drift'),patch.object(m,name,new=drift),self.assertRaises(LifecycleError):collect()
                class Expired(datetime):
                    @classmethod
                    def now(cls,tz=None):
                        return datetime.fromisoformat(funding['admittedAtUtc'])+timedelta(hours=2)
                with self.subTest(allRoles='expired-batch'),patch.object(m,'datetime',Expired),self.assertRaises(LifecycleError):collect()
            if section=='eligibility':
                with self.subTest(parentClosure='eligible-only-until-composite-and-native-gates'):
                    result=collect(with_evidence=True)
                    self.assertTrue(result['parentClosureEligible'])
                    self.assertEqual(result['eligibleParentFindingIds'],['RB-OBSERVER-TIMEOUT-01'])
                    self.assertEqual(result['parentVerdict'],'FAIL')
                    self.assertNotIn('closedParentFindingIds',result);self.assertNotIn('reviewerClosedParentFindingIds',result)
                    self.assertEqual([(row['scope'],row['roleId']) for row in result['integrationApprovals']],
                        [('COLLECTOR_FIRST_NATIVE','source-01'),('OBSERVER_TERMINAL','source-02')])
                    m.finalize_source_review_assignment(root,review_id=review,role_delivery=True)
                    qualified=m.collect_source_review_qualified_evidence(root,review_id=review,role_delivery=True)
                    self.assertTrue(qualified['parentClosureEligible']);self.assertFalse(qualified['firstNativeBootstrapEligible'])
                    self.assertEqual(qualified['parentVerdict'],'FAIL');self.assertIsNone(qualified['actualModelTokens'])
                    self.assertNotIn('closedParentFindingIds',qualified);self.assertNotIn('reviewerClosedParentFindingIds',qualified)
            if section in (None,'findings'):
                for level,severity in [('P1','HIGH'),('P2','MEDIUM'),('P3','LOW')]:
                    path=root/m._R11_REVIEW_ROOT/'shards/source-01/review-body.raw';raw=path.read_bytes();changed=json.loads(raw)
                    changed['findings']=[{'id':'CURRENT-'+level,'reviewLevel':level,'severity':severity,'status':'OPEN',
                        'sourcePath':'src/fixture.py','sourceLine':1,'evidence':'current defect','rawSpan':'current defect','spanOrdinal':0}]
                    self.assertTrue(m._r11_role_schema_matches(changed,authority['schemas']['reviewerBody']))
                    path.write_bytes(canonical_bytes(changed))
                    try:
                        with self.subTest(parentClosure='well-shaped-current-'+level),self.assertRaises(LifecycleError) as failure:collect()
                        self.assertEqual(failure.exception.code,'r11-role-not-pass')
                    finally:path.write_bytes(raw)
            if section in (None,'closure'):
                with self.subTest(parentClosure='both-primaries-and-ordinary-role-pass'):
                    result=collect(with_evidence=True)
                    self.assertEqual([(row['scope'],row['roleId']) for row in result['integrationApprovals']],
                        [('COLLECTOR_FIRST_NATIVE','source-01'),('OBSERVER_TERMINAL','source-02')])
                    self.assertEqual(result['eligibleParentFindingIds'],['RB-OBSERVER-TIMEOUT-01'])
                    self.assertNotIn('reviewerClosedParentFindingIds',result);self.assertNotIn('closedParentFindingIds',result)
                    self.assertEqual(result['parentVerdict'],'FAIL');self.assertFalse(result['firstNativeBootstrapEligible'])
                mutations=[('missing-primary','source-02','approvedIntegrationScopes',[]),
                    ('extra-primary','source-01','approvedIntegrationScopes',['COLLECTOR_FIRST_NATIVE','OBSERVER_TERMINAL']),
                    ('duplicate-primary','source-01','approvedIntegrationScopes',['COLLECTOR_FIRST_NATIVE','COLLECTOR_FIRST_NATIVE']),
                    ('ordinary-approves','source-03','approvedIntegrationScopes',['OBSERVER_TERMINAL']),
                    ('shared-approves','shared-01','approvedIntegrationScopes',['OBSERVER_TERMINAL']),
                    ('shared-closes-parent','shared-01','closedParentFindingIds',['RB-OBSERVER-TIMEOUT-01']),
                    ('source-closes-parent','source-01','closedParentFindingIds',['RB-OBSERVER-TIMEOUT-01']),
                    ('ordinary-fails','source-03','verdict','FAIL'),('primary-incomplete','source-02','assignedContentComplete',False),
                    ('current-finding','source-01','findings',[{'id':'CURRENT-P1','severity':'P1'}])]
                for kind,role_id,key,value in mutations:
                    path=root/m._R11_REVIEW_ROOT/'shards'/role_id/'review-body.raw';raw=path.read_bytes();changed=json.loads(raw);changed[key]=value;path.write_bytes(canonical_bytes(changed))
                    try:
                        with self.subTest(parentClosure=kind),self.assertRaises(LifecycleError):collect()
                    finally:path.write_bytes(raw)

    def _check_fresh_role_gate(self,root,authority,basis,cost,fit,sealed,producers,catalog,*,only_worker=False):
        import time
        # Real current task/reservation/source binding, all-role reconstruction,
        # raw request/body matching, fresh protocol projection and gate storage.
        # Composite/financial ancestry/catalog and actual worker are boundaries.
        from datetime import datetime,timedelta,timezone
        m=bootstrap_r11;review=basis['identity']['base']['reviewId'];directory=m._r11_review_directory(root,review)
        for name in m._SOURCES:
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((_R11_REAL_SRC.parent/name).read_bytes())
        catalog.update(binaryPath='/fixture/codex');catalog['selected'].update(binarySha256='a'*64,model='fixture-model')
        responses={}
        for role,original in sealed.items():
            request=json.loads(original['requestRaw']);thread=original['seal']['binding']['threadId'];turn='turn-'+role
            raw=(root/m._R11_REVIEW_ROOT/'shards'/role/'review-body.raw').read_bytes()
            response={'thread':{'id':thread,'turns':[{'id':turn,'status':'completed','error':None,'items':[
                {'id':'input','type':'userMessage','content':request['params']['input']},
                {'id':'output','type':'agentMessage','phase':'final_answer','text':raw.decode()}]}]}}
            responses[thread]=response
            producers[role]['transport']['transport']['bodyReadMatch'].update(turnId=turn,
                stableProjectionSha256=canonical_digest(exact._single_turn_projection(response,thread_id=thread,turn_id=turn,request=request)))
        assignment=m.finalize_source_review_assignment(root,review_id=review,role_delivery=True)
        receipt={'schemaVersion':'alk-route-bootstrap-composite.v6-r11','collectorStatus':'VERIFIED','reviewId':review,
            'finalLedgerHeadSha256':'4'*64,'completedAssignmentSha256':canonical_digest(assignment),
            'orderedRoleEvidenceSha256':canonical_digest(m.collect_source_review_qualified_evidence(root,review_id=review,role_delivery=True)['roleEvidence']),
            'firstNativeBootstrapEligible':False}
        state=root/'workflow-state.json';state.write_bytes(canonical_bytes({'runId':'run','sourceRevision':'revision','tasks':[{'id':'task','status':'RUNNING','attempt':1}]}))
        intent_path=root/m._ROOT/'run/task/1/prelaunch-intent.json'
        intent={'schemaVersion':'alk-codex-prelaunch-intent.v1','runId':'run','taskId':'task','attemptId':'1','operationId':'native-op',
            'routeId':exact.ROUTE_ID,'requestedClaim':exact.CLAIM,'sourceRevision':'revision','planDigest':authority['planDigest'],
            'lockDigest':authority['lockSha256'],'requestSha256':'c'*64,'finalPromptSha256':'d'*64,'commandIdentityHash':'e'*64,
            'binarySha256':'a'*64,'plannedStdinBytes':12,'hostLaunchStarted':False,
            **m.capture_attempt_authority(root,lock_path=root/'tasks/release-2-16/plan.lock.json')}
        m._write(root,intent_path,intent);m.reserve_attempt_result(root,intent_path=intent_path)
        task=m._r11_native_task(root,intent_path,state)
        key=canonical_digest({k:intent[k] for k in ('runId','taskId','attemptId')})[:56]
        binding={'operationId':'r11-fresh/'+key,'shardId':'fresh-'+key,'threadId':'FIRST_NATIVE_READ_ONLY',
            'binarySha256':'a'*64,'transportSourceSha256':hashlib.sha256((root/m._R11_FIXED_WORKER).read_bytes()).hexdigest()}
        now=datetime.now(timezone.utc)-timedelta(seconds=1);mono=time.monotonic_ns()-1_000_000_000;timeout=120
        operation={'schemaVersion':'alk-r11-fresh-operation.v1','reviewId':review,'taskSha256':canonical_digest(task),
            'compositeSha256':canonical_digest(receipt),'binding':binding,'timeoutSeconds':timeout,
            'startedAtUtc':now.isoformat(),'absoluteDeadlineUtc':(now+timedelta(seconds=timeout)).isoformat(),
            'startedMonotonicNs':mono,'deadlineMonotonicNs':mono+timeout*1_000_000_000,'modelRequestsAuthorized':0,'retryAuthorized':False}
        held=basis['identity']['funding']['admittedUnknownHolds']+40000
        source={'status':'ADMITTED_PREAPPROVED_BY_USER','modelRequestCount':0,'freshMetadataOperation':operation,
            'tokenCap':40000,'unknownHoldsIncludingThisWindow':held}
        head={'headSha256':'d'*64,'source':source,'head':{'sourcePath':m._R11_COORDINATOR_BASE+'/r900-fresh/admission.json',
            'sourceSha256':canonical_digest(source),'unknownHolds':held}}
        class Wire:
            def __init__(self):self.sent=[];self.buffer=b'';self.override=None
            def send_bootstrap(self,value):self.sent.append(copy.deepcopy(value))
            def bootstrap_reply(self,ident,thread):
                if not thread:return {'userAgent':'fixture'}
                response=copy.deepcopy(responses[thread])
                return self.override(response) if self.override else response
        with patch.object(m,'__file__',str(root/m._R11_FIXED_WORKER)), \
             patch.object(m,'_r11_native_composite',new=lambda *a:(review,copy.deepcopy(receipt))), \
             patch.object(m,'read_coordinator_cost_head',new=lambda *a,**kw:copy.deepcopy(head)):
            def build():return m._r11_fresh_basis(root,review,intent_path,state,timeout)
            if only_worker:
                value,requests=build();path=directory/(binding['shardId']+'.json');m._write(root,path,value)
                self._check_fresh_worker_join(root,value,requests,responses)
                return
            with self.subTest(fresh='exact-four-role-raw-input-and-current-task'):
                value,requests=build();self.assertEqual([r['roleId'] for r in value['threads']],list(sealed))
                self.assertEqual(value['heldUnknownTokens'],held);self.assertEqual(value['operationDeadlineMonotonicNs'],operation['deadlineMonotonicNs'])
                self.assertEqual([canonical_bytes(r)+b'\n' for r in requests],[s['requestRaw'] for s in sealed.values()])
            with self.subTest(fresh='reads-shared-and-every-source-with-no-turn-start'):
                wire=Wire();exchange=m._r11_fresh_exchange(wire,value,requests)
                self.assertEqual([r['roleId'] for r in exchange['reads']],list(sealed));self.assertEqual(exchange['modelRequestsSent'],0)
                self.assertEqual([r['method'] for r in wire.sent],['initialize','initialized']+['thread/read']*4)
                self.assertFalse(exchange['firstNativeBootstrapEligible'])
            for role in sealed:
                original=producers[role]['transport']['transport']['bodyReadMatch']['bodySha256']
                producers[role]['transport']['transport']['bodyReadMatch']['bodySha256']='0'*64
                try:
                    with self.subTest(fresh='changed-producer-'+role),self.assertRaises(LifecycleError):build()
                finally:producers[role]['transport']['transport']['bodyReadMatch']['bodySha256']=original
            for role in ('shared-01','source-03'):
                raw=sealed[role]['requestRaw'];sealed[role]['requestRaw']+=b' '
                try:
                    with self.subTest(fresh='changed-request-'+role),self.assertRaises(LifecycleError):build()
                finally:sealed[role]['requestRaw']=raw
            for name,new in [('stale-task',dict(status='PENDING')),('other-attempt',dict(attempt=2))]:
                raw=state.read_bytes();changed=json.loads(raw);changed['tasks'][0].update(new);state.write_bytes(canonical_bytes(changed))
                try:
                    with self.subTest(fresh=name),self.assertRaises(LifecycleError):build()
                finally:state.write_bytes(raw)
            for path in (root/'tasks/release-2-16/plan.lock.json',root/m._R11_FIXED_WORKER):
                raw=path.read_bytes();path.write_bytes(raw+b' ')
                try:
                    with self.subTest(fresh='changed-task-authority-'+path.name),self.assertRaises(LifecycleError):build()
                finally:path.write_bytes(raw)
            for field,new in [('schemaVersion','alk-r11-fresh-operation.v0'),('taskSha256','0'*64),('compositeSha256','0'*64),
                              ('modelRequestsAuthorized',1),('retryAuthorized',True),('timeoutSeconds',121),('deadlineMonotonicNs',mono+121_000_000_000)]:
                old=operation[field];operation[field]=new
                try:
                    with self.subTest(fresh='admission-'+field),self.assertRaises(LifecycleError):build()
                finally:operation[field]=old
            source.pop('freshMetadataOperation')
            try:
                with self.subTest(fresh='ordinary-window-is-not-metadata-funding'),self.assertRaises(LifecycleError):build()
            finally:source['freshMetadataOperation']=operation
            old=source['status'];source['status']='UNAVAILABLE_FULL_HOLD_RETAINED'
            try:
                with self.subTest(fresh='closed-window-cannot-start'),self.assertRaises(LifecycleError):build()
            finally:source['status']=old
            for mutation in ('omit-shared','omit-source','extra','reverse','duplicate-thread','changed-request'):
                v=copy.deepcopy(value);q=copy.deepcopy(requests)
                if mutation=='omit-shared':v['threads'].pop(0);q.pop(0)
                if mutation=='omit-source':q.pop()
                if mutation=='extra':v['threads'].append(copy.deepcopy(v['threads'][-1]));q.append(copy.deepcopy(q[-1]))
                if mutation=='reverse':v['threads'].reverse();q.reverse()
                if mutation=='duplicate-thread':v['threads'][1]['threadId']=v['threads'][0]['threadId']
                if mutation=='changed-request':q[-1]['params']['threadId']='other'
                wire=Wire()
                with self.subTest(fresh='vector-'+mutation),self.assertRaises(LifecycleError):m._r11_fresh_exchange(wire,v,q)
                self.assertEqual(wire.sent,[])
            for role in sealed:
                wire=Wire();thread=sealed[role]['seal']['binding']['threadId']
                def changed(response):
                    if response['thread']['id']==thread:response['thread']['turns'][0]['items'][-1]['text']+=' '
                    return response
                wire.override=changed
                with self.subTest(fresh='changed-live-body-'+role),self.assertRaises(LifecycleError):m._r11_fresh_exchange(wire,value,requests)
            with self.subTest(fresh='expired-original-clock-denies-before-io'),patch.object(m.time,'monotonic_ns',return_value=operation['deadlineMonotonicNs']),self.assertRaises(LifecycleError):m._r11_fresh_exchange(Wire(),value,requests)
            wire=Wire();original_reply=wire.bootstrap_reply
            def late_reply(ident,thread):
                result=original_reply(ident,thread)
                if thread==value['threads'][-1]['threadId']:wire.buffer=b'trailing'
                return result
            wire.bootstrap_reply=late_reply
            with self.subTest(fresh='trailing-wire-refuses'),self.assertRaises(LifecycleError):m._r11_fresh_exchange(wire,value,requests)
            path=directory/(binding['shardId']+'.json');m._write(root,path,value)
            with self.subTest(fresh='input-reread-rebuilds-current-joins'):self.assertEqual(m._r11_read_fresh_input(root,path),(value,requests))
            old=head['headSha256'];head['headSha256']='8'*64
            try:
                with self.subTest(fresh='later-financial-head-invalidates-task-input'),self.assertRaises(LifecycleError):m._r11_read_fresh_input(root,path)
            finally:head['headSha256']=old
            raw=path.read_bytes();v=json.loads(raw);v['schemaVersion']='alk-r11-first-native-input.v1';path.write_bytes(canonical_bytes(v))
            try:
                with self.subTest(fresh='legacy-input-refuses'),self.assertRaises(LifecycleError):m._r11_read_fresh_input(root,path)
            finally:path.write_bytes(raw)
            for original in (None,operation['deadlineMonotonicNs']+1):
                with self.subTest(fresh='supervisor-requires-original-clock',supplied=original),patch.object(m,'_r11_worker_sources',new=lambda *a:{'instructionSha256':canonical_digest(value)}),self.assertRaises(LifecycleError):
                    m._supervise_source_review_worker(root,binding=binding,worker_path=root/m._R11_FIXED_WORKER,instruction_path=path,
                        expected_instruction_sha256=canonical_digest(value),timeout_seconds=timeout,held_unknown_tokens=held,
                        absolute_deadline_monotonic_ns=original)
            path.unlink()
            args={'intent_path':intent_path,'state_path':state,'plan_digest':intent['planDigest'],'lock_sha256':intent['lockDigest'],
                'selected_binary_sha256':intent['binarySha256'],'timeout_seconds':timeout}
            proof={'evidenceSha256':'7'*64}
            calls=[]
            def supervisor(*a,**kw):
                calls.append(kw);self.assertEqual(kw['absolute_deadline_monotonic_ns'],operation['deadlineMonotonicNs'])
                self.assertEqual(m._r11_read_fresh_input(root,kw['instruction_path']),(value,requests))
                m._write(root,m._r11_worker_directory(root,binding)/'process-result.json',{'deadlineMonotonicNs':operation['deadlineMonotonicNs']})
                return {'status':'WORKER_PROCESS_FINISHED'}
            def collected(*a,**kw):
                current,queries=m._r11_read_fresh_input(root,kw['fresh_input_path'])
                self.assertEqual(len(m._r11_fresh_exchange(Wire(),current,queries)['reads']),4)
                return copy.deepcopy(proof)
            with patch.object(m,'_supervise_source_review_worker',new=supervisor),patch.object(m,'collect_source_review_threads',new=collected):
                with self.subTest(fresh='task-bound-publish-and-consume-with-original-deadline'):
                    audit=m.require_source_review_fresh_gate(root,**args);m.verify_source_review_fresh_gate(root,audit=audit,intent_path=intent_path)
                    self.assertEqual(audit['metadataOperationSha256'],canonical_digest(operation));self.assertEqual(audit['ledgerHeadSha256'],head['headSha256'])
                    self.assertFalse(audit['hostContextQualified']);self.assertEqual(len(calls),1)
                with self.subTest(fresh='cannot-repeat-task-metadata-dispatch'),self.assertRaises(LifecycleError):m.require_source_review_fresh_gate(root,**args)
                self.assertEqual(len(calls),1)
                with self.subTest(fresh='expired-gate-cannot-consume'),patch.object(m.time,'monotonic_ns',return_value=operation['deadlineMonotonicNs']),self.assertRaises(LifecycleError):m.verify_source_review_fresh_gate(root,audit=audit,intent_path=intent_path)
                changed=copy.deepcopy(audit);changed['ledgerHeadSha256']='0'*64
                with self.subTest(fresh='changed-gate-ledger-refuses'),self.assertRaises(LifecycleError):m.verify_source_review_fresh_gate(root,audit=changed,intent_path=intent_path)
                old=state.read_bytes();v=json.loads(old);v['tasks'][0]['status']='DONE';state.write_bytes(canonical_bytes(v))
                try:
                    with self.subTest(fresh='cached-pass-cannot-consume-after-task-change'),self.assertRaises(LifecycleError):m.verify_source_review_fresh_gate(root,audit=audit,intent_path=intent_path)
                finally:state.write_bytes(old)
                result=m._r11_worker_directory(root,binding)/'process-result.json';old=result.read_bytes();result.write_bytes(canonical_bytes({'deadlineMonotonicNs':1}))
                try:
                    with self.subTest(fresh='late-process-receipt-refuses'),self.assertRaises(LifecycleError):m.verify_source_review_fresh_gate(root,audit=audit,intent_path=intent_path)
                finally:result.write_bytes(old)

    @_retired_r11_positive
    def test_fresh_gate_reopens_shared_and_every_source_thread(self):
        self._check_completed_role_assignment(section='fresh')
        self._check_completed_role_assignment(section='fresh-worker')
        self._check_fresh_gate_selector_race()

    def _check_fresh_gate_selector_race(self):
        m=bootstrap_r11
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();identity={'planDigest':'1'*64,'lockDigest':'2'*64,'binarySha256':'3'*64}
            old={'fixtureComposite':'before'};current={'fixtureComposite':'after'}
            value={'task':{'identity':identity},'compositeSha256':canonical_digest(current)}
            with patch.object(m,'_r11_native_composite',new=lambda *a:('review',old)), \
                 patch.object(m,'_r11_fresh_basis',new=lambda *a:(value,[])):
                with self.subTest(freshRace='changed-selected-composite-during-input-reconstruction'),self.assertRaises(LifecycleError) as raised:
                    m.require_source_review_fresh_gate(root,intent_path=root/'intent.json',state_path=root/'state.json',
                        plan_digest=identity['planDigest'],lock_sha256=identity['lockDigest'],selected_binary_sha256=identity['binarySha256'])
                self.assertEqual(raised.exception.code,'r11-native-identity');self.assertEqual(list(root.iterdir()),[])

    def _check_fresh_worker_join(self,root,value,requests,responses):
        import time,os,sys,shutil
        from agent_lifecycle.contracts.process_execution_schemas import command_identity_hash,process_identity_hash
        m=bootstrap_r11;binding=value['binding'];review=value['reviewId'];path=m._r11_review_directory(root,review)/(binding['shardId']+'.json')
        sources={'instructionSha256':canonical_digest(value),'fixtureSourceBoundary':'captured'}
        directory=m._r11_worker_directory(root,binding);base=directory.parent
        argv=[str(Path(sys.executable).resolve(strict=True)),'-B',str(root/m._R11_FIXED_WORKER),str(path)]
        env={**os.environ,'PYTHONPATH':str(root/'src'),'PYTHONDONTWRITEBYTECODE':'1','PYTHONUNBUFFERED':'1'}
        original=value['operationDeadlineMonotonicNs'];start=value['metadataOperation']['startedMonotonicNs']+1_000_000_000;pid=os.getpid()
        reserved={'schemaVersion':'alk-r11-worker-reservation.v1','binding':binding,'workerPath':m._R11_FIXED_WORKER,
            'instructionPath':path.relative_to(root).as_posix(),'argv':argv,'commandIdentityHash':command_identity_hash(argv),
            'environmentSha256':canonical_digest(env),'sourceSha256':sources,'timeoutSeconds':value['timeoutSeconds'],
            'heldUnknownTokens':value['heldUnknownTokens'],'costStatus':'UNAVAILABLE','actualModelTokens':None,'retryAuthorized':False,
            'absoluteDeadlineMonotonicNs':original}
        result={'startedMonotonicNs':start,'absoluteDeadlineMonotonicNs':original,
            'deadlineMonotonicNs':min(original,start+value['timeoutSeconds']*1_000_000_000),'cleanup':{'mode':'posix-session'},
            'processReceipt':{'processIdentityHash':process_identity_hash(pid=pid,started_ns=start)}}
        worker={'status':'WORKER_PROCESS_FINISHED','finishedMonotonicNs':time.monotonic_ns()}
        groups=[('SESSION',canonical_bytes(binding))]
        class RecordedWire:
            buffer=b''
            def send_bootstrap(self,row):
                raw=canonical_bytes(row)+b'\n';groups.extend([('SEND_PENDING',raw),('WRITE_ACCEPTED',raw),('FLUSHED',canonical_bytes({'sha256':hashlib.sha256(raw).hexdigest()}))])
            def bootstrap_reply(self,ident,thread):
                response=responses[thread] if thread else {'userAgent':'fixture'}
                groups.append(('RECEIVED_CHUNK',canonical_bytes({'id':ident,'result':response})+b'\n'));return copy.deepcopy(response)
        exchange=m._r11_fresh_exchange(RecordedWire(),value,requests)
        with patch.object(m,'_r11_worker_sources',new=lambda *a:copy.deepcopy(sources)):
            for supplied in (None,original+1):
                with self.subTest(freshRepair='supervisor-requires-original-clock',supplied=supplied),self.assertRaises(LifecycleError) as raised:
                    m._supervise_source_review_worker(root,binding=binding,worker_path=root/m._R11_FIXED_WORKER,instruction_path=path,
                        expected_instruction_sha256=canonical_digest(value),timeout_seconds=value['timeoutSeconds'],held_unknown_tokens=value['heldUnknownTokens'],absolute_deadline_monotonic_ns=supplied)
                self.assertEqual(raised.exception.code,'r11-worker-deadline')
            args={'intent_path':root/value['task']['intentPath'],'state_path':root/value['task']['statePath'],
                'plan_digest':value['task']['identity']['planDigest'],'lock_sha256':value['task']['identity']['lockDigest'],
                'selected_binary_sha256':binding['binarySha256'],'timeout_seconds':value['timeoutSeconds']}
            with self.subTest(freshRepair='cannot-repeat-task-metadata-dispatch'),self.assertRaises(LifecycleError) as raised:m.require_source_review_fresh_gate(root,**args)
            self.assertEqual(raised.exception.code,'codex-exact-private-create-failed');self.assertFalse(directory.exists())
            m._write(root,directory/'reservation.json',reserved)
            m._write(root,directory/'dispatch.pending.json',{'reservationSha256':canonical_digest(reserved),'state':'START_UNCERTAIN'})
            with patch.dict(os.environ,env),patch.object(m.os,'getpgrp',return_value=pid), \
                 patch.object(m,'_r11_require_fresh_review_catalog',new=lambda *a,**kw:{'evidenceSha256':value['catalogEvidenceSha256']}), \
                 patch.object(m,'_run_source_review_app_server_worker',new=lambda *a,**kw:{'fresh':kw['fresh_read'],'request':kw['expected_request']}):
                with self.subTest(freshWorker='fixed-child-accepts-funded-role-input-and-original-clock'):
                    accepted=m._run_source_review_thread_preparation(root,path);self.assertEqual(accepted,{'fresh':(value,requests),'request':b''})
                raw=(directory/'reservation.json').read_bytes();changed=copy.deepcopy(reserved);changed.pop('absoluteDeadlineMonotonicNs');(directory/'reservation.json').write_bytes(canonical_bytes(changed))
                try:
                    with self.subTest(freshWorker='fixed-child-refuses-reset-clock'),self.assertRaises(LifecycleError):m._run_source_review_thread_preparation(root,path)
                finally:(directory/'reservation.json').write_bytes(raw)
            (directory/'dispatch.pending.json').unlink()
            m._write(root,directory/'process-result.json',result);m._write(root,directory/'terminal.json',worker)
            m._write(root,base/'host-process/launch.json',{'binding':binding,'argv':[value['binaryPath'],'app-server','--listen','stdio://'],
                'supervisorPid':pid,'processGroupId':pid,'model':value['model'],'state':'START_UNCERTAIN','retryAuthorized':False})
            m._write(root,base/'host-process/finished.json',{**exchange,'hostPid':pid+1,'hostExitCode':0,'supervisorPid':pid,'processGroupId':pid,'binarySha256':binding['binarySha256']})
            m._write(root,base/'host-wire/exchange.json',exchange)
            sequence=0
            for kind,raw in groups:
                for offset in range(0,len(raw),32768):
                    m._write(root,base/'host-wire'/f'{sequence:08d}.json',{'sequence':sequence,'monotonicNs':start,'kind':kind,'offset':offset,'bytes':len(raw),'rawHex':raw[offset:offset+32768].hex()});sequence+=1
            with patch.object(m,'read_source_review_worker',new=lambda *a,**kw:copy.deepcopy(worker)):
                def collect():return m.collect_source_review_threads(root,review_id=review,fresh_input_path=path)
                with self.subTest(freshWorker='collector-replays-actual-raw-writes-flushes-and-all-reads'):
                    got=collect();self.assertEqual(got['threadIds'],[v['threadId'] for v in value['threads']]);self.assertEqual(got['modelRequestsSent'],0)
                    self.assertFalse(got['firstNativeBootstrapEligible']);self.assertEqual(got['historyScope'],'TASK_BOUND_ONE_FRESH_READ_PER_ROLE')
                for field,new in [('absoluteDeadlineMonotonicNs',original+1),('deadlineMonotonicNs',original+1),('startedMonotonicNs',start+1)]:
                    target=directory/'process-result.json';raw=target.read_bytes();changed=copy.deepcopy(result);changed[field]=new;target.write_bytes(canonical_bytes(changed))
                    try:
                        with self.subTest(freshWorker='collector-changed-'+field),self.assertRaises(LifecycleError):collect()
                    finally:target.write_bytes(raw)
                old=worker['finishedMonotonicNs'];worker['finishedMonotonicNs']=original+1
                try:
                    with self.subTest(freshWorker='collector-late-worker'),self.assertRaises(LifecycleError):collect()
                finally:worker['finishedMonotonicNs']=old
                target=base/'host-wire/00000001.json';raw=target.read_bytes();changed=json.loads(raw);changed['rawHex']='00'+changed['rawHex'][2:];target.write_bytes(canonical_bytes(changed))
                try:
                    with self.subTest(freshWorker='collector-changed-actual-write'),self.assertRaises(LifecycleError):collect()
                finally:target.write_bytes(raw)
                with self.subTest(freshWorker='collector-expired-original-clock'),patch.object(m.time,'monotonic_ns',return_value=original),self.assertRaises(LifecycleError):collect()
        shutil.rmtree(base)

    def _check_v6_composite(self,root,authority,basis,cost,fit,sealed):
        m=bootstrap_r11
        with _r11_v6_composite_fixture(self,root,authority,basis,cost,fit,sealed) as fixture:
            identity,review,directory,role_ids,opening,original,later,steps,chain,holds,head,extra = (fixture.identity,fixture.review,fixture.directory,fixture.role_ids,fixture.opening,fixture.original,fixture.later,fixture.steps,fixture.chain,fixture.holds,fixture.head,fixture.extra)
            m.finalize_source_review_assignment(root,review_id=review,role_delivery=True)
            with self.subTest(composite='actual-v6-composition-closes-parent-only'):
                receipt,proof=m._r11_composite_verified(root,review)
                self.assertEqual(receipt['schemaVersion'],'alk-route-bootstrap-composite.v6-r11')
                self.assertTrue(m._r11_role_schema_matches(receipt,authority['schemas']['verifiedComposite']))
                self.assertEqual(receipt['completedAssignmentSha256'],hashlib.sha256((directory/'assignment.json').read_bytes()).hexdigest())
                self.assertEqual(receipt['closedParentFindingIds'],['RB-OBSERVER-TIMEOUT-01']);self.assertEqual(receipt['parentVerdict'],'FAIL')
                self.assertFalse(receipt['firstNativeBootstrapEligible']);self.assertIsNone(proof['actualModelTokens'])
                inventory=json.loads(proof['privateInventoryRaw'])['files']
                for row in inventory:self.assertEqual(hashlib.sha256((root/row['path']).read_bytes()).hexdigest(),row['sha256'])
                self.assertEqual(len(proof['producerEvidenceSha256']),4)
            with self.subTest(composite='publication-read-install-no-native'):
                published=m.publish_source_review_composite(root,review_id=review)
                self.assertEqual(published,receipt);self.assertEqual(m.read_source_review_composite(root,review_id=review),receipt)
                self.assertEqual(m.install_source_review_composite(root,review_id=review),receipt)
                self.assertEqual(m._r11_native_composite(root),(review,receipt));self.assertFalse(receipt['firstNativeBootstrapEligible'])
            with self.subTest(composite='exclusive-collector-cannot-retry'),self.assertRaises(FileExistsError):m.publish_source_review_composite(root,review_id=review)
            with self.subTest(composite='final-ledger-must-include-last-settlement'),self.assertRaises(LifecycleError):m._r11_composite_verified(root,review,ledger_head_sha256=opening)
            # A monotonic external append changes current accounting, not accepted
            # immutable role evidence or the saved composite's final anchor.
            with self.subTest(composite='authorized-external-head-append-preserves-receipt'):
                chain.insert(0,later);holds[later]=holds[original]+40000
                cost['fundingOrigin']['currentHeadSha256']=later;cost['currentCoordinatorUnknownHolds']=holds[later];fit['coordinatorHeadSha256']=later
                self.assertEqual(m.read_source_review_composite(root,review_id=review),receipt)
            chain.remove(original)
            try:
                with self.subTest(composite='missing-financial-anchor-refuses'),self.assertRaises(LifecycleError):m.read_source_review_composite(root,review_id=review)
            finally:chain.insert(1,original)
            prior=cost['costChainSha256'];cost['costChainSha256']='0'*64
            try:
                with self.subTest(composite='changed-final-role-prefix-refuses'),self.assertRaises(LifecycleError):m.read_source_review_composite(root,review_id=review)
            finally:cost['costChainSha256']=prior
            assignment=directory/'assignment.json';raw=assignment.read_bytes()
            for mutation in ['omitted','extra','mixed-v5']:
                value=json.loads(raw)
                if mutation=='omitted':value['roles'].pop()
                if mutation=='extra':value['roles'].append(copy.deepcopy(value['roles'][-1]))
                if mutation=='mixed-v5':value['roles'][1]['roleId']='r11-01'
                assignment.write_bytes(canonical_bytes(value))
                try:
                    with self.subTest(composite='assignment-'+mutation),self.assertRaises(LifecycleError):m.read_source_review_composite(root,review_id=review)
                finally:assignment.write_bytes(raw)
            collector=directory/'collector';receipt_path=collector/'receipt.json';receipt_raw=receipt_path.read_bytes();terminal_path=collector/'qualification.json';terminal_raw=terminal_path.read_bytes()
            for mutation in ['v5','extra-field','native-promotion']:
                value=json.loads(receipt_raw)
                if mutation=='v5':value['schemaVersion']='alk-route-bootstrap-composite.v5-r11'
                if mutation=='extra-field':value['trustMe']=True
                if mutation=='native-promotion':value['firstNativeBootstrapEligible']=True
                changed=canonical_bytes(value);receipt_path.write_bytes(changed);terminal_path.write_bytes(canonical_bytes({**json.loads(terminal_raw),'receiptSha256':hashlib.sha256(changed).hexdigest()}))
                try:
                    with self.subTest(composite='closed-schema-'+mutation),self.assertRaises(LifecycleError):m.read_source_review_composite(root,review_id=review)
                finally:receipt_path.write_bytes(receipt_raw);terminal_path.write_bytes(terminal_raw)
            changed=directory/'support/fixture.json';raw=changed.read_bytes();changed.write_bytes(raw+b' ')
            try:
                with self.subTest(composite='earlier-private-support-byte-drift'),self.assertRaises(LifecycleError):m.read_source_review_composite(root,review_id=review)
            finally:changed.write_bytes(raw)
            body=root/m._R11_REVIEW_ROOT/'shards/source-03/review-body.raw';raw=body.read_bytes();value=json.loads(raw);value['verdict']='FAIL';body.write_bytes(canonical_bytes(value))
            try:
                with self.subTest(composite='current-role-finding-or-failure-refuses'),self.assertRaises(LifecycleError):m.read_source_review_composite(root,review_id=review)
            finally:body.write_bytes(raw)
            part=collector/'inventory/00000000.raw';raw=part.read_bytes();part.write_bytes(raw+b' ')
            try:
                with self.subTest(composite='private-inventory-part-tamper'),self.assertRaises(LifecycleError):m.read_source_review_composite(root,review_id=review)
            finally:part.write_bytes(raw)
            extra=collector/'inventory/99999999.raw';extra.write_bytes(b'x');extra.chmod(0o600)
            try:
                with self.subTest(composite='extra-private-inventory-part'),self.assertRaises(LifecycleError):m.read_source_review_composite(root,review_id=review)
            finally:extra.unlink()
            # A partial publication is sticky and cannot be treated as VERIFIED.
            pending=collector/'receipt.pending.json';pending.write_bytes(b'{}');pending.chmod(0o600)
            try:
                with self.subTest(composite='pending-publication-refuses'),self.assertRaises(LifecycleError):m.read_source_review_composite(root,review_id=review)
            finally:pending.unlink()
            link=directory/'support/indirect.json';link.symlink_to(directory/'support/fixture.json')
            try:
                with self.subTest(composite='symlink-private-proof-refuses'),self.assertRaises(LifecycleError):m._r11_composite_inventory(root,review,role_ids)
                with self.subTest(composite='partial-inventory-marks-unreadable'):
                    rows=json.loads(m._r11_composite_inventory(root,review,role_ids,partial=True))['files']
                    row=next(row for row in rows if row['path']==link.relative_to(root).as_posix());self.assertIsNone(row['sha256']);self.assertTrue(row['unavailable'])
            finally:link.unlink()
            # Isolated copy keeps all original accepted proof; only its collector
            # is absent so a distinct fixture may exercise a failed attempt.
            temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);denied=Path(temporary.name).resolve()/'project'
            shutil.copytree(root,denied,ignore=shutil.ignore_patterns('collector'))
            with patch.object(m,'_r11_composite_verified',side_effect=LifecycleError('fixture-current-finding','controlled refusal')):
                negative=m.publish_source_review_composite(denied,review_id=review)
            with self.subTest(composite='closed-v6-refusal-keeps-holds'):
                self.assertTrue(m._r11_role_schema_matches(negative,authority['schemas']['refusal']));self.assertEqual(negative['collectorStatus'],'DENY')
                self.assertEqual(negative['unknownHoldsReleased'],0)
                terminal=json.loads((m._r11_review_directory(denied,review)/'collector/qualification.json').read_bytes())
                self.assertEqual(terminal['heldUnknownTokens'],cost['currentCoordinatorUnknownHolds']);self.assertIsNone(terminal['actualModelTokens'])
            with self.subTest(composite='negative-never-requalified-by-late-evidence'),patch.object(m,'_r11_composite_verified',side_effect=AssertionError('no late proof')):
                self.assertEqual(m.read_source_review_composite(denied,review_id=review),negative)
                with self.assertRaises(LifecycleError):m.install_source_review_composite(denied,review_id=review)
            with self.subTest(composite='negative-attempt-cannot-retry'),self.assertRaises(FileExistsError):m.publish_source_review_composite(denied,review_id=review)
            # Inventory metadata can exceed the generic private-file cap. Only
            # this archive boundary is captured; requests/scopes are not split.
            temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);chunked=Path(temporary.name).resolve()/'project'
            shutil.copytree(root,chunked,ignore=shutil.ignore_patterns('collector'))
            inventory=canonical_bytes({'files':[{'path':f'fixture/{n:06d}/'+('x'*120),'bytes':1,'sha256':'0'*64} for n in range(900)]})
            self.assertGreater(len(inventory),131072)
            with patch.object(m,'_r11_composite_inventory',return_value=inventory),patch.object(m,'_r11_composite_verified',side_effect=LifecycleError('fixture-refusal','captured inventory archive')):
                large=m.publish_source_review_composite(chunked,review_id=review)
            with self.subTest(composite='large-private-inventory-preserves-exact-bytes'):
                self.assertEqual(m.read_source_review_composite(chunked,review_id=review),large)
                saved=m._r11_review_directory(chunked,review)/'collector/inventory'
                self.assertEqual(b''.join(path.read_bytes() for path in sorted(saved.iterdir())),inventory)
                self.assertTrue(all(path.stat().st_size<=65536 for path in saved.iterdir()))

    def _check_composite_inventory_limit(self, *, only_limit=False):
        m=bootstrap_r11;temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name).resolve();review='bounded-inventory';role_ids=['shared-01','source-01']
        directory=root/m._R11_REVIEW_ROOT/'shards/metadata-source-01';body=directory/'terminal.json'
        m._write(root,body,{'fixture':'preserved'})
        if not only_limit:
            with self.subTest(compositeInventory='partial-keeps-present-bytes-and-explicit-unknowns'):
                inventory=json.loads(m._r11_composite_inventory(root,review,role_ids,partial=True))['files']
                found=next(row for row in inventory if row['path']==body.relative_to(root).as_posix())
                self.assertEqual(found['sha256'],hashlib.sha256(body.read_bytes()).hexdigest())
                self.assertEqual(found['bytes'],len(body.read_bytes()))
                self.assertTrue(any(row.get('unavailable') is True and row['sha256'] is None for row in inventory))
        count=[0];real=Path.iterdir
        def children(path):
            if path!=directory:return real(path)
            def stream():
                while count[0]<262145:
                    count[0]+=1;yield body
                raise AssertionError('entry limit must stop enumeration before exhausting input')
            return stream()
        with self.subTest(compositeInventory='entry-limit-stops-directory-enumeration'),patch.object(Path,'iterdir',new=children):
            with self.assertRaises(LifecycleError) as failure:m._r11_composite_inventory(root,review,role_ids,partial=True)
            self.assertEqual(failure.exception.code,'r11-composite-inventory-limit')
            self.assertLessEqual(count[0],262144)
        self.assertEqual(body.read_bytes(),canonical_bytes({'fixture':'preserved'}))

    @_retired_r11_positive
    def test_composite_v6_exact_roles_and_no_native_promotion(self):
        self._check_completed_role_assignment(section='composite')
        self._check_composite_inventory_limit()

    @_retired_r11_positive
    def test_parent_closure_requires_both_designated_integration_roles(self):
        self._check_completed_role_assignment(section='closure')
        self._check_completed_role_assignment(section='findings')
        self._check_completed_role_assignment(section='eligibility')

    @_retired_r11_positive
    def test_role_hash_dag_and_realized_assignment_reconstruct(self):
        self._check_completed_role_assignment(section='assignment')
        # Ancestor/request cases retain their independent component boundaries.
        root, authority, base, inventory, funding, shared, source = self._role_request_fixture()
        def identity(b=base, i=inventory, f=funding):
            return bootstrap_r11._r11_role_identity(authority=authority, base_raw=canonical_bytes(b),
                inventory_raw=canonical_bytes(i), funding_raw=canonical_bytes(f))
        value = identity()
        self.assertFalse(value['fundingAdmitted'])
        subject = bootstrap_r11._r11_role_subject(value, 'shared-01', None, authority['schemas'])
        self.assertEqual(subject['baseSha256'], canonical_digest(base))
        self.assertEqual(subject['roleInventorySha256'], canonical_digest(inventory))
        self.assertEqual(subject['fundingBatchSha256'], canonical_digest(funding))
        self.assertEqual(subject['slotSha256'], canonical_digest(funding['slots'][0]))
        def candidate(t='actual-thread'):
            return bootstrap_r11._r11_role_request_candidate(root, base_raw=canonical_bytes(base),
                inventory_raw=canonical_bytes(inventory), funding_raw=canonical_bytes(funding), role_id='shared-01',
                exposure_raw=canonical_bytes(shared), thread_id=t, model_context_window=1000000)
        one, two = candidate(), candidate()
        self.assertEqual(one['requestRaw'], two['requestRaw'])
        self.assertEqual(one['subject'], subject)
        shared_payload = json.loads(json.loads(one['requestRaw'])['params']['input'][0]['text'].split('\n', 2)[2])
        self.assertEqual(shared_payload['base'], base)
        self.assertEqual(shared_payload['roleInventory'], inventory)
        self.assertEqual(shared_payload['fundingSchedule'], funding)
        self.assertEqual(shared_payload['sharedExposureRaw'].encode(), canonical_bytes(shared))
        self.assertNotIn('fundingBatchSha256', shared_payload['base'])
        self.assertNotIn('base', json.loads(shared_payload['sharedExposureRaw']))
        changed = candidate('a-different-thread')
        self.assertEqual(changed['subject'], subject)
        self.assertNotEqual(changed['requestSha256'], one['requestSha256'])
        self.assertEqual(base['sharedExposureSha256'], inventory['roles'][0]['exposureSha256'])
        self.assertNotIn(one['requestSha256'], one['requestRaw'].decode())
        self.assertFalse(one['dispatchAllowed'])
        # No future request, reservation, body, shared result or realized
        # assignment can enter its own immutable ancestry via extra fields.
        for field in ('requestSha256', 'reservationSha256', 'sharedEvidenceSha256', 'completedAssignmentSha256'):
            for target in ('base', 'inventory', 'funding'):
                b, i, f = copy.deepcopy((base, inventory, funding))
                {'base': b, 'inventory': i, 'funding': f}[target][field] = 'c' * 64
                with self.subTest(cycleField=field, ancestor=target), self.assertRaises(LifecycleError):
                    identity(b, i, f)
        variants = []
        for kind in ('duplicateOperation', 'reversedRoles', 'missingScope', 'duplicateScope', 'noncontiguousRole', 'futureThread'):
            i = copy.deepcopy(inventory)
            if kind == 'duplicateOperation': i['roles'][1]['operationId'] = i['roles'][0]['operationId']
            if kind == 'reversedRoles': i['roles'].reverse()
            if kind == 'missingScope': i['roles'][1]['requiredIntegrationScopes'].pop()
            if kind == 'duplicateScope': i['roles'][0]['requiredIntegrationScopes'] = ['OBSERVER_TERMINAL']
            if kind == 'noncontiguousRole': i['roles'][1]['roleId'] = 'source-02'
            if kind == 'futureThread': i['roles'][1]['threadId'] = 'future'
            f = {**funding, 'roleInventorySha256': canonical_digest(i)}
            variants.append((kind, i, f))
        for kind, i, f in variants:
            with self.subTest(inventoryMutation=kind), self.assertRaises(LifecycleError): identity(i=i, f=f)
        for kind in ('reversedSlots', 'reducedHold', 'reducedReserve', 'lateDeadline', 'zeroDeadline', 'oldHoldReused'):
            f = copy.deepcopy(funding)
            if kind == 'reversedSlots': f['slots'].reverse()
            if kind == 'reducedHold': f['admittedUnknownHolds'] -= 360000
            if kind == 'reducedReserve': f['protectedCloseoutTokens'] = 100000
            if kind == 'lateDeadline': f['absoluteDeadlineUtc'] = '2026-09-28T16:30:01Z'
            if kind == 'zeroDeadline': f['absoluteDeadlineUtc'] = f['admittedAtUtc']
            if kind == 'oldHoldReused': f['reusedFirstHold'] = {'windowId': 'old', 'operationId': 'shared-op',
                'roleId': 'shared-01', 'tokenCap': 300000, 'reservationSha256': 'a' * 64, 'priorHeadSha256': 'b' * 64}
            with self.subTest(fundingMutation=kind), self.assertRaises(LifecycleError): identity(f=f)
        with self.subTest(kind='duplicate-json-key'), self.assertRaises(LifecycleError):
            bootstrap_r11._r11_role_identity(authority=authority, base_raw=canonical_bytes(base)[:-1]+b',"reviewId":"other"}',
                inventory_raw=canonical_bytes(inventory), funding_raw=canonical_bytes(funding))
        self.assertEqual(base['limits']['perRoleProtectedCloseoutTokens'], 100000)
        self._check_role_request_reservation()

    @_retired_r11_positive
    def test_shared_receipt_required_before_source_dispatch(self):
        self._check_accepted_shared()
        self._check_source_reservation_predecessor()
        root, authority, base, inventory, funding, shared, source = self._role_request_fixture()
        identity = bootstrap_r11._r11_role_identity(authority=authority, base_raw=canonical_bytes(base),
            inventory_raw=canonical_bytes(inventory), funding_raw=canonical_bytes(funding))
        subject = bootstrap_r11._r11_role_subject(identity, 'shared-01', None, authority['schemas'])
        body = {'schemaVersion': 'alk-route-bootstrap-reviewer-body.v6-r11', 'verdict': 'PASS',
                'phase': 'PRE_WS01', 'rb11RuntimeStatus': 'NOT_RUN',
                'subjectSha256': canonical_digest(subject),
                **{key: subject[key] for key in ('baseSha256', 'roleInventorySha256', 'fundingBatchSha256',
                     'roleId', 'roleKind', 'exposureSha256', 'sharedEvidenceSha256')},
                'sharedContentSeenByThisRole': True, 'assignedContentComplete': True,
                'inheritedCoverageAccepted': True, 'interactionScopeComplete': True,
                'approvedIntegrationScopes': [], 'closedParentFindingIds': [],
                'findings': [], 'reviewText': 'NO_CURRENT_FINDINGS'}
        # Exact pretty-printed raw body survives all embedding; no normalized
        # replacement is claimed to be the body the SHARED role actually sent.
        body_raw = json.dumps(body, indent=1).encode() + b'\n'
        receipt = {key: 'c' * 64 for key in authority['schemas']['sharedEvidence']['properties']}
        receipt.update(schemaVersion='alk-r11-shared-evidence.v1', status='SHARED_ACCEPTED',
            reviewId=base['reviewId'], **{key: identity[key] for key in ('baseSha256', 'roleInventorySha256', 'fundingBatchSha256')},
            subjectSha256=canonical_digest(subject), bodyRawSha256=hashlib.sha256(body_raw).hexdigest(),
            binding={'shardId': 'shared-01', 'operationId': 'shared-op', 'threadId': 'shared-thread',
                     'binarySha256': 'd' * 64, 'transportSourceSha256': 'e' * 64}, firstNativeBootstrapEligible=False)
        def build(evidence=canonical_bytes(receipt), raw=body_raw, thread='source-thread', content=source):
            return bootstrap_r11._r11_role_request_candidate(root, base_raw=canonical_bytes(base),
                inventory_raw=canonical_bytes(inventory), funding_raw=canonical_bytes(funding), role_id='source-01',
                exposure_raw=canonical_bytes(content), thread_id=thread, model_context_window=1000000,
                shared_evidence_raw=evidence, shared_body_raw=raw)
        candidate = build()
        request = json.loads(candidate['requestRaw'])
        payload = json.loads(request['params']['input'][0]['text'].split('\n', 2)[2])
        view = payload['sharedDecisionView']
        self.assertEqual(view['sharedBodyRaw'].encode(), body_raw)
        self.assertEqual(view['sharedEvidenceSha256'], hashlib.sha256(canonical_bytes(receipt)).hexdigest())
        self.assertEqual(payload['sourceContent'], source['sourceContent'])
        self.assertFalse(payload['sharedContentSeenByThisRole'])
        self.assertFalse(candidate['sharedEvidenceAccepted'])
        self.assertFalse(candidate['dispatchAllowed'])  # Shape PASS never starts a role.
        for label, ev, raw, thread in (
            ('missingBoth', None, None, 'source-thread'), ('barePassBody', None, body_raw, 'source-thread'),
            ('missingBody', canonical_bytes(receipt), None, 'source-thread'),
            ('normalizedBodyDiffers', canonical_bytes(receipt), canonical_bytes(body), 'source-thread'),
            ('sameThread', canonical_bytes(receipt), body_raw, 'shared-thread')):
            with self.subTest(refusal=label), self.assertRaises(LifecycleError): build(ev, raw, thread)
        for key in ('baseSha256', 'roleInventorySha256', 'fundingBatchSha256', 'subjectSha256', 'bodyRawSha256'):
            changed = {**receipt, key: 'f' * 64}
            with self.subTest(receiptMutation=key), self.assertRaises(LifecycleError): build(canonical_bytes(changed))
        for key, value in (('operationId', 'other'), ('shardId', 'source-01')):
            changed = {**receipt, 'binding': {**receipt['binding'], key: value}}
            with self.subTest(bindingMutation=key), self.assertRaises(LifecycleError): build(canonical_bytes(changed))
        for key, value in (('verdict', 'FAIL'), ('sharedContentSeenByThisRole', False),
                           ('assignedContentComplete', False), ('closedParentFindingIds', ['RB-OBSERVER-TIMEOUT-01'])):
            changed_raw = canonical_bytes({**body, key: value})
            changed = {**receipt, 'bodyRawSha256': hashlib.sha256(changed_raw).hexdigest()}
            with self.subTest(bodyMutation=key), self.assertRaises(LifecycleError): build(canonical_bytes(changed), changed_raw)
        with self.subTest(refusal='changedLiteral'), self.assertRaises(LifecycleError):
            build(content={**source, 'sourceContent': []})

    @_retired_r11_positive
    def test_complete_envelope_limits_refuse_before_model_start(self):
        self._check_role_inventory_preparation()
        self._check_role_source_assembly()
        root, authority, base, inventory, funding, shared, source = self._role_request_fixture()
        def build(*, padding='', thread='thread', window=1000000):
            exposure = {**shared, 'padding': padding}
            b = {**base, 'sharedExposureSha256': canonical_digest(exposure)}
            i = copy.deepcopy(inventory); i['baseSha256'] = canonical_digest(b);i['roles'][0]['exposureSha256'] = canonical_digest(exposure)
            f = {**funding, 'baseSha256': canonical_digest(b), 'roleInventorySha256': canonical_digest(i)}
            return bootstrap_r11._r11_role_request_candidate(root, base_raw=canonical_bytes(b),
                inventory_raw=canonical_bytes(i), funding_raw=canonical_bytes(f), role_id='shared-01',
                exposure_raw=canonical_bytes(exposure), thread_id=thread, model_context_window=window)
        baseline = build()
        parsed = json.loads(baseline['requestRaw'])
        self.assertEqual(parsed['method'], 'turn/start')
        self.assertEqual(parsed['params']['outputSchema'], authority['schemas']['reviewerBody'])
        self.assertEqual(parsed['params']['sandboxPolicy'], {'type': 'readOnly'})
        self.assertEqual(parsed['params']['approvalPolicy'], 'never')
        self.assertEqual(len(parsed['params']['input']), 1)
        self.assertEqual(baseline['serializedRequestBytes'], len(baseline['requestRaw']))
        bound = baseline['serializedRequestBytes'] + 8192 + 16384
        with self.subTest(kind='exact-declared-context-bound'): self.assertEqual(build(window=bound)['requestRaw'], baseline['requestRaw'])
        for window in (bound - 1, 0, None, True):
            with self.subTest(invalidWindow=window), self.assertRaises(LifecycleError): build(window=window)
        for thread in ('', 'x' * 257, 'ё' * 129, '\ud800', None):
            with self.subTest(invalidThread=repr(thread)), self.assertRaises(LifecycleError): build(thread=thread)
        self.assertFalse(build(thread='ё' * 128)['dispatchAllowed'])
        padding = 'x' * (245760 - baseline['serializedRequestBytes'])
        edge = build(padding=padding)
        self.assertEqual(len(edge['requestRaw']), 245760)
        self.assertLessEqual(edge['knownAlkInputTokenUpperBound'] + 8192, 260000)
        self.assertFalse(edge['selectedHostQualified'])
        with self.subTest(kind='one-byte-over-limit'), self.assertRaises(LifecycleError): build(padding=padding + 'x')
        # Backslashes and controls expand repeatedly inside the protocol's JSON
        # string. A raw-byte-only subtraction would accept this invalid envelope.
        with self.subTest(kind='escaped-envelope-overflow'), self.assertRaises(LifecycleError): build(padding='\\' * 60000)
        with self.subTest(kind='shared-cannot-reference-future-receipt'), self.assertRaises(LifecycleError):
            bootstrap_r11._r11_role_request_candidate(root, base_raw=canonical_bytes(base),
                inventory_raw=canonical_bytes(inventory), funding_raw=canonical_bytes(funding), role_id='shared-01',
                exposure_raw=canonical_bytes(shared), thread_id='thread', model_context_window=1000000,
                shared_evidence_raw=b'{}', shared_body_raw=b'{}')
        self._check_all_role_envelope_fit()

    def _check_role_material_authority(self, root, authority):
        material = bootstrap_r11._r11_role_material_authority(root)
        self.assertEqual(material['sourceOracle']['schemaVersion'], 'alk-r69q-source-exposure-oracle.v10')
        self.assertEqual(material['supportOracle']['schemaVersion'], 'alk-r69q-support-membership-oracle.v5')
        self.assertEqual(len(material['privateMembership']['requiredKeys']), 14)
        self.assertFalse(material['firstNativeBootstrapEligible'])
        source = bootstrap_r11._r11_source_inputs(root, role_delivery=True)
        support = bootstrap_r11._r11_support_authority(root, role_delivery=True)
        self.assertEqual(source, (material['sourceOracle'], material['expectedWip'], material['authoritySha256']))
        self.assertEqual(support, (material['supportOracle'], material['expectedWip'], material['route'], material['authoritySha256']))
        self.assertTrue(all(material['authoritySha256'][name] == digest for name, digest in authority['rawSha256'].items()))
        # Explicit v6 entry does not unlock legacy v5 producers under r69q.
        for reader in (bootstrap_r11._r11_source_inputs, bootstrap_r11._r11_support_authority):
            with self.subTest(legacyReader=reader.__name__), self.assertRaises(LifecycleError): reader(root)
            for value in (1, 'v6', None):
                with self.subTest(reader=reader.__name__, invalidVersion=value), self.assertRaises(LifecycleError):
                    reader(root, role_delivery=value)
        for name in ('SOURCE-EXPOSURE-ORACLE-v10.json', 'SUPPORT-MEMBERSHIP-ORACLE-v5.json',
                     'EXPECTED-WIP-PATHS-v2.json', 'REQUIRED-PRIVATE-SUPPORT-v1.json', 'SOURCE-EXPOSURE-ORACLE-v9.json'):
            path = root / 'tasks/release-2-16' / name
            raw = path.read_bytes()
            try:
                path.write_bytes(raw + b' ')
                with self.subTest(changedLockedMaterial=name), self.assertRaises(LifecycleError):
                    bootstrap_r11._r11_role_material_authority(root)
            finally:
                path.write_bytes(raw)
        # The top-level source producer reopens exact immutable parent files;
        # a caller cannot replace them with a clean-looking source subject.
        with self.subTest(kind='missing-parent-refuses-source-basis'), self.assertRaises(LifecycleError):
            bootstrap_r11._r11_role_source_basis(root)

    def _check_shared_coverage_core(self):
        source = 'def sample():\n    return "ё"\n'.encode()
        sources = {('CURRENT', f'src/sample{i}.py'): source for i in range(5)}
        required = {key: [(0, len(source))] for key in sources}
        rows = [bootstrap_r11._r11_coverage_rows(sources, {key: spans}) for key, spans in required.items()]
        with self.subTest(kind='legacy-still-four'), self.assertRaises(LifecycleError):
            bootstrap_r11._r11_validate_coverage(sources, required, rows, [])
        value, selections = bootstrap_r11._r11_validate_coverage(sources, required, rows, [], role_delivery=True)
        self.assertEqual(len(selections), 5)
        self.assertEqual(value['rows'], bootstrap_r11._r11_coverage_rows(sources, required))
        self.assertFalse(value['firstNativeBootstrapEligible'])
        whole = [bootstrap_r11._r11_coverage_rows(sources, required)]
        legacy = bootstrap_r11._r11_validate_coverage(sources, required, whole, [required])
        modern, _ = bootstrap_r11._r11_validate_coverage(sources, required, whole, [required], role_delivery=True)
        self.assertEqual(legacy, modern)
        with self.subTest(kind='split-pair-refuses-both'):
            for version in (False, True):
                with self.assertRaises(LifecycleError):
                    bootstrap_r11._r11_validate_coverage(sources, required, rows[:3]+[rows[3]+rows[4]], [required], role_delivery=version)
        for version in (False, True):
            for label, changed in (
                ('missing', [whole[0][:-1]]), ('duplicate', [whole[0]+whole[0][:1]]),
                ('bad-hash', [[{**row, 'sha256':'0'*64} for row in whole[0]]]),
                ('partial-unit', [[{**row, 'start':1, 'sha256':hashlib.sha256(source[1:]).hexdigest()} for row in whole[0]]])):
                with self.subTest(delivery=version, mutation=label), self.assertRaises(LifecycleError):
                    bootstrap_r11._r11_validate_coverage(sources, required, changed, [], role_delivery=version)
        for flag in (1, 'v6', None):
            with self.subTest(invalidVersion=flag), self.assertRaises(LifecycleError):
                bootstrap_r11._r11_validate_coverage(sources, required, whole, [], role_delivery=flag)
        key = ('CURRENT','src/sample.py')
        literal = {key: source}
        extents = bootstrap_r11._r11_coverage_rows(literal, {key:[(0,len(source))]})
        kwargs = dict(root=Path('/legacy-fixture'), sources=literal, rows=extents,
            shared={'currentSubjectSha256':'a'*64,'parentSubjectSha256':'b'*64}, calls=[], schema={'type':'object'},
            shard_id='r11-01', inventory_sha='c'*64, thread_id='thread', request_id=1)
        request = bootstrap_r11._r11_shard_request(**kwargs)
        # Captured from the unchanged pre-refactor serializer, independently
        # compared byte-for-byte. This fixes the historic UTF-8 wire contract.
        self.assertEqual(hashlib.sha256(request).hexdigest(), '1f3e269a4b559ba35ab9effb803d58f5ed23a3067251e0488fcb2b4cd63fac6c')
        kwargs['rows'] = [{**extents[0], 'start':1, 'sha256':hashlib.sha256(source[1:]).hexdigest()}]
        with self.subTest(kind='renderer-also-rejects-partial-owner'), self.assertRaises(LifecycleError):
            bootstrap_r11._r11_shard_request(**kwargs)

    def _check_role_source_assembly(self):
        from unittest import mock
        # The producer boundary is a controlled small fixture. Packing, raw
        # rendering, AST/call/pair expansion, union and version guards are real;
        # final-host/SHARED qualification is deliberately never asserted.
        root, authority, *_ = self._role_request_fixture()
        a, b = ('CURRENT', 'src/caller.py'), ('CURRENT', 'src/target.py')
        original = {a: b'def caller(cb):\n    return cb()\n', b: b'def target():\n    return 1\n'}
        graph = {'edges': [[a[1], 'caller', b[1], 'target']],
                 'callsRequiringInteractionReview': [[a[1], 'caller', 2, 'cb']]}
        state = {}
        def reset(extra=None, *, selected_graph=None, scope_source=None):
            sources = {**original, **(extra or {})}
            required = {key: [(0, len(raw))] for key, raw in sources.items()}
            scopes = {'OBSERVER_TERMINAL': {a: required[a]},
                      'COLLECTOR_FIRST_NATIVE': {b: required[b]}}
            if scope_source is not None:
                scopes['COLLECTOR_FIRST_NATIVE'] = {scope_source: required[scope_source]}
            dependencies = graph if selected_graph is None else selected_graph
            state.clear();state.update(sources=sources, required=required,
                dependencies=dependencies, integrationScopes=scopes,
                staticPairs=bootstrap_r11._r11_interaction_requirements(
                    {key: raw for key, raw in sources.items() if key[1].endswith('.py')}, dependencies),
                partition={'rows': []},
                subject={'fixtureOnly': True}, parent={'parentVerdict': 'FAIL'})
        reset()
        with mock.patch.object(bootstrap_r11, '_r11_role_source_basis', side_effect=lambda _: state) as producer, \
             mock.patch.object(bootstrap_r11, 'capture_review_validation_sources', return_value={'fixture': 'a' * 64}) as snapshot, \
             mock.patch.object(bootstrap_r11, 'collect_source_review_parent', side_effect=lambda _: state['parent']), \
             mock.patch.object(bootstrap_r11, '_r11_required_interaction_scopes', side_effect=lambda _: state['integrationScopes']), \
             mock.patch.object(bootstrap_r11, '_r11_review_parent_sources', side_effect=lambda *args:
                 {name: raw for (version, name), raw in state['sources'].items() if version == 'PARENT'}) as parents:
            def build(**kw):
                return bootstrap_r11.build_source_review_shards(root, role_delivery=True,
                    model_context_window=1000000, **kw)
            for version in (False, None, 1, 'v6'):
                with self.subTest(assembly='explicit-version', value=version), self.assertRaises(LifecycleError):
                    bootstrap_r11.build_source_review_shards(root, role_delivery=version, model_context_window=1000000)
            with self.subTest(assembly='legacy-subject-refused'), self.assertRaises(LifecycleError):
                build(current_subject={'schemaVersion': 'v5'}, thread_ids=['old-thread'])
            for window in (None, True, 0, -1):
                with self.subTest(assembly='invalid-window', value=window), self.assertRaises(LifecycleError):
                    bootstrap_r11.build_source_review_shards(root, role_delivery=True, model_context_window=window)
            self.assertEqual(producer.call_count, 0)
            with self.subTest(assembly='actual-source-pair-call-projection'):
                result = build()
                self.assertEqual(result['status'], 'ROLE_SOURCE_ASSEMBLY_UNQUALIFIED')
                self.assertEqual(len(result['sourceContent']), 1)
                content = result['sourceContent'][0]
                self.assertEqual(content['requiredIntegrationScopes'], ['COLLECTOR_FIRST_NATIVE', 'OBSERVER_TERMINAL'])
                self.assertEqual(content['callProjection'], [{'path': a[1], 'allCallsOnLines': [2]}])
                self.assertEqual(len(content['staticPairAssignment']), 1)
                for item in content['sourceContent']:
                    self.assertEqual(item['content'].encode(), original[(item['extent']['version'], item['extent']['path'])])
                for key in ('completeEnvelopeFit', 'hostContextQualified', 'fundingAdmitted', 'sharedEvidenceAccepted',
                            'dispatchAllowed', 'firstNativeBootstrapEligible'):
                    self.assertIs(result[key], False)
                self.assertNotIn('requests', result)
                self.assertEqual(build(), result)
            doc = ('CURRENT', 'src/escaped.txt')
            with self.subTest(assembly='mandatory-scope-escaped-overflow'):
                reset({doc: b'\\' * 70000}, scope_source=doc)
                result = build()
                self.assertEqual(result['reasonCode'], 'r11-role-mandatory-scope-overflow')
                self.assertGreater(result['mandatoryScopeLowerBoundBytes']['COLLECTOR_FIRST_NATIVE'], 245760)
                self.assertEqual(result['sourceContent'], [])
                self.assertIsNone(result['sourceProjection'])
                self.assertEqual(result['refusalStage'], 'PRE_SEND')
            with self.subTest(assembly='indivisible-nonpython-overflow'):
                reset({doc: b'x' * 250000})
                self.assertEqual(build()['reasonCode'], 'r11-role-complete-unit-or-pair-overflow')
            with self.subTest(assembly='indivisible-static-pair-overflow'):
                c, d = ('CURRENT', 'src/first.py'), ('CURRENT', 'src/second.py')
                large = {c: b'def first():\n    "' + b'x' * 130000 + b'"\n    return 1\n',
                         d: b'def second():\n    "' + b'x' * 130000 + b'"\n    return 2\n'}
                reset(large, selected_graph={'edges': graph['edges'] + [[c[1], 'first', d[1], 'second']],
                                            'callsRequiringInteractionReview': graph['callsRequiringInteractionReview']})
                self.assertEqual(build()['reasonCode'], 'r11-role-complete-unit-or-pair-overflow')
            with self.subTest(assembly='32-source-boundary'):
                reset({('CURRENT', f'src/doc-{i:02d}.txt'): b'x' * 130000 for i in range(32)})
                result = build()
                self.assertEqual(result['status'], 'ROLE_SOURCE_ASSEMBLY_UNQUALIFIED')
                self.assertEqual(len(result['sourceProjection']['roles']), 32)
                self.assertEqual([row['roleId'] for row in result['sourceProjection']['roles']],
                                 [f'source-{i:02d}' for i in range(1, 33)])
                self.assertTrue(all(n <= 245760 for n in result['assignedContentLowerBoundBytes']))
            with self.subTest(assembly='33-source-refusal'):
                reset({('CURRENT', f'src/doc-{i:02d}.txt'): b'x' * 130000 for i in range(33)})
                result = build()
                self.assertEqual(result['reasonCode'], 'r11-role-packing-exceeds-policy')
                self.assertEqual(result['sourceContent'], [])
            with self.subTest(assembly='context-reserve-enforced'):
                reset()
                result = bootstrap_r11.build_source_review_shards(root, role_delivery=True, model_context_window=24576)
                self.assertEqual(result['reasonCode'], 'r11-role-mandatory-scope-overflow')
            with self.subTest(assembly='source-staleness-also-invalidates-denial'), self.assertRaises(LifecycleError):
                reset({doc: b'x' * 250000}, scope_source=doc)
                snapshot.side_effect = [{'fixture': 'a' * 64}, {'fixture': 'b' * 64}]
                build()
            snapshot.side_effect = None
            with self.subTest(assembly='literal-parent-bytes-retained'):
                old = ('PARENT', 'src/caller.py')
                reset({old: b'def caller(cb):\n    return cb(0)\n'})
                result = build()
                rows = [item for role in result['sourceContent'] for item in role['sourceContent']
                        if item['extent']['version'] == 'PARENT']
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['content'].encode(), state['sources'][old])
            with self.subTest(assembly='parent-source-change-refused'), self.assertRaises(LifecycleError):
                parents.side_effect = lambda *args: {'src/caller.py': b'changed'}
                build()

    def _check_role_reconstruction(self):
        # Real frozen files, retained plan joins, private membership, origin
        # reader, packing and base/inventory construction. Expensive source,
        # negative-parent and final test-support producers are controlled
        # fixture boundaries; this is not actual support or host qualification.
        root, authority, *_ = self._role_request_fixture()
        real_root = Path(__file__).parents[2]
        def private(path, raw):
            path.parent.mkdir(parents=True, exist_ok=True)
            for parent in path.parents:
                if parent == root: break
                parent.chmod(0o700)
            path.write_bytes(raw);path.chmod(0o600)
        for name in ('plan.lock.json', 'plan.manifest.json', 'independent-s2-review.json'):
            relative = Path(bootstrap_r11._R11_REVIEW_ROOT) / 'parent-r69k' / name
            private(root / relative, (real_root / relative).read_bytes())
        material = bootstrap_r11._r11_role_material_authority(root)
        actual_authorities = bootstrap_r11._r11_review_authorities(root, role_delivery=True)
        with self.subTest(reconstruction='current-locked-terminal-and-retained-lineage'):
            terminal = root / 'tasks/release-2-16/r69l-r11-bootstrap-delta.md'
            self.assertEqual(actual_authorities['terminalContractContent'].encode(), terminal.read_bytes())
            self.assertEqual(actual_authorities['installedAuthoritySha256'], material['authoritySha256'])
        a, b = ('CURRENT', 'src/caller.py'), ('CURRENT', 'src/target.py')
        sources = {a: b'def caller(cb):\n    return cb()\n', b: b'def target():\n    return 1\n'}
        selected = {key: [(0, len(raw))] for key, raw in sources.items()}
        graph = {'edges': [[a[1], 'caller', b[1], 'target']],
                 'callsRequiringInteractionReview': [[a[1], 'caller', 2, 'cb']]}
        scopes = {'OBSERVER_TERMINAL': {a: selected[a]}, 'COLLECTOR_FIRST_NATIVE': {b: selected[b]}}
        pairs = bootstrap_r11._r11_interaction_requirements(sources, graph)
        rows = lambda value: bootstrap_r11._r11_coverage_rows(sources, value)
        parent_body = b'{ "verdict": "FAIL", "findings": [{"id":"RB-OBSERVER-TIMEOUT-01","status":"OPEN"}] }\n'
        parent = {'parentVerdict': 'FAIL', 'parentReviewBodySha256': _r11_sha(parent_body),
                  'content': {'parentBody': json.loads(parent_body)}}
        partition = {'authoritySha256': material['authoritySha256'], 'rows': [], 'partitionSha256': '1' * 64}
        subject = {'authorityInventorySha256': canonical_digest(material['authoritySha256']),
                   'parentSubjectSha256': '2' * 64, 'sourcePartitionSha256': '1' * 64,
                   'sourceSelectionSha256': '3' * 64, 'sourceGraphSha256': canonical_digest(graph),
                   'sourceInteractionMatrixSha256': canonical_digest([rows(pair) for pair in pairs]),
                   'sourceCoverageSha256': canonical_digest(rows(selected))}
        source_basis = {'sources': sources, 'required': selected, 'dependencies': graph,
                        'integrationScopes': scopes, 'staticPairs': pairs, 'parent': parent,
                        'partition': partition, 'subject': subject, 'authority': material}
        directory = bootstrap_r11._r11_review_directory(root, 'fixture-role-review')
        opening_raw = b'{ "actualTokens": null, "costStatus": "UNAVAILABLE" }\n'
        opening = {'schemaVersion': 'fixture-coordinator-origin', 'status': 'CURRENT_DECLARED_SOURCE_MATCHED',
                   'primaryCheckout': '/fixture-primary', 'head': {'sourcePath': 'fixture/cost.json',
                   'unknownHolds': 113750000, 'exposureLowerBound': 117606844}, 'headSha256': '4' * 64,
                   'measurementQualified': False, 'wholeHistoryComplete': False, 'hardCapClaim': 'DENY',
                   'sourceRaw': opening_raw}
        private(directory / 'cost-opening.json', opening_raw)
        private(directory / 'cost-opening-origin.json', canonical_bytes({k:v for k,v in opening.items() if k != 'sourceRaw'}))
        raw_support = {key: canonical_bytes({'fixtureOnly': True, 'member': key})
                       for key in material['privateMembership']['requiredKeys']}
        for name, raw in raw_support.items(): private(directory / 'support' / name, raw)
        support_content = {'wip': {'fixtureOnly': True}, 'tests': {'fixtureOnly': True},
                           'caseMappings': {'fixtureOnly': True}, 'opening': json.loads(opening_raw)}
        support = {'authoritySha256': material['authoritySha256'], 'costOpeningSha256': _r11_sha(opening_raw),
                   'privateSupportReceiptDigests': {key: _r11_sha(raw) for key, raw in raw_support.items()},
                   'content': support_content}
        def coordinator_origin(*args, ancestor_head_sha256=None):
            value = copy.deepcopy(opening)
            if ancestor_head_sha256 is not None:
                if ancestor_head_sha256 != value['headSha256']:
                    raise LifecycleError('fixture-opening-ancestry', 'fixture has no such ancestor')
                value['ancestor'] = copy.deepcopy(value)
            return value
        with patch.object(bootstrap_r11, '_r11_role_source_basis', return_value=source_basis), \
             patch.object(bootstrap_r11, '_r11_required_interaction_scopes', return_value=scopes), \
             patch.object(bootstrap_r11, 'capture_review_validation_sources', return_value={'fixtureOnly': 'a' * 64}), \
             patch.object(bootstrap_r11, 'collect_source_review_parent', return_value=parent), \
             patch.object(bootstrap_r11, '_r11_review_parent_sources', return_value={}), \
             patch.object(bootstrap_r11, '_r11_parent_snapshot', return_value=({'review-body.raw': parent_body}, {})) as raw_parent, \
             patch.object(bootstrap_r11, 'collect_source_review_support', side_effect=lambda *a, **kw: copy.deepcopy(support)) as collect_support, \
             patch.object(bootstrap_r11, 'read_coordinator_cost_head', side_effect=coordinator_origin):
            def build(**kw):
                args = {'review_id': 'fixture-role-review', 'model_context_window': 1000000,
                        'role_delivery': True, 'operation_ids': ['shared-op', 'source-op']}
                args.update(kw)
                return bootstrap_r11.reconstruct_source_review(root, **args)
            with self.subTest(reconstruction='immutable-dag-and-exact-raw-exposure'):
                result = build();candidate = result['candidate'];basis = candidate['roleBasis']
                self.assertEqual(result['status'], 'ROLE_RECONSTRUCTION_UNQUALIFIED')
                self.assertFalse(result['dispatchAllowed']);self.assertFalse(candidate['completeEnvelopeFit'])
                self.assertEqual(basis['baseRaw'], canonical_bytes(basis['base']))
                self.assertEqual(basis['roleInventory']['baseSha256'], basis['baseSha256'])
                self.assertEqual([r['operationId'] for r in basis['roleInventory']['roles']], ['shared-op', 'source-op'])
                self.assertNotIn('fundingBatchSha256', basis['base'])
                self.assertNotIn('sharedEvidenceSha256', basis['roleInventory'])
                shared = json.loads(basis['roleExposureRaw']['shared-01'])
                self.assertEqual(shared['parentReviewRaw'].encode(), parent_body)
                self.assertEqual(shared['openingRaw'].encode(), opening_raw)
                self.assertEqual(shared['support'], support_content)
                self.assertEqual(shared['identityOnly']['privateSupportReceiptDigests'], support['privateSupportReceiptDigests'])
                self.assertEqual(shared['identityOnly']['installedAuthoritySha256'], material['authoritySha256'])
                self.assertEqual(len(shared['sourceIdentities']), 2)
                self.assertEqual(basis['base']['sharedExposureSha256'], canonical_digest(shared))
                source = json.loads(basis['roleExposureRaw']['source-01'])
                self.assertNotIn('support', source);self.assertNotIn('openingRaw', source)
                self.assertEqual(set(source['integrationClosureContent']), set(scopes))
                for name, raw in source['integrationClosureContent'].items():
                    closure = json.loads(raw)
                    self.assertEqual(closure['scope'], name)
                    self.assertEqual(closure['parentReviewRaw'].encode(), parent_body)
                    self.assertEqual(closure['retainedTerminalContractRaw'], actual_authorities['terminalContractContent'])
                    self.assertEqual(closure['currentScopeRules'], authority['contract']['roles'])
                for role in basis['roleInventory']['roles']:
                    self.assertEqual(role['exposureSha256'], canonical_digest(json.loads(basis['roleExposureRaw'][role['roleId']])))
                self.assertTrue(all(call.kwargs['role_delivery'] is True for call in collect_support.call_args_list))
                self.assertEqual(build(), result)
            for changes in ({'role_delivery': False}, {'role_delivery': 1}, {'thread_ids': ['early-thread']},
                            {'operation_ids': None}, {'operation_ids': ['same','same']},
                            {'operation_ids': ['shared']}, {'operation_ids': ['a','b','extra']},
                            {'operation_ids': ['a','ё' * 129]}, {'operation_ids': ['a',True]},
                            {'review_id': '../escape'}):
                with self.subTest(reconstruction='invalid-assignment', change=changes), self.assertRaises(LifecycleError): build(**changes)
            member = directory / 'support' / 'c34-execution.json'
            with self.subTest(reconstruction='missing-private-member'):
                member.unlink()
                try:
                    with self.assertRaises(LifecycleError): build()
                finally: private(member, raw_support[member.name])
            with self.subTest(reconstruction='extra-private-member'):
                extra = directory / 'support' / 'extra.json';private(extra,b'{}')
                try:
                    with self.assertRaises(LifecycleError): build()
                finally: extra.unlink()
            with self.subTest(reconstruction='changed-private-content'):
                private(member,b'{}')
                try:
                    with self.assertRaises(LifecycleError): build()
                finally: private(member,raw_support[member.name])
            with self.subTest(reconstruction='opening-head-changed'), self.assertRaises(LifecycleError):
                opening['headSha256'] = '5' * 64; build()
            opening['headSha256'] = '4' * 64
            with self.subTest(reconstruction='raw-parent-body-mismatch'), self.assertRaises(LifecycleError):
                raw_parent.return_value = ({'review-body.raw': parent_body + b' '}, {}); build()
            raw_parent.return_value = ({'review-body.raw': parent_body}, {})
            with self.subTest(reconstruction='support-authority-mismatch'), self.assertRaises(LifecycleError):
                support['authoritySha256'] = {}; build()
            support['authoritySha256'] = material['authoritySha256']
            with self.subTest(reconstruction='raw-support-changes-after-check'):
                calls = 0
                original_private = bootstrap_r11._r11_private_support
                def changing(*args, **kwargs):
                    nonlocal calls
                    calls += 1
                    raw = original_private(*args, **kwargs)
                    if calls == 2: raw = {**raw, 'c34-execution.json': b'changed-after-check'}
                    return raw
                with patch.object(bootstrap_r11, '_r11_private_support', side_effect=changing), self.assertRaises(LifecycleError): build()
            with self.subTest(reconstruction='stale-retained-authority'):
                path = root / bootstrap_r11._R11_REVIEW_ROOT / 'parent-r69k/plan.manifest.json'
                saved = path.read_bytes();private(path,saved+b' ')
                try:
                    with self.assertRaises(LifecycleError): build()
                finally: private(path,saved)

    @_retired_r11_positive
    def test_legacy_role_funding_contract_primitives(self):
        self._check_v6_cost_primitives_after_retirement()
        self._check_role_cost_prefixes()
        self._check_global_role_funding()

    def test_funding_batch_preserves_prefixes_and_all_unknown_holds(self):
        # Real writer/archive/private origin reader in an isolated Git primary.
        # This covers coordinator-prefix ancestry; role batch admission, reuse
        # and settlement remain separate obligations of this planned case.
        import subprocess
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True, timeout=10)
            primary = bootstrap_r11._r11_coordinator_root(Path(__file__).parents[2])
            seed_path = root / bootstrap_r11._R11_COORDINATOR_SEED
            seed_path.parent.mkdir(parents=True)
            seed_path.write_bytes((primary / bootstrap_r11._R11_COORDINATOR_SEED).read_bytes())
            seed = bootstrap_r11.advance_coordinator_cost_head(root, source_path=bootstrap_r11._R11_COORDINATOR_SEED)
            review_id = 'coordinator-prefix-fixture'
            # The public experimental importer must remain refused. Seed
            # immutable historical opening DATA only, then exercise the real
            # current coordinator writer, ancestry and private origin reader.
            with self.assertRaises(LifecycleError) as disabled:
                bootstrap_r11.import_source_review_opening(root, review_id=review_id)
            self.assertEqual(disabled.exception.code, 'r11-experimental-disabled')
            directory = bootstrap_r11._r11_review_directory(root, review_id)
            self.assertFalse(directory.exists())
            receipt = {key: seed[key] for key in ('schemaVersion', 'status', 'primaryCheckout', 'head',
                'headSha256', 'measurementQualified', 'wholeHistoryComplete', 'hardCapClaim')}
            _write_exclusive(directory / 'cost-opening.json', seed['sourceRaw'], root=root)
            _write_exclusive(directory / 'cost-opening-origin.json', canonical_bytes(receipt), root=root)
            opening = bootstrap_r11.read_source_review_opening_origin(root, review_id=review_id, role_delivery=True)
            anchor = seed['headSha256']
            head_path = root / bootstrap_r11._R11_COORDINATOR_HEAD
            history = head_path.parent / 'coordinator-cost-head-history'
            def admission(number, cap, prior):
                value = {'status': 'ADMITTED_PREAPPROVED_BY_USER', 'tokenCap': cap,
                         'protectedCloseoutTokens': 3000, 'actualInputTokens': None, 'actualTokens': None,
                         'costStatus': 'UNAVAILABLE', 'priorBudgetResumed': False, 'priorUnknownHoldsReleased': 0,
                         'priorUnknownHolds': prior['head']['unknownHolds'],
                         'priorLedgerLowerBound': prior['head']['exposureLowerBound']}
                value['unknownHoldsIncludingThisWindow'] = value['priorUnknownHolds'] + cap
                value['ledgerLowerBoundIncludingThisHold'] = value['priorLedgerLowerBound'] + cap
                relative = bootstrap_r11._R11_COORDINATOR_BASE + f'/r{number}-prefix-fixture/admission.json'
                path = root / relative;path.parent.mkdir();path.write_bytes(canonical_bytes(value))
                return relative, value
            def close(relative, value):
                target = str(Path(relative).with_name('cost.json'))
                (root / target).write_bytes(canonical_bytes({**value, 'status': 'UNAVAILABLE_FULL_HOLD_RETAINED'}))
                return bootstrap_r11.advance_coordinator_cost_head(root, source_path=target)
            def read():
                return bootstrap_r11.read_coordinator_cost_head(root, ancestor_head_sha256=anchor)
            with self.subTest(prefix='current-is-its-own-ancestor'):
                initial = read()
                self.assertEqual(initial['ancestryHeadSha256s'], [anchor])
                self.assertEqual(initial['ancestor'], seed)
            rel1, window1 = admission(900, 12000, seed)
            first = bootstrap_r11.advance_coordinator_cost_head(root, source_path=rel1)
            with self.subTest(prefix='original-opening-after-admission'):
                self.assertEqual(bootstrap_r11.read_source_review_opening_origin(root, review_id=review_id, role_delivery=True), opening)
                with self.assertRaises(LifecycleError):
                    bootstrap_r11.read_source_review_opening_origin(root, review_id=review_id)
            closed1 = close(rel1, window1)
            rel2, window2 = admission(901, 16000, closed1)
            second = bootstrap_r11.advance_coordinator_cost_head(root, source_path=rel2)
            final = close(rel2, window2)
            with self.subTest(prefix='all-admissions-and-closes-reopened'):
                proof = read()
                self.assertEqual(proof['ancestryHeadSha256s'], [final['headSha256'], second['headSha256'],
                    closed1['headSha256'], first['headSha256'], seed['headSha256']])
                self.assertEqual(proof['ancestor'], seed)
                self.assertTrue(proof['ancestryQualified'])
                self.assertEqual(proof['head']['unknownHolds'], seed['head']['unknownHolds'] + 28000)
                self.assertEqual(proof['head']['exposureLowerBound'], seed['head']['exposureLowerBound'] + 28000)
                self.assertIsNone(proof['source']['actualTokens'])
                self.assertFalse(proof['wholeHistoryComplete']);self.assertEqual(proof['hardCapClaim'], 'DENY')
                self.assertEqual(bootstrap_r11.read_source_review_opening_origin(root, review_id=review_id, role_delivery=True), opening)
                self.assertEqual(opening['coordinatorHeadSha256'], seed['headSha256'])
                self.assertEqual(opening['unknownHolds'], seed['head']['unknownHolds'])
            with self.subTest(prefix='duplicate-close-does-not-double-charge'), self.assertRaises(LifecycleError):
                bootstrap_r11.advance_coordinator_cost_head(root, source_path=final['head']['sourcePath'])
            self.assertEqual(bootstrap_r11.read_coordinator_cost_head(root), final)
            archived = history / (second['headSha256'] + '.json')
            archived_raw = archived.read_bytes()
            def refuses_with(path, raw):
                saved = path.read_bytes()
                try:
                    path.write_bytes(raw)
                    with self.assertRaises(LifecycleError): read()
                finally: path.write_bytes(saved)
            with self.subTest(prefix='archived-hash-mutated'): refuses_with(archived, archived_raw+b' ')
            with self.subTest(prefix='archived-source-mutated'): refuses_with(root / rel1, (root / rel1).read_bytes()+b' ')
            with self.subTest(prefix='archived-head-missing'):
                archived.unlink()
                try:
                    with self.assertRaises(LifecycleError): read()
                finally: archived.write_bytes(archived_raw)
            with self.subTest(prefix='archived-source-missing'):
                source_path = root / rel1;saved = source_path.read_bytes();source_path.unlink()
                try:
                    with self.assertRaises(LifecycleError): read()
                finally: source_path.write_bytes(saved)
            with self.subTest(prefix='archived-head-symlink'):
                target = root / 'same-head-bytes';target.write_bytes(archived_raw);archived.unlink();archived.symlink_to(target)
                try:
                    with self.assertRaises(LifecycleError): read()
                finally: archived.unlink();archived.write_bytes(archived_raw)
            with self.subTest(prefix='unexplained-skip-even-with-valid-file-hashes'):
                refuses_with(head_path, canonical_bytes({**final['head'], 'previousHeadSha256': closed1['headSha256']}))
            with self.subTest(prefix='same-window-close-cannot-change-hold'):
                cost_path = root / final['head']['sourcePath'];saved = cost_path.read_bytes()
                value = json.loads(saved)
                for name in ('tokenCap','unknownHoldsIncludingThisWindow','ledgerLowerBoundIncludingThisHold'): value[name] += 1
                cost_raw = canonical_bytes(value);cost_path.write_bytes(cost_raw)
                try:
                    forged = {**final['head'], 'sourceSha256': _r11_sha(cost_raw),
                              'unknownHolds': value['unknownHoldsIncludingThisWindow'],
                              'exposureLowerBound': value['ledgerLowerBoundIncludingThisHold']}
                    refuses_with(head_path, canonical_bytes(forged))
                finally: cost_path.write_bytes(saved)
            with self.subTest(prefix='new-window-cannot-reset-prior-balances'):
                rel3, value = admission(902, 18000, seed)
                with self.assertRaises(LifecycleError): bootstrap_r11.advance_coordinator_cost_head(root, source_path=rel3)
                # Also test the reader against a manually forged, correctly
                # hashed append: writer rejection cannot be its only defense.
                (history / (final['headSha256'] + '.json')).write_bytes(final['headRaw'])
                forged = {**final['head'], 'sourcePath': rel3, 'sourceSha256': _r11_sha((root / rel3).read_bytes()),
                          'previousHeadSha256': final['headSha256'],
                          'unknownHolds': value['unknownHoldsIncludingThisWindow'],
                          'exposureLowerBound': value['ledgerLowerBoundIncludingThisHold']}
                refuses_with(head_path, canonical_bytes(forged))
            with self.subTest(prefix='unresolved-pending-writer'):
                pending = head_path.with_suffix('.pending.json');pending.write_bytes(b'{}')
                try:
                    with self.assertRaises(LifecycleError): read()
                finally: pending.unlink()
            for invalid in ('f'*64, '', 'a'*63, True, 7):
                with self.subTest(prefix='unknown-or-invalid-anchor', value=invalid), self.assertRaises(LifecycleError):
                    bootstrap_r11.read_coordinator_cost_head(root, ancestor_head_sha256=invalid)
            with self.subTest(prefix='strict-delivery-type'), self.assertRaises(LifecycleError):
                bootstrap_r11.read_source_review_opening_origin(root, review_id=review_id, role_delivery=1)
            with self.subTest(prefix='typed-opening-receipt-is-not-bool-int-equality'):
                receipt = bootstrap_r11._r11_review_directory(root, review_id) / 'cost-opening-origin.json'
                saved = receipt.read_bytes();value = json.loads(saved);value['measurementQualified'] = 0
                receipt.write_bytes(canonical_bytes(value))
                try:
                    with self.assertRaises(LifecycleError):
                        bootstrap_r11.read_source_review_opening_origin(root, review_id=review_id, role_delivery=True)
                finally: receipt.write_bytes(saved)
            with self.subTest(prefix='archive-stability-reread-required'):
                from agent_lifecycle.accounting import declared_ledger as coordinator_ledger
                original_read = coordinator_ledger.read_authority_bytes;seen = 0
                def changing(path, **kw):
                    nonlocal seen
                    if path == archived:
                        seen += 1
                        if seen == 2: archived.write_bytes(archived_raw+b' ')
                    return original_read(path, **kw)
                try:
                    with patch.object(coordinator_ledger, 'read_authority_bytes', side_effect=changing), self.assertRaises(LifecycleError): read()
                finally: archived.write_bytes(archived_raw)
            self.assertEqual(bootstrap_r11.read_coordinator_cost_head(root), final)
            self.assertEqual(bootstrap_r11.read_source_review_opening_origin(root, review_id=review_id, role_delivery=True), opening)


    def _check_retired_v5_runtime(self):
        m=bootstrap_r11
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();binding={'threadId':'U'*256}
            cases=[
                ('basis',lambda mode:m._r11_review_cost_basis(root,'review',role_delivery=mode)),
                ('read-cost',lambda mode:m.read_source_review_cost(root,review_id='review',role_delivery=mode)),
                ('reserve-cost',lambda mode:m.reserve_source_review_cost(root,review_id='review',binding=binding,role_delivery=mode)),
                ('settle-cost',lambda mode:m.settle_source_review_cost(root,review_id='review',binding=binding,role_delivery=mode)),
                ('before-start',lambda mode:m._r11_cost_before_start(root,'review',binding,1,1,role_delivery=mode)),
                ('costed-worker',lambda mode:m._supervise_costed_source_review_worker(root,review_id='review',binding=binding,
                    worker_path=root/'worker.py',instruction_path=root/'input.json',expected_instruction_sha256='0'*64,timeout_seconds=1,role_delivery=mode)),
                ('producer',lambda mode:m.collect_source_review_producer(root,review_id='review',shard_id='r11-01',role_delivery=mode)),
                ('rpc',lambda mode:m._exchange_source_review_rpc(root,binding=binding,expected_request=b'',expected_subject={},
                    model='model',binary_path=root/'codex',reader=None,writer=None,role_delivery=mode)),
                ('host-collection',lambda mode:m.collect_source_review_host(root,binding=binding,expected_request=b'',expected_subject={},role_delivery=mode)),
                ('prelude',lambda mode:m._r11_match_host_prelude(root,binding,'model',[],role_delivery=mode)),
            ]
            for name,call in cases:
                for mode in (False,1):
                    with self.subTest(retired=name,mode=repr(mode)),self.assertRaises(LifecycleError) as raised:call(mode)
                    self.assertEqual(raised.exception.code,'r11-v5-runtime-retired');self.assertEqual(list(root.iterdir()),[])
            stubs=[
                ('dispatch-read',lambda:m._r11_read_live_dispatch(root,binding)),
                ('dispatch-seal',lambda:m._r11_seal_live_dispatch(root,root/'input.json',planned_binding=binding,template=b'',expected_subject={},started={})),
                ('closed-v5-funding',lambda:m._r11_closed_worker_funding(root,'review',0,{})),
                ('accounted-v5',lambda:m.collect_source_review_accounted_evidence(root,review_id='review')),
                ('supervised-v5',lambda:m.collect_source_review_supervised_evidence(root,review_id='review')),
                ('origin-v5',lambda:m.collect_source_review_origin_bound_evidence(root,review_id='review')),
                ('metadata-v5',lambda:m._r11_thread_preparation_basis(root,'review',1,1)),
                ('placeholder-cost',lambda:m._r11_cost_worker(root,binding,1,review_id='review',cost_chain_sha='0'*64,request_sha='1'*64)),
            ]
            for name,call in stubs:
                with self.subTest(retired=name),self.assertRaises(LifecycleError) as raised:call()
                self.assertEqual(raised.exception.code,'r11-v5-runtime-retired');self.assertEqual(list(root.iterdir()),[])
            with self.subTest(retired='private-host-default-model-lane'),self.assertRaises(LifecycleError) as raised:
                m._run_source_review_app_server_worker(root,binding=binding,binary_path=root/'codex',expected_request=b'',expected_subject={},model='model')
            self.assertEqual(raised.exception.code,'r11-role-send-mode');self.assertEqual(list(root.iterdir()),[])
            with self.subTest(retired='v6-cannot-request-v5-live-dispatch'),self.assertRaises(LifecycleError) as raised:
                m._exchange_source_review_rpc(root,binding=binding,expected_request=b'',expected_subject={},model='model',binary_path=root/'codex',
                    reader=None,writer=None,role_delivery=True,live_instruction_path=root/'input.json')
            self.assertEqual(raised.exception.code,'r11-v5-runtime-retired');self.assertEqual(list(root.iterdir()),[])

    def _check_retired_v5_auxiliaries(self):
        m=bootstrap_r11
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve()
            sentinel=root/'existing-evidence.json';sentinel.write_bytes(b'unknown holds remain')
            def forbidden(*a,**kw):raise AssertionError('retired entry accessed current evidence')
            with patch.object(m,'read_source_review_catalog',new=forbidden), \
                 patch.object(m,'collect_source_review_threads',new=forbidden), \
                 patch.object(m,'_r11_json',new=forbidden), \
                 patch.object(Path,'exists',new=forbidden),patch.object(Path,'is_symlink',new=forbidden):
                calls=[
                    ('bind-v5-template',lambda:m._r11_bind_request(b'{}', 'thread',245760)),
                    ('choose-v5-assignment',lambda:m._r11_cost_assignment_path(root)),
                    ('qualify-v5-catalog-fit',lambda:m._r11_source_review_catalog_fit(root,review_id='review',
                        binary_path=root/'codex',binding={},model='model',candidate={},model_context_window=1000000)),
                    ('join-v5-thread-assignment',lambda:m._r11_assignment_thread_preparation(root,'review',[],'model')),
                ]
                for name,call in calls:
                    with self.subTest(retiredAuxiliary=name):
                        with self.assertRaises(LifecycleError) as refusal:call()
                        self.assertEqual(refusal.exception.code,'r11-v5-runtime-retired')
                        self.assertEqual(sentinel.read_bytes(),b'unknown holds remain')
                        self.assertEqual(list(root.iterdir()),[sentinel])

    def _check_v6_producer_after_retirement(self):
        # Test the independently re-read producer join without replaying the
        # slow joined role/host fixture. These boundaries do not prove a host.
        m=bootstrap_r11
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();binding={'operationId':'op','shardId':'source-01','threadId':'actual-thread','binarySha256':'1'*64,'transportSourceSha256':'2'*64}
            reserved={'binding':binding,'requestSha256':'3'*64};worker_evidence={'terminal.json':'4'*64}
            settled={'binding':binding,'reservationSha256':canonical_digest(reserved),'worker':{'state':'WORKER_PROCESS_FINISHED','evidenceSha256':worker_evidence}}
            instruction={'reviewId':'review','binding':binding,'metadataThreadOriginQualified':True,'reservationSha256':canonical_digest(reserved),
                'heldUnknownTokens':50000,'costChainSha256':'5'*64,'metadataOrigin':{'fixture':'original-clock'}}
            basis={'instruction':instruction,'subject':{'roleKind':'SOURCE'},'request':b'original raw request'}
            host={'binding':binding,'status':'HOST_SUPERVISION_MATCHED','worker':{'status':'WORKER_PROCESS_FINISHED','heldUnknownTokens':50000},
                'workerEvidenceSha256':canonical_digest(worker_evidence),'hostEvidenceSha256':'6'*64,'costReservationSha256':'5'*64,'transport':{'fixture':'raw-host-join'}}
            cost={'fundingAdmitted':True,'rolePrefixesAnchored':True,'reservations':[reserved],'settlements':[settled]}
            with patch.object(m,'_r11_read_fixed_worker_input',new=lambda *a,**kw:copy.deepcopy(basis)), \
                 patch.object(m,'collect_source_review_host',new=lambda *a,**kw:copy.deepcopy(host)), \
                 patch.object(m,'read_source_review_cost',new=lambda *a,**kw:copy.deepcopy(cost)):
                def collect():return m.collect_source_review_producer(root,review_id='review',shard_id='source-01',role_delivery=True)
                with self.subTest(producerRetirement='v6-retains-completed-original-producer-join'):
                    result=collect();self.assertTrue(result['producerQualified']);self.assertFalse(result['firstNativeBootstrapEligible'])
                    self.assertEqual(result['requestSha256'],hashlib.sha256(basis['request']).hexdigest());self.assertEqual(result['costSettlementSha256'],canonical_digest(settled))
                for field,new in [('fundingAdmitted',False),('rolePrefixesAnchored',False),('settlements',[]),('reservations',[reserved,reserved])]:
                    old=cost[field];cost[field]=new
                    try:
                        with self.subTest(producerRetirement='reject-'+field),self.assertRaises(LifecycleError):collect()
                    finally:cost[field]=old
                old=settled['worker']['state'];settled['worker']['state']='WORKER_FAILED'
                try:
                    with self.subTest(producerRetirement='failed-original-worker'),self.assertRaises(LifecycleError):collect()
                finally:settled['worker']['state']=old
                old=host['workerEvidenceSha256'];host['workerEvidenceSha256']='0'*64
                try:
                    with self.subTest(producerRetirement='foreign-worker-proof'),self.assertRaises(LifecycleError):collect()
                finally:host['workerEvidenceSha256']=old
                calls=[]
                def changed(*a,**kw):
                    calls.append(True);answer=copy.deepcopy(basis)
                    if len(calls)>1:answer['request']=b'changed earlier proof'
                    return answer
                with patch.object(m,'_r11_read_fixed_worker_input',new=changed),self.subTest(producerRetirement='earlier-input-changed-during-join'),self.assertRaises(LifecycleError):collect()

    def _check_v6_rpc_after_retirement(self):
        from agent_lifecycle.adapter_sessions.codex_exact_prompt import _file_sha
        m=bootstrap_r11
        for scenario in ('complete','changed-send-basis','changed-summary','unread-bootstrap'):
            with tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary).resolve();binary=root/'codex';binary.write_bytes(b'fixture-not-executable')
                binding={'operationId':'role-op','shardId':'shared-01','threadId':'actual-thread','binarySha256':_file_sha(binary),'transportSourceSha256':_file_sha(Path(m.__file__))}
                request={'id':1,'method':'turn/start','params':{'threadId':binding['threadId'],'approvalPolicy':'never','sandboxPolicy':{'type':'readOnly'},'cwd':str(root),'model':'fixture-model'}}
                raw=canonical_bytes(request)+b'\n';subject={'roleKind':'SHARED'};sent=[];bootstrap=[];groups=[{'kind':'SESSION','raw':canonical_bytes(binding),'firstNs':1,'lastNs':1}]
                thread={'id':binding['threadId'],'turns':[],'ephemeral':False,'forkedFromId':None,'historyMode':'legacy','status':{'type':'idle'}}
                response={'turn':{'id':'turn','status':'inProgress','error':None}}
                frames=[{'id':1,'result':response},{'method':'item/completed','params':{'item':{'type':'agentMessage','text':'fixture-body'}}},
                    {'method':'turn/completed','params':{'threadId':binding['threadId'],'turn':{'id':'turn','status':'completed','error':None}}},
                    {'id':2,'result':{'fixture':'stable-read'}},{'id':3,'result':{'fixture':'stable-read'}}]
                def group(kind,raw):groups.append({'kind':kind,'raw':raw,'firstNs':len(groups)+1,'lastNs':len(groups)+1})
                class Wire:
                    def __init__(self,*args):self.buffer=b'';self.directory=root/'private-wire'
                    def send_bootstrap(self,row):
                        bootstrap.append(copy.deepcopy(row));wire_raw=canonical_bytes(row)+b'\n'
                        group('SEND_PENDING',wire_raw);group('WRITE_ACCEPTED',wire_raw);group('FLUSHED',canonical_bytes({'sha256':hashlib.sha256(wire_raw).hexdigest()}))
                    def bootstrap_reply(self,ident,thread_id):
                        if ident==1_000_001:answer={'userAgent':'fixture'}
                        elif ident==1_000_002:answer={'data':[{'model':'fixture-model'}]}
                        elif ident==1_000_003:answer={'thread':thread,'model':'fixture-model'}
                        else:
                            answer={'thread':{**thread,'id':'foreign' if scenario=='changed-summary' else binding['threadId']}}
                            if scenario=='unread-bootstrap':self.buffer=b'unread'
                        group('RECEIVED_CHUNK',canonical_bytes({'id':ident,'result':answer})+b'\n');return answer
                    def receive(self,transcript):
                        answer=frames.pop(0);wire_raw=canonical_bytes(answer)+b'\n';group('RECEIVED_CHUNK',wire_raw);return wire_raw,answer
                class Transcript:
                    def __init__(self,*a,**kw):pass
                    def send(self,raw,writer):sent.append(raw)
                calls=[]
                def send_basis(*a,**kw):
                    calls.append(True);return {'reviewId':'review','catalogEvidenceSha256':'1'*64,'fixture':len(calls) if scenario=='changed-send-basis' else 1}
                with patch.object(m,'_R11AppServerPipe',new=Wire),patch.object(m,'SourceReviewTranscript',new=Transcript), \
                     patch.object(m,'_r11_role_send_basis',new=send_basis),patch.object(m,'_r11_require_fresh_review_catalog',new=lambda *a,**kw:{'evidenceSha256':'1'*64}), \
                     patch.object(m,'collect_source_review_transport',new=lambda *a,**kw:{'fixture':'separate-transport-boundary'}):
                    def exchange():return m._exchange_source_review_rpc(root,binding=binding,expected_request=raw,expected_subject=subject,model='fixture-model',binary_path=binary,reader=None,writer=None,role_delivery=True)
                    with self.subTest(retainedRpc=scenario):
                        if scenario=='complete':
                            result=exchange();self.assertEqual(result['threadCreationMode'],'RESERVED_EMPTY_ROLE_THREAD');self.assertFalse(result['firstNativeBootstrapEligible'])
                            self.assertEqual(sent[0],raw);self.assertEqual([json.loads(x)['method'] for x in sent],['turn/start','thread/read','thread/read'])
                            self.assertEqual([x['method'] for x in bootstrap],['initialize','initialized','model/list','thread/resume','thread/read'])
                            prelude=m._r11_match_host_prelude(root,binding,'fixture-model',groups,role_delivery=True)
                            self.assertEqual(prelude['resumeSha256'],result['resumeSha256']);self.assertEqual(prelude['summarySha256'],result['summarySha256'])
                            self.assertEqual((root/m._R11_REVIEW_ROOT/'shards/shared-01/review-body.raw').read_bytes(),b'fixture-body')
                        else:
                            with self.assertRaises(LifecycleError):exchange()
                            self.assertEqual(sent,[]);self.assertNotIn('thread/start',[x['method'] for x in bootstrap])

    def _check_v6_cost_primitives_after_retirement(self):
        from datetime import datetime,timedelta
        m=bootstrap_r11
        root,authority,base,inventory,funding,shared,source=self._role_request_fixture();root=root.resolve()
        identity=m._r11_role_identity(authority=authority,base_raw=canonical_bytes(base),inventory_raw=canonical_bytes(inventory),funding_raw=canonical_bytes(funding))
        basis={'identity':identity,'schemas':authority['schemas']};role=inventory['roles'][0]
        start=datetime.fromisoformat(funding['admittedAtUtc'].replace('Z','+00:00'))+timedelta(seconds=1)
        dispatch={'binding':{'operationId':role['operationId'],'shardId':role['roleId'],'threadId':'actual-thread','binarySha256':'1'*64,'transportSourceSha256':'2'*64},
            'requestSha256':'3'*64,'sharedEvidenceSha256':None,'reservedAtUtc':start.isoformat(),'absoluteDeadlineUtc':(start+timedelta(seconds=60)).isoformat()}
        prefix={'immutable-role-base':'4'*64}
        with self.subTest(retainedCost='reservation-retains-full-batch-hold-and-prefix'):
            value=m._r11_cost_reservation(basis,0,None,dispatch=dispatch,prefix=prefix)
            self.assertEqual(value['heldUnknownTokens'],funding['admittedUnknownHolds']);self.assertEqual(value['holdIncrement'],0)
            self.assertEqual(value['previousCostPrefixSha256'],canonical_digest(prefix));self.assertIsNone(value['actualModelTokens']);self.assertFalse(value['retryAuthorized'])
        with self.subTest(retainedCost='legacy-basis-refuses-before-reservation'),self.assertRaises(LifecycleError) as raised:m._r11_cost_reservation({'assignment':{},'opening':{}},0,None)
        self.assertEqual(raised.exception.code,'r11-v5-runtime-retired')
        for key,new in [('threadId','U'*256),('shardId','r11-01'),('operationId','foreign')]:
            changed=copy.deepcopy(dispatch);changed['binding'][key]=new
            with self.subTest(retainedCost='wrong-'+key),self.assertRaises(LifecycleError):m._r11_cost_reservation(basis,0,None,dispatch=changed,prefix=prefix)
        changed=copy.deepcopy(dispatch);changed['absoluteDeadlineUtc']=(start+timedelta(seconds=1801)).isoformat()
        with self.subTest(retainedCost='no-new-deadline'),self.assertRaises(LifecycleError):m._r11_cost_reservation(basis,0,None,dispatch=changed,prefix=prefix)
        directory=m._r11_review_directory(root,base['reviewId'])/'role-cost';m._write(root,directory/'shared-01/reservation.json',value)
        ids=[r['roleId'] for r in inventory['roles']]
        with self.subTest(retainedCost='actual-private-v6-cost-files'):
            self.assertEqual(m._r11_cost_files(root,base['reviewId'],role_ids=ids),{'shared-01/reservation.json':canonical_bytes(value)})
        with self.subTest(retainedCost='legacy-storage-selector-refuses'),self.assertRaises(LifecycleError) as raised:m._r11_cost_files(root,base['reviewId'])
        self.assertEqual(raised.exception.code,'r11-v5-runtime-retired')
        m._write(root,directory/'shared-01/settlement.pending.json',{})
        with self.subTest(retainedCost='partial-cost-still-refuses'),self.assertRaises(LifecycleError):m._r11_cost_files(root,base['reviewId'],role_ids=ids)

    def _check_role_cost_prefixes(self):
        # Real private files, current frozen schemas and isolated coordinator
        # journal. These are declared prefixes, NOT globally admitted funding.
        import subprocess
        root, authority, base, inventory, funding, _, _ = self._role_request_fixture()
        root = root.resolve()
        subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True, timeout=10)
        primary = bootstrap_r11._r11_coordinator_root(Path(__file__).parents[2])
        seed_path = root / bootstrap_r11._R11_COORDINATOR_SEED
        seed_path.parent.mkdir(parents=True)
        seed_path.write_bytes((primary / bootstrap_r11._R11_COORDINATOR_SEED).read_bytes())
        seed = bootstrap_r11.advance_coordinator_cost_head(root, source_path=bootstrap_r11._R11_COORDINATOR_SEED)
        review_id = base['reviewId']
        bootstrap_r11.import_source_review_opening(root, review_id=review_id)
        origin = bootstrap_r11.read_source_review_opening_origin(root, review_id=review_id, role_delivery=True)
        base.update(openingHeadSha256=origin['coordinatorHeadSha256'], openingSourceSha256=origin['costOpeningSha256'])
        inventory['baseSha256'] = canonical_digest(base)
        funding.update(baseSha256=canonical_digest(base), roleInventorySha256=canonical_digest(inventory),
            priorHeadSha256=seed['headSha256'], priorUnknownHolds=seed['head']['unknownHolds'],
            priorExposureLowerBound=seed['head']['exposureLowerBound'],
            admittedUnknownHolds=seed['head']['unknownHolds']+720000,
            admittedExposureLowerBound=seed['head']['exposureLowerBound']+720000)
        directory = bootstrap_r11._r11_review_directory(root, review_id)
        for name, value in [('role-base.json',base), ('role-inventory.json',inventory), ('role-funding.json',funding)]:
            _write_exclusive(directory/name, canonical_bytes(value), root=root)
        def read(): return bootstrap_r11.read_source_review_cost(root, review_id=review_id, role_delivery=True)
        with self.subTest(roleCost='all-slots-retained-before-any-reservation'):
            initial = read()
            self.assertFalse(initial['fundingAdmitted']);self.assertFalse(initial['firstNativeBootstrapEligible'])
            self.assertEqual(initial['declaredUnknownHoldsAtFunding'], funding['admittedUnknownHolds'])
            self.assertEqual(initial['unreservedRoleIds'], ['shared-01','source-01'])
            self.assertIsNone(initial['actualModelTokens']);self.assertEqual(initial['releasedUnknownTokens'],0)
        basis = bootstrap_r11._r11_review_cost_basis(root, review_id, role_delivery=True)
        binding = {'operationId': inventory['roles'][0]['operationId'], 'shardId': 'shared-01',
                   'threadId': 'actual-shared-thread', 'binarySha256': 'a'*64, 'transportSourceSha256': 'b'*64}
        dispatch = {'binding': binding, 'requestSha256': 'c'*64, 'sharedEvidenceSha256': None,
                    'reservedAtUtc': '2026-09-28T00:01:00Z', 'absoluteDeadlineUtc': '2026-09-28T00:31:00Z'}
        reservation = bootstrap_r11._r11_cost_reservation(basis,0,None,dispatch=dispatch,prefix=initial['prefixSha256'])
        path = directory/'role-cost/shared-01/reservation.json'
        _write_exclusive(path,canonical_bytes(reservation),root=root)
        with self.subTest(roleCost='dispatch-consumes-slot-without-double-charge'):
            reserved = read()
            self.assertEqual(reserved['reservations'],[reservation])
            self.assertEqual(reservation['holdIncrement'],0)
            self.assertEqual(reserved['declaredUnknownHoldsAtFunding'],initial['declaredUnknownHoldsAtFunding'])
            self.assertEqual(reserved['unreservedRoleIds'],['source-01'])
        def mutation_refuses(target,value):
            saved=target.read_bytes();target.write_bytes(canonical_bytes(value))
            try:
                with self.assertRaises(LifecycleError): read()
            finally: target.write_bytes(saved)
        for key,value in [('holdIncrement',360000),('heldUnknownTokens',0),('actualModelTokens',0),
                          ('previousCostPrefixSha256','f'*64),('requestSha256','x'),('tokenCap',300000),
                          ('protectedCloseoutTokens',0),('absoluteDeadlineUtc','2026-09-28T00:31:01Z'),
                          ('reservedAtUtc','2026-09-27T23:59:59Z'),('retryAuthorized',0)]:
            with self.subTest(roleCost='reservation-mutation',field=key): mutation_refuses(path,{**reservation,key:value})
        for key,value in [('threadId','U'*256),('threadId','ё'*129),('operationId','foreign'),('shardId','source-01')]:
            with self.subTest(roleCost='dispatch-identity',field=key,value=value):
                mutation_refuses(path,{**reservation,'binding':{**binding,key:value}})
        for filename in ('settlement.pending.json','extra.json'):
            extra=path.parent/filename
            with self.subTest(roleCost='pending-or-extra',filename=filename):
                _write_exclusive(extra,b'{}',root=root)
                try:
                    with self.assertRaises(LifecycleError):read()
                finally:extra.unlink()
        worker = bootstrap_r11._r11_cost_worker(root,binding,funding['admittedUnknownHolds'],
            review_id=review_id,cost_chain_sha=reserved['costChainSha256'],request_sha=dispatch['requestSha256'])
        self.assertEqual(worker['state'],'START_UNCERTAIN')
        settlement={'schemaVersion':'alk-r11-role-cost-settlement.v1','reviewId':review_id,'binding':binding,
            'reservationSha256':canonical_digest(reservation),'previousCostPrefixSha256':reserved['costChainSha256'],
            'worker':worker,'costStatus':'UNAVAILABLE','actualModelTokens':None,'releasedUnknownTokens':0,
            'heldUnknownTokens':funding['admittedUnknownHolds'],
            'accountedExposureLowerBound':funding['admittedExposureLowerBound'],'retryAuthorized':False,'hardCapClaim':'DENY'}
        settled_path=path.with_name('settlement.json');_write_exclusive(settled_path,canonical_bytes(settlement),root=root)
        with self.subTest(roleCost='uncertain-worker-and-unused-tail-retain-full-batch'):
            settled=read();self.assertEqual(settled['settlements'],[settlement])
            self.assertEqual(settled['declaredUnknownHoldsAtFunding'],initial['declaredUnknownHoldsAtFunding'])
            self.assertFalse(settled['allRolesSettled']);self.assertFalse(settled['fundingAdmitted'])
        for key,value in [('releasedUnknownTokens',360000),('actualModelTokens',0),('heldUnknownTokens',0),
                          ('reservationSha256','f'*64),('previousCostPrefixSha256','f'*64),('retryAuthorized',True)]:
            with self.subTest(roleCost='settlement-mutation',field=key): mutation_refuses(settled_path,{**settlement,key:value})
        second_dispatch={**dispatch,'binding':{**binding,'operationId':inventory['roles'][1]['operationId'],
            'shardId':'source-01','threadId':'actual-source-thread'},'sharedEvidenceSha256':'d'*64}
        second=bootstrap_r11._r11_cost_reservation(basis,1,canonical_bytes(settlement),
            dispatch=second_dispatch,prefix=settled['prefixSha256'])
        second_path=directory/'role-cost/source-01/reservation.json'
        with self.subTest(roleCost='cannot-continue-after-uncertain-worker'):
            _write_exclusive(second_path,canonical_bytes(second),root=root)
            try:
                with self.assertRaises(LifecycleError):read()
            finally:second_path.unlink();second_path.parent.rmdir()
        # Only this branch controls the worker collector result to exercise
        # successful ordering. It is not actual positive host/worker evidence.
        finished={'state':'WORKER_PROCESS_FINISHED','evidenceSha256':{}}
        first_finished={**settlement,'worker':finished}
        settled_path.write_bytes(canonical_bytes(first_finished))
        try:
            with patch.object(bootstrap_r11,'_r11_cost_worker',return_value=finished):
                first_prefix=read()
                second=bootstrap_r11._r11_cost_reservation(basis,1,canonical_bytes(first_finished),
                    dispatch=second_dispatch,prefix=first_prefix['prefixSha256'])
                _write_exclusive(second_path,canonical_bytes(second),root=root)
                next_prefix=read()
                second_settlement={**settlement,'binding':second['binding'],
                    'reservationSha256':canonical_digest(second),'previousCostPrefixSha256':next_prefix['costChainSha256'],
                    'worker':finished}
                next_settled=second_path.with_name('settlement.json')
                _write_exclusive(next_settled,canonical_bytes(second_settlement),root=root)
                with self.subTest(roleCost='two-slots-one-batch-controlled-worker'):
                    full=read();self.assertTrue(full['allRolesSettled']);self.assertFalse(full['fundingAdmitted'])
                    self.assertEqual(full['declaredUnknownHoldsAtFunding'],initial['declaredUnknownHoldsAtFunding'])
                    self.assertEqual([r['holdIncrement'] for r in full['reservations']],[0,0])
                    self.assertTrue(all(full['prefixSha256'][k]==v for k,v in first_prefix['prefixSha256'].items()))
                for key,value in [('previousSettlementSha256','f'*64),('previousCostPrefixSha256',initial['costChainSha256']),
                                  ('heldUnknownTokens',funding['admittedUnknownHolds']+360000),('subjectSha256','e'*64)]:
                    with self.subTest(roleCost='source-prefix-mutation',field=key):mutation_refuses(second_path,{**second,key:value})
                with self.subTest(roleCost='source-thread-reuse'):
                    mutation_refuses(second_path,{**second,'binding':{**second['binding'],'threadId':binding['threadId']}})
                with self.subTest(roleCost='unsettled-earlier-slot-refuses'):
                    saved=settled_path.read_bytes();settled_path.unlink()
                    try:
                        with self.assertRaises(LifecycleError):read()
                    finally:settled_path.write_bytes(saved);settled_path.chmod(0o600)
        finally:
            if second_path.with_name('settlement.json').exists():second_path.with_name('settlement.json').unlink()
            if second_path.exists():second_path.unlink()
            if second_path.parent.exists():second_path.parent.rmdir()
            settled_path.write_bytes(canonical_bytes(settlement))
        with self.subTest(roleCost='all-33-slots-storage-bound'):
            ids=['shared-01']+[f'source-{i:02d}' for i in range(1,33)]
            for name in ids[1:]:_write_exclusive(directory/'role-cost'/name/'reservation.json',b'{}',root=root)
            try:
                self.assertEqual(len(bootstrap_r11._r11_cost_files(root,review_id,role_ids=ids)),34)
                with self.assertRaises(LifecycleError):bootstrap_r11._r11_cost_files(root,review_id,role_ids=ids+['source-33'])
                missing=directory/'role-cost/source-16/reservation.json';missing.unlink()
                with self.assertRaises(LifecycleError):bootstrap_r11._r11_cost_files(root,review_id,role_ids=ids)
            finally:
                for name in ids[1:]:shutil.rmtree(directory/'role-cost'/name)
        # A structurally legal credit is still not proof of an existing unused
        # hold; current implementation refuses instead of inventing reuse.
        credit={'windowId':'fixture-window','operationId':binding['operationId'],'roleId':'shared-01',
                'tokenCap':360000,'reservationSha256':'e'*64,'priorHeadSha256':seed['headSha256']}
        with self.subTest(roleCost='unproved-first-credit-refuses'):
            mutation_refuses(directory/'role-funding.json',{**funding,'reusedFirstHold':credit,
                'admittedUnknownHolds':funding['admittedUnknownHolds']-360000,
                'admittedExposureLowerBound':funding['admittedExposureLowerBound']-360000})
        with self.subTest(roleCost='prior-balance-reset-refuses'):
            mutation_refuses(directory/'role-funding.json',{**funding,'priorUnknownHolds':0,'admittedUnknownHolds':720000})
        # Independent ordinary coordinator append must not rebase old role bytes.
        window={'status':'ADMITTED_PREAPPROVED_BY_USER','tokenCap':12000,'protectedCloseoutTokens':3000,
            'actualInputTokens':None,'actualTokens':None,'costStatus':'UNAVAILABLE','priorBudgetResumed':False,
            'priorUnknownHolds':seed['head']['unknownHolds'],'priorLedgerLowerBound':seed['head']['exposureLowerBound'],
            'unknownHoldsIncludingThisWindow':seed['head']['unknownHolds']+12000,
            'ledgerLowerBoundIncludingThisHold':seed['head']['exposureLowerBound']+12000}
        relative=bootstrap_r11._R11_COORDINATOR_BASE+'/r900-role-cost-fixture/admission.json'
        (root/relative).parent.mkdir();(root/relative).write_bytes(canonical_bytes(window))
        bootstrap_r11.advance_coordinator_cost_head(root,source_path=relative)
        with self.subTest(roleCost='external-append-preserves-original-prefix'):
            advanced=read();self.assertEqual(advanced['prefixSha256'],settled['prefixSha256'])
            self.assertEqual(advanced['costChainSha256'],settled['costChainSha256'])
            self.assertEqual(advanced['reservations'],settled['reservations'])
            self.assertEqual(advanced['currentCoordinatorUnknownHolds'],settled['currentCoordinatorUnknownHolds']+12000)
            self.assertEqual(advanced['declaredUnknownHoldsAtFunding'],settled['declaredUnknownHoldsAtFunding'])
        with self.subTest(roleCost='worker-byte-mutation-invalidates-settlement'):
            worker_path=bootstrap_r11._r11_worker_directory(root,binding)/'reservation.json'
            _write_exclusive(worker_path,b'{}',root=root)
            try:
                with self.assertRaises(LifecycleError):read()
            finally:worker_path.unlink();worker_path.parent.rmdir();worker_path.parent.parent.rmdir()
        with self.subTest(roleCost='missing-prefix-never-empty-success'):
            saved=path.read_bytes();path.unlink()
            try:
                with self.assertRaises(LifecycleError):read()
            finally:path.write_bytes(saved);path.chmod(0o600)
        with self.subTest(roleCost='symlink-prefix-refuses'):
            saved=path.read_bytes();target=root/'same-bytes';target.write_bytes(saved);path.unlink();path.symlink_to(target)
            try:
                with self.assertRaises(LifecycleError):read()
            finally:path.unlink();path.write_bytes(saved);path.chmod(0o600)
        with self.subTest(roleCost='stable-read-required'):
            original=bootstrap_r11._r11_cost_files;calls=0
            def changed(*a,**kw):
                nonlocal calls
                calls+=1
                if calls==2: settled_path.write_bytes(canonical_bytes({**settlement,'releasedUnknownTokens':1}))
                return original(*a,**kw)
            try:
                with patch.object(bootstrap_r11,'_r11_cost_files',side_effect=changed),self.assertRaises(LifecycleError):read()
            finally:settled_path.write_bytes(canonical_bytes(settlement))
        for mode in (1,None,'v6'):
            with self.subTest(roleCost='explicit-mode',mode=mode),self.assertRaises(LifecycleError):
                bootstrap_r11.read_source_review_cost(root,review_id=review_id,role_delivery=mode)
        with self.subTest(roleCost='legacy-cannot-spend-declared-role-schedule'),self.assertRaises(LifecycleError):
            bootstrap_r11.reserve_source_review_cost(root,review_id=review_id,binding=binding)
        self.assertEqual(read()['prefixSha256'],settled['prefixSha256'])

        with self.subTest(roleCost='retired-legacy-cannot-reuse-or-release-current-holds'):
            before=read();raw=bootstrap_r11._r11_cost_files(root,review_id,role_ids=[r['roleId'] for r in inventory['roles']])
            for operation in (bootstrap_r11.reserve_source_review_cost,bootstrap_r11.settle_source_review_cost):
                with self.assertRaises(LifecycleError) as refusal:
                    operation(root,review_id=review_id,binding=binding)
                self.assertEqual(refusal.exception.code,'r11-v5-runtime-retired')
            self.assertEqual(read(),before)
            self.assertEqual(bootstrap_r11._r11_cost_files(root,review_id,role_ids=[r['roleId'] for r in inventory['roles']]),raw)


    def _check_global_role_funding(self):
        # Actual isolated primary journal, exclusive publisher and durable raw
        # receipts. Fixture inventory is not source/support or host acceptance.
        import subprocess
        from datetime import datetime, timedelta, timezone
        root, authority, prototype_base, prototype_inventory, prototype_funding, _, _ = self._role_request_fixture()
        root=root.resolve()
        subprocess.run(['git','init','-q',str(root)],check=True,capture_output=True,timeout=10)
        primary=bootstrap_r11._r11_coordinator_root(Path(__file__).parents[2])
        seed_path=root/bootstrap_r11._R11_COORDINATOR_SEED;seed_path.parent.mkdir(parents=True)
        seed_path.write_bytes((primary/bootstrap_r11._R11_COORDINATOR_SEED).read_bytes())
        seed=bootstrap_r11.advance_coordinator_cost_head(root,source_path=bootstrap_r11._R11_COORDINATOR_SEED)
        head_path=root/bootstrap_r11._R11_COORDINATOR_HEAD
        def head():return bootstrap_r11.read_coordinator_cost_head(root)
        def read(review):return bootstrap_r11.read_source_review_cost(root,review_id=review,role_delivery=True)
        def publish(review):return bootstrap_r11.admit_source_review_funding(root,review_id=review)
        def declare(review,prefix,source_count=1):
            prior=head();bootstrap_r11.import_source_review_opening(root,review_id=review)
            origin=bootstrap_r11.read_source_review_opening_origin(root,review_id=review,role_delivery=True)
            base,inventory,funding=copy.deepcopy((prototype_base,prototype_inventory,prototype_funding))
            base.update(reviewId=review,openingHeadSha256=origin['coordinatorHeadSha256'],openingSourceSha256=origin['costOpeningSha256'])
            roles=[{**inventory['roles'][0],'operationId':prefix+'-shared'}]
            for i in range(1,source_count+1):
                roles.append({**inventory['roles'][1],'roleId':f'source-{i:02d}','operationId':prefix+f'-source-{i:02d}',
                              'requiredIntegrationScopes':inventory['roles'][1]['requiredIntegrationScopes'] if i==1 else []})
            inventory.update(reviewId=review,baseSha256=canonical_digest(base),roles=roles)
            start=datetime.now(timezone.utc).replace(microsecond=0)
            funding.update(reviewId=review,baseSha256=canonical_digest(base),roleInventorySha256=canonical_digest(inventory),
                priorHeadSha256=prior['headSha256'],priorUnknownHolds=prior['head']['unknownHolds'],
                priorExposureLowerBound=prior['head']['exposureLowerBound'],reusedFirstHold=None,
                admittedAtUtc=start.isoformat().replace('+00:00','Z'),
                absoluteDeadlineUtc=(start+timedelta(seconds=59400)).isoformat().replace('+00:00','Z'),
                tokenCap=len(roles)*360000,protectedCloseoutTokens=len(roles)*100000,
                admittedUnknownHolds=prior['head']['unknownHolds']+len(roles)*360000,
                admittedExposureLowerBound=prior['head']['exposureLowerBound']+len(roles)*360000,
                slots=[{**funding['slots'][0],'roleId':row['roleId']} for row in roles])
            directory=bootstrap_r11._r11_review_directory(root,review)
            for name,value in [('role-base.json',base),('role-inventory.json',inventory),('role-funding.json',funding)]:
                _write_exclusive(directory/name,canonical_bytes(value),root=root)
            return directory,funding,inventory
        directory,funding,inventory=declare('global-main','main')
        with self.subTest(globalFunding='declaration-is-not-admission'):
            initial=read('global-main');self.assertFalse(initial['fundingAdmitted'])
            self.assertEqual(head()['headSha256'],seed['headSha256'])
        for name,changed in [('future',{'admittedAtUtc':'2099-01-01T00:00:00Z','absoluteDeadlineUtc':'2099-01-01T01:00:00Z'}),
                             ('expired',{'admittedAtUtc':'2020-01-01T00:00:00Z','absoluteDeadlineUtc':'2020-01-01T01:00:00Z'})]:
            p=directory/'role-funding.json';saved=p.read_bytes();p.write_bytes(canonical_bytes({**funding,**changed}))
            try:
                with self.subTest(globalFunding=name),self.assertRaises(LifecycleError):publish('global-main')
                self.assertFalse((directory/'role-funding-origin.pending.json').exists())
                self.assertEqual(head()['headSha256'],seed['headSha256'])
            finally:p.write_bytes(saved)
        with self.subTest(globalFunding='retrospective-role-prefix-refuses'):
            p=directory/'role-cost';p.mkdir(mode=0o700)
            try:
                with self.assertRaises(LifecycleError):publish('global-main')
            finally:p.rmdir()
        with self.subTest(globalFunding='all-roles-admitted-exactly-once'):
            funded=publish('global-main');first=head()
            self.assertTrue(funded['fundingAdmitted']);self.assertFalse(funded['producerQualified'])
            self.assertFalse(funded['sharedEvidenceAccepted']);self.assertFalse(funded['firstNativeBootstrapEligible'])
            self.assertEqual(first['head']['unknownHolds'],seed['head']['unknownHolds']+720000)
            self.assertEqual(first['head']['exposureLowerBound'],seed['head']['exposureLowerBound']+720000)
            self.assertEqual(funded['prefixSha256'],initial['prefixSha256'])
            self.assertIsNone(first['source']['actualTokens']);self.assertEqual(first['source']['protectedCloseoutTokens'],200000)
            self.assertFalse((directory/'role-funding-origin.pending.json').exists())
        with self.subTest(globalFunding='duplicate-publish-cannot-charge-or-replace'):
            receipt_raw=(directory/'role-funding-origin.json').read_bytes();ledger_raw=head_path.read_bytes()
            with self.assertRaises(LifecycleError):publish('global-main')
            self.assertEqual(head_path.read_bytes(),ledger_raw)
            self.assertEqual((directory/'role-funding-origin.json').read_bytes(),receipt_raw)
        with self.subTest(globalFunding='pending-origin-blocks-even-after-commit'):
            p=directory/'role-funding-origin.pending.json';_write_exclusive(p,receipt_raw,root=root)
            try:
                with self.assertRaises(LifecycleError):read('global-main')
            finally:p.unlink()
        with self.subTest(globalFunding='missing-receipt-retains-global-hold-without-grant'):
            p=directory/'role-funding-origin.json';p.unlink()
            try:
                self.assertFalse(read('global-main')['fundingAdmitted'])
                self.assertEqual(head()['head']['unknownHolds'],funding['admittedUnknownHolds'])
            finally:p.write_bytes(receipt_raw);p.chmod(0o600)
        record_path=root/first['head']['sourcePath'];record_raw=record_path.read_bytes();record=json.loads(record_raw)
        mutations=[('tokenCap',record['tokenCap']+360000),('priorUnknownHolds',0),('unknownHoldsIncludingThisWindow',0),
                   ('actualTokens',0),('priorUnknownHoldsReleased',True),('coordinatorCursor',bootstrap_r11._R11_COORDINATOR_SEED.replace('cost.json','admission.json')),
                   ('roleContractRaw',record['roleContractRaw']+' '),('roleSchemasRaw',{**record['roleSchemasRaw'],'base':record['roleSchemasRaw']['base']+' '})]
        for key,value in mutations:
            with self.subTest(globalFunding='typed-record-mutation',field=key):
                record_path.write_bytes(canonical_bytes({**record,key:value}))
                try:
                    with self.assertRaises(LifecycleError):head()
                finally:record_path.write_bytes(record_raw)
        with self.subTest(globalFunding='ordinary-window-cannot-use-role-cap'):
            bad={k:record[k] for k in ('tokenCap','protectedCloseoutTokens','actualInputTokens','actualTokens','costStatus','priorBudgetResumed')}
            bad.update(status='ADMITTED_PREAPPROVED_BY_USER',priorUnknownHolds=first['head']['unknownHolds'],
                priorLedgerLowerBound=first['head']['exposureLowerBound'],
                unknownHoldsIncludingThisWindow=first['head']['unknownHolds']+bad['tokenCap'],
                ledgerLowerBoundIncludingThisHold=first['head']['exposureLowerBound']+bad['tokenCap'])
            relative=bootstrap_r11._R11_COORDINATOR_BASE+'/r899-invalid-role-cap/admission.json'
            (root/relative).parent.mkdir();(root/relative).write_bytes(canonical_bytes(bad))
            with self.assertRaises(LifecycleError):bootstrap_r11.advance_coordinator_cost_head(root,source_path=relative)
            self.assertEqual(head()['headSha256'],first['headSha256'])
        # A second independently budgeted batch uses the same global stream.
        other_dir,other_funding,_=declare('global-second','second')
        with self.subTest(globalFunding='second-batch-retains-all-earlier-holds'):
            second=publish('global-second');second_head=head()
            self.assertEqual(second_head['head']['unknownHolds'],seed['head']['unknownHolds']+1440000)
            old=read('global-main');self.assertEqual(old['prefixSha256'],funded['prefixSha256'])
            self.assertEqual(old['fundingOrigin']['receiptSha256'],funded['fundingOrigin']['receiptSha256'])
            self.assertEqual(old['fundingOrigin']['unknownHolds'],second_head['head']['unknownHolds'])
        # Closed ordinary windows can follow a role admission; old window close
        # or stale number cannot reset the balance. Open windows cannot be split.
        with self.subTest(globalFunding='old-coordinator-close-cannot-overwrite-roles'),self.assertRaises(LifecycleError):
            bootstrap_r11.advance_coordinator_cost_head(root,source_path=bootstrap_r11._R11_COORDINATOR_SEED)
        window={'status':'ADMITTED_PREAPPROVED_BY_USER','tokenCap':12000,'protectedCloseoutTokens':3000,
            'actualInputTokens':None,'actualTokens':None,'costStatus':'UNAVAILABLE','priorBudgetResumed':False,
            'priorUnknownHoldsReleased':0,'priorUnknownHolds':second_head['head']['unknownHolds'],
            'priorLedgerLowerBound':second_head['head']['exposureLowerBound'],
            'unknownHoldsIncludingThisWindow':second_head['head']['unknownHolds']+12000,
            'ledgerLowerBoundIncludingThisHold':second_head['head']['exposureLowerBound']+12000}
        relative=bootstrap_r11._R11_COORDINATOR_BASE+'/r900-after-role/admission.json'
        (root/relative).parent.mkdir();(root/relative).write_bytes(canonical_bytes(window))
        bootstrap_r11.advance_coordinator_cost_head(root,source_path=relative)
        open_dir,_,_=declare('open-window','open')
        with self.subTest(globalFunding='cannot-interpose-role-funding-in-open-coordinator-window'):
            open_head=head()
            with self.assertRaises(LifecycleError):publish('open-window')
            self.assertFalse((open_dir/'role-funding-origin.pending.json').exists())
            self.assertEqual(head()['headSha256'],open_head['headSha256'])
        close_relative=str(Path(relative).with_name('cost.json'))
        (root/close_relative).write_bytes(canonical_bytes({**window,'status':'UNAVAILABLE_FULL_HOLD_RETAINED'}))
        bootstrap_r11.advance_coordinator_cost_head(root,source_path=close_relative)
        with self.subTest(globalFunding='ordinary-append-preserves-funding-and-role-prefix'):
            later=read('global-main');self.assertEqual(later['prefixSha256'],funded['prefixSha256'])
            self.assertEqual(later['fundingOrigin']['receipt'],funded['fundingOrigin']['receipt'])
            self.assertEqual(later['fundingOrigin']['unknownHolds'],second_head['head']['unknownHolds']+12000)
        with self.subTest(globalFunding='stale-batch-cannot-be-rebased-at-publication'),self.assertRaises(LifecycleError):
            publish('open-window')
        duplicate_dir,duplicate_funding,duplicate_inventory=declare('duplicate-operation','main')
        with self.subTest(globalFunding='duplicate-operations-rejected-globally'):
            before=head()
            with self.assertRaises(LifecycleError):publish('duplicate-operation')
            self.assertEqual(head()['headSha256'],before['headSha256'])
            self.assertTrue((duplicate_dir/'role-funding-origin.pending.json').exists())
            with self.assertRaises(LifecycleError):read('duplicate-operation')
        # Independently forge a well-hashed duplicate append, bypassing writer:
        # the history reader must also reject it. Only isolated fixture files.
        relative_duplicate=bootstrap_r11._R11_COORDINATOR_BASE+'/role-funding/'+canonical_digest(duplicate_funding)+'/admission.json'
        duplicate_raw=(root/relative_duplicate).read_bytes()
        forged=bootstrap_r11._r11_coordinator_head_value(relative_duplicate,duplicate_raw,json.loads(duplicate_raw),before['headSha256'])
        archive=head_path.parent/'coordinator-cost-head-history'/(before['headSha256']+'.json')
        if not archive.exists():archive.write_bytes(before['headRaw'])
        with self.subTest(globalFunding='reader-independently-rejects-duplicate-budget'):
            head_path.write_bytes(canonical_bytes(forged))
            try:
                with self.assertRaises(LifecycleError):bootstrap_r11.read_coordinator_cost_head(root,ancestor_head_sha256=seed['headSha256'])
            finally:head_path.write_bytes(before['headRaw'])
        with self.subTest(globalFunding='archived-role-source-missing-or-altered'):
            record_path.unlink()
            try:
                with self.assertRaises(LifecycleError):read('global-main')
            finally:record_path.write_bytes(record_raw);record_path.chmod(0o600)
        # Exact maximum N=32 SOURCE plus SHARED is a different typed budget,
        # never a widened ordinary coordinator cap.
        maximum_dir,maximum_funding,_=declare('maximum-roles','maximum',32)
        with self.subTest(globalFunding='all-33-roles-before-any-start'):
            before_max=head();maximum=publish('maximum-roles');max_head=head()
            self.assertTrue(maximum['fundingAdmitted']);self.assertEqual(maximum_funding['tokenCap'],11880000)
            self.assertEqual(max_head['head']['unknownHolds'],before_max['head']['unknownHolds']+11880000)
            self.assertEqual(len(maximum['unreservedRoleIds']),33)
            self.assertEqual(max_head['source']['protectedCloseoutTokens'],3300000)
            self.assertLessEqual(len(max_head['sourceRaw']),131072)
            self.assertEqual(maximum['reservations'],[]);self.assertFalse(maximum['allRolesSettled'])
        # A failure after global publication leaves its entire budget and sticky
        # local pending marker. Neither a missing receipt nor retry can refund it.
        crash_dir,crash_funding,_=declare('receipt-failure','crash')
        original_write=bootstrap_r11._write
        def fail_receipt(project,path,value):
            if path==crash_dir/'role-funding-origin.json':raise OSError('fixture receipt publication failure')
            return original_write(project,path,value)
        with self.subTest(globalFunding='post-commit-failure-retains-budget-and-denies-retry'):
            before_crash=head()
            with patch.object(bootstrap_r11,'_write',side_effect=fail_receipt),self.assertRaises(OSError):publish('receipt-failure')
            self.assertEqual(head()['head']['unknownHolds'],before_crash['head']['unknownHolds']+720000)
            self.assertTrue((crash_dir/'role-funding-origin.pending.json').exists())
            with self.assertRaises(LifecycleError):read('receipt-failure')
            with self.assertRaises(LifecycleError):publish('receipt-failure')
        # Two independent claims based on one head race through the existing
        # exclusive head writer. Exactly one can enter the global accounting.
        concurrent_a,_,_=declare('concurrent-a','race-a')
        concurrent_b,_,_=declare('concurrent-b','race-b')
        barrier=threading.Barrier(2);outcomes=[];advance=bootstrap_r11.advance_coordinator_cost_head
        def synchronized(*args,**kwargs):
            barrier.wait(timeout=60)
            return advance(*args,**kwargs)
        def run(review):
            try:outcomes.append((review,'OK',publish(review)))
            except (LifecycleError,OSError) as exc:outcomes.append((review,'REFUSED',str(exc)))
        with self.subTest(globalFunding='concurrent-batches-have-one-global-winner'):
            before_race=head()
            with patch.object(bootstrap_r11,'advance_coordinator_cost_head',side_effect=synchronized):
                threads=[threading.Thread(target=run,args=(r,)) for r in ('concurrent-a','concurrent-b')]
                for thread in threads:thread.start()
                for thread in threads:thread.join(90)
                self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(sorted(row[1] for row in outcomes),['OK','REFUSED'],outcomes)
            self.assertEqual(head()['head']['unknownHolds'],before_race['head']['unknownHolds']+720000)
        with self.subTest(globalFunding='final-pinned-history-keeps-all-committed-budgets'):
            history=bootstrap_r11.read_coordinator_cost_head(root,ancestor_head_sha256=seed['headSha256'])
            rows=history['roleFundingAdmissions'];self.assertEqual(len(rows),5)
            self.assertEqual(len({op for row in rows for op in row['operationIds']}),41)
            self.assertEqual(history['head']['unknownHolds'],seed['head']['unknownHolds']+12000+14760000)
            self.assertFalse(history['wholeHistoryComplete']);self.assertEqual(history['hardCapClaim'],'DENY')
            self.assertTrue(read('global-main')['fundingAdmitted'])
        self._check_global_role_prefixes(root,seed)


    def _check_global_role_prefixes(self,root,seed):
        # Existing isolated funded batches; real global/local publication. These
        # synthetic request hashes are accounting identities, not actual sends.
        from datetime import datetime,timedelta,timezone
        def read(review='global-main'):
            return bootstrap_r11.read_source_review_cost(root,review_id=review,role_delivery=True)
        def publish(review='global-main'):
            return bootstrap_r11.publish_source_review_cost_prefix(root,review_id=review)
        def head():return bootstrap_r11.read_coordinator_cost_head(root)
        def history():return bootstrap_r11.read_coordinator_cost_head(root,ancestor_head_sha256=seed['headSha256'])
        def local_reservation(review):
            basis=bootstrap_r11._r11_review_cost_basis(root,review,role_delivery=True)
            initial=read(review);role=basis['identity']['inventory']['roles'][0]
            now=datetime.now(timezone.utc).replace(microsecond=0)
            binding={'operationId':role['operationId'],'shardId':role['roleId'],'threadId':review+'-thread',
                     'binarySha256':'a'*64,'transportSourceSha256':'b'*64}
            dispatch={'binding':binding,'requestSha256':'c'*64,'sharedEvidenceSha256':None,
                'reservedAtUtc':now.isoformat().replace('+00:00','Z'),
                'absoluteDeadlineUtc':(now+timedelta(seconds=1800)).isoformat().replace('+00:00','Z')}
            reservation=bootstrap_r11._r11_cost_reservation(basis,0,None,dispatch=dispatch,prefix=initial['prefixSha256'])
            directory=bootstrap_r11._r11_review_directory(root,review)
            path=directory/'role-cost/shared-01/reservation.json'
            _write_exclusive(path,canonical_bytes(reservation),root=root)
            return basis,directory,path,reservation
        baseline=head();basis,directory,path,reservation=local_reservation('global-main')
        with self.subTest(globalPrefix='local-record-is-not-global-publication'),self.assertRaises(LifecycleError):read()
        with self.subTest(globalPrefix='one-reservation-anchored-with-zero-new-charge'):
            reserved=publish();reserved_head=head()
            self.assertTrue(reserved['rolePrefixesAnchored']);self.assertFalse(reserved['dispatchReservationQualified'])
            self.assertFalse(reserved['firstNativeBootstrapEligible']);self.assertFalse(reserved['producerQualified'])
            self.assertEqual(reserved['reservations'],[reservation]);self.assertEqual(reserved_head['head']['unknownHolds'],baseline['head']['unknownHolds'])
            self.assertEqual(reserved_head['head']['exposureLowerBound'],baseline['head']['exposureLowerBound'])
            self.assertEqual(reserved_head['source']['tokenCap'],0)
            self.assertEqual(reserved['fundingOrigin']['costPrefix']['recordCount'],1)
            self.assertEqual(reserved['workerEvidenceReadMode'],'CURRENT_PRIVATE_FILES')
            self.assertEqual(reserved['fundingOrigin']['costPrefix']['workerEvidenceReadMode'],'ARCHIVED_DIGESTS_ONLY')
        with self.subTest(globalPrefix='duplicate-publication-refuses-without-head-change'):
            saved=head()['headRaw']
            with self.assertRaises(LifecycleError):publish()
            self.assertEqual(head()['headRaw'],saved)
        with self.subTest(globalPrefix='entire-local-history-removal-refuses'):
            saved=path.read_bytes();shutil.rmtree(directory/'role-cost')
            try:
                with self.assertRaises(LifecycleError):read()
                self.assertEqual(head()['head']['unknownHolds'],baseline['head']['unknownHolds'])
            finally:_write_exclusive(path,saved,root=root)
        receipt_path=directory/'role-prefix-receipts'/(reserved['costChainSha256']+'.json')
        with self.subTest(globalPrefix='receipt-removal-refuses'):
            saved=receipt_path.read_bytes();receipt_path.unlink()
            try:
                with self.assertRaises(LifecycleError):read()
            finally:receipt_path.write_bytes(saved);receipt_path.chmod(0o600)
        with self.subTest(globalPrefix='pending-prefix-refuses'):
            p=directory/'role-cost-prefix.pending.json';_write_exclusive(p,b'{}',root=root)
            try:
                with self.assertRaises(LifecycleError):read()
                with self.assertRaises(LifecycleError):publish()
            finally:p.unlink()
        archive_path=root/reserved_head['head']['sourcePath'];archive_raw=archive_path.read_bytes();archive=json.loads(archive_raw)
        for field,value in [('tokenCap',1),('protectedCloseoutTokens',1),('priorUnknownHoldsReleased',1),
                            ('actualTokens',0),('priorUnknownHolds',0),('previousCostPrefixSha256','f'*64),
                            ('roleSubjectSchemaRaw',archive['roleSubjectSchemaRaw']+' '),('priorHeadSha256','f'*64)]:
            with self.subTest(globalPrefix='archive-mutation',field=field):
                archive_path.write_bytes(canonical_bytes({**archive,field:value}))
                try:
                    with self.assertRaises(LifecycleError):history()
                finally:archive_path.write_bytes(archive_raw)
        # Correctly hashed forged append bypasses the writer; independent replay
        # must reject a duplicate reservation instead of treating it as settlement.
        prior=head();forged={**archive,'priorHeadSha256':prior['headSha256'],
            'previousCostPrefixSha256':reserved['costChainSha256'],'costPrefixSha256':'f'*64}
        relative=bootstrap_r11._R11_COORDINATOR_BASE+'/role-prefixes/'+archive['fundingBatchSha256']+'/'+'f'*64+'/record.json'
        target=root/relative;_write_exclusive(target,canonical_bytes(forged),root=root/bootstrap_r11._R11_COORDINATOR_BASE)
        with self.subTest(globalPrefix='writer-refuses-repeated-role-record'),self.assertRaises(LifecycleError):
            bootstrap_r11.advance_coordinator_cost_head(root,source_path=relative)
        head_path=root/bootstrap_r11._R11_COORDINATOR_HEAD
        previous_archive=head_path.parent/'coordinator-cost-head-history'/(prior['headSha256']+'.json')
        if not previous_archive.exists():previous_archive.write_bytes(prior['headRaw'])
        forged_head=bootstrap_r11._r11_coordinator_head_value(relative,canonical_bytes(forged),forged,prior['headSha256'])
        with self.subTest(globalPrefix='reader-refuses-repeated-role-record'):
            head_path.write_bytes(canonical_bytes(forged_head))
            try:
                with self.assertRaises(LifecycleError):history()
            finally:head_path.write_bytes(prior['headRaw'])
        # Authorized coordinator activity advances the financial total but never
        # rebases the original role reservation or its prefix receipt.
        window={'status':'ADMITTED_PREAPPROVED_BY_USER','tokenCap':14000,'protectedCloseoutTokens':3000,
            'actualInputTokens':None,'actualTokens':None,'costStatus':'UNAVAILABLE','priorBudgetResumed':False,
            'priorUnknownHoldsReleased':0,'priorUnknownHolds':prior['head']['unknownHolds'],
            'priorLedgerLowerBound':prior['head']['exposureLowerBound'],
            'unknownHoldsIncludingThisWindow':prior['head']['unknownHolds']+14000,
            'ledgerLowerBoundIncludingThisHold':prior['head']['exposureLowerBound']+14000}
        relative=bootstrap_r11._R11_COORDINATOR_BASE+'/r901-after-prefix/admission.json'
        (root/relative).parent.mkdir();(root/relative).write_bytes(canonical_bytes(window))
        bootstrap_r11.advance_coordinator_cost_head(root,source_path=relative)
        with self.subTest(globalPrefix='external-window-preserves-prefix'):
            later=read();self.assertEqual(later['prefixSha256'],reserved['prefixSha256'])
            self.assertEqual(later['fundingOrigin']['costPrefix'],reserved['fundingOrigin']['costPrefix'])
            self.assertEqual(later['fundingOrigin']['unknownHolds'],baseline['head']['unknownHolds']+14000)
        worker=bootstrap_r11._r11_cost_worker(root,reservation['binding'],reservation['heldUnknownTokens'],
            review_id='global-main',cost_chain_sha=reserved['costChainSha256'],request_sha=reservation['requestSha256'])
        self.assertEqual(worker['state'],'START_UNCERTAIN')
        settlement={'schemaVersion':'alk-r11-role-cost-settlement.v1','reviewId':'global-main','binding':reservation['binding'],
            'reservationSha256':canonical_digest(reservation),'previousCostPrefixSha256':reserved['costChainSha256'],'worker':worker,
            'costStatus':'UNAVAILABLE','actualModelTokens':None,'releasedUnknownTokens':0,
            'heldUnknownTokens':reservation['heldUnknownTokens'],'accountedExposureLowerBound':reservation['accountedExposureLowerBound'],
            'retryAuthorized':False,'hardCapClaim':'DENY'}
        settlement_path=path.with_name('settlement.json');_write_exclusive(settlement_path,canonical_bytes(settlement),root=root)
        with self.subTest(globalPrefix='open-coordinator-window-cannot-be-split'),self.assertRaises(LifecycleError):publish()
        self.assertFalse((directory/'role-cost-prefix.pending.json').exists())
        close_relative=str(Path(relative).with_name('cost.json'))
        (root/close_relative).write_bytes(canonical_bytes({**window,'status':'UNAVAILABLE_FULL_HOLD_RETAINED'}))
        bootstrap_r11.advance_coordinator_cost_head(root,source_path=close_relative)
        with self.subTest(globalPrefix='uncertain-close-anchors-full-hold-and-unused-tail'):
            settled=publish();self.assertEqual(settled['settlements'],[settlement])
            self.assertEqual(settled['fundingOrigin']['costPrefix']['recordCount'],2)
            self.assertEqual(settled['unreservedRoleIds'],['source-01']);self.assertFalse(settled['allRolesSettled'])
            self.assertIsNone(settled['actualModelTokens']);self.assertEqual(settled['releasedUnknownTokens'],0)
            self.assertEqual(head()['head']['unknownHolds'],baseline['head']['unknownHolds']+14000)
        with self.subTest(globalPrefix='failed-prefix-cannot-admit-next-role'):
            next_basis=bootstrap_r11._r11_review_cost_basis(root,'global-main',role_delivery=True)
            role=next_basis['identity']['inventory']['roles'][1]
            dispatch={key:reservation[key] for key in ('binding','requestSha256','sharedEvidenceSha256','reservedAtUtc','absoluteDeadlineUtc')}
            dispatch.update(binding={**reservation['binding'],'operationId':role['operationId'],'shardId':role['roleId'],
                                     'threadId':'unstarted-source'},sharedEvidenceSha256='d'*64)
            next_res=bootstrap_r11._r11_cost_reservation(next_basis,1,canonical_bytes(settlement),dispatch=dispatch,prefix=settled['prefixSha256'])
            next_path=directory/'role-cost/source-01/reservation.json';_write_exclusive(next_path,canonical_bytes(next_res),root=root)
            try:
                with self.assertRaises(LifecycleError):publish()
            finally:next_path.unlink();next_path.parent.rmdir()
            self.assertEqual(read()['costChainSha256'],settled['costChainSha256'])
        with self.subTest(globalPrefix='deleted-settlement-cannot-reopen-reservation'):
            saved=settlement_path.read_bytes();settlement_path.unlink()
            try:
                with self.assertRaises(LifecycleError):read()
                with self.assertRaises(LifecycleError):publish()
            finally:settlement_path.write_bytes(saved);settlement_path.chmod(0o600)
        # Fault after successful global commit must leave the local publication
        # sticky and the immutable global prefix discoverable independently.
        _,failed_dir,_,_=local_reservation('global-second')
        original_write=bootstrap_r11._write
        def fail_receipt(project,path,value):
            if path.parent==failed_dir/'role-prefix-receipts':raise OSError('fixture role-prefix receipt failure')
            return original_write(project,path,value)
        with self.subTest(globalPrefix='post-commit-receipt-failure-no-refund-or-retry'):
            before=head()
            with patch.object(bootstrap_r11,'_write',side_effect=fail_receipt),self.assertRaises(OSError):publish('global-second')
            self.assertEqual(head()['head']['unknownHolds'],before['head']['unknownHolds'])
            self.assertTrue((failed_dir/'role-cost-prefix.pending.json').exists())
            with self.assertRaises(LifecycleError):read('global-second')
            with self.assertRaises(LifecycleError):publish('global-second')
        # Same-record concurrent publication is fenced by its durable local
        # pending file before either publisher can claim a second global append.
        _,race_dir,_,_=local_reservation('maximum-roles')
        entered=threading.Event();release=threading.Event();outcomes=[]
        def block_pending(project,path,value):
            result=original_write(project,path,value)
            if path==race_dir/'role-cost-prefix.pending.json':entered.set();release.wait(30)
            return result
        def first_publish():
            try:outcomes.append(publish('maximum-roles'))
            except BaseException as exc:outcomes.append(exc)
        with self.subTest(globalPrefix='concurrent-same-record-has-one-publisher'):
            before=head()
            with patch.object(bootstrap_r11,'_write',side_effect=block_pending):
                thread=threading.Thread(target=first_publish);thread.start()
                try:
                    self.assertTrue(entered.wait(30))
                    with self.assertRaises(LifecycleError):publish('maximum-roles')
                finally:release.set();thread.join(60)
                self.assertFalse(thread.is_alive())
            self.assertEqual(len(outcomes),1);self.assertIsInstance(outcomes[0],dict,outcomes)
            self.assertEqual(outcomes[0]['fundingOrigin']['costPrefix']['recordCount'],1)
            self.assertEqual(head()['head']['unknownHolds'],before['head']['unknownHolds'])
        with self.subTest(globalPrefix='all-pinned-records-preserved-without-spend-inference'):
            proof=history();prefixes=proof['roleCostPrefixes']
            self.assertEqual(sum(value['recordCount'] for value in prefixes.values()),4)
            self.assertEqual(len(proof['roleFundingAdmissions']),5)
            self.assertEqual(read()['fundingOrigin']['costPrefix'],settled['fundingOrigin']['costPrefix'])
            self.assertFalse(read()['dispatchReservationQualified'])
            self.assertEqual(head()['head']['unknownHolds'],baseline['head']['unknownHolds']+14000)

        for malformed in ([],{}):
            with self.subTest(globalPrefix='malformed-archived-worker-state',value=malformed):
                entries=copy.deepcopy(proof['roleLedgerEntries'])
                entry=next(e for e in entries if e['source'].get('schemaVersion')=='alk-r11-global-role-prefix.v1'
                           and e['source']['reviewId']=='global-main' and e['source']['recordPath'].endswith('/settlement.json'))
                record=json.loads(entry['source']['recordRaw']);record['worker']['state']=malformed
                entry['source']['recordRaw']=canonical_bytes(record).decode()
                with self.assertRaises(LifecycleError):bootstrap_r11._r11_global_role_prefixes(entries)

        with self.subTest(globalPrefix='existing-settlement-api-publishes-v6-close'):
            current=read('maximum-roles');binding=current['reservations'][-1]['binding'];before=head()
            terminal=bootstrap_r11.settle_source_review_cost(root,review_id='maximum-roles',binding=binding,role_delivery=True)
            complete=read('maximum-roles')
            self.assertEqual(terminal['worker']['state'],'START_UNCERTAIN')
            self.assertEqual(complete['settlements'],[terminal]);self.assertEqual(terminal['releasedUnknownTokens'],0)
            self.assertIsNone(terminal['actualModelTokens']);self.assertEqual(terminal['heldUnknownTokens'],current['declaredUnknownHoldsAtFunding'])
            self.assertEqual(complete['fundingOrigin']['costPrefix']['recordCount'],2)
            self.assertEqual(len(complete['unreservedRoleIds']),32);self.assertFalse(complete['allRolesSettled'])
            self.assertTrue(complete['rolePrefixesAnchored']);self.assertFalse(complete['dispatchReservationQualified'])
            self.assertEqual(head()['head']['unknownHolds'],before['head']['unknownHolds'])
        with self.subTest(globalPrefix='settlement-api-replay-cannot-reopen-or-charge'):
            saved=head()['headRaw']
            with self.assertRaises(LifecycleError):
                bootstrap_r11.settle_source_review_cost(root,review_id='maximum-roles',binding=binding,role_delivery=True)
            self.assertEqual(head()['headRaw'],saved)
        for mode in (1,'v6'):
            with self.subTest(globalPrefix='settlement-mode-is-explicit',mode=mode),self.assertRaises(LifecycleError):
                bootstrap_r11.settle_source_review_cost(root,review_id='maximum-roles',binding=binding,role_delivery=mode)


    def _check_role_request_reservation(self):
        # Real isolated private request bytes and global ledger. Literal inputs
        # and selected thread are fixtures, never current host/source proof.
        import subprocess
        from datetime import datetime, timedelta, timezone
        root, authority, proto_base, proto_inventory, proto_funding, shared, source = self._role_request_fixture()
        root = root.resolve()
        subprocess.run(['git','init','-q',str(root)],check=True,capture_output=True,timeout=10)
        primary = bootstrap_r11._r11_coordinator_root(Path(__file__).parents[2])
        seed_path = root/bootstrap_r11._R11_COORDINATOR_SEED;seed_path.parent.mkdir(parents=True)
        seed_path.write_bytes((primary/bootstrap_r11._R11_COORDINATOR_SEED).read_bytes())
        bootstrap_r11.advance_coordinator_cost_head(root,source_path=bootstrap_r11._R11_COORDINATOR_SEED)
        def head():return bootstrap_r11.read_coordinator_cost_head(root)
        def declare(review):
            prior=head();bootstrap_r11.import_source_review_opening(root,review_id=review)
            origin=bootstrap_r11.read_source_review_opening_origin(root,review_id=review,role_delivery=True)
            base,inventory,funding=copy.deepcopy((proto_base,proto_inventory,proto_funding))
            base.update(reviewId=review,openingHeadSha256=origin['coordinatorHeadSha256'],openingSourceSha256=origin['costOpeningSha256'])
            inventory.update(reviewId=review,baseSha256=canonical_digest(base),
                roles=[{**r,'operationId':review+'-'+r['roleId']} for r in inventory['roles']])
            now=datetime.now(timezone.utc).replace(microsecond=0)
            funding.update(reviewId=review,baseSha256=canonical_digest(base),roleInventorySha256=canonical_digest(inventory),
                priorHeadSha256=prior['headSha256'],priorUnknownHolds=prior['head']['unknownHolds'],
                priorExposureLowerBound=prior['head']['exposureLowerBound'],
                admittedAtUtc=now.isoformat().replace('+00:00','Z'),
                absoluteDeadlineUtc=(now+timedelta(seconds=59400)).isoformat().replace('+00:00','Z'),
                admittedUnknownHolds=prior['head']['unknownHolds']+720000,
                admittedExposureLowerBound=prior['head']['exposureLowerBound']+720000)
            directory=bootstrap_r11._r11_review_directory(root,review)
            for name,value in [('role-base.json',base),('role-inventory.json',inventory),('role-funding.json',funding)]:
                _write_exclusive(directory/name,canonical_bytes(value),root=root)
            binding={'operationId':inventory['roles'][0]['operationId'],'shardId':'shared-01','threadId':review+'-thread',
                     'binarySha256':'a'*64,'transportSourceSha256':'b'*64}
            return directory,binding
        def seal(review,binding,**kwargs):
            return bootstrap_r11.seal_source_review_request(root,review_id=review,binding=binding,
                exposure_raw=kwargs.pop('exposure_raw',canonical_bytes(shared)),
                model_context_window=kwargs.pop('model_context_window',1000000),**kwargs)
        def read(review='sealed',**kwargs):
            return bootstrap_r11.read_source_review_request(root,review_id=review,role_id='shared-01',**kwargs)
        def reserve(review,binding):
            return bootstrap_r11.reserve_source_review_cost(root,review_id=review,binding=binding,role_delivery=True)
        directory,binding=declare('sealed');request_dir=directory/'role-requests/shared-01'
        with self.subTest(requestSeal='unfunded-refuses'),self.assertRaises(LifecycleError):seal('sealed',binding)
        self.assertFalse(request_dir.exists())
        bootstrap_r11.admit_source_review_funding(root,review_id='sealed');funded_head=head()
        with self.subTest(requestSeal='unsealed-reservation-refuses'),self.assertRaises(LifecycleError):reserve('sealed',binding)
        for change in ({'exposure_raw':canonical_bytes({**shared,'padding':'changed'})},{'model_context_window':1}):
            with self.subTest(requestSeal='candidate-refuses-before-any-write',change=list(change)),self.assertRaises(LifecycleError):
                seal('sealed',binding,**change)
            self.assertFalse(request_dir.exists())
        with self.subTest(requestSeal='placeholder-thread-refuses'),self.assertRaises(LifecycleError):
            seal('sealed',{**binding,'threadId':'U'*256})
        with self.subTest(requestSeal='canonical-complete-request-persisted'):
            sealed=seal('sealed',binding)
            self.assertEqual(read(),sealed)
            self.assertEqual((request_dir/'request.jsonl').read_bytes(),sealed['requestRaw'])
            self.assertEqual(json.loads(sealed['requestRaw'])['params']['threadId'],binding['threadId'])
            self.assertEqual((request_dir/'subject.json').read_bytes(),canonical_bytes(sealed['subject']))
            self.assertEqual(sealed['seal']['requestSha256'],hashlib.sha256(sealed['requestRaw']).hexdigest())
            self.assertFalse(sealed['reservationRequestMatched']);self.assertFalse(sealed['selectedHostQualified'])
            self.assertFalse(sealed['sourceFreshnessQualified']);self.assertFalse(sealed['dispatchAllowed'])
            self.assertTrue(sealed['fundingAdmitted']);self.assertEqual(head()['headRaw'],funded_head['headRaw'])
        with self.subTest(requestSeal='duplicate-seal-does-not-replace'),self.assertRaises((LifecycleError,OSError)):
            seal('sealed',binding)
        with self.subTest(requestSeal='unreserved-match-refuses'),self.assertRaises(LifecycleError):read(require_reservation=True)
        originals={p.name:p.read_bytes() for p in request_dir.iterdir()}
        for name in originals:
            with self.subTest(requestSeal='changed-raw-file-refuses',name=name):
                p=request_dir/name;p.write_bytes(originals[name]+b' ')
                try:
                    with self.assertRaises(LifecycleError):read()
                    with self.assertRaises(LifecycleError):reserve('sealed',binding)
                finally:p.write_bytes(originals[name])
        for name in ('pending.json','extra.json'):
            with self.subTest(requestSeal='extra-or-pending-refuses',name=name):
                p=request_dir/name;_write_exclusive(p,b'{}',root=root)
                try:
                    with self.assertRaises(LifecycleError):read()
                finally:p.unlink()
        with self.subTest(requestSeal='symlink-request-refuses'):
            p=request_dir/'request.jsonl';other=root/'copy-request';other.write_bytes(originals[p.name]);other.chmod(0o600)
            p.unlink();p.symlink_to(other)
            try:
                with self.assertRaises(LifecycleError):read()
            finally:p.unlink();_write_exclusive(p,originals[p.name],root=root)
        with self.subTest(requestSeal='forged-flags-refuse'):
            p=request_dir/'seal.json';p.write_bytes(canonical_bytes({**sealed['seal'],'dispatchAllowed':True}))
            try:
                with self.assertRaises(LifecycleError):read()
            finally:p.write_bytes(originals[p.name])
        with self.subTest(requestSeal='wrong-binding-refuses'),self.assertRaises(LifecycleError):
            reserve('sealed',{**binding,'threadId':'different-thread'})
        worker=root/bootstrap_r11._R11_REVIEW_ROOT/'shards/shared-01'
        with self.subTest(requestSeal='retrospective-reservation-refuses'):
            worker.mkdir(parents=True)
            try:
                with self.assertRaises(LifecycleError):reserve('sealed',binding)
            finally:worker.rmdir()
        class ExpiredClock(datetime):
            @classmethod
            def now(cls,tz=None):return datetime.fromisoformat(sealed['seal']['sealedAtUtc'].replace('Z','+00:00'))+timedelta(seconds=1801)
        with self.subTest(requestSeal='elapsed-seal-cannot-renew-role-deadline'):
            with patch.object(bootstrap_r11,'datetime',ExpiredClock),self.assertRaises(LifecycleError):reserve('sealed',binding)
            self.assertFalse((directory/'role-cost').exists())
        with self.subTest(requestSeal='reservation-binds-durable-bytes-without-new-charge'):
            reservation=reserve('sealed',binding);matched=read(require_reservation=True)
            self.assertTrue(matched['reservationRequestMatched']);self.assertFalse(matched['dispatchAllowed'])
            self.assertEqual(reservation['requestSha256'],sealed['requestSha256'])
            self.assertEqual(reservation['subjectSha256'],sealed['subjectSha256'])
            self.assertEqual(reservation['binding'],binding);self.assertEqual(reservation['holdIncrement'],0)
            self.assertIsNone(reservation['actualModelTokens']);self.assertFalse(reservation['retryAuthorized'])
            self.assertEqual(head()['head']['unknownHolds'],funded_head['head']['unknownHolds'])
            cost=bootstrap_r11.read_source_review_cost(root,review_id='sealed',role_delivery=True)
            self.assertEqual(cost['fundingOrigin']['costPrefix']['recordCount'],1)
            self.assertFalse(cost['dispatchReservationQualified'])
        with self.subTest(requestSeal='replayed-reservation-refuses'),self.assertRaises(LifecycleError):reserve('sealed',binding)
        with self.subTest(requestSeal='deleted-seal-does-not-erase-hold'):
            p=request_dir/'seal.json';p.unlink()
            try:
                with self.assertRaises(LifecycleError):read(require_reservation=True)
                self.assertEqual(head()['head']['unknownHolds'],funded_head['head']['unknownHolds'])
            finally:_write_exclusive(p,originals[p.name],root=root)
        # No worker exists: settlement conservatively retains full unknown hold.
        with self.subTest(requestSeal='settlement-preserves-sealed-request-and-unused-tail'):
            terminal=bootstrap_r11.settle_source_review_cost(root,review_id='sealed',binding=binding,role_delivery=True)
            self.assertEqual(terminal['worker']['state'],'START_UNCERTAIN')
            self.assertTrue(read(require_reservation=True)['reservationRequestMatched'])
            self.assertEqual({p.name:p.read_bytes() for p in request_dir.iterdir()},originals)
        for mode in (1,'v6'):
            with self.subTest(requestSeal='reservation-mode-explicit',mode=mode),self.assertRaises(LifecycleError):
                bootstrap_r11.reserve_source_review_cost(root,review_id='sealed',binding=binding,role_delivery=mode)
        for mode in (1,'yes'):
            with self.subTest(requestSeal='request-mode-explicit',mode=mode),self.assertRaises(LifecycleError):read(require_reservation=mode)
        # Fault halfway through the durable publication leaves an unrepeatable
        # claim, even though neither global head nor spend changed.
        broken_dir,broken_binding=declare('broken')
        bootstrap_r11.admit_source_review_funding(root,review_id='broken');before=head()
        from agent_lifecycle.adapter_sessions import codex_exact_prompt as transport
        original_write=transport._write_exclusive
        def fail_subject(path,raw,*,root):
            if path==broken_dir/'role-requests/shared-01/subject.json':raise OSError('fixture seal fsync/write failure')
            return original_write(path,raw,root=root)
        with self.subTest(requestSeal='partial-write-is-sticky-with-full-hold'):
            with patch.object(transport,'_write_exclusive',side_effect=fail_subject),self.assertRaises(OSError):seal('broken',broken_binding)
            self.assertTrue((broken_dir/'role-requests/shared-01/pending.json').exists())
            with self.assertRaises(LifecycleError):read('broken')
            with self.assertRaises((LifecycleError,OSError)):seal('broken',broken_binding)
            with self.assertRaises(LifecycleError):reserve('broken',broken_binding)
            self.assertEqual(head()['headRaw'],before['headRaw'])
        # A real reservation may commit globally before private receipt failure;
        # that committed budget/prefix must remain, and retries must fail closed.
        failed_dir,failed_binding=declare('prefix-failure')
        bootstrap_r11.admit_source_review_funding(root,review_id='prefix-failure')
        seal('prefix-failure',failed_binding);before=head();original=bootstrap_r11._write
        def fail_receipt(project,path,value):
            if path.parent==failed_dir/'role-prefix-receipts':raise OSError('fixture receipt failure')
            return original(project,path,value)
        with self.subTest(requestSeal='post-commit-failure-retains-global-prefix'):
            with patch.object(bootstrap_r11,'_write',side_effect=fail_receipt),self.assertRaises(OSError):reserve('prefix-failure',failed_binding)
            self.assertEqual(head()['head']['unknownHolds'],before['head']['unknownHolds'])
            self.assertTrue((failed_dir/'role-cost/shared-01/reservation.json').exists())
            self.assertTrue((failed_dir/'role-cost-prefix.pending.json').exists())
            with self.assertRaises(LifecycleError):reserve('prefix-failure',failed_binding)
            with self.assertRaises(LifecycleError):read('prefix-failure',require_reservation=True)


    def _role_funded_transport_fixture(self, *, padding=160000):
        import subprocess
        from datetime import datetime,timedelta,timezone
        root,authority,base,inventory,funding,shared,source=self._role_request_fixture(padding='x'*padding)
        root=root.resolve();subprocess.run(['git','init','-q',str(root)],check=True,capture_output=True,timeout=10)
        primary=bootstrap_r11._r11_coordinator_root(Path(__file__).parents[2])
        seed_path=root/bootstrap_r11._R11_COORDINATOR_SEED;seed_path.parent.mkdir(parents=True)
        seed_path.write_bytes((primary/bootstrap_r11._R11_COORDINATOR_SEED).read_bytes())
        prior=bootstrap_r11.advance_coordinator_cost_head(root,source_path=bootstrap_r11._R11_COORDINATOR_SEED)
        review=base['reviewId'];bootstrap_r11.import_source_review_opening(root,review_id=review)
        origin=bootstrap_r11.read_source_review_opening_origin(root,review_id=review,role_delivery=True)
        base.update(openingHeadSha256=origin['coordinatorHeadSha256'],openingSourceSha256=origin['costOpeningSha256'])
        inventory['baseSha256']=canonical_digest(base);now=datetime.now(timezone.utc).replace(microsecond=0)
        funding.update(baseSha256=canonical_digest(base),roleInventorySha256=canonical_digest(inventory),
            priorHeadSha256=prior['headSha256'],priorUnknownHolds=prior['head']['unknownHolds'],
            priorExposureLowerBound=prior['head']['exposureLowerBound'],
            admittedAtUtc=now.isoformat().replace('+00:00','Z'),
            absoluteDeadlineUtc=(now+timedelta(seconds=59400)).isoformat().replace('+00:00','Z'),
            admittedUnknownHolds=prior['head']['unknownHolds']+720000,
            admittedExposureLowerBound=prior['head']['exposureLowerBound']+720000)
        directory=bootstrap_r11._r11_review_directory(root,review)
        for name,value in [('role-base.json',base),('role-inventory.json',inventory),('role-funding.json',funding)]:
            _write_exclusive(directory/name,canonical_bytes(value),root=root)
        bootstrap_r11.admit_source_review_funding(root,review_id=review)
        binding={'operationId':inventory['roles'][0]['operationId'],'shardId':'shared-01','threadId':'thread',
                 'binarySha256':'d'*64,'transportSourceSha256':'e'*64}
        return root,authority,base,inventory,funding,shared,source,directory,binding

    @_retired_r11_positive
    def test_every_role_raw_transport_and_terminal_joins(self):
        self._check_v6_producer_after_retirement()
        self._check_v6_rpc_after_retirement()
        self._check_v6_model_route()
        self._check_source_model_route()
        self._check_v6_role_metadata(continuation='absolute_delta',role_id='source-01')
        self._check_costed_absolute_forwarding()
        self._check_absolute_worker_supervision()
        self._check_v6_entry_deadline_refusal()
        self._check_v6_original_deadline_request()
        self._check_v6_role_metadata()
        self._check_v6_fixed_worker_input()
        self._check_fixed_input_publication()
        # Exact v6 body/transport and durable large-request components only.
        # Actual host/worker terminal admission and accepted-SHARED are pending;
        # one method ID is not proof that this whole planned requirement closed.
        root,authority,base,inventory,funding,shared,source,directory,binding=self._role_funded_transport_fixture()
        review=base['reviewId'];request_dir=directory/'role-requests/shared-01'
        # Regression: r425 allowed this serialized request but the generic
        # 131072-byte private writer rejected it before publication completed.
        sealed=bootstrap_r11.seal_source_review_request(root,review_id=review,binding=binding,
            exposure_raw=canonical_bytes(shared),model_context_window=1000000)
        with self.subTest(roleTransport='large-request-seal-roundtrip'):
            self.assertGreater(sealed['serializedRequestBytes'],131072)
            self.assertLessEqual(sealed['serializedRequestBytes'],245760)
            self.assertEqual(bootstrap_r11.read_source_review_request(root,review_id=review,role_id='shared-01'),sealed)
            self.assertTrue((request_dir/'parts.json').exists())
            self.assertTrue(all(p.stat().st_size<=131072 for p in request_dir.iterdir()))
        names={'seal.json','request.jsonl','subject.json','exposure.json'}
        logical=bootstrap_r11._r11_read_role_request_files(root,request_dir,names)
        manifest_path=request_dir/'parts.json';manifest_raw=manifest_path.read_bytes();manifest=json.loads(manifest_raw)
        self.assertEqual(set(manifest['files']),{'exposure.json','request.jsonl'})
        for label,mutate in [
            ('excess-total',lambda x:x['files']['request.jsonl'].update(bytes=245761)),
            ('boolean-size',lambda x:x['files']['request.jsonl'].update(bytes=True)),
            ('wrong-whole-hash',lambda x:x['files']['request.jsonl'].update(sha256='f'*64)),
            ('reordered-parts',lambda x:x['files']['request.jsonl']['parts'].reverse()),
            ('omitted-part',lambda x:x['files']['request.jsonl']['parts'].pop()),
            ('path-traversal',lambda x:x['files'].update({'../elsewhere':x['files']['request.jsonl']})),
            ('extra-field',lambda x:x.update(extra=True))]:
            with self.subTest(roleTransport='part-manifest-refusal',mutation=label):
                changed=copy.deepcopy(manifest);mutate(changed);manifest_path.write_bytes(canonical_bytes(changed))
                try:
                    with self.assertRaises(LifecycleError):bootstrap_r11._r11_read_role_request_files(root,request_dir,names)
                finally:manifest_path.write_bytes(manifest_raw)
        part_path=request_dir/'request.jsonl.part-00';part_raw=part_path.read_bytes()
        with self.subTest(roleTransport='changed-part-refuses'):
            part_path.write_bytes(b'!'+part_raw[1:])
            try:
                with self.assertRaises(LifecycleError):bootstrap_r11._r11_read_role_request_files(root,request_dir,names)
            finally:part_path.write_bytes(part_raw)
        with self.subTest(roleTransport='extra-part-refuses'):
            p=request_dir/'request.jsonl.part-99';_write_exclusive(p,b'x',root=root)
            try:
                with self.assertRaises(LifecycleError):bootstrap_r11._r11_read_role_request_files(root,request_dir,names)
            finally:p.unlink()
        with self.subTest(roleTransport='indirect-part-refuses'):
            copy_path=root/'part-copy';copy_path.write_bytes(part_raw);copy_path.chmod(0o600)
            part_path.unlink();part_path.symlink_to(copy_path)
            try:
                with self.assertRaises(LifecycleError):bootstrap_r11._r11_read_role_request_files(root,request_dir,names)
            finally:part_path.unlink();_write_exclusive(part_path,part_raw,root=root)
        for size in (131072,131073,245760):
            with self.subTest(roleTransport='exact-storage-boundaries',bytes=size):
                target=directory/('storage-'+str(size));raw=b'x'*size
                bootstrap_r11._r11_write_role_request_files(root,target,{'exposure.json':raw})
                self.assertEqual(bootstrap_r11._r11_read_role_request_files(root,target,{'exposure.json'}),{'exposure.json':raw})
                self.assertTrue(all(p.stat().st_size<=131072 for p in target.iterdir()))
        with self.subTest(roleTransport='storage-over-cap-refuses'),self.assertRaises(LifecycleError):
            bootstrap_r11._r11_write_role_request_files(root,directory/'storage-over',{'request.jsonl':b'x'*245761})
        reservation=bootstrap_r11.reserve_source_review_cost(root,review_id=review,binding=binding,role_delivery=True)
        self.assertEqual(reservation['requestSha256'],sealed['requestSha256'])
        subject=sealed['subject']
        def body_for(subject):
            return {'schemaVersion':'alk-route-bootstrap-reviewer-body.v6-r11','verdict':'PASS',
                'phase':'PRE_WS01','rb11RuntimeStatus':'NOT_RUN','subjectSha256':canonical_digest(subject),
                **{key:subject[key] for key in ('baseSha256','roleInventorySha256','fundingBatchSha256','roleId',
                                               'roleKind','exposureSha256','sharedEvidenceSha256')},
                'sharedContentSeenByThisRole':subject['roleKind']=='SHARED','assignedContentComplete':True,
                'inheritedCoverageAccepted':True,'interactionScopeComplete':True,
                'approvedIntegrationScopes':subject['requiredIntegrationScopes'],'closedParentFindingIds':[],
                'findings':[],'reviewText':'NO_CURRENT_FINDINGS'}
        body=body_for(subject);body_raw=json.dumps(body,indent=1).encode()+b'\n'
        fixture=_R11TransportFixture(methodName='runTest')
        fixture.root=root;fixture.binding=binding;fixture.request=sealed['requestRaw'];fixture.body_raw=body_raw
        records=fixture.build()
        def transport(rows=records,expected_binding=binding,body_bytes=body_raw):
            return bootstrap_r11.verify_source_review_transport_records(root,expected_binding=expected_binding,
                expected_request=sealed['requestRaw'],expected_subject=subject,body_raw=body_bytes,
                transcript_raw=b''.join(canonical_bytes(row)+b'\n' for row in rows),role_delivery=True)
        with self.subTest(roleTransport='shared-exact-raw-body-ordered-writes-and-two-reads'):
            matched=transport();self.assertEqual(matched['bodyReadMatch']['roleId'],'shared-01')
            self.assertEqual(matched['bodyReadMatch']['bodySha256'],hashlib.sha256(body_raw).hexdigest())
            self.assertTrue(matched['bodyReadMatch']['reservationRequestMatched'])
            self.assertEqual(matched['bodyReadMatch']['closedParentFindingIds'],[])
            self.assertFalse(matched['bodyReadMatch']['sharedEvidenceAccepted'])
            self.assertFalse(matched['producerQualified']);self.assertFalse(matched['firstNativeBootstrapEligible'])
        for label,change in [('bad-write',lambda rows:rows[2].update(acceptedBytes=1)),
                            ('wrong-session',lambda rows:rows[0]['binding'].update(operationId='other')),
                            ('missing-flush',lambda rows:rows.pop(4)),
                            ('missing-second-read',lambda rows:rows.pop())]:
            with self.subTest(roleTransport='raw-transcript-refuses',mutation=label):
                rows=copy.deepcopy(records);change(rows)
                with self.assertRaises(LifecycleError):transport(rows)
        read_raw=canonical_bytes(fixture.read(body_raw))
        def body_read(*,body_bytes=body_raw,first=read_raw,second=read_raw,expected=subject,request=sealed['requestRaw']):
            return bootstrap_r11.verify_source_review_body_and_reads(root,expected_request=request,request_raw=request,
                expected_subject=expected,body_raw=body_bytes,first_read_raw=first,second_read_raw=second,
                turn_id='turn',role_delivery=True)
        for key,value in [('roleId','source-01'),('assignedContentComplete',False),
                          ('sharedContentSeenByThisRole',False),('closedParentFindingIds',['RB-OBSERVER-TIMEOUT-01']),
                          ('approvedIntegrationScopes',['COLLECTOR_FIRST_NATIVE'])]:
            with self.subTest(roleTransport='v6-body-refuses',field=key),self.assertRaises(LifecycleError):
                body_read(body_bytes=canonical_bytes({**body,key:value}))
        with self.subTest(roleTransport='normalized-body-is-not-raw-body'),self.assertRaises(LifecycleError):
            body_read(body_bytes=canonical_bytes(body))
        for label,change in [('input-substitution',lambda x:x['thread']['turns'][0]['items'][0]['content'][0].update(text='changed')),
                             ('extra-turn',lambda x:x['thread']['turns'].append(x['thread']['turns'][0].copy())),
                             ('tool-item',lambda x:x['thread']['turns'][0]['items'][1].update(type='commandExecution')),
                             ('changed-reasoning',lambda x:x['thread']['turns'][0]['items'][1].update(summary=['changed']))]:
            with self.subTest(roleTransport='stable-read-refuses',mutation=label):
                value=json.loads(read_raw);change(value)
                with self.assertRaises(LifecycleError):body_read(second=canonical_bytes(value))
        with self.subTest(roleTransport='reserved-operation-must-match-session'):
            other={**binding,'operationId':'other'};rows=copy.deepcopy(records);rows[0]['binding']=other
            with self.assertRaises(LifecycleError):transport(rows,expected_binding=other)
        # Exercise SOURCE semantics with a controlled strict-request reader. This
        # cannot establish accepted SHARED, real source dispatch or host terminal.
        identity=bootstrap_r11._r11_role_identity(authority=authority,base_raw=canonical_bytes(base),
            inventory_raw=canonical_bytes(inventory),funding_raw=canonical_bytes(funding))
        source_subject=bootstrap_r11._r11_role_subject(identity,'source-01','c'*64,authority['schemas'])
        source_body=body_for(source_subject);source_raw=canonical_bytes(source_body)
        source_request=json.loads(sealed['requestRaw']);source_request['params']['input'][0]['text']='controlled SOURCE request'
        source_request_raw=canonical_bytes(source_request)+b'\n'
        controlled={**sealed,'requestRaw':source_request_raw,'subject':source_subject,'reservationRequestMatched':True}
        source_read=json.loads(read_raw);source_read['thread']['turns'][0]['items'][0]['content']=source_request['params']['input']
        source_read['thread']['turns'][0]['items'][-1]['text']=source_raw.decode()
        with self.subTest(roleTransport='source-body-component-with-controlled-reserved-request'):
            with patch.object(bootstrap_r11,'read_source_review_request',return_value=controlled):
                result=body_read(body_bytes=source_raw,first=canonical_bytes(source_read),second=canonical_bytes(source_read),
                    expected=source_subject,request=source_request_raw)
            self.assertEqual(result['approvedIntegrationScopes'],['COLLECTOR_FIRST_NATIVE','OBSERVER_TERMINAL'])
            self.assertEqual(result['closedParentFindingIds'],[]);self.assertFalse(result['sharedEvidenceAccepted'])
        # Durable recorder/readback uses actual oversized request records, hence
        # its existing multipart transcript path participates in this join.
        class Writer:
            def write(self,raw):return len(raw)
            def flush(self):pass
        recorder=bootstrap_r11.SourceReviewTranscript(root,binding=binding)
        for row in records[1:]:
            if row['kind']=='RECEIVED':recorder.receive(bytes.fromhex(row['rawHex']))
            else:recorder._record(row['kind'],**{k:v for k,v in row.items() if k not in {'sequence','monotonicNs','kind'}})
        with self.subTest(roleTransport='private-archive-independent-reopen'):
            archived=bootstrap_r11.collect_source_review_transport(root,expected_binding=binding,
                expected_request=sealed['requestRaw'],expected_subject=subject,body_raw=body_raw,role_delivery=True)
            self.assertEqual(archived['transport']['bodyReadMatch']['bodySha256'],hashlib.sha256(body_raw).hexdigest())
            self.assertFalse(archived['producerQualified']);self.assertFalse(archived['costQualified'])
        with self.subTest(roleTransport='body-without-worker-terminal-cannot-be-promoted'):
            worker=bootstrap_r11._r11_cost_worker(root,binding,reservation['heldUnknownTokens'],review_id=review,
                cost_chain_sha=bootstrap_r11.read_source_review_cost(root,review_id=review,role_delivery=True)['costChainSha256'],
                request_sha=sealed['requestSha256'])
            self.assertEqual(worker['state'],'START_UNCERTAIN')
            self.assertFalse(archived['firstNativeBootstrapEligible'])
        for mode in (1,'v6'):
            with self.subTest(roleTransport='mode-is-explicit',mode=mode),self.assertRaises(LifecycleError):
                bootstrap_r11.verify_source_review_transport_records(root,expected_binding=binding,
                    expected_request=sealed['requestRaw'],expected_subject=subject,body_raw=body_raw,
                    transcript_raw=b''.join(canonical_bytes(row)+b'\n' for row in records),role_delivery=mode)
        self._check_role_rpc_sender()


    @_retired_r11_positive
    def test_role_failure_preserves_successful_evidence_without_retry(self):
        self._check_retired_v5_auxiliaries()
        self._check_retired_v5_runtime()
        # Existing supervised process runner and terminal/cost readers are real;
        # child is a local Python fixture, not Codex or a source-review auditor.
        from datetime import datetime,timedelta
        for outcome in ('PASS','FAILED','TIMEOUT'):
            root,authority,base,inventory,funding,shared,source,directory,binding=self._role_funded_transport_fixture(padding=0)
            review=base['reviewId']
            sealed=bootstrap_r11.seal_source_review_request(root,review_id=review,binding=binding,
                exposure_raw=canonical_bytes(shared),model_context_window=1000000)
            reservation=bootstrap_r11.reserve_source_review_cost(root,review_id=review,binding=binding,role_delivery=True)
            cost=bootstrap_r11.read_source_review_cost(root,review_id=review,role_delivery=True)
            for name in bootstrap_r11._R11_VALIDATION_ROOTS:(root/name).mkdir(parents=True,exist_ok=True)
            worker=root/'src/role_fixture.py'
            worker.write_text("import sys,json,time,hashlib\nfrom pathlib import Path\nv=json.loads(Path(sys.argv[1]).read_bytes())\nr=Path(v['reservation']).read_bytes()\nassert hashlib.sha256(r).hexdigest()==v['reservationSha256']\nh=json.loads(Path(v['head']).read_bytes())\nassert h['sourcePath']==v['globalPrefixPath']\nPath(v['marker']).write_text('prestart reservation and global prefix present')\nif v['outcome']=='TIMEOUT':time.sleep(3)\nsys.exit(7 if v['outcome']=='FAILED' else 0)\n")
            instruction=directory/'fixture-worker.json';marker=root/'fixture-started.txt'
            value={'reservation':str(directory/'role-cost/shared-01/reservation.json'),'reservationSha256':canonical_digest(reservation),
                'head':str(root/bootstrap_r11._R11_COORDINATOR_HEAD),'globalPrefixPath':bootstrap_r11.read_coordinator_cost_head(root)['head']['sourcePath'],
                'marker':str(marker),'outcome':outcome}
            _write_exclusive(instruction,canonical_bytes(value),root=root)
            timeout=1 if outcome=='TIMEOUT' else 10
            options=dict(review_id=review,binding=binding,worker_path=worker,instruction_path=instruction,
                expected_instruction_sha256=canonical_digest(value),timeout_seconds=timeout,role_delivery=True)
            immutable={p.relative_to(directory).as_posix():p.read_bytes() for p in directory.rglob('*') if p.is_file()}
            if outcome=='PASS':
                class Expired(datetime):
                    @classmethod
                    def now(cls,tz=None):return datetime.fromisoformat(reservation['absoluteDeadlineUtc'].replace('Z','+00:00'))+timedelta(seconds=1)
                with self.subTest(roleWorker='expired-original-deadline-refuses-before-process'):
                    with patch.object(bootstrap_r11,'datetime',Expired),self.assertRaises(LifecycleError):
                        bootstrap_r11._r11_cost_before_start(root,review,binding,reservation['heldUnknownTokens'],timeout,role_delivery=True)
                    self.assertFalse(marker.exists());self.assertFalse(bootstrap_r11._r11_worker_directory(root,binding).exists())
                for held in (0,reservation['heldUnknownTokens']+360000):
                    with self.subTest(roleWorker='different-hold-refuses',held=held),self.assertRaises(LifecycleError):
                        bootstrap_r11._r11_cost_before_start(root,review,binding,held,timeout,role_delivery=True)
            with self.subTest(roleWorker='real-supervised-outcome-and-full-settlement',outcome=outcome):
                result=bootstrap_r11._supervise_costed_source_review_worker(root,**options)
                expected='WORKER_PROCESS_FINISHED' if outcome=='PASS' else 'WORKER_FAILED'
                self.assertEqual(result['worker']['status'],expected)
                self.assertEqual(result['cost']['worker']['state'],expected)
                self.assertTrue(marker.exists());self.assertFalse(result['producerQualified'])
                self.assertFalse(result['firstNativeBootstrapEligible']);self.assertFalse(result['retryAuthorized'])
                self.assertEqual(result['worker']['hostModelStart'],'UNPROVEN')
                self.assertEqual(result['cost']['releasedUnknownTokens'],0);self.assertIsNone(result['cost']['actualModelTokens'])
                self.assertEqual(result['cost']['heldUnknownTokens'],reservation['heldUnknownTokens'])
                fresh=bootstrap_r11.read_source_review_cost(root,review_id=review,role_delivery=True)
                self.assertEqual(fresh['fundingOrigin']['costPrefix']['recordCount'],2)
                self.assertEqual(fresh['unreservedRoleIds'],['source-01']);self.assertFalse(fresh['allRolesSettled'])
                self.assertEqual(bootstrap_r11.read_source_review_worker(root,binding=binding),result['worker'])
                self.assertTrue(all((directory/name).read_bytes()==raw for name,raw in immutable.items()))
                self.assertEqual(bootstrap_r11.read_coordinator_cost_head(root)['head']['unknownHolds'],funding['admittedUnknownHolds'])
            with self.subTest(roleWorker='settled-attempt-cannot-run-again',outcome=outcome):
                before=bootstrap_r11.read_coordinator_cost_head(root)['headRaw'];marker_raw=marker.read_bytes()
                with self.assertRaises(LifecycleError):bootstrap_r11._supervise_costed_source_review_worker(root,**options)
                self.assertEqual(bootstrap_r11.read_coordinator_cost_head(root)['headRaw'],before);self.assertEqual(marker.read_bytes(),marker_raw)
            with self.subTest(roleWorker='terminal-mutation-refuses-without-refund',outcome=outcome):
                terminal=bootstrap_r11._r11_worker_directory(root,binding)/'terminal.json';raw=terminal.read_bytes()
                terminal.write_bytes(canonical_bytes({**json.loads(raw),'heldUnknownTokens':0}))
                try:
                    with self.assertRaises(LifecycleError):bootstrap_r11.read_source_review_cost(root,review_id=review,role_delivery=True)
                    self.assertEqual(bootstrap_r11.read_coordinator_cost_head(root)['head']['unknownHolds'],funding['admittedUnknownHolds'])
                finally:terminal.write_bytes(raw)
            if outcome=='PASS':
                next_binding={**binding,'shardId':'source-01','operationId':inventory['roles'][1]['operationId'],'threadId':'source-thread'}
                with self.subTest(roleWorker='process-success-is-not-accepted-shared'),self.assertRaises(LifecycleError):
                    bootstrap_r11.reserve_source_review_cost(root,review_id=review,binding=next_binding,role_delivery=True)


    def _check_all_role_envelope_fit(self):
        root,authority,base,inventory,funding,shared,source=self._role_request_fixture()
        exposures={'shared-01':canonical_bytes(shared),'source-01':canonical_bytes(source)}
        def fit(b=base,i=inventory,f=funding,e=exposures,window=1000000):
            return bootstrap_r11._r11_role_envelope_fit(root,base_raw=canonical_bytes(b),inventory_raw=canonical_bytes(i),
                funding_raw=canonical_bytes(f),exposure_raw_by_role=e,model_context_window=window)
        def altered_shared(padding):
            x={**shared,'padding':padding};b={**base,'sharedExposureSha256':canonical_digest(x)}
            i=copy.deepcopy(inventory);i['baseSha256']=canonical_digest(b);i['roles'][0]['exposureSha256']=canonical_digest(x)
            f={**funding,'baseSha256':canonical_digest(b),'roleInventorySha256':canonical_digest(i)}
            return b,i,f,{**exposures,'shared-01':canonical_bytes(x)}
        initial=fit();by_role={r['roleId']:r for r in initial['rows']}
        with self.subTest(allEnvelopes='all-roles-in-one-complete-bound'):
            self.assertTrue(initial['completeEnvelopeFit']);self.assertEqual(len(initial['rows']),2)
            self.assertEqual(initial['hostIdWorstCaseJsonBytes'],1536)
            self.assertEqual(by_role['shared-01']['futureSharedViewAllowanceUtf8Bytes'],0)
            self.assertEqual(by_role['source-01']['futureSharedViewAllowanceUtf8Bytes'],16380)
            self.assertTrue(all(r['actualRequestSha256'] is None and not r['dispatchableTemplate'] for r in initial['rows']))
            for key in ('sourceFreshnessQualified','selectedHostQualified','sharedEvidenceAccepted','fundingAdmitted','dispatchAllowed','firstNativeBootstrapEligible'):
                self.assertFalse(initial[key])
        edge_padding='x'*(245760-by_role['shared-01']['templateUtf8Bytes'])
        with self.subTest(allEnvelopes='exact-complete-request-cap'):
            edge=fit(*altered_shared(edge_padding));self.assertTrue(edge['completeEnvelopeFit'])
            self.assertEqual(edge['rows'][0]['requestUtf8ByteUpperBound'],245760)
        with self.subTest(allEnvelopes='one-role-overflow-denies-whole-batch'):
            denied=fit(*altered_shared(edge_padding+'x'));self.assertEqual(denied['status'],'DENY')
            self.assertEqual(denied['refusedRoleIds'],['shared-01']);self.assertEqual(len(denied['rows']),2)
            self.assertFalse(denied['dispatchAllowed'])
        with self.subTest(allEnvelopes='escaping-counted-in-all-json-layers'):
            denied=fit(*altered_shared('\\'*60000));self.assertFalse(denied['completeEnvelopeFit'])
            self.assertIn('shared-01',denied['refusedRoleIds'])
        minimum=max(r['requestUtf8ByteUpperBound']+8192+16384 for r in initial['rows'])
        with self.subTest(allEnvelopes='exact-context-budget-bound'):self.assertTrue(fit(window=minimum)['completeEnvelopeFit'])
        with self.subTest(allEnvelopes='one-byte-context-short'):self.assertFalse(fit(window=minimum-1)['completeEnvelopeFit'])
        for value in (0,True,'272000',None):
            with self.subTest(allEnvelopes='invalid-window',value=value),self.assertRaises(LifecycleError):fit(window=value)
        for bad in ({'shared-01':exposures['shared-01']},{**exposures,'source-02':exposures['source-01']},
                    {**exposures,'source-01':b'{}'},{**exposures,'shared-01':'not-bytes'}):
            with self.subTest(allEnvelopes='missing-extra-or-changed-exposure',keys=list(bad)),self.assertRaises(LifecycleError):fit(e=bad)
        # Compare actual serialized requests with the pre-model bound for
        # maximal control/quote/backslash/Unicode identifiers and valid exact
        # shared bodies with differing raw whitespace/escape representations.
        identity=bootstrap_r11._r11_role_identity(authority=authority,base_raw=canonical_bytes(base),
            inventory_raw=canonical_bytes(inventory),funding_raw=canonical_bytes(funding))
        subject=bootstrap_r11._r11_role_subject(identity,'shared-01',None,authority['schemas'])
        body={'schemaVersion':'alk-route-bootstrap-reviewer-body.v6-r11','verdict':'PASS','phase':'PRE_WS01',
            'rb11RuntimeStatus':'NOT_RUN','subjectSha256':canonical_digest(subject),
            **{key:subject[key] for key in ('baseSha256','roleInventorySha256','fundingBatchSha256','roleId',
                                           'roleKind','exposureSha256','sharedEvidenceSha256')},
            'sharedContentSeenByThisRole':True,'assignedContentComplete':True,'inheritedCoverageAccepted':True,
            'interactionScopeComplete':True,'approvedIntegrationScopes':[],'closedParentFindingIds':[],
            'findings':[],'reviewText':'NO_CURRENT_FINDINGS'}
        compact=canonical_bytes(body);escaped=compact.replace(b'NO_CURRENT_FINDINGS',b'\\u004eO_CURRENT_FINDINGS')
        bodies=[compact,escaped,compact+b'\n'*(4096-len(compact)),compact+b'\t'*(4096-len(compact))]
        for thread in ('\x00'*256,'"'*256,'\\'*256,'ё'*128,'😀'*64):
            actual=bootstrap_r11._r11_role_request_candidate(root,base_raw=canonical_bytes(base),
                inventory_raw=canonical_bytes(inventory),funding_raw=canonical_bytes(funding),role_id='shared-01',
                exposure_raw=exposures['shared-01'],thread_id=thread,model_context_window=1000000)
            with self.subTest(allEnvelopes='actual-shared-below-bound',thread=repr(thread[:2])):
                self.assertLessEqual(len(actual['requestRaw']),by_role['shared-01']['requestUtf8ByteUpperBound'])
        for raw in bodies:
            receipt={key:'c'*64 for key in authority['schemas']['sharedEvidence']['properties']}
            receipt.update(schemaVersion='alk-r11-shared-evidence.v1',status='SHARED_ACCEPTED',reviewId=base['reviewId'],
                **{key:identity[key] for key in ('baseSha256','roleInventorySha256','fundingBatchSha256')},
                subjectSha256=canonical_digest(subject),bodyRawSha256=hashlib.sha256(raw).hexdigest(),
                binding={'shardId':'shared-01','operationId':'shared-op','threadId':'shared-thread',
                         'binarySha256':'d'*64,'transportSourceSha256':'e'*64},firstNativeBootstrapEligible=False)
            for thread in ('\x00'*256,'\\'*256,'ё'*128):
                with self.subTest(allEnvelopes='actual-source-below-future-view-bound',bodyBytes=len(raw),thread=repr(thread[:2])):
                    actual=bootstrap_r11._r11_role_request_candidate(root,base_raw=canonical_bytes(base),
                        inventory_raw=canonical_bytes(inventory),funding_raw=canonical_bytes(funding),role_id='source-01',
                        exposure_raw=exposures['source-01'],thread_id=thread,model_context_window=1000000,
                        shared_evidence_raw=canonical_bytes(receipt),shared_body_raw=raw)
                    self.assertLessEqual(len(actual['requestRaw']),by_role['source-01']['requestUtf8ByteUpperBound'])
                    self.assertFalse(actual['dispatchAllowed']);self.assertFalse(actual['sharedEvidenceAccepted'])
        # Full33-role inventory; no first-role-only shortcut or dropped tail.
        i=copy.deepcopy(inventory);e=dict(exposures)
        for index in range(2,33):
            role_id=f'source-{index:02d}';x={**source,'requiredIntegrationScopes':[],'integrationClosureContent':{}}
            e[role_id]=canonical_bytes(x);i['roles'].append({**i['roles'][1],'roleId':role_id,
                'operationId':role_id+'-op','exposureSha256':canonical_digest(x),'requiredIntegrationScopes':[]})
        f={**funding,'roleInventorySha256':canonical_digest(i),'tokenCap':33*360000,'protectedCloseoutTokens':33*100000,
            'admittedUnknownHolds':funding['priorUnknownHolds']+33*360000,
            'admittedExposureLowerBound':funding['priorExposureLowerBound']+33*360000,
            'slots':[{**funding['slots'][0],'roleId':r['roleId']} for r in i['roles']]}
        with self.subTest(allEnvelopes='maximum33-role-batch'):
            full=fit(i=i,f=f,e=e);self.assertTrue(full['completeEnvelopeFit']);self.assertEqual(len(full['rows']),33)
            self.assertEqual(full['rows'][-1]['roleId'],'source-32')
        # Integration boundary: actual local declared funding/prefix/immutable
        # files, controlled source reconstruction and bundled-catalog reader.
        r,auth,b,i,f,sh,so,directory,binding=self._role_funded_transport_fixture(padding=0)
        for name in bootstrap_r11._R11_VALIDATION_ROOTS:(r/name).mkdir(parents=True,exist_ok=True)
        catalog={'selected':{'catalogWindowTokens':1000000},'evidenceSha256':'e'*64}
        role_basis={'baseRaw':canonical_bytes(b),'roleInventoryRaw':canonical_bytes(i),
                    'roleExposureRaw':{'shared-01':canonical_bytes(sh),'source-01':canonical_bytes(so)}}
        rebuilt={'candidate':{'status':'ROLE_RECONSTRUCTION_UNQUALIFIED','roleBasis':role_basis}}
        def joined(value=rebuilt,selected=catalog):
            with patch.object(bootstrap_r11,'reconstruct_source_review',return_value=value) as recon, \
                 patch.object(bootstrap_r11,'read_source_review_catalog',return_value=selected):
                result=bootstrap_r11.read_source_review_envelope_fit(r,review_id=b['reviewId'])
                self.assertEqual(recon.call_args.kwargs['operation_ids'],[x['operationId'] for x in i['roles']])
                self.assertTrue(recon.call_args.kwargs['role_delivery'])
                return result
        with self.subTest(allEnvelopes='joined-current-basis-with-controlled-source-catalog'):
            current=joined();self.assertTrue(current['completeEnvelopeFit']);self.assertTrue(current['sourceFreshnessQualified'])
            self.assertTrue(current['fundingAdmitted']);self.assertFalse(current['dispatchAllowed'])
            self.assertFalse(current['selectedHostQualified']);self.assertEqual(current['actualChildWindow'],'UNPROVEN')
        for label,changed in [('source-refusal',{'candidate':{'status':'DENY','completeEnvelopeFit':True}}),
                              ('base-substitution',{'candidate':{'status':'ROLE_RECONSTRUCTION_UNQUALIFIED',
                                  'roleBasis':{**role_basis,'baseRaw':b'{}'}}}),
                              ('inventory-substitution',{'candidate':{'status':'ROLE_RECONSTRUCTION_UNQUALIFIED',
                                  'roleBasis':{**role_basis,'roleInventoryRaw':b'{}'}}})]:
            with self.subTest(allEnvelopes='reconstruction-refuses',reason=label),self.assertRaises(LifecycleError):joined(changed)
        with self.subTest(allEnvelopes='current-catalog-too-small'),self.assertRaises(LifecycleError):
            joined(selected={**catalog,'selected':{'catalogWindowTokens':100}})
        def mutate_source(*args,**kwargs):
            (r/'src/changed.py').write_text('# changed after initial snapshot\n');return rebuilt
        with self.subTest(allEnvelopes='source-changed-during-reconstruction'):
            with patch.object(bootstrap_r11,'reconstruct_source_review',side_effect=mutate_source), \
                 patch.object(bootstrap_r11,'read_source_review_catalog',return_value=catalog),self.assertRaises(LifecycleError):
                bootstrap_r11.read_source_review_envelope_fit(r,review_id=b['reviewId'])
        with self.subTest(allEnvelopes='catalog-changed-during-fit'):
            with patch.object(bootstrap_r11,'reconstruct_source_review',return_value=rebuilt), \
                 patch.object(bootstrap_r11,'read_source_review_catalog',side_effect=[catalog,{**catalog,'evidenceSha256':'f'*64}]),self.assertRaises(LifecycleError):
                bootstrap_r11.read_source_review_envelope_fit(r,review_id=b['reviewId'])


    def _check_role_rpc_sender(self):
        # Real private request/cost/all-envelope joins and RPC recorder; source
        # reconstruction/catalog and raw host frames controlled, no actual Codex.
        from agent_lifecycle.adapter_sessions.codex_exact_prompt import _file_sha
        for scenario in ('complete','changed-seal-after-resume'):
            root,authority,base,inventory,funding,shared,source,directory,binding=self._role_funded_transport_fixture(padding=0)
            for name in bootstrap_r11._R11_VALIDATION_ROOTS:(root/name).mkdir(parents=True,exist_ok=True)
            binary=root/'codex';binary.write_bytes(b'fixture binary; never executed\n');binary.chmod(0o700)
            binding.update(binarySha256=_file_sha(binary),transportSourceSha256=_file_sha(Path(bootstrap_r11.__file__)))
            sealed=bootstrap_r11.seal_source_review_request(root,review_id=base['reviewId'],binding=binding,
                exposure_raw=canonical_bytes(shared),model_context_window=1000000)
            reservation=bootstrap_r11.reserve_source_review_cost(root,review_id=base['reviewId'],binding=binding,role_delivery=True)
            catalog={'binaryPath':str(binary),'selected':{'catalogWindowTokens':1000000,'model':'fixture-model',
                     'binarySha256':binding['binarySha256']},'evidenceSha256':'e'*64}
            rebuilt={'candidate':{'status':'ROLE_RECONSTRUCTION_UNQUALIFIED','roleBasis':{
                'baseRaw':canonical_bytes(base),'roleInventoryRaw':canonical_bytes(inventory),
                'roleExposureRaw':{'shared-01':canonical_bytes(shared),'source-01':canonical_bytes(source)}}}}
            subject=sealed['subject'];body={'schemaVersion':'alk-route-bootstrap-reviewer-body.v6-r11','verdict':'PASS',
                'phase':'PRE_WS01','rb11RuntimeStatus':'NOT_RUN','subjectSha256':canonical_digest(subject),
                **{key:subject[key] for key in ('baseSha256','roleInventorySha256','fundingBatchSha256','roleId',
                                               'roleKind','exposureSha256','sharedEvidenceSha256')},
                'sharedContentSeenByThisRole':True,'assignedContentComplete':True,'inheritedCoverageAccepted':True,
                'interactionScopeComplete':True,'approvedIntegrationScopes':[],'closedParentFindingIds':[],
                'findings':[],'reviewText':'NO_CURRENT_FINDINGS'}
            body_raw=canonical_bytes(body);fixture=_R11TransportFixture(methodName='runTest')
            fixture.root=root;fixture.binding=binding;fixture.request=sealed['requestRaw'];fixture.body_raw=body_raw
            raw_messages=[bytes.fromhex(row['rawHex'])+b'\n' for row in fixture.build() if row['kind']=='RECEIVED']
            review_messages=raw_messages[:-2];read_result=fixture.read(body_raw);frames=[];sent=[];self_test=self
            thread={'id':'thread','turns':[],'ephemeral':False,'forkedFromId':None,'historyMode':'legacy','status':{'type':'idle'}}
            class PipeWriter:
                def write(self,raw):
                    q=json.loads(raw);sent.append(q);ident=q.get('id');method=q['method']
                    if method=='initialize':frames.append(canonical_bytes({'id':ident,'result':{'userAgent':'fixture'}})+b'\n')
                    elif method=='initialized':pass
                    elif method=='model/list':frames.append(canonical_bytes({'id':ident,'result':{'data':[{'model':'fixture-model'}]}})+b'\n')
                    elif method=='thread/resume':
                        frames.append(canonical_bytes({'id':ident,'result':{'thread':thread,'model':'fixture-model'}})+b'\n')
                        if scenario=='changed-seal-after-resume':
                            path=directory/'role-requests/shared-01/seal.json';v=json.loads(path.read_bytes());v['unexpected']=True;path.write_bytes(canonical_bytes(v))
                    elif method=='thread/read':
                        result=read_result if q['params']['includeTurns'] else {'thread':thread}
                        frames.append(canonical_bytes({'id':ident,'result':result})+b'\n')
                    elif method=='turn/start':
                        self_test.assertEqual(raw,sealed['requestRaw'])
                        current=bootstrap_r11.read_source_review_cost(root,review_id=base['reviewId'],role_delivery=True)
                        self_test.assertEqual(current['reservations'],[reservation])
                        self_test.assertEqual(current['fundingOrigin']['costPrefix']['recordCount'],1)
                        frames.extend(review_messages)
                    else:raise AssertionError(method)
                    return len(raw)
                def flush(self):pass
            original_read=os.read
            def read_frame(fd,size):
                if fd!=987654321:return original_read(fd,size)
                self.assertTrue(frames,'sender attempted unexpected read')
                raw=frames.pop(0);self.assertLessEqual(len(raw),size);return raw
            options=dict(binding=binding,expected_request=sealed['requestRaw'],expected_subject=subject,
                model='fixture-model',binary_path=binary,reader=SimpleNamespace(fileno=lambda:987654321),
                writer=PipeWriter(),role_delivery=True)
            with patch.object(bootstrap_r11,'read_source_review_catalog',return_value=catalog), \
                 patch.object(bootstrap_r11,'_r11_require_fresh_review_catalog',return_value=catalog), \
                 patch.object(bootstrap_r11,'reconstruct_source_review',return_value=rebuilt), \
                 patch.object(bootstrap_r11.os,'read',side_effect=read_frame):
                if scenario=='complete':
                    with self.subTest(roleSender='unfit-batch-refuses-before-any-rpc'):
                        with patch.object(bootstrap_r11,'reconstruct_source_review',return_value={'candidate':{'status':'DENY'}}),self.assertRaises(LifecycleError):
                            bootstrap_r11._exchange_source_review_rpc(root,**options)
                        self.assertEqual(sent,[]);self.assertFalse((root/bootstrap_r11._R11_REVIEW_ROOT/'shards/shared-01/host-wire').exists())
                    with self.subTest(roleSender='source-remains-blocked-without-shared-collector'),self.assertRaises(LifecycleError):
                        bootstrap_r11._r11_role_send_basis(root,binding={**binding,'shardId':'source-01'},
                            request_raw=sealed['requestRaw'],subject={**subject,'roleKind':'SOURCE'},binary_path=binary,model='fixture-model')
                    with self.subTest(roleSender='v6-host-launch-refuses-unfit-before-popen'):
                        real_popen=bootstrap_r11.subprocess.Popen;host_launches=[]
                        def checked_popen(argv,*args,**kwargs):
                            # Git subprocesses used by the real authority reader
                            # must remain real; intercept only the selected host.
                            if str(argv[0])==str(binary):
                                host_launches.append(argv)
                                raise AssertionError('unfit batch reached host launch')
                            return real_popen(argv,*args,**kwargs)
                        with patch.object(bootstrap_r11.os,'getpgrp',return_value=os.getpid()), \
                             patch.object(bootstrap_r11,'reconstruct_source_review',return_value={'candidate':{'status':'DENY'}}), \
                             patch.object(bootstrap_r11.subprocess,'Popen',side_effect=checked_popen),self.assertRaisesRegex(LifecycleError,'current complete source/support reconstruction refused'):
                            bootstrap_r11._run_source_review_app_server_worker(root,binding=binding,binary_path=binary,
                                expected_request=sealed['requestRaw'],expected_subject=subject,model='fixture-model',role_delivery=True)
                        self.assertEqual(host_launches,[])
                    with self.subTest(roleSender='one-exact-v6-turn-after-all-guards'):
                        result=bootstrap_r11._exchange_source_review_rpc(root,**options)
                        self.assertTrue(result['roleDelivery']);self.assertEqual(result['threadCreationMode'],'RESERVED_EMPTY_ROLE_THREAD')
                        self.assertEqual([q['method'] for q in sent],['initialize','initialized','model/list','thread/resume','thread/read','turn/start','thread/read','thread/read'])
                        self.assertEqual(len([q for q in sent if q['method']=='turn/start']),1)
                        self.assertEqual(result['transport']['transport']['bodyReadMatch']['roleId'],'shared-01')
                        self.assertFalse(result['producerQualified']);self.assertFalse(result['firstNativeBootstrapEligible'])
                        self.assertEqual(result['actualChildWindow'],'UNPROVEN');self.assertEqual(frames,[])
                        self.assertEqual((root/bootstrap_r11._R11_REVIEW_ROOT/'shards/shared-01/review-body.raw').read_bytes(),body_raw)
                    with self.subTest(roleSender='exclusive-exchange-cannot-send-a-second-turn'):
                        count=len(sent)
                        with self.assertRaises((LifecycleError,OSError)):bootstrap_r11._exchange_source_review_rpc(root,**options)
                        self.assertEqual(len(sent),count)
                else:
                    with self.subTest(roleSender='change-after-host-metadata-refuses-model-bytes'),self.assertRaises(LifecycleError):
                        bootstrap_r11._exchange_source_review_rpc(root,**options)
                    self.assertEqual([q['method'] for q in sent],['initialize','initialized','model/list','thread/resume','thread/read'])
                    self.assertFalse((root/bootstrap_r11._R11_REVIEW_ROOT/'shards/shared-01/transport').exists())
            self.assertEqual(bootstrap_r11.read_coordinator_cost_head(root)['head']['unknownHolds'],funding['admittedUnknownHolds'])


    def _check_role_inventory_preparation(self):
        # Real packing/serializer and private publication/ledger primitives;
        # current source/support reconstruction and host catalog are controlled.
        m=bootstrap_r11
        root,authority,*_=self._role_request_fixture()
        keys=[('CURRENT','src/a.py'),('CURRENT','src/b.py')]
        sources={key:('def f():\n    return "'+'x'*115000+'"\n').encode() for key in keys}
        required={key:[(0,len(raw))] for key,raw in sources.items()}
        scopes=dict(zip(('OBSERVER_TERMINAL','COLLECTOR_FIRST_NATIVE'),({key:required[key]} for key in keys)))
        state={'sources':sources,'required':required,'dependencies':{'edges':[],'callsRequiringInteractionReview':[]},
            'integrationScopes':scopes,'staticPairs':[],'partition':{},'subject':{},'parent':{'parentVerdict':'FAIL'}}
        with patch.object(m,'_r11_role_source_basis',return_value=state), \
             patch.object(m,'capture_review_validation_sources',return_value={'controlled':'a'*64}), \
             patch.object(m,'collect_source_review_parent',return_value=state['parent']), \
             patch.object(m,'_r11_review_parent_sources',return_value={}), \
             patch.object(m,'_r11_required_interaction_scopes',return_value=scopes), \
             patch.object(m,'_r11_parent_snapshot',return_value=({'review-body.raw':b'{"verdict":"FAIL"}'},{})), \
             patch.object(m,'_r11_review_authorities',return_value={'terminalContractContent':'Exact terminal contract'}), \
             patch.object(m,'_r11_reconstruct_review_basis',return_value={'controlledBasisOnly':True}):
            def pack(window=1000000):
                return m.build_source_review_shards(root,role_delivery=True,review_id='review',
                    operation_ids=['shared-op','source-a','source-b'],model_context_window=window)
            with self.subTest(preparation='complete-envelope-packs-two-where-source-only-packs-one'):
                old=m.build_source_review_shards(root,role_delivery=True,model_context_window=1000000)
                result=pack()
                self.assertEqual(len(old['sourceProjection']['roles']),1)
                self.assertEqual(len(result['sourceProjection']['roles']),2)
                self.assertEqual(result['packingFitScope'],'COMPLETE_SOURCE_ENVELOPE_UPPER_BOUND')
                self.assertEqual(result['status'],'ROLE_RECONSTRUCTION_UNQUALIFIED')
                self.assertFalse(result['completeEnvelopeFit']);self.assertFalse(result['dispatchAllowed'])
                self.assertTrue(all(n<=245760 for n in result['assignedCompleteEnvelopeUpperBoundBytes']))
            with self.subTest(preparation='context-bound-and-one-byte-short'):
                window=max(result['assignedCompleteEnvelopeUpperBoundBytes'])+8192+16384
                self.assertEqual(pack(window)['status'],'ROLE_RECONSTRUCTION_UNQUALIFIED')
                self.assertEqual(pack(window-1)['status'],'DENY')
            with self.subTest(preparation='unsplittable-pair-overflow-refuses'):
                state['staticPairs']=[required]
                self.assertEqual(pack()['reasonCode'],'r11-role-complete-unit-or-pair-overflow')
                state['staticPairs']=[]
            with self.subTest(preparation='mandatory-closure-overflow-refuses'), \
                 patch.object(m,'_r11_review_authorities',return_value={'terminalContractContent':'\\"'*70000}):
                self.assertEqual(pack()['reasonCode'],'r11-role-mandatory-envelope-overflow')
        # Publication uses a real isolated coordinator seed/opening. No global
        # funds are admitted by prepare; its exact output can subsequently fund.
        for scenario in ('success','overflow','partial-write','source-stale','head-stale','expired'):
            root,authority,base,inventory,_,shared,source=self._role_request_fixture(
                padding='x'*245000 if scenario=='overflow' else '')
            import subprocess
            from agent_lifecycle.adapter_sessions import codex_exact_prompt as storage
            from datetime import datetime,timedelta,timezone
            subprocess.run(['git','init','-q',str(root)],check=True,capture_output=True,timeout=10)
            primary=m._r11_coordinator_root(Path(__file__).parents[2]);seed_path=root/m._R11_COORDINATOR_SEED
            seed_path.parent.mkdir(parents=True);seed_path.write_bytes((primary/m._R11_COORDINATOR_SEED).read_bytes())
            head=m.advance_coordinator_cost_head(root,source_path=m._R11_COORDINATOR_SEED)
            origin=m.import_source_review_opening(root,review_id=base['reviewId'])
            origin=m.read_source_review_opening_origin(root,review_id=base['reviewId'],role_delivery=True)
            base.update(openingHeadSha256=origin['coordinatorHeadSha256'],openingSourceSha256=origin['costOpeningSha256'])
            inventory['baseSha256']=canonical_digest(base)
            for name in m._R11_VALIDATION_ROOTS:(root/name).mkdir(parents=True,exist_ok=True)
            directory=m._r11_review_directory(root,base['reviewId']);ops=[r['operationId'] for r in inventory['roles']]
            basis={'baseRaw':canonical_bytes(base),'roleInventoryRaw':canonical_bytes(inventory),
                'roleExposureRaw':{'shared-01':canonical_bytes(shared),'source-01':canonical_bytes(source)}}
            rebuilt={'candidate':{'status':'ROLE_RECONSTRUCTION_UNQUALIFIED','roleBasis':basis}}
            catalog={'selected':{'catalogWindowTokens':1000000},'evidenceSha256':'e'*64}
            real_write=storage._write_exclusive;calls=[]
            def write(path,raw,**kwargs):
                real_write(path,raw,**kwargs)
                if scenario=='partial-write' and path.name=='role-inventory.json':raise OSError('fixture failure after durable inventory write')
            def reconstruct(*args,**kwargs):
                self.assertTrue(kwargs['role_delivery']);self.assertEqual(kwargs['operation_ids'],ops);calls.append(1)
                if scenario=='source-stale' and len(calls)==2:return {**rebuilt,'changedPrivateSupport':True}
                if scenario=='head-stale' and len(calls)==1:
                    value={'status':'ADMITTED_PREAPPROVED_BY_USER','tokenCap':12000,'protectedCloseoutTokens':3000,
                        'actualInputTokens':None,'actualTokens':None,'costStatus':'UNAVAILABLE',
                        'priorUnknownHolds':head['head']['unknownHolds'],
                        'unknownHoldsIncludingThisWindow':head['head']['unknownHolds']+12000,
                        'priorLedgerLowerBound':head['head']['exposureLowerBound'],
                        'ledgerLowerBoundIncludingThisHold':head['head']['exposureLowerBound']+12000,
                        'priorBudgetResumed':False,'priorUnknownHoldsReleased':0}
                    relative=m._R11_COORDINATOR_BASE+'/r900-preparation-race/admission.json'
                    path=root/relative;path.parent.mkdir();path.write_bytes(canonical_bytes(value))
                    m.advance_coordinator_cost_head(root,source_path=relative)
                return rebuilt
            with self.subTest(preparation='public-'+scenario), \
                 patch.object(m,'read_source_review_catalog',return_value=catalog), \
                 patch.object(m,'reconstruct_source_review',side_effect=reconstruct), \
                 patch.object(storage,'_write_exclusive',side_effect=write), \
                 patch.object(m,'datetime',wraps=datetime) as clock:
                now=datetime.now(timezone.utc)
                clock.now.side_effect=[now,now+timedelta(seconds=59401)] if scenario=='expired' else lambda *args:datetime.now(*args)
                if scenario=='success':
                    with self.assertRaises(LifecycleError):m.prepare_source_review_inventory(root,review_id=base['reviewId'],operation_ids=[ops[0],ops[0]])
                    self.assertEqual(calls,[])
                    receipt=m.prepare_source_review_inventory(root,review_id=base['reviewId'],operation_ids=ops)
                    self.assertTrue(receipt['completeEnvelopeFit']);self.assertFalse(receipt['fundingAdmitted'])
                    self.assertFalse(receipt['dispatchAllowed']);self.assertFalse(receipt['firstNativeBootstrapEligible'])
                    self.assertEqual(m.read_coordinator_cost_head(root)['headSha256'],head['headSha256'])
                    current=m._r11_review_cost_basis(root,base['reviewId'],role_delivery=True)
                    funding=current['identity']['funding']
                    self.assertEqual(funding['priorHeadSha256'],head['headSha256'])
                    self.assertEqual(funding['tokenCap'],720000);self.assertIsNone(funding['reusedFirstHold'])
                    self.assertEqual(funding['admittedUnknownHolds'],head['head']['unknownHolds']+720000)
                    self.assertEqual((datetime.fromisoformat(funding['absoluteDeadlineUtc'])-datetime.fromisoformat(funding['admittedAtUtc'])).total_seconds(),59400)
                    for name,digest in receipt['artifactSha256'].items():self.assertEqual(hashlib.sha256(m._r11_review_private(root,directory/name)).hexdigest(),digest)
                    self.assertFalse((directory/'role-preparation.pending.json').exists())
                    self.assertFalse((directory/'planned-assignment.json').exists())
                    with self.assertRaises(LifecycleError):m.prepare_source_review_inventory(root,review_id=base['reviewId'],operation_ids=ops)
                    admitted=m.admit_source_review_funding(root,review_id=base['reviewId'])
                    self.assertTrue(admitted['fundingAdmitted']);self.assertFalse(admitted['dispatchReservationQualified'])
                else:
                    with self.assertRaises((LifecycleError,OSError)):m.prepare_source_review_inventory(root,review_id=base['reviewId'],operation_ids=ops)
                    self.assertFalse((directory/'role-preparation.json').exists())
                    if scenario in ('partial-write','source-stale'):
                        self.assertTrue((directory/'role-preparation.pending.json').exists())
                        self.assertTrue((directory/'role-base.json').exists())
                        with self.assertRaisesRegex(LifecycleError,'partial immutable preparation'):
                            m._r11_review_cost_basis(root,base['reviewId'],role_delivery=True)
                        with self.assertRaises(LifecycleError):m.prepare_source_review_inventory(root,review_id=base['reviewId'],operation_ids=ops)
                    else:self.assertFalse((directory/'role-base.json').exists())
                    if scenario!='head-stale':self.assertEqual(m.read_coordinator_cost_head(root)['headSha256'],head['headSha256'])


    def _check_v6_fixed_worker_input(self):
        # One actual request/funding/current-envelope join. Later input mutation
        # cases reuse these proven immutable reader values at named boundaries;
        # they do not repeatedly traverse the unchanged financial history.
        from agent_lifecycle.adapter_sessions.codex_exact_prompt import _file_sha
        m=bootstrap_r11;module_source=Path(m.__file__).read_bytes()
        root,authority,base,inventory,funding,shared,source,directory,binding=self._role_funded_transport_fixture(padding=0)
        root=root.resolve();worker=root/m._R11_FIXED_WORKER;worker.parent.mkdir(parents=True,exist_ok=True);worker.write_bytes(module_source)
        for name in m._R11_VALIDATION_ROOTS:(root/name).mkdir(parents=True,exist_ok=True)
        binary=root/'codex';binary.write_bytes(b'fixture selected executable; never run\n');binary.chmod(0o700)
        binding.update(binarySha256=_file_sha(binary),transportSourceSha256=_file_sha(worker))
        catalog={'binaryPath':str(binary),'selected':{'catalogWindowTokens':1000000,'model':'fixture-model',
            'binarySha256':binding['binarySha256']},'evidenceSha256':'e'*64}
        rebuilt={'candidate':{'status':'ROLE_RECONSTRUCTION_UNQUALIFIED','roleBasis':{
            'baseRaw':canonical_bytes(base),'roleInventoryRaw':canonical_bytes(inventory),
            'roleExposureRaw':{'shared-01':canonical_bytes(shared),'source-01':canonical_bytes(source)}}}}
        options=dict(review_id=base['reviewId'],binding=binding,binary_path=binary,model='fixture-model',timeout_seconds=60)
        with patch.object(m,'__file__',str(worker)), \
             patch.object(m,'read_source_review_catalog',return_value=catalog), \
             patch.object(m,'reconstruct_source_review',return_value=rebuilt):
            sealed=m.seal_source_review_request(root,review_id=base['reviewId'],binding=binding,
                exposure_raw=canonical_bytes(shared),model_context_window=1000000)
            reservation=m.reserve_source_review_cost(root,review_id=base['reviewId'],binding=binding,role_delivery=True)
            with self.subTest(fixedInput='actual-v6-guarded-basis-without-v5-assignment'):
                basis=m._r11_fixed_worker_basis(root,**options)
                instruction=basis['instruction'];self.assertEqual(instruction['schemaVersion'],'alk-r11-fixed-worker-input.v3-role')
                self.assertEqual(basis['request'],sealed['requestRaw']);self.assertEqual(basis['subject'],sealed['subject'])
                self.assertEqual(instruction['requestSha256'],sealed['requestSha256'])
                self.assertEqual(instruction['requestSealSha256'],sealed['sealSha256'])
                self.assertEqual(instruction['reservationSha256'],canonical_digest(reservation))
                self.assertEqual(instruction['absoluteDeadlineUtc'],reservation['absoluteDeadlineUtc'])
                self.assertEqual(instruction['heldUnknownTokens'],funding['admittedUnknownHolds'])
                self.assertFalse((directory/'planned-assignment.json').exists())
                self.assertEqual(instruction['threadCreationMode'],'RESERVED_THREAD_ORIGIN_UNPROVEN')
                for key in ('metadataThreadOriginQualified','producerQualified','dispatchAllowed','firstNativeBootstrapEligible'):
                    self.assertFalse(instruction[key])
            cost=m.read_source_review_cost(root,review_id=base['reviewId'],role_delivery=True)
            origin=m.read_source_review_opening_origin(root,review_id=base['reviewId'],role_delivery=True)
            def guard(*args,**kwargs):
                self.assertEqual(args,(root,));self.assertEqual(kwargs,dict(binding=binding,request_raw=sealed['requestRaw'],
                    subject=sealed['subject'],binary_path=binary,model='fixture-model'))
                return instruction['sendBasis']
            with patch.object(m,'read_source_review_request',return_value=sealed), \
                 patch.object(m,'read_source_review_cost',return_value=cost), \
                 patch.object(m,'read_source_review_opening_origin',return_value=origin), \
                 patch.object(m,'_r11_role_send_basis',side_effect=guard) as checked_guard:
                with self.subTest(fixedInput='exclusive-publication-and-independent-reader'):
                    prepared=m.prepare_source_review_worker(root,**options);path=Path(prepared['instructionPath'])
                    self.assertEqual(prepared['status'],'V6_FIXED_INPUT_PREPARED_ORIGIN_UNPROVEN')
                    self.assertFalse(prepared['dispatchAllowed']);self.assertFalse(prepared['metadataThreadOriginQualified'])
                    raw=m._r11_review_private(root,path);self.assertEqual(raw,canonical_bytes(instruction))
                    self.assertEqual(m._r11_read_fixed_worker_input(root,path),basis)
                    self.assertGreaterEqual(checked_guard.call_count,3)
                    with self.assertRaises((LifecycleError,OSError)):m.prepare_source_review_worker(root,**options)
                    self.assertEqual(path.read_bytes(),raw)
                with self.subTest(fixedInput='public-supervisor-refuses-before-any-process'), \
                     patch.object(m,'_supervise_costed_source_review_worker') as spawn:
                    with self.assertRaisesRegex(LifecycleError,'actual role metadata creation'):
                        m._supervise_fixed_source_review_worker(root,instruction_path=path)
                    spawn.assert_not_called();self.assertFalse(m._r11_worker_directory(root,binding).exists())
                with self.subTest(fixedInput='fixed-child-refuses-before-host-start'), \
                     patch.object(m.os,'getpgrp',return_value=os.getpid()), \
                     patch.object(m,'_run_source_review_app_server_worker') as host:
                    with self.assertRaisesRegex(LifecycleError,'actual role metadata creation'):
                        m._run_fixed_source_review_worker(root,instruction_path=path)
                    host.assert_not_called()
                for key,value in [('schemaVersion','alk-r11-fixed-worker-input.v2'),('requestSha256','f'*64),
                                  ('metadataThreadOriginQualified',True),('dispatchAllowed',True),('extra','injected')]:
                    with self.subTest(fixedInput='modified-input-refuses',field=key):
                        changed={**instruction,key:value};path.write_bytes(canonical_bytes(changed))
                        try:
                            with self.assertRaises(LifecycleError):m._r11_read_fixed_worker_input(root,path)
                        finally:path.write_bytes(raw)
                with self.subTest(fixedInput='timeout-cannot-reset-reserved-deadline'):
                    with self.assertRaisesRegex(LifecycleError,'original role deadline'):
                        m._r11_fixed_worker_basis(root,**{**options,'timeout_seconds':1800})
                with self.subTest(fixedInput='binding-executable-completed-or-typed-timeout-refuses'):
                    for bad in ({'binding':{**binding,'threadId':'another-thread'}},{'model':''},{'timeout_seconds':True},
                                {'timeout_seconds':1801},{'completed':True},{'completed':1}):
                        with self.assertRaises(LifecycleError):m._r11_fixed_worker_basis(root,**{**options,**bad})
                    original=binary.read_bytes();binary.write_bytes(b'changed selected executable')
                    try:
                        with self.assertRaises(LifecycleError):m._r11_fixed_worker_basis(root,**options)
                    finally:binary.write_bytes(original)
                with self.subTest(fixedInput='source-identity-refuses-before-guard'):
                    old_calls=checked_guard.call_count
                    with self.assertRaises(LifecycleError):m._r11_fixed_worker_basis(root,**{**options,'binding':{**binding,'transportSourceSha256':'0'*64}})
                    self.assertEqual(checked_guard.call_count,old_calls)
            self.assertEqual(m.read_coordinator_cost_head(root)['head']['unknownHolds'],funding['admittedUnknownHolds'])


    def _check_fixed_input_publication(self):
        # Only the changed exclusive-publication wrapper is exercised here;
        # immutable input reconstruction is a controlled boundary. Actual
        # request/funding/all-envelope integration has its separate receipt.
        m=bootstrap_r11
        for scenario in ('success','post-write-basis-failure','write-failure','changed-written-bytes','orphan-pending'):
            with tempfile.TemporaryDirectory() as temporary, self.subTest(fixedPublication=scenario):
                root=Path(temporary).resolve();review='fixed-publication';directory=m._r11_review_directory(root,review)
                binding={'operationId':'shared-op','shardId':'shared-01','threadId':'thread',
                    'binarySha256':'a'*64,'transportSourceSha256':'b'*64}
                instruction={'schemaVersion':'alk-r11-fixed-worker-input.v3-role','projectRoot':str(root),
                    'reviewId':review,'binding':binding,'binaryPath':str(root/'codex'),'model':'fixture',
                    'timeoutSeconds':60,'dispatchAllowed':False,'metadataThreadOriginQualified':False}
                basis={'instruction':instruction,'request':b'controlled','subject':{}}
                options=dict(review_id=review,binding=binding,binary_path=root/'codex',model='fixture',timeout_seconds=60)
                path=directory/'worker-shared-01.json';pending=path.with_suffix('.pending.json');original=m._write
                def write(r,p,value):
                    original(r,p,value)
                    if p==path:
                        self.assertTrue(pending.exists())
                        with self.assertRaisesRegex(LifecycleError,'unfinished fixed-input publication'):
                            m._r11_read_fixed_worker_input(root,path)
                        if scenario=='write-failure':raise OSError('fixture failure after write')
                        if scenario=='changed-written-bytes':path.write_bytes(canonical_bytes({**value,'injected':True}))
                with patch.object(m,'_r11_fixed_worker_basis',return_value=basis) as reconstruct, \
                     patch.object(m,'_write',side_effect=write):
                    if scenario=='orphan-pending':
                        original(root,pending,{'state':'unfinished'})
                        with self.assertRaisesRegex(LifecycleError,'unfinished fixed-input publication'):
                            m._r11_read_fixed_worker_input(root,path)
                        self.assertFalse(path.exists())
                        with self.assertRaises(LifecycleError):m.prepare_source_review_worker(root,**options)
                    elif scenario=='success':
                        result=m.prepare_source_review_worker(root,**options)
                        self.assertFalse(pending.exists());self.assertFalse(result['dispatchAllowed'])
                        self.assertEqual(m._r11_read_fixed_worker_input(root,path),basis)
                        raw=path.read_bytes()
                        with self.assertRaises(LifecycleError):m.prepare_source_review_worker(root,**options)
                        self.assertEqual(path.read_bytes(),raw);self.assertFalse(pending.exists())
                    else:
                        if scenario=='post-write-basis-failure':reconstruct.side_effect=[basis,LifecycleError('fixture-stale','changed after publication')]
                        with self.assertRaises((LifecycleError,OSError)):m.prepare_source_review_worker(root,**options)
                        self.assertTrue(path.exists());self.assertTrue(pending.exists());raw=path.read_bytes()
                        with self.assertRaisesRegex(LifecycleError,'unfinished fixed-input publication'):
                            m._r11_read_fixed_worker_input(root,path)
                        reconstruct.side_effect=None
                        with self.assertRaises(LifecycleError):m.prepare_source_review_worker(root,**options)
                        self.assertEqual(path.read_bytes(),raw);self.assertTrue(pending.exists())

    def _check_v6_role_metadata(self, *, continuation=False, role_id='shared-01'):
        # Actual isolated full-batch admission is reopened once. Mutations below
        # reuse its immutable financial outputs at named boundaries, rather than
        # replaying the same ledger for every metadata-only case. No host runs.
        from datetime import datetime, timedelta, timezone
        from agent_lifecycle.adapter_sessions.codex_exact_prompt import _file_sha
        from agent_lifecycle.contracts.process_execution_schemas import command_identity_hash, process_identity_hash
        m=bootstrap_r11;module_source=Path(m.__file__).read_bytes()
        root,authority,base,inventory,funding,shared,source,directory,binding=self._role_funded_transport_fixture(padding=0)
        review=base['reviewId'];worker=root/m._R11_FIXED_WORKER
        worker.parent.mkdir(parents=True,exist_ok=True);worker.write_bytes(module_source)
        binary=root/'codex';binary.write_bytes(b'fixture executable never run');binary.chmod(0o700)
        basis=m._r11_review_cost_basis(root,review,role_delivery=True)
        cost=m.read_source_review_cost(root,review_id=review,role_delivery=True)
        head=m.read_coordinator_cost_head(root)
        catalog={'binaryPath':str(binary),'selected':{'catalogWindowTokens':1000000,'model':'fixture-model',
            'binarySha256':_file_sha(binary)},'evidenceSha256':'e'*64}
        fit={**{key:basis['identity'][key] for key in ('baseSha256','roleInventorySha256','fundingBatchSha256')},
             'completeEnvelopeFit':True,'catalogEvidenceSha256':catalog['evidenceSha256'],
             'modelContextWindow':1000000,'rows':[{'roleId':'shared-01'},{'roleId':'source-01'}],
             'validationSourcesSha256':{m._R11_FIXED_WORKER:_file_sha(worker)}}
        accepted={'evidenceRaw':b'controlled accepted SHARED boundary'}
        if role_id!='shared-01':
            cost=copy.deepcopy(cost)
            cost['reservations']=[{'binding':binding}]
            cost['settlements']=[{'binding':binding,'worker':{'state':'WORKER_PROCESS_FINISHED'}}]
        options=dict(review_id=review,role_id=role_id,count=1,timeout_seconds=60)
        claim=directory/'role-operations'/role_id;start_path=claim/'start.json'
        input_path=directory/('thread-preparation-'+role_id+'.json');pending=input_path.with_suffix('.pending.json')
        with patch.object(m,'__file__',str(worker)), patch.object(m,'collect_source_review_shared',return_value=accepted), \
             patch.object(m,'_r11_review_cost_basis',return_value=basis), \
             patch.object(m,'read_source_review_cost',return_value=cost), \
             patch.object(m,'read_coordinator_cost_head',return_value=head), \
             patch.object(m,'read_source_review_envelope_fit',return_value=fit), \
             patch.object(m,'read_source_review_catalog',return_value=catalog):
            with patch.object(m,'_supervise_source_review_worker',return_value={'status':'WORKER_PROCESS_FINISHED'}) as supervisor, \
                 patch.object(m,'collect_source_review_threads',return_value={'fixtureCollector':True}) as collector:
                prepared=m.prepare_source_review_threads(root,**options)
                operation=m._r11_role_operation_start(root,review,role_id);value=m._r11_read_thread_preparation_input(root,input_path)
                if not continuation:
                    with self.subTest(metadata='funded-exclusive-operation-and-exact-private-input'):
                        self.assertEqual(prepared,{'fixtureCollector':True})
                        self.assertEqual(operation['value']['operationId'],inventory['roles'][0 if role_id=='shared-01' else 1]['operationId'])
                        self.assertEqual(value['binding']['operationId'],operation['value']['operationId'])
                        self.assertEqual(value['binding']['shardId'],'metadata-'+role_id)
                        self.assertEqual(value['binding']['threadId'],'PREPARATION_ONLY')
                        self.assertEqual(value['operationStartSha256'],operation['sha256'])
                        self.assertEqual(value['heldUnknownTokens'],funding['admittedUnknownHolds'])
                        self.assertEqual(value['modelRequestsAuthorized'],0);self.assertFalse(value['retryAuthorized'])
                        self.assertFalse(pending.exists());self.assertEqual(input_path.read_bytes(),canonical_bytes(value))
                        supervisor.assert_called_once_with(root,binding=value['binding'],worker_path=worker,instruction_path=input_path,
                            expected_instruction_sha256=canonical_digest(value),timeout_seconds=60,held_unknown_tokens=funding['admittedUnknownHolds'],absolute_deadline_monotonic_ns=operation['value']['deadlineMonotonicNs'])
                        collector.assert_called_once_with(root,review_id=review,role_id=role_id)
                        self.assertEqual(len(cost['reservations']),0 if role_id=='shared-01' else 1);self.assertEqual(len(cost['settlements']),len(cost['reservations']))
            if role_id != 'shared-01':
                with self.subTest(sourceMetadata='original-operation-binds-accepted-shared'):
                    self.assertEqual(operation['value']['sharedEvidenceSha256'],hashlib.sha256(accepted['evidenceRaw']).hexdigest())
                    self.assertEqual(value['sharedEvidenceSha256'],operation['value']['sharedEvidenceSha256'])
                    self.assertEqual(value['binding']['shardId'],'metadata-source-01')
                with self.subTest(sourceMetadata='changed-shared-proof-refuses-before-host'),patch.object(m,'collect_source_review_shared',return_value={'evidenceRaw':b'changed'}):
                    with self.assertRaises(LifecycleError):m._r11_role_operation_start(root,review,role_id)
                    with self.assertRaises(LifecycleError):m._r11_role_metadata_before_start(root,value)
                for kind,changed in [('missing-predecessor',{'reservations':[],'settlements':[]}),
                                     ('unsettled-predecessor',{'settlements':[]}),
                                     ('failed-predecessor',{'settlements':[{'worker':{'state':'WORKER_FAILED'}}]})]:
                    with self.subTest(sourceMetadata=kind),patch.object(m,'read_source_review_cost',return_value={**cost,**changed}):
                        with self.assertRaises(LifecycleError):m._r11_role_metadata_before_start(root,value)
                with self.subTest(sourceMetadata='unknown-role-refuses-before-operation-file'):
                    with self.assertRaises(LifecycleError):m.prepare_source_review_threads(root,**{**options,'role_id':'source-33'})
            if continuation == 'absolute_delta':
                with self.subTest(metadata='original-deadline-forwarded-to-supervisor'):
                    self.assertEqual(supervisor.call_args.kwargs['absolute_deadline_monotonic_ns'],operation['value']['deadlineMonotonicNs'])
            if not continuation:
                start_raw=start_path.read_bytes();input_raw=input_path.read_bytes()
                with self.subTest(metadata='no-retry-or-source-or-invalid-count'),patch.object(m,'_supervise_source_review_worker') as supervisor:
                    for changes in ({},{'role_id':'source-01'},{'count':True},{'count':2},{'timeout_seconds':True},{'timeout_seconds':121}):
                        with self.assertRaises(LifecycleError):m.prepare_source_review_threads(root,**{**options,**changes})
                    supervisor.assert_not_called();self.assertEqual(start_path.read_bytes(),start_raw)
                for key,new in [('operationId','other'),('startedMonotonicNs',True),('deadlineMonotonicNs',operation['value']['deadlineMonotonicNs']+1),
                                ('absoluteDeadlineUtc',(datetime.fromisoformat(operation['value']['absoluteDeadlineUtc'])+timedelta(seconds=1)).isoformat()),
                                ('baseSha256','0'*64),('extra',1)]:
                    with self.subTest(metadata='altered-original-operation',field=key):
                        start_path.write_bytes(canonical_bytes({**operation['value'],key:new}))
                        try:
                            with self.assertRaises(LifecycleError):m._r11_role_operation_start(root,review,role_id)
                        finally:start_path.write_bytes(start_raw)
                for key,new in [('modelRequestsAuthorized',1),('operationStartSha256','0'*64),('operationDeadlineMonotonicNs',1),
                                ('envelopeFitIdentitySha256','f'*64),('roleId','unknown-role'),('extra',True)]:
                    with self.subTest(metadata='altered-private-input',field=key):
                        input_path.write_bytes(canonical_bytes({**value,key:new}))
                        try:
                            with self.assertRaises(LifecycleError):m._r11_read_thread_preparation_input(root,input_path)
                        finally:input_path.write_bytes(input_raw)
                with self.subTest(metadata='changed-fit-catalog-binary-refuses'):
                    with patch.object(m,'read_source_review_envelope_fit',return_value={**fit,'rows':[]}):
                        with self.assertRaises(LifecycleError):m._r11_read_thread_preparation_input(root,input_path)
                    with patch.object(m,'read_source_review_catalog',return_value={**catalog,'evidenceSha256':'0'*64}):
                        with self.assertRaises(LifecycleError):m._r11_read_thread_preparation_input(root,input_path)
                    raw=binary.read_bytes();binary.write_bytes(b'changed')
                    try:
                        with self.assertRaises(LifecycleError):m._r11_read_thread_preparation_input(root,input_path)
                    finally:binary.write_bytes(raw)
                for scenario,mono,utc in [('expired-monotonic',operation['value']['deadlineMonotonicNs'],datetime.now(timezone.utc)),
                                         ('backwards-monotonic',operation['value']['startedMonotonicNs']-1,datetime.now(timezone.utc)),
                                         ('expired-wall',operation['value']['startedMonotonicNs'],datetime.fromisoformat(operation['value']['absoluteDeadlineUtc'])),
                                         ('backwards-wall',operation['value']['startedMonotonicNs'],datetime.fromisoformat(operation['value']['startedAtUtc'])-timedelta(seconds=1))]:
                    with self.subTest(metadata=scenario),patch.object(m.time,'monotonic_ns',return_value=mono),patch.object(m,'datetime',wraps=datetime) as clock:
                        clock.now.return_value=utc
                        with self.assertRaises(LifecycleError):m._r11_role_metadata_before_start(root,value)
                for scenario,changed in [('unfunded',{'fundingAdmitted':False}),('unanchored',{'rolePrefixesAnchored':False}),
                                         ('retrospective',{'reservations':[{}]}),('released-hold',{'declaredUnknownHoldsAtFunding':0})]:
                    with self.subTest(metadata=scenario),patch.object(m,'read_source_review_cost',return_value={**cost,**changed}):
                        with self.assertRaises(LifecycleError):m._r11_role_metadata_before_start(root,value)
                with self.subTest(metadata='ordinary-window-and-stale-head-refuse'):
                    for changed in ({'headSha256':'f'*64},{'source':{},'head':{**head['head'],'sourcePath':'window/admission.json'}}):
                        with patch.object(m,'read_coordinator_cost_head',return_value={**head,**changed}):
                            with self.assertRaises(LifecycleError):m._r11_role_metadata_before_start(root,value)
            # Successful collection exercises actual canonical raw wire replay,
            # clock/process/command/environment joins and final stable rereads.
            # The outer worker outcome/source snapshot boundaries are controlled.
            class Wire:
                def __init__(self,thread_id='actual-fixture-thread'):
                    self.buffer=bytearray();self.thread_id=thread_id;self.messages=[];self.groups=[('SESSION',canonical_bytes(value['binding']))]
                def send_bootstrap(self,message):
                    self.messages.append(message);raw=canonical_bytes(message)+b'\n'
                    self.groups.extend([('SEND_PENDING',raw),('WRITE_ACCEPTED',raw),('FLUSHED',canonical_bytes({'sha256':hashlib.sha256(raw).hexdigest()}))])
                def bootstrap_reply(self,ident,thread_id):
                    thread={'id':self.thread_id,'ephemeral':False,'forkedFromId':None,'historyMode':'legacy','turns':[],'status':{'type':'idle'}}
                    reply=({'userAgent':'fixture'} if ident==1000001 else {'thread':thread,'model':value['model']})
                    self.groups.append(('RECEIVED_CHUNK',canonical_bytes({'id':ident,'result':reply})+b'\n'));return reply
            def replay_exchange(wire):
                # Produce synthetic archival bytes, without invoking source dispatch.
                for message in [
                    {'id':1000001,'method':'initialize','params':{'clientInfo':{'name':'agent_lifecycle_kit','title':'Agent Lifecycle Kit','version':'2.16.0'},'capabilities':{'experimentalApi':True}}},
                    {'method':'initialized','params':{}},
                    {'id':1000100,'method':'thread/start','params':{'model':value['model'],'cwd':str(root),'approvalPolicy':'never','sandbox':'read-only','historyMode':'legacy'}},
                    {'id':1000101,'method':'thread/read','params':{'threadId':wire.thread_id,'includeTurns':True}},
                    {'id':1000102,'method':'thread/read','params':{'threadId':wire.thread_id,'includeTurns':True}}]:
                    wire.send_bootstrap(message)
                    if 'id' in message:wire.bootstrap_reply(message['id'],wire.thread_id)
                groups=[{'kind':kind,'raw':raw} for kind,raw in wire.groups]
                return m._r11_empty_thread_exchange(m._R11PreparationReplay(groups,value['binding']),root,value['model'],1)
            wire=Wire();exchange=replay_exchange(wire)
            if not continuation:
                with self.subTest(metadata='metadata-only-methods-and-utf8-id-bound'):
                    self.assertEqual([v['method'] for v in wire.messages],['initialize','initialized','thread/start','thread/read','thread/read'])
                    self.assertEqual(exchange['modelRequestsSent'],0)
                    self.assertEqual(replay_exchange(Wire('я'*128))['threadIds'],['я'*128])
                    with self.assertRaises(LifecycleError):replay_exchange(Wire('я'*129))
            start_ns=operation['value']['startedMonotonicNs']+1_000_000;finish_ns=start_ns+1_000_000
            process={'startedMonotonicNs':start_ns,'absoluteDeadlineMonotonicNs':operation['value']['deadlineMonotonicNs'],'deadlineMonotonicNs':start_ns+60_000_000_000,'cleanup':{'mode':'posix-session'},
                     'processReceipt':{'processIdentityHash':process_identity_hash(pid=12345,started_ns=start_ns)}}
            worker_result={'status':'WORKER_PROCESS_FINISHED','finishedMonotonicNs':finish_ns}
            source_snapshot={'fixture':'a'*64}
            argv=[str(Path(sys.executable).resolve()),'-B',str(worker),str(input_path)]
            env={**os.environ,'PYTHONPATH':str(root/'src'),'PYTHONDONTWRITEBYTECODE':'1','PYTHONUNBUFFERED':'1'}
            reservation={'schemaVersion':'alk-r11-worker-reservation.v1','binding':value['binding'],'workerPath':m._R11_FIXED_WORKER,
                'instructionPath':input_path.relative_to(root).as_posix(),'argv':argv,'commandIdentityHash':command_identity_hash(argv),
                'environmentSha256':canonical_digest(env),'sourceSha256':source_snapshot,'timeoutSeconds':60,
                'absoluteDeadlineMonotonicNs':operation['value']['deadlineMonotonicNs'],
                'heldUnknownTokens':value['heldUnknownTokens'],'costStatus':'UNAVAILABLE','actualModelTokens':None,'retryAuthorized':False}
            worker_dir=m._r11_worker_directory(root,value['binding']);exact._private_dir(worker_dir,boundary=root)
            for name,row in [('reservation.json',reservation),('process-result.json',process),('terminal.json',worker_result)]:
                _write_exclusive(worker_dir/name,canonical_bytes(row),root=root)
            snapshot={'host-process/launch.json':canonical_bytes({'binding':value['binding'],'argv':[str(binary),'app-server','--listen','stdio://'],
                'supervisorPid':12345,'processGroupId':12345,'model':value['model'],'state':'START_UNCERTAIN','retryAuthorized':False}),
                'host-process/finished.json':canonical_bytes({**exchange,'hostPid':12346,'hostExitCode':0,'supervisorPid':12345,
                    'processGroupId':12345,'binarySha256':value['binding']['binarySha256']}),'host-wire/exchange.json':canonical_bytes(exchange)}
            for i,(kind,raw) in enumerate(wire.groups):
                snapshot[f'host-wire/{i:08d}.json']=canonical_bytes({'sequence':i,'monotonicNs':start_ns+i,'kind':kind,'offset':0,'bytes':len(raw),'rawHex':raw.hex()})
            if continuation != 'publication':
                with patch.object(m,'read_source_review_worker',return_value=worker_result), \
                     patch.object(m,'_r11_worker_sources',return_value=source_snapshot),patch.object(m,'_r11_host_snapshot',return_value=snapshot):
                    with self.subTest(metadata='raw-origin-collector-with-original-operation-deadline'):
                        matched=m.collect_source_review_threads(root,review_id=review,role_id=role_id)
                        self.assertEqual(matched['threadIds'],['actual-fixture-thread']);self.assertTrue(matched['metadataOriginQualified'])
                        self.assertEqual(matched['operationStartSha256'],operation['sha256'])
                        self.assertEqual(matched['operationDeadlineMonotonicNs'],operation['value']['deadlineMonotonicNs'])
                        for key in ('modelDispatchAllowed','producerQualified','firstNativeBootstrapEligible','retryAuthorized'):self.assertFalse(matched[key])
                    if role_id != 'shared-01':
                        actual={**binding,'shardId':role_id,'operationId':operation['value']['operationId'],'threadId':matched['threadIds'][0],
                            'binarySha256':value['binding']['binarySha256'],'transportSourceSha256':value['binding']['transportSourceSha256']}
                        with self.subTest(sourceMetadata='actual-source-origin-joins-role-and-shared'):
                            origin=m._r11_role_request_origin(root,review,actual)
                            self.assertEqual(origin['sharedEvidenceSha256'],value['sharedEvidenceSha256'])
                            self.assertEqual(origin['threadId'],matched['threadIds'][0])
                        with self.subTest(sourceMetadata='reused-shared-thread-refuses'):
                            wrong={**actual,'threadId':binding['threadId']}
                            with self.assertRaises(LifecycleError):m._r11_role_request_origin(root,review,wrong)
                    if continuation == 'absolute_delta':
                        for key in ('startedMonotonicNs','absoluteDeadlineMonotonicNs'):
                            with self.subTest(metadata='collector-requires-original-clock-receipt',field=key):
                                changed={k:v for k,v in process.items() if k!=key};(worker_dir/'process-result.json').write_bytes(canonical_bytes(changed))
                                try:
                                    with self.assertRaises(LifecycleError):m.collect_source_review_threads(root,review_id=review,role_id=role_id)
                                finally:(worker_dir/'process-result.json').write_bytes(canonical_bytes(process))
                    with self.subTest(metadata='collector-process-deadline-or-completion-cannot-reset-clock'):
                        # Preserve actual process identity as the inferred start moves.
                        changed={**process,'startedMonotonicNs':operation['value']['deadlineMonotonicNs']+1-60_000_000_000,'deadlineMonotonicNs':operation['value']['deadlineMonotonicNs']+1,
                            'processReceipt':{'processIdentityHash':process_identity_hash(pid=12345,started_ns=operation['value']['deadlineMonotonicNs']+1-60_000_000_000)}}
                        (worker_dir/'process-result.json').write_bytes(canonical_bytes(changed))
                        try:
                            with self.assertRaisesRegex(LifecycleError,'original operation deadline'):m.collect_source_review_threads(root,review_id=review,role_id=role_id)
                        finally:(worker_dir/'process-result.json').write_bytes(canonical_bytes(process))
                        with patch.object(m,'read_source_review_worker',return_value={**worker_result,'finishedMonotonicNs':operation['value']['deadlineMonotonicNs']+1}):
                            with self.assertRaisesRegex(LifecycleError,'original operation deadline'):m.collect_source_review_threads(root,review_id=review,role_id=role_id)
                    with self.subTest(metadata='collector-refuses-unflushed-extra-or-reordered-wire'):
                        key='host-wire/00000003.json';old=snapshot[key];row=json.loads(old);snapshot[key]=canonical_bytes({**row,'kind':'SEND_PENDING'})
                        try:
                            with self.assertRaises(LifecycleError):m.collect_source_review_threads(root,review_id=review,role_id=role_id)
                        finally:snapshot[key]=old
                    with self.subTest(metadata='collector-stable-operation-reopen-required'), \
                         patch.object(m,'_r11_role_operation_start',side_effect=[operation]*5+[{**operation,'sha256':'f'*64}]):
                        with self.assertRaises(LifecycleError):m.collect_source_review_threads(root,review_id=review,role_id=role_id)
            if continuation is False or continuation in ('publication','absolute_delta'):
                # The actual child entry must run the same original-clock gate
                # immediately before the host; source/catalog are controlled.
                (worker_dir/'process-result.json').unlink();(worker_dir/'terminal.json').unlink()
                _write_exclusive(worker_dir/'dispatch.pending.json',canonical_bytes({'reservationSha256':canonical_digest(reservation),
                    'state':'START_UNCERTAIN'}),root=root)
                with patch.dict(os.environ,env,clear=True),patch.object(m.os,'getpgrp',return_value=os.getpid()), \
                     patch.object(m,'_r11_worker_sources',return_value=source_snapshot), \
                     patch.object(m,'_r11_require_fresh_review_catalog',return_value=catalog), \
                     patch.object(m,'_run_source_review_app_server_worker',return_value={'status':'FIXTURE_METADATA'}) as host:
                    with self.subTest(metadata='child-reconstructs-and-starts-only-metadata-exchange'):
                        self.assertEqual(m._run_source_review_thread_preparation(root,input_path),{'status':'FIXTURE_METADATA'})
                        host.assert_called_once_with(root,binding=value['binding'],binary_path=binary,expected_request=b'',expected_subject={},
                            model=value['model'],preparation_count=1,fresh_read=None)
                    host.reset_mock()
                    with self.subTest(metadata='child-expired-operation-refuses-before-host'), \
                         patch.object(m.time,'monotonic_ns',return_value=operation['value']['deadlineMonotonicNs']):
                        with self.assertRaises(LifecycleError):m._run_source_review_thread_preparation(root,input_path)
                        host.assert_not_called()
                import io
                with self.subTest(metadata='fixed-cli-dispatches-role-metadata-with-no-model-fallback'), \
                     patch.object(Path,'cwd',return_value=root),patch.object(sys,'stdout',io.StringIO()), \
                     patch.object(m,'_run_source_review_thread_preparation',return_value={'status':'FIXTURE_METADATA'}) as metadata, \
                     patch.object(m,'_run_fixed_source_review_worker') as model:
                    self.assertEqual(m._source_review_worker_main([str(input_path)]),0)
                    metadata.assert_called_once_with(root,input_path);model.assert_not_called()
            if continuation == 'absolute_delta':
                return
            # Independent fixture resets below are test-only; production retains
            # each failed claim. The entry is called again only to prove refusal.
            shutil.rmtree(worker_dir.parent)
            for scenario in ('write-failure','post-write-stale','worker-failed'):
                with self.subTest(metadata=scenario),patch.object(m,'_supervise_source_review_worker',return_value={'status':'WORKER_PROCESS_UNCERTAIN'}) as supervisor:
                    shutil.rmtree(claim);input_path.unlink(missing_ok=True);pending.unlink(missing_ok=True)
                    real_write=m._write;real_basis=m._r11_role_thread_preparation_basis;calls=[]
                    def write(boundary,path,row):
                        if scenario=='write-failure' and path==input_path:raise OSError('fixture write failure')
                        return real_write(boundary,path,row)
                    def reconstruct(*args):
                        calls.append(1)
                        if scenario=='post-write-stale' and len(calls)==2:raise LifecycleError('fixture-stale','fixture changed basis')
                        return real_basis(*args)
                    with patch.object(m,'_write',side_effect=write),patch.object(m,'_r11_role_thread_preparation_basis',side_effect=reconstruct):
                        with self.assertRaises((LifecycleError,OSError)):m.prepare_source_review_threads(root,**options)
                    retained=start_path.read_bytes();self.assertTrue(claim.exists())
                    self.assertEqual(pending.exists(),scenario!='worker-failed')
                    if scenario!='worker-failed':
                        supervisor.assert_not_called()
                        with self.assertRaises(LifecycleError):m._r11_read_thread_preparation_input(root,input_path)
                    else:supervisor.assert_called_once()
                    with self.assertRaises(LifecycleError):m.prepare_source_review_threads(root,**options)
                    self.assertEqual(start_path.read_bytes(),retained)
        current=m.read_source_review_cost(root,review_id=review,role_delivery=True)
        self.assertEqual(current,cost);self.assertEqual(m.read_coordinator_cost_head(root),head)

    def _check_v6_original_deadline_request(self):
        from datetime import datetime,timedelta,timezone
        from agent_lifecycle.adapter_sessions.codex_exact_prompt import _file_sha
        m=bootstrap_r11;module_source=Path(m.__file__).read_bytes()
        root,authority,base,inventory,funding,shared,source,directory,binding=self._role_funded_transport_fixture(padding=0)
        review=base['reviewId'];worker=root/m._R11_FIXED_WORKER;worker.parent.mkdir(parents=True,exist_ok=True);worker.write_bytes(module_source)
        for name in m._R11_VALIDATION_ROOTS:(root/name).mkdir(parents=True,exist_ok=True)
        binary=root/'codex';binary.write_bytes(b'fixture selected executable never run');binary.chmod(0o700)
        binding.update(binarySha256=_file_sha(binary),transportSourceSha256=_file_sha(worker),threadId='metadata-fixture-thread')
        basis=m._r11_review_cost_basis(root,review,role_delivery=True)
        start=datetime.now(timezone.utc);mono=m.time.monotonic_ns();end=start+timedelta(seconds=1800)
        operation={'schemaVersion':'alk-r11-role-operation-start.v1','reviewId':review,'roleId':'shared-01',
            'operationId':binding['operationId'],**{k:basis['identity'][k] for k in ('baseSha256','roleInventorySha256','fundingBatchSha256')},
            'startedAtUtc':start.isoformat(),'absoluteDeadlineUtc':end.isoformat(),'startedMonotonicNs':mono,'deadlineMonotonicNs':mono+1800_000_000_000}
        start_path=directory/'role-operations/shared-01/start.json';m._write(root,start_path,operation)
        metadata={'status':'ROLE_FRESH_EMPTY_THREAD_MATCHED','metadataOriginQualified':True,'modelRequestsSent':0,'modelDispatchAllowed':False,
            'reviewId':review,'roleId':'shared-01','operationId':binding['operationId'],'threadIds':[binding['threadId']],
            'operationStartSha256':canonical_digest(operation),'operationDeadlineUtc':operation['absoluteDeadlineUtc'],
            'operationDeadlineMonotonicNs':operation['deadlineMonotonicNs'],'binarySha256':binding['binarySha256'],
            'transportSourceSha256':binding['transportSourceSha256'],'evidenceSha256':'9'*64,'model':'fixture-model'}
        catalog={'binaryPath':str(binary),'selected':{'catalogWindowTokens':1000000,'model':'fixture-model','binarySha256':binding['binarySha256']},'evidenceSha256':'e'*64}
        rebuilt={'candidate':{'status':'ROLE_RECONSTRUCTION_UNQUALIFIED','roleBasis':{'baseRaw':canonical_bytes(base),
            'roleInventoryRaw':canonical_bytes(inventory),'roleExposureRaw':{'shared-01':canonical_bytes(shared),'source-01':canonical_bytes(source)}}}}
        seal_options=dict(review_id=review,binding=binding,exposure_raw=canonical_bytes(shared),model_context_window=1000000,require_metadata_origin=True)
        clock_now=[start+timedelta(seconds=120)];clock_mono=[mono+120_000_000_000]
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return clock_now[0].astimezone(tz) if tz else clock_now[0].replace(tzinfo=None)
        # Raw metadata collector is the controlled boundary here. r430 retained
        # its raw replay coverage; this delta executes the new independent joins.
        with patch.object(m,'__file__',str(worker)),patch.object(m,'collect_source_review_threads',return_value=metadata), \
             patch.object(m,'read_source_review_catalog',return_value=catalog),patch.object(m,'reconstruct_source_review',return_value=rebuilt), \
             patch.object(m,'datetime',Clock),patch.object(m.time,'monotonic_ns',side_effect=lambda:clock_mono[0]):
            with self.subTest(originalDeadline='actual-operation-and-collected-thread-join'):
                origin=m._r11_role_request_origin(root,review,binding)
                self.assertEqual(origin['operationStartSha256'],canonical_digest(operation));self.assertEqual(origin['deadlineMonotonicNs'],operation['deadlineMonotonicNs'])
                self.assertEqual(origin['threadId'],binding['threadId']);self.assertEqual(origin['metadataEvidenceSha256'],metadata['evidenceSha256'])
            # Financial basis is already exercised above. Use a captured immutable
            # operation on independent metadata-result mutation cases only.
            reopened={'value':operation,'sha256':canonical_digest(operation)}
            with patch.object(m,'_r11_role_operation_start',return_value=reopened):
                for field,value in [('threadIds',['other-thread']),('metadataOriginQualified',False),('modelRequestsSent',1),
                    ('modelDispatchAllowed',True),('operationId','other'),('binarySha256','0'*64),('transportSourceSha256','0'*64),
                    ('operationStartSha256','0'*64),('operationDeadlineMonotonicNs',operation['deadlineMonotonicNs']+1),
                    ('operationDeadlineUtc',(end+timedelta(seconds=1)).isoformat())]:
                    with self.subTest(originalDeadline='origin-mismatch',field=field),patch.object(m,'collect_source_review_threads',return_value={**metadata,field:value}):
                        with self.assertRaises(LifecycleError):m._r11_role_request_origin(root,review,binding)
            with self.subTest(originalDeadline='explicit-origin-mode-rejects-nonboolean'):
                with self.assertRaises(LifecycleError):m.seal_source_review_request(root,**{**seal_options,'require_metadata_origin':1})
            request_dir=directory/'role-requests/shared-01'
            with self.subTest(originalDeadline='changed-origin-publication-sticky-pending'), \
                 patch.object(m,'_r11_role_request_origin',side_effect=[origin,{**origin,'metadataEvidenceSha256':'8'*64}]):
                with self.assertRaises(LifecycleError):m.seal_source_review_request(root,**seal_options)
                self.assertTrue((request_dir/'pending.json').exists())
                with self.assertRaises(LifecycleError):m.read_source_review_request(root,review_id=review,role_id='shared-01')
            # Reset only this negative fixture; production retains its claim.
            shutil.rmtree(request_dir)
            with self.subTest(originalDeadline='sealed-request-binds-original-metadata-clock'):
                sealed=m.seal_source_review_request(root,**seal_options)
                self.assertEqual(sealed['seal']['schemaVersion'],'alk-r11-role-request-seal.v2-origin')
                self.assertEqual(sealed['seal']['metadataOrigin'],origin)
                self.assertEqual(datetime.fromisoformat(sealed['seal']['sealedAtUtc']),start+timedelta(seconds=120))
                self.assertFalse(sealed['dispatchAllowed'])
            clock_now[0]=start+timedelta(seconds=180);clock_mono[0]=mono+180_000_000_000
            with self.subTest(originalDeadline='zero-charge-global-reservation-does-not-reset-metadata-time'):
                reserved=m.reserve_source_review_cost(root,review_id=review,binding=binding,role_delivery=True)
                self.assertEqual(datetime.fromisoformat(reserved['absoluteDeadlineUtc']),end)
                self.assertLess(datetime.fromisoformat(reserved['absoluteDeadlineUtc']),datetime.fromisoformat(sealed['seal']['sealedAtUtc'])+timedelta(seconds=1800))
                self.assertEqual(reserved['holdIncrement'],0);self.assertEqual(reserved['heldUnknownTokens'],funding['admittedUnknownHolds'])
                self.assertTrue(m.read_source_review_request(root,review_id=review,role_id='shared-01',require_reservation=True)['reservationRequestMatched'])
            with self.subTest(originalDeadline='fixed-input-and-pre-send-guard-carry-same-origin-and-clock'):
                fixed=m._r11_fixed_worker_basis(root,review_id=review,binding=binding,binary_path=binary,model='fixture-model',timeout_seconds=60)
                instruction=fixed['instruction'];self.assertEqual(instruction['threadCreationMode'],'COLLECTED_ROLE_METADATA')
                self.assertTrue(instruction['metadataThreadOriginQualified']);self.assertEqual(instruction['metadataOrigin'],origin)
                self.assertEqual(instruction['deadlineMonotonicNs'],operation['deadlineMonotonicNs'])
                self.assertEqual(instruction['sendBasis']['metadataOriginSha256'],canonical_digest(origin))
                for key in ('hostContextQualified','producerQualified','dispatchAllowed','firstNativeBootstrapEligible'):self.assertFalse(instruction[key])
            cost=m.read_source_review_cost(root,review_id=review,role_delivery=True)
            # Remaining component mutations capture the proven seal/cost/basis;
            # they continue exercising actual deadline and fixed-input checks.
            sealed_reserved=m.read_source_review_request(root,review_id=review,role_id='shared-01',require_reservation=True)
            financial_basis=m._r11_review_cost_basis(root,review,role_delivery=True)
            with patch.object(m,'read_source_review_cost',return_value=cost),patch.object(m,'_r11_review_cost_basis',return_value=financial_basis):
                with self.subTest(originalDeadline='full-requested-timeout-must-fit-original-deadline'):
                    with self.assertRaises(LifecycleError):m._r11_cost_before_start(root,review,binding,funding['admittedUnknownHolds'],1630,role_delivery=True)
                for mode in ('monotonic-expired','monotonic-backwards','utc-expired','utc-backwards'):
                    old_now,old_mono=clock_now[0],clock_mono[0]
                    if mode=='monotonic-expired':clock_mono[0]=operation['deadlineMonotonicNs']
                    elif mode=='monotonic-backwards':clock_mono[0]=mono-1
                    elif mode=='utc-expired':clock_now[0]=end
                    else:clock_now[0]=start-timedelta(seconds=1)
                    try:
                        with self.subTest(originalDeadline=mode):
                            # Historical seal readability never grants live start.
                            self.assertEqual(m.read_source_review_request(root,review_id=review,role_id='shared-01',require_reservation=True),sealed_reserved)
                            with self.assertRaises(LifecycleError):m._r11_cost_before_start(root,review,binding,funding['admittedUnknownHolds'],1,role_delivery=True)
                    finally:clock_now[0],clock_mono[0]=old_now,old_mono
                with self.subTest(originalDeadline='independent-reader-rejects-reset-reservation'), \
                     patch.object(m,'read_source_review_cost',return_value={**cost,'reservations':[{**reserved,'absoluteDeadlineUtc':(end+timedelta(seconds=120)).isoformat()}]}):
                    with self.assertRaisesRegex(LifecycleError,'reset the original'):m.read_source_review_request(root,review_id=review,role_id='shared-01',require_reservation=True)
                seal_path=request_dir/'seal.json';raw=seal_path.read_bytes()
                for scenario,value in [('forged-origin',{**sealed['seal'],'metadataOrigin':{**origin,'metadataEvidenceSha256':'0'*64}}),
                    ('missing-origin',{k:v for k,v in sealed['seal'].items() if k!='metadataOrigin'}),
                    ('origin-in-v1',{**sealed['seal'],'schemaVersion':'alk-r11-role-request-seal.v1'})]:
                    with self.subTest(originalDeadline=scenario):
                        seal_path.write_bytes(canonical_bytes(value))
                        try:
                            with self.assertRaises(LifecycleError):m.read_source_review_request(root,review_id=review,role_id='shared-01')
                        finally:seal_path.write_bytes(raw)
                with self.subTest(originalDeadline='altered-original-record-invalidates-seal'):
                    raw=start_path.read_bytes();start_path.write_bytes(canonical_bytes({**operation,'startedMonotonicNs':mono+1}))
                    try:
                        with self.assertRaises(LifecycleError):m.read_source_review_request(root,review_id=review,role_id='shared-01')
                    finally:start_path.write_bytes(raw)
                with self.subTest(originalDeadline='prepared-input-without-reopened-origin-cannot-start'), \
                     patch.object(m,'_r11_fixed_worker_basis',return_value=fixed),patch.object(m,'_r11_read_fixed_worker_input',return_value=fixed), \
                     patch.object(m,'_supervise_costed_source_review_worker') as spawn,patch.object(m,'_run_source_review_app_server_worker') as host, \
                     patch.object(m.os,'getpgrp',return_value=os.getpid()):
                    prepared=m.prepare_source_review_worker(root,review_id=review,binding=binding,binary_path=binary,model='fixture-model',timeout_seconds=60)
                    self.assertTrue(prepared['metadataThreadOriginQualified']);self.assertFalse(prepared['dispatchAllowed'])
                    changed={**fixed,'instruction':{**fixed['instruction'],'metadataThreadOriginQualified':False}}
                    with patch.object(m,'_r11_read_fixed_worker_input',return_value=changed):
                        with self.assertRaises(LifecycleError):m._supervise_fixed_source_review_worker(root,instruction_path=Path(prepared['instructionPath']))
                        with self.assertRaises(LifecycleError):m._run_fixed_source_review_worker(root,instruction_path=Path(prepared['instructionPath']))
                    spawn.assert_not_called();host.assert_not_called()
            self.assertEqual(m.read_coordinator_cost_head(root)['head']['unknownHolds'],funding['admittedUnknownHolds'])

    def _check_v6_entry_deadline_refusal(self):
        m=bootstrap_r11;root=Path(tempfile.mkdtemp()).resolve();self.addCleanup(shutil.rmtree,root);path=root/'fixed-input.json'
        for qualified in (False,True):
            for entry in (m._run_fixed_source_review_worker,m._supervise_fixed_source_review_worker):
                with self.subTest(entry=entry.__name__,metadataOriginQualified=qualified), \
                     patch.object(m,'_r11_read_fixed_worker_input',return_value={'instruction':{'metadataThreadOriginQualified':qualified}}), \
                     patch.object(m.os,'getpgrp',return_value=os.getpid()), \
                     patch.object(m,'_supervise_costed_source_review_worker') as worker, \
                     patch.object(m,'_run_source_review_app_server_worker') as host:
                    message='absolute model supervision' if qualified else 'actual role metadata creation'
                    with self.assertRaisesRegex(LifecycleError,message):entry(root,instruction_path=path)
                    worker.assert_not_called();host.assert_not_called()

    def _check_absolute_worker_supervision(self):
        import time
        m=bootstrap_r11
        for outcome in ('finished','timeout','missing-original','different-original'):
            with tempfile.TemporaryDirectory() as temporary,self.subTest(absoluteWorker=outcome):
                root=Path(temporary).resolve()
                for name in m._R11_VALIDATION_ROOTS:(root/name).mkdir(parents=True,exist_ok=True)
                worker=root/'src/fixture_worker.py';worker.write_text('import time\ntime.sleep(5)\n' if outcome=='timeout' else 'pass\n')
                deadline=time.monotonic_ns()+(200_000_000 if outcome=='timeout' else 3_000_000_000)
                value={'schemaVersion':'alk-r11-thread-preparation-input.v2-role','operationDeadlineMonotonicNs':deadline}
                instruction=root/m._R11_REVIEW_ROOT/'reviews/fixture-review/input.json';m._write(root,instruction,value)
                binding={'operationId':'fixture-op','shardId':'metadata-shared-01','threadId':'PREPARATION_ONLY','binarySha256':'a'*64,'transportSourceSha256':'b'*64}
                options=dict(binding=binding,worker_path=worker,instruction_path=instruction,expected_instruction_sha256=canonical_digest(value),timeout_seconds=60,held_unknown_tokens=360000)
                if outcome in ('missing-original','different-original'):
                    with patch('agent_lifecycle.adapter_sessions.process.run_process') as process:
                        with self.assertRaises(LifecycleError):m._supervise_source_review_worker(root,**options,absolute_deadline_monotonic_ns=None if outcome=='missing-original' else deadline+1)
                        process.assert_not_called();self.assertFalse(m._r11_worker_directory(root,binding).exists())
                    continue
                terminal=m._supervise_source_review_worker(root,**options,absolute_deadline_monotonic_ns=deadline)
                self.assertEqual(terminal,m.read_source_review_worker(root,binding=binding));self.assertEqual(terminal['heldUnknownTokens'],360000)
                self.assertFalse(terminal['retryAuthorized']);self.assertFalse(terminal['producerQualified']);self.assertFalse(terminal['firstNativeBootstrapEligible'])
                directory=m._r11_worker_directory(root,binding);result=json.loads((directory/'process-result.json').read_text());reserved=json.loads((directory/'reservation.json').read_text())
                self.assertEqual(reserved['absoluteDeadlineMonotonicNs'],deadline);self.assertEqual(result['deadlineMonotonicNs'],deadline)
                if outcome=='finished':
                    self.assertEqual(terminal['status'],'WORKER_PROCESS_FINISHED')
                    self.assertNotEqual(result['startedMonotonicNs'],deadline-60_000_000_000)
                    changed={**result,'startedMonotonicNs':deadline+1}
                    self.assertEqual(m._r11_worker_disposition(changed,reserved,terminal['finishedMonotonicNs'],True),'WORKER_FAILED')
                else:
                    self.assertEqual(terminal['status'],'WORKER_FAILED');self.assertTrue(result['timedOut']);self.assertEqual(result['cleanup']['status'],'PASS')
                with self.assertRaises(LifecycleError):m._supervise_source_review_worker(root,**options,absolute_deadline_monotonic_ns=deadline)

    def _check_costed_absolute_forwarding(self):
        from datetime import datetime,timedelta,timezone
        import time
        m=bootstrap_r11;root=Path(tempfile.mkdtemp()).resolve();self.addCleanup(shutil.rmtree,root)
        binding={'operationId':'fixture','shardId':'shared-01','threadId':'fixture-thread','binarySha256':'a'*64,'transportSourceSha256':'b'*64}
        cost={'reservations':[{'binding':binding}],'settlements':[],'declaredUnknownHoldsAtFunding':360000}
        now=datetime.now(timezone.utc);mono=time.monotonic_ns()
        origin={'operationStartedAtUtc':(now-timedelta(seconds=1)).isoformat(),'absoluteDeadlineUtc':(now+timedelta(seconds=120)).isoformat(),
            'operationStartedMonotonicNs':mono-1_000_000_000,'deadlineMonotonicNs':mono+120_000_000_000}
        options=dict(review_id='fixture-review',binding=binding,worker_path=root/'src/fixture.py',instruction_path=root/'input.json',
                     expected_instruction_sha256='c'*64,timeout_seconds=60,role_delivery=True)
        for scenario in ('origin-bound','declared-only','expired','worker-error'):
            with self.subTest(costedDeadline=scenario):
                seal={'binding':binding}
                if scenario!='declared-only':seal['metadataOrigin']={**origin,'deadlineMonotonicNs':mono-1} if scenario=='expired' else origin
                with patch.object(m,'read_source_review_cost',return_value=cost), \
                     patch.object(m,'read_source_review_request',return_value={'seal':seal}), \
                     patch.object(m,'_supervise_source_review_worker',side_effect=RuntimeError('fixture started error') if scenario=='worker-error' else None,
                                  return_value={'status':'WORKER_PROCESS_FINISHED'}) as worker, \
                     patch.object(m,'settle_source_review_cost',return_value={'heldUnknownTokens':360000}) as settle:
                    if scenario in ('expired','worker-error'):
                        with self.assertRaises((LifecycleError,RuntimeError)):m._supervise_costed_source_review_worker(root,**options)
                    else:
                        result=m._supervise_costed_source_review_worker(root,**options)
                        self.assertFalse(result['producerQualified']);self.assertFalse(result['retryAuthorized']);self.assertFalse(result['firstNativeBootstrapEligible'])
                        self.assertEqual(result['cost']['heldUnknownTokens'],360000)
                    settle.assert_called_once_with(root,review_id=options['review_id'],binding=binding,role_delivery=True)
                    if scenario=='expired':worker.assert_not_called()
                    else:
                        worker.assert_called_once()
                        expected=origin['deadlineMonotonicNs'] if scenario!='declared-only' else None
                        self.assertEqual(worker.call_args.kwargs.get('absolute_deadline_monotonic_ns'),expected)

    def _check_v6_model_route(self):
        from datetime import datetime,timedelta,timezone
        from agent_lifecycle.adapter_sessions.codex_exact_prompt import _file_sha
        m=bootstrap_r11;module_source=Path(m.__file__).read_bytes()
        root,authority,base,inventory,funding,shared,source,directory,binding=self._role_funded_transport_fixture(padding=0)
        review=base['reviewId'];worker=root/m._R11_FIXED_WORKER;worker.parent.mkdir(parents=True,exist_ok=True);worker.write_bytes(module_source)
        for name in m._R11_VALIDATION_ROOTS:(root/name).mkdir(parents=True,exist_ok=True)
        binary=root/'codex';binary.write_bytes(b'fixture selected executable never run');binary.chmod(0o700)
        binding.update(binarySha256=_file_sha(binary),transportSourceSha256=_file_sha(worker),threadId='thread')
        basis=m._r11_review_cost_basis(root,review,role_delivery=True)
        start=datetime.now(timezone.utc);mono=m.time.monotonic_ns();end=start+timedelta(seconds=1800)
        operation={'schemaVersion':'alk-r11-role-operation-start.v1','reviewId':review,'roleId':'shared-01',
            'operationId':binding['operationId'],**{k:basis['identity'][k] for k in ('baseSha256','roleInventorySha256','fundingBatchSha256')},
            'startedAtUtc':start.isoformat(),'absoluteDeadlineUtc':end.isoformat(),'startedMonotonicNs':mono,'deadlineMonotonicNs':mono+1800_000_000_000}
        start_path=directory/'role-operations/shared-01/start.json';m._write(root,start_path,operation)
        metadata={'status':'ROLE_FRESH_EMPTY_THREAD_MATCHED','metadataOriginQualified':True,'modelRequestsSent':0,'modelDispatchAllowed':False,
            'reviewId':review,'roleId':'shared-01','operationId':binding['operationId'],'threadIds':[binding['threadId']],
            'operationStartSha256':canonical_digest(operation),'operationDeadlineUtc':operation['absoluteDeadlineUtc'],
            'operationDeadlineMonotonicNs':operation['deadlineMonotonicNs'],'binarySha256':binding['binarySha256'],
            'transportSourceSha256':binding['transportSourceSha256'],'evidenceSha256':'9'*64,'model':'fixture-model'}
        catalog={'binaryPath':str(binary),'selected':{'catalogWindowTokens':1000000,'model':'fixture-model','binarySha256':binding['binarySha256']},'evidenceSha256':'e'*64}
        rebuilt={'candidate':{'status':'ROLE_RECONSTRUCTION_UNQUALIFIED','roleBasis':{'baseRaw':canonical_bytes(base),
            'roleInventoryRaw':canonical_bytes(inventory),'roleExposureRaw':{'shared-01':canonical_bytes(shared),'source-01':canonical_bytes(source)}}}}
        seal_options=dict(review_id=review,binding=binding,exposure_raw=canonical_bytes(shared),model_context_window=1000000,require_metadata_origin=True)

        from agent_lifecycle.contracts.process_execution_schemas import process_identity_hash
        with patch.object(m,'__file__',str(worker)),patch.object(m,'collect_source_review_threads',return_value=metadata), \
             patch.object(m,'read_source_review_catalog',return_value=catalog),patch.object(m,'reconstruct_source_review',return_value=rebuilt):
            with self.subTest(modelRoute='actual-origin-seal-reservation-and-live-fixed-input'):
                m.seal_source_review_request(root,**seal_options)
                reserved=m.reserve_source_review_cost(root,review_id=review,binding=binding,role_delivery=True)
                live=m._r11_fixed_worker_basis(root,review_id=review,binding=binding,binary_path=binary,model='fixture-model',timeout_seconds=60)
                self.assertTrue(live['instruction']['metadataThreadOriginQualified']);self.assertFalse(live['instruction']['dispatchAllowed'])
            sealed=m.read_source_review_request(root,review_id=review,role_id='shared-01',require_reservation=True)
            cost=m.read_source_review_cost(root,review_id=review,role_delivery=True);fit=m.read_source_review_envelope_fit(root,review_id=review)
            instruction=live['instruction'];input_path=directory/'worker-shared-01.json';m._write(root,input_path,instruction)
            completed_cost=copy.deepcopy(cost);completed_cost.update(costChainSha256='d'*64,settlements=[{'binding':binding,'worker':{'state':'WORKER_PROCESS_FINISHED'}}])
            completed_cost['fundingOrigin']['currentHeadSha256']='f'*64
            completed_fit={**fit,'coordinatorHeadSha256':'f'*64}
            # One actual funding/reservation/fit join above. Subsequent suffix
            # and process/host boundaries are controlled, not actual Codex proof.
            with patch.object(m,'read_source_review_request',return_value=sealed), \
                 patch.object(m,'read_source_review_cost',return_value=cost),patch.object(m,'read_source_review_envelope_fit',return_value=fit):
                with self.subTest(modelRoute='completed-input-reconstructs-original-prefix-after-expiry'), \
                     patch.object(m,'read_source_review_cost',return_value=completed_cost),patch.object(m,'read_source_review_envelope_fit',return_value=completed_fit), \
                     patch.object(m,'datetime',wraps=datetime) as clock:
                    clock.now.return_value=end+timedelta(seconds=1)
                    self.assertEqual(m._r11_read_fixed_worker_input(root,input_path,completed=True),live)
                with self.subTest(modelRoute='completed-mode-refuses-missing-or-failed-settlement'):
                    for settlements in ([],[{'binding':binding,'worker':{'state':'WORKER_FAILED'}}]):
                        with patch.object(m,'read_source_review_cost',return_value={**completed_cost,'settlements':settlements}):
                            with self.assertRaises(LifecycleError):m._r11_read_fixed_worker_input(root,input_path,completed=True)
                with self.subTest(modelRoute='original-reservation-prefix-cannot-be-rebased'):
                    bad=copy.deepcopy(cost);bad['fundingOrigin']['currentHeadSha256']='f'*64
                    with patch.object(m,'read_source_review_cost',return_value=bad):
                        with self.assertRaises(LifecycleError):m._r11_read_fixed_worker_input(root,input_path)
                    bad=copy.deepcopy(completed_cost);bad['fundingOrigin']['costPrefix']['steps'][0]['recordSha256']='0'*64
                    with patch.object(m,'read_source_review_cost',return_value=bad):
                        with self.assertRaises(LifecycleError):m._r11_read_fixed_worker_input(root,input_path,completed=True)
                with self.subTest(modelRoute='declared-only-cannot-be-completed-origin'), \
                     patch.object(m,'read_source_review_request',return_value={**sealed,'seal':{k:v for k,v in sealed['seal'].items() if k!='metadataOrigin'}}):
                    with self.assertRaises(LifecycleError):m._r11_read_fixed_worker_input(root,input_path,completed=True)
                worker_dir=m._r11_worker_directory(root,binding);env={**os.environ,'PYTHONPATH':str(root/'src'),'PYTHONDONTWRITEBYTECODE':'1','PYTHONUNBUFFERED':'1'}
                with patch.dict(os.environ,env,clear=True),patch.object(m,'_r11_read_fixed_worker_input',return_value=live), \
                     patch.object(m.os,'getpgrp',return_value=os.getpid()),patch.object(m,'_r11_require_fresh_review_catalog',return_value=catalog), \
                     patch.object(m,'_run_source_review_app_server_worker',return_value={'status':'HOST_EXCHANGE_MATCHED'}) as host:
                    expected=m._r11_fixed_supervisor_reservation(root,input_path,live,child=True)
                    m._write(root,worker_dir/'reservation.json',expected)
                    pending={'reservationSha256':canonical_digest(expected),'state':'START_UNCERTAIN'};m._write(root,worker_dir/'dispatch.pending.json',pending)
                    with self.subTest(modelRoute='fixed-child-joins-actual-reservation-and-calls-only-v6'):
                        self.assertEqual(m._run_fixed_source_review_worker(root,instruction_path=input_path),{'status':'HOST_EXCHANGE_MATCHED'})
                        host.assert_called_once_with(root,binding=binding,binary_path=binary,expected_request=live['request'],expected_subject=live['subject'],model='fixture-model',role_delivery=True)
                    host.reset_mock()
                    for key,value in [('absoluteDeadlineMonotonicNs',expected['absoluteDeadlineMonotonicNs']+1),('costChainSha256','0'*64),('environmentSha256','0'*64),('extra',True)]:
                        with self.subTest(modelRoute='child-refuses-changed-supervisor',field=key):
                            (worker_dir/'reservation.json').write_bytes(canonical_bytes({**expected,key:value}))
                            try:
                                with self.assertRaises(LifecycleError):m._run_fixed_source_review_worker(root,instruction_path=input_path)
                            finally:(worker_dir/'reservation.json').write_bytes(canonical_bytes(expected))
                            host.assert_not_called()
                    with self.subTest(modelRoute='child-refuses-fresh-catalog-drift'),patch.object(m,'_r11_require_fresh_review_catalog',return_value={**catalog,'evidenceSha256':'0'*64}):
                        with self.assertRaises(LifecycleError):m._run_fixed_source_review_worker(root,instruction_path=input_path)
                        host.assert_not_called()
                    with self.subTest(modelRoute='child-refuses-expired-original-clock'),patch.object(m.time,'monotonic_ns',return_value=operation['deadlineMonotonicNs']):
                        with self.assertRaises(LifecycleError):m._run_fixed_source_review_worker(root,instruction_path=input_path)
                        host.assert_not_called()
                with self.subTest(modelRoute='parent-consumes-one-reservation-and-collects-only-finished-worker'), \
                     patch.object(m,'_r11_read_fixed_worker_input',return_value=live), \
                     patch.object(m,'_supervise_costed_source_review_worker',return_value={'worker':{'status':'WORKER_PROCESS_FINISHED'},'cost':{},'producerQualified':False,'firstNativeBootstrapEligible':False,'retryAuthorized':False}) as supervisor, \
                     patch.object(m,'collect_source_review_host',return_value={'status':'HOST_SUPERVISION_MATCHED','producerQualified':False}) as collector:
                    result=m._supervise_fixed_source_review_worker(root,instruction_path=input_path)
                    self.assertEqual(result['status'],'ROLE_WORKER_COLLECTED');self.assertFalse(result['producerQualified'])
                    self.assertTrue(supervisor.call_args.kwargs['role_delivery']);self.assertEqual(supervisor.call_args.kwargs['expected_instruction_sha256'],canonical_digest(instruction))
                    collector.assert_called_once_with(root,binding=binding,expected_request=live['request'],expected_subject=live['subject'],role_delivery=True)
                    collector.reset_mock();supervisor.return_value['worker']['status']='WORKER_FAILED'
                    self.assertEqual(m._supervise_fixed_source_review_worker(root,instruction_path=input_path)['status'],'WORKER_FAILED');collector.assert_not_called()
                with self.subTest(modelRoute='declared-only-public-entry-refuses'),patch.object(m.os,'getpgrp',return_value=os.getpid()), \
                     patch.object(m,'_r11_read_fixed_worker_input',return_value={**live,'instruction':{**instruction,'metadataThreadOriginQualified':False}}), \
                     patch.object(m,'_supervise_costed_source_review_worker') as supervisor,patch.object(m,'_run_source_review_app_server_worker') as host:
                    for entry in (m._run_fixed_source_review_worker,m._supervise_fixed_source_review_worker):
                        with self.assertRaises(LifecycleError):entry(root,instruction_path=input_path)
                    supervisor.assert_not_called();host.assert_not_called()
                # Generate actual canonical private host-wire + v6 transport IO
                # using the existing sender and a controlled in-memory peer.
                subject=sealed['subject'];body={'schemaVersion':'alk-route-bootstrap-reviewer-body.v6-r11','verdict':'PASS','phase':'PRE_WS01','rb11RuntimeStatus':'NOT_RUN',
                    'subjectSha256':canonical_digest(subject),**{k:subject[k] for k in ('baseSha256','roleInventorySha256','fundingBatchSha256','roleId','roleKind','exposureSha256','sharedEvidenceSha256')},
                    'sharedContentSeenByThisRole':True,'assignedContentComplete':True,'inheritedCoverageAccepted':True,'interactionScopeComplete':True,'approvedIntegrationScopes':[],'closedParentFindingIds':[],
                    'findings':[],'reviewText':'NO_CURRENT_FINDINGS'}
                body_raw=canonical_bytes(body);fixture=_R11TransportFixture(methodName='runTest');fixture.root=root;fixture.binding=binding;fixture.request=sealed['requestRaw'];fixture.body_raw=body_raw
                messages=[bytes.fromhex(row['rawHex'])+b'\n' for row in fixture.build() if row['kind']=='RECEIVED'][:-2]
                frames=[];sent=[];thread={'id':binding['threadId'],'turns':[],'ephemeral':False,'forkedFromId':None,'historyMode':'legacy','status':{'type':'idle'}}
                class Writer:
                    def write(self,raw):
                        q=json.loads(raw);sent.append(q);method=q['method'];ident=q.get('id')
                        if method=='initialized':return len(raw)
                        if method=='initialize':result={'userAgent':'fixture'}
                        elif method=='model/list':result={'data':[{'model':'fixture-model'}]}
                        elif method=='thread/resume':result={'thread':thread,'model':'fixture-model'}
                        elif method=='thread/read':result=fixture.read(body_raw) if q['params']['includeTurns'] else {'thread':thread}
                        elif method=='turn/start':frames.extend(messages);return len(raw)
                        else:raise AssertionError(method)
                        frames.append(canonical_bytes({'id':ident,'result':result})+b'\n');return len(raw)
                    def flush(self):pass
                real_read=os.read
                def read(fd,size):return frames.pop(0) if fd==987654321 else real_read(fd,size)
                start_ns=m.time.monotonic_ns()
                with patch.object(m.os,'read',side_effect=read),patch.object(m,'_r11_role_send_basis',return_value=instruction['sendBasis']),patch.object(m,'_r11_require_fresh_review_catalog',return_value=catalog):
                    exchange=m._exchange_source_review_rpc(root,binding=binding,expected_request=sealed['requestRaw'],expected_subject=subject,model='fixture-model',binary_path=binary,
                        reader=SimpleNamespace(fileno=lambda:987654321),writer=Writer(),role_delivery=True)
                finish_ns=m.time.monotonic_ns();self.assertEqual(frames,[])
                base_dir=root/m._R11_REVIEW_ROOT/'shards/shared-01';pid=12345
                launch={'binding':binding,'argv':[str(binary),'app-server','--listen','stdio://'],'supervisorPid':pid,'processGroupId':pid,'model':'fixture-model','state':'START_UNCERTAIN','retryAuthorized':False}
                finished={**exchange,'hostPid':12346,'hostExitCode':0,'supervisorPid':pid,'processGroupId':pid,'binarySha256':binding['binarySha256']}
                m._write(root,base_dir/'host-process/launch.json',launch);m._write(root,base_dir/'host-process/finished.json',finished)
                worker_result={'status':'WORKER_PROCESS_FINISHED','finishedMonotonicNs':finish_ns}
                process={'startedMonotonicNs':start_ns,'absoluteDeadlineMonotonicNs':instruction['deadlineMonotonicNs'],
                    'deadlineMonotonicNs':min(instruction['deadlineMonotonicNs'],start_ns+60_000_000_000),'cleanup':{'mode':'posix-session'},
                    'processReceipt':{'processIdentityHash':process_identity_hash(pid=pid,started_ns=start_ns)}}
                expected=m._r11_fixed_supervisor_reservation(root,input_path,live)
                (worker_dir/'reservation.json').write_bytes(canonical_bytes(expected));(worker_dir/'dispatch.pending.json').unlink()
                m._write(root,worker_dir/'process-result.json',process);m._write(root,worker_dir/'terminal.json',worker_result)
                with patch.object(m,'read_source_review_cost',return_value=completed_cost),patch.object(m,'read_source_review_envelope_fit',return_value=completed_fit), \
                     patch.object(m,'read_source_review_worker',return_value=worker_result):
                    options=dict(binding=binding,expected_request=sealed['requestRaw'],expected_subject=subject,role_delivery=True)
                    with self.subTest(modelRoute='independent-completed-v6-host-raw-collector'):
                        matched=m.collect_source_review_host(root,**options)
                        self.assertEqual(matched['status'],'HOST_SUPERVISION_MATCHED');self.assertEqual(matched['transport']['transport']['bodyReadMatch']['roleId'],'shared-01')
                        self.assertFalse(matched['producerQualified']);self.assertFalse(matched['firstNativeBootstrapEligible'])
                        self.assertEqual(len([q for q in sent if q['method']=='turn/start']),1)
                    for key,value in [('startedMonotonicNs',start_ns+1),('absoluteDeadlineMonotonicNs',instruction['deadlineMonotonicNs']+1),('deadlineMonotonicNs',instruction['deadlineMonotonicNs']+1)]:
                        with self.subTest(modelRoute='collector-refuses-clock-or-process-identity',field=key):
                            (worker_dir/'process-result.json').write_bytes(canonical_bytes({**process,key:value}))
                            try:
                                with self.assertRaises(LifecycleError):m.collect_source_review_host(root,**options)
                            finally:(worker_dir/'process-result.json').write_bytes(canonical_bytes(process))
                    with self.subTest(modelRoute='collector-refuses-changed-guard-receipt'):
                        path=base_dir/'host-wire/exchange.json';raw=path.read_bytes();path.write_bytes(canonical_bytes({**exchange,'roleSendBasis':{**instruction['sendBasis'],'coordinatorHeadSha256':'0'*64}}))
                        try:
                            with self.assertRaises(LifecycleError):m.collect_source_review_host(root,**options)
                        finally:path.write_bytes(raw)
                    with self.subTest(modelRoute='v6-cannot-fall-back-to-legacy-host-collector'):
                        with self.assertRaises(LifecycleError):m.collect_source_review_host(root,**{**options,'role_delivery':False})
            self.assertEqual(m.read_coordinator_cost_head(root)['head']['unknownHolds'],funding['admittedUnknownHolds'])

    def _check_accepted_shared(self):
        from datetime import datetime,timedelta,timezone
        from agent_lifecycle.adapter_sessions.codex_exact_prompt import _file_sha
        m=bootstrap_r11;module_source=Path(m.__file__).read_bytes()
        root,authority,base,inventory,funding,shared,source,directory,binding=self._role_funded_transport_fixture(padding=0)
        review=base['reviewId'];worker=root/m._R11_FIXED_WORKER;worker.parent.mkdir(parents=True,exist_ok=True);worker.write_bytes(module_source)
        for name in m._R11_VALIDATION_ROOTS:(root/name).mkdir(parents=True,exist_ok=True)
        binary=root/'codex';binary.write_bytes(b'fixture selected executable never run');binary.chmod(0o700)
        binding.update(binarySha256=_file_sha(binary),transportSourceSha256=_file_sha(worker),threadId='thread')
        basis=m._r11_review_cost_basis(root,review,role_delivery=True)
        start=datetime.now(timezone.utc);mono=m.time.monotonic_ns();end=start+timedelta(seconds=1800)
        operation={'schemaVersion':'alk-r11-role-operation-start.v1','reviewId':review,'roleId':'shared-01',
            'operationId':binding['operationId'],**{k:basis['identity'][k] for k in ('baseSha256','roleInventorySha256','fundingBatchSha256')},
            'startedAtUtc':start.isoformat(),'absoluteDeadlineUtc':end.isoformat(),'startedMonotonicNs':mono,'deadlineMonotonicNs':mono+1800_000_000_000}
        start_path=directory/'role-operations/shared-01/start.json';m._write(root,start_path,operation)
        metadata={'status':'ROLE_FRESH_EMPTY_THREAD_MATCHED','metadataOriginQualified':True,'modelRequestsSent':0,'modelDispatchAllowed':False,
            'reviewId':review,'roleId':'shared-01','operationId':binding['operationId'],'threadIds':[binding['threadId']],
            'operationStartSha256':canonical_digest(operation),'operationDeadlineUtc':operation['absoluteDeadlineUtc'],
            'operationDeadlineMonotonicNs':operation['deadlineMonotonicNs'],'binarySha256':binding['binarySha256'],
            'transportSourceSha256':binding['transportSourceSha256'],'evidenceSha256':'9'*64,'model':'fixture-model'}
        catalog={'binaryPath':str(binary),'selected':{'catalogWindowTokens':1000000,'model':'fixture-model','binarySha256':binding['binarySha256']},'evidenceSha256':'e'*64}
        rebuilt={'candidate':{'status':'ROLE_RECONSTRUCTION_UNQUALIFIED','roleBasis':{'baseRaw':canonical_bytes(base),
            'roleInventoryRaw':canonical_bytes(inventory),'roleExposureRaw':{'shared-01':canonical_bytes(shared),'source-01':canonical_bytes(source)}}}}
        seal_options=dict(review_id=review,binding=binding,exposure_raw=canonical_bytes(shared),model_context_window=1000000,require_metadata_origin=True)

        from agent_lifecycle.contracts.process_execution_schemas import process_identity_hash
        with patch.object(m,'__file__',str(worker)),patch.object(m,'collect_source_review_threads',return_value=metadata), \
             patch.object(m,'read_source_review_catalog',return_value=catalog),patch.object(m,'reconstruct_source_review',return_value=rebuilt):
            m.seal_source_review_request(root,**seal_options)
            reserved=m.reserve_source_review_cost(root,review_id=review,binding=binding,role_delivery=True)
            live=m._r11_fixed_worker_basis(root,review_id=review,binding=binding,binary_path=binary,model='fixture-model',timeout_seconds=60)
            sealed=m.read_source_review_request(root,review_id=review,role_id='shared-01',require_reservation=True)
            instruction=live['instruction'];input_path=directory/'worker-shared-01.json';m._write(root,input_path,instruction)
            worker_dir=m._r11_worker_directory(root,binding)
            subject=sealed['subject'];body={'schemaVersion':'alk-route-bootstrap-reviewer-body.v6-r11','verdict':'PASS','phase':'PRE_WS01','rb11RuntimeStatus':'NOT_RUN',
                'subjectSha256':canonical_digest(subject),**{k:subject[k] for k in ('baseSha256','roleInventorySha256','fundingBatchSha256','roleId','roleKind','exposureSha256','sharedEvidenceSha256')},
                'sharedContentSeenByThisRole':True,'assignedContentComplete':True,'inheritedCoverageAccepted':True,'interactionScopeComplete':True,'approvedIntegrationScopes':[],'closedParentFindingIds':[],
                'findings':[],'reviewText':'NO_CURRENT_FINDINGS'}
            body_raw=canonical_bytes(body);fixture=_R11TransportFixture(methodName='runTest');fixture.root=root;fixture.binding=binding;fixture.request=sealed['requestRaw'];fixture.body_raw=body_raw
            messages=[bytes.fromhex(row['rawHex'])+b'\n' for row in fixture.build() if row['kind']=='RECEIVED'][:-2]
            frames=[];sent=[];thread={'id':binding['threadId'],'turns':[],'ephemeral':False,'forkedFromId':None,'historyMode':'legacy','status':{'type':'idle'}}
            class Writer:
                def write(self,raw):
                    q=json.loads(raw);sent.append(q);method=q['method'];ident=q.get('id')
                    if method=='initialized':return len(raw)
                    if method=='initialize':result={'userAgent':'fixture'}
                    elif method=='model/list':result={'data':[{'model':'fixture-model'}]}
                    elif method=='thread/resume':result={'thread':thread,'model':'fixture-model'}
                    elif method=='thread/read':result=fixture.read(body_raw) if q['params']['includeTurns'] else {'thread':thread}
                    elif method=='turn/start':frames.extend(messages);return len(raw)
                    else:raise AssertionError(method)
                    frames.append(canonical_bytes({'id':ident,'result':result})+b'\n');return len(raw)
                def flush(self):pass
            real_read=os.read
            def read(fd,size):return frames.pop(0) if fd==987654321 else real_read(fd,size)
            start_ns=m.time.monotonic_ns()
            with patch.object(m.os,'read',side_effect=read),patch.object(m,'_r11_role_send_basis',return_value=instruction['sendBasis']),patch.object(m,'_r11_require_fresh_review_catalog',return_value=catalog):
                exchange=m._exchange_source_review_rpc(root,binding=binding,expected_request=sealed['requestRaw'],expected_subject=subject,model='fixture-model',binary_path=binary,
                    reader=SimpleNamespace(fileno=lambda:987654321),writer=Writer(),role_delivery=True)
            finish_ns=m.time.monotonic_ns();self.assertEqual(frames,[])
            base_dir=root/m._R11_REVIEW_ROOT/'shards/shared-01';pid=12345
            launch={'binding':binding,'argv':[str(binary),'app-server','--listen','stdio://'],'supervisorPid':pid,'processGroupId':pid,'model':'fixture-model','state':'START_UNCERTAIN','retryAuthorized':False}
            finished={**exchange,'hostPid':12346,'hostExitCode':0,'supervisorPid':pid,'processGroupId':pid,'binarySha256':binding['binarySha256']}
            m._write(root,base_dir/'host-process/launch.json',launch);m._write(root,base_dir/'host-process/finished.json',finished)
            worker_result={'status':'WORKER_PROCESS_FINISHED','finishedMonotonicNs':finish_ns,'heldUnknownTokens':funding['admittedUnknownHolds']}
            process={'startedMonotonicNs':start_ns,'absoluteDeadlineMonotonicNs':instruction['deadlineMonotonicNs'],
                'deadlineMonotonicNs':min(instruction['deadlineMonotonicNs'],start_ns+60_000_000_000),'cleanup':{'mode':'posix-session'},
                'processReceipt':{'processIdentityHash':process_identity_hash(pid=pid,started_ns=start_ns)}}
            expected=m._r11_fixed_supervisor_reservation(root,input_path,live)
            m._write(root,worker_dir/'reservation.json',expected)
            m._write(root,worker_dir/'process-result.json',process);m._write(root,worker_dir/'terminal.json',worker_result)
            with patch.object(m,'read_source_review_worker',return_value=worker_result):
                m.settle_source_review_cost(root,review_id=review,binding=binding,role_delivery=True)
                cost=m.read_source_review_cost(root,review_id=review,role_delivery=True)
                fit=m.read_source_review_envelope_fit(root,review_id=review)
                self.assertEqual(len(cost['settlements']),1);self.assertFalse(cost['allRolesSettled'])
                # Completed financial prefix is real. The worker reader remains
                # controlled: these are raw-RPC/component joins, not actual host.
                with patch.object(m,'read_source_review_request',return_value=sealed),patch.object(m,'read_source_review_cost',return_value=cost), \
                     patch.object(m,'read_source_review_envelope_fit',return_value=fit):
                    with self.subTest(acceptedShared='completed-original-basis-after-actual-settlement'):
                        self.assertEqual(m._r11_read_fixed_worker_input(root,input_path,completed=True),live)
                    future=copy.deepcopy(cost)
                    future['reservations'].append({**reserved,'binding':{**binding,'shardId':'source-01','threadId':'source-thread'}})
                    future['settlements'].append({'binding':future['reservations'][-1]['binding'],'worker':{'state':'WORKER_FAILED'}})
                    with self.subTest(acceptedShared='completed-shared-does-not-depend-on-future-source'),patch.object(m,'read_source_review_cost',return_value=future):
                        self.assertEqual(m._r11_read_fixed_worker_input(root,input_path,completed=True),live)
                    with patch.object(m,'_r11_read_fixed_worker_input',return_value=live):
                        with self.subTest(acceptedShared='actual-raw-host-producer-and-funded-shared-receipt'):
                            accepted=m.collect_source_review_shared(root,review_id=review)
                            self.assertTrue(accepted['sharedEvidenceAccepted']);self.assertFalse(accepted['firstNativeBootstrapEligible'])
                            self.assertFalse(accepted['sourceCompletionRequired']);self.assertFalse(accepted['hostContextQualified'])
                            self.assertIsNone(accepted['actualModelTokens']);self.assertEqual(accepted['bodyRaw'],body_raw)
                            self.assertEqual(accepted['receipt']['settlementSha256'],canonical_digest(cost['settlements'][0]))
                            self.assertEqual(accepted['receipt']['producerSha256'],canonical_digest(accepted['producer']))
                            self.assertEqual(accepted['receipt']['privateEvidenceInventorySha256'],canonical_digest(accepted['privateEvidenceInventory']))
                            self.assertFalse(accepted['producer']['firstNativeBootstrapEligible'])
                        for field in ('reservationSha256','binding','worker'):
                            bad=copy.deepcopy(cost)
                            if field=='reservationSha256':bad['settlements'][0][field]='0'*64
                            elif field=='binding':bad['settlements'][0][field]={**binding,'threadId':'wrong'}
                            else:bad['settlements'][0][field]={**bad['settlements'][0][field],'state':'WORKER_FAILED'}
                            with self.subTest(acceptedShared='producer-refuses-settlement-substitution',field=field),patch.object(m,'read_source_review_cost',return_value=bad):
                                with self.assertRaises(LifecycleError):m.collect_source_review_shared(root,review_id=review)
                        for field in ('fundingAdmitted','rolePrefixesAnchored'):
                            with self.subTest(acceptedShared='producer-refuses-unfunded-prefix',field=field),patch.object(m,'read_source_review_cost',return_value={**cost,field:False}):
                                with self.assertRaises(LifecycleError):m.collect_source_review_shared(root,review_id=review)
                        with self.subTest(acceptedShared='producer-refuses-worker-digest-substitution'):
                            bad=copy.deepcopy(cost);bad['settlements'][0]['worker']['evidenceSha256']['terminal.json']='0'*64
                            with patch.object(m,'read_source_review_cost',return_value=bad):
                                with self.assertRaises(LifecycleError):m.collect_source_review_shared(root,review_id=review)
                        for rel in ('role-cost/shared-01/reservation.json','role-cost/shared-01/settlement.json','worker-shared-01.json'):
                            path=directory/rel;raw=path.read_bytes();path.write_bytes(raw+b' ')
                            try:
                                with self.subTest(acceptedShared='raw-inventory-must-match-checked-proof',path=rel):
                                    with self.assertRaises(LifecycleError):m.collect_source_review_shared(root,review_id=review)
                            finally:path.write_bytes(raw)
                        with self.subTest(acceptedShared='changed-raw-body-cannot-be-accepted'):
                            path=base_dir/'review-body.raw';raw=path.read_bytes();path.write_bytes(raw+b' ')
                            try:
                                with self.assertRaises(LifecycleError):m.collect_source_review_shared(root,review_id=review)
                            finally:path.write_bytes(raw)
                        with self.subTest(acceptedShared='changed-raw-transport-cannot-be-accepted'):
                            path=base_dir/'host-wire/exchange.json';raw=path.read_bytes();value=json.loads(raw);value['roleSendBasis']['coordinatorHeadSha256']='0'*64;path.write_bytes(canonical_bytes(value))
                            try:
                                with self.assertRaises(LifecycleError):m.collect_source_review_shared(root,review_id=review)
                            finally:path.write_bytes(raw)
                        with self.subTest(acceptedShared='candidate-pass-cannot-replace-producer'):
                            bad={**accepted['producer'],'producerQualified':False}
                            with patch.object(m,'collect_source_review_producer',return_value=bad):
                                with self.assertRaises(LifecycleError):m.collect_source_review_shared(root,review_id=review)
                        with self.subTest(acceptedShared='stale-second-producer-read-refuses'):
                            bad={**accepted['producer'],'hostEvidenceSha256':'0'*64}
                            with patch.object(m,'collect_source_review_producer',side_effect=[accepted['producer'],bad]):
                                with self.assertRaises(LifecycleError):m.collect_source_review_shared(root,review_id=review)
                        with self.subTest(acceptedShared='shared-proof-stable-with-future-cost-suffix'),patch.object(m,'read_source_review_cost',return_value=future):
                            self.assertEqual(m.collect_source_review_shared(root,review_id=review),accepted)
                        with self.subTest(acceptedShared='source-producer-stays-denied'):
                            with self.assertRaises(LifecycleError):m.collect_source_review_producer(root,review_id=review,shard_id='source-01',role_delivery=True)
                # SOURCE admission uses the real sealed request/global financial
                # publisher. Its SHARED collector boundary is the captured proof.
                source_binding={**binding,'shardId':'source-01','operationId':inventory['roles'][1]['operationId'],'threadId':'source-thread'}
                opts=dict(review_id=review,binding=source_binding,exposure_raw=canonical_bytes(source),model_context_window=1000000,
                    shared_evidence_raw=accepted['evidenceRaw'],shared_body_raw=accepted['bodyRaw'])
                with patch.object(m,'collect_source_review_shared',return_value=accepted):
                    for key in ('shared_evidence_raw','shared_body_raw'):
                        with self.subTest(acceptedShared='source-seal-refuses-supplied-substitute',field=key):
                            with self.assertRaises(LifecycleError):m.seal_source_review_request(root,**{**opts,key:opts[key]+b' '})
                            self.assertFalse((directory/'role-requests/source-01').exists())
                    with self.subTest(acceptedShared='source-seal-binds-accepted-raw-shared'):
                        source_sealed=m.seal_source_review_request(root,**opts)
                        self.assertEqual(source_sealed['subject']['sharedEvidenceSha256'],hashlib.sha256(accepted['evidenceRaw']).hexdigest())
                        self.assertFalse(source_sealed['dispatchAllowed'])
                    with self.subTest(acceptedShared='source-reservation-binds-recomputed-shared-prefix'):
                        source_reserved=m.reserve_source_review_cost(root,review_id=review,binding=source_binding,role_delivery=True)
                        self.assertEqual(source_reserved['sharedEvidenceSha256'],hashlib.sha256(accepted['evidenceRaw']).hexdigest())
                        final=m.read_source_review_cost(root,review_id=review,role_delivery=True)
                        self.assertEqual(len(final['reservations']),2);self.assertEqual(len(final['settlements']),1)
                        self.assertTrue(final['rolePrefixesAnchored']);self.assertFalse(final['dispatchReservationQualified'])
                        self.assertEqual(final['declaredUnknownHoldsAtFunding'],funding['admittedUnknownHolds'])
                    with self.subTest(acceptedShared='source-read-reopens-current-shared-proof'):
                        with patch.object(m,'collect_source_review_shared',return_value={**accepted,'evidenceRaw':accepted['evidenceRaw']+b' '}):
                            with self.assertRaises(LifecycleError):m.read_source_review_request(root,review_id=review,role_id='source-01',require_reservation=True)
                    with self.subTest(acceptedShared='source-cannot-claim-metadata-origin-or-start'):
                        with self.assertRaises(LifecycleError):m._r11_role_request_origin(root,review,source_binding)
                        self.assertFalse((root/m._R11_REVIEW_ROOT/'shards/source-01').exists())
                self.assertEqual(m.read_coordinator_cost_head(root)['head']['unknownHolds'],funding['admittedUnknownHolds'])

    def _check_source_reservation_predecessor(self):
        m=bootstrap_r11
        root,authority,base,inventory,funding,shared,source,directory,binding=self._role_funded_transport_fixture(padding=0)
        review=base['reviewId']
        sealed=m.seal_source_review_request(root,review_id=review,binding=binding,exposure_raw=canonical_bytes(shared),model_context_window=1000000)
        m.reserve_source_review_cost(root,review_id=review,binding=binding,role_delivery=True)
        cost=m.read_source_review_cost(root,review_id=review,role_delivery=True)
        worker_dir=m._r11_worker_directory(root,binding)
        m._write(root,worker_dir/'reservation.json',{'costReviewId':review,'costChainSha256':cost['costChainSha256'],'requestSha256':sealed['requestSha256']})
        terminal={'status':'WORKER_PROCESS_FINISHED','heldUnknownTokens':funding['admittedUnknownHolds']}
        m._write(root,worker_dir/'terminal.json',terminal)
        # Narrow financial continuation: controlled terminal and accepted-SHARED
        # boundaries. Actual global prefix writer, private ledger and seal reader.
        with patch.object(m,'read_source_review_worker',return_value=terminal):
            m.settle_source_review_cost(root,review_id=review,binding=binding,role_delivery=True)
            cost=m.read_source_review_cost(root,review_id=review,role_delivery=True);settlement=cost['settlements'][0]
            basis=m._r11_review_cost_basis(root,review,role_delivery=True);subject=sealed['subject']
            body={'schemaVersion':'alk-route-bootstrap-reviewer-body.v6-r11','verdict':'PASS','phase':'PRE_WS01','rb11RuntimeStatus':'NOT_RUN',
                'subjectSha256':canonical_digest(subject),**{k:subject[k] for k in ('baseSha256','roleInventorySha256','fundingBatchSha256','roleId','roleKind','exposureSha256','sharedEvidenceSha256')},
                'sharedContentSeenByThisRole':True,'assignedContentComplete':True,'inheritedCoverageAccepted':True,'interactionScopeComplete':True,
                'approvedIntegrationScopes':[],'closedParentFindingIds':[],'findings':[],'reviewText':'NO_CURRENT_FINDINGS'}
            body_raw=canonical_bytes(body)
            receipt={k:'c'*64 for k in authority['schemas']['sharedEvidence']['properties']}
            receipt.update(schemaVersion='alk-r11-shared-evidence.v1',status='SHARED_ACCEPTED',reviewId=review,
                **{k:basis['identity'][k] for k in ('baseSha256','roleInventorySha256','fundingBatchSha256')},subjectSha256=canonical_digest(subject),
                bodyRawSha256=hashlib.sha256(body_raw).hexdigest(),binding=binding,firstNativeBootstrapEligible=False)
            accepted={'evidenceRaw':canonical_bytes(receipt),'bodyRaw':body_raw}
            source_binding={**binding,'shardId':'source-01','operationId':inventory['roles'][1]['operationId'],'threadId':'source-thread'}
            with patch.object(m,'collect_source_review_shared',return_value=accepted):
                m.seal_source_review_request(root,review_id=review,binding=source_binding,exposure_raw=canonical_bytes(source),model_context_window=1000000,
                    shared_evidence_raw=accepted['evidenceRaw'],shared_body_raw=body_raw)
                with self.subTest(sourcePrefix='exact-shared-settlement-predecessor-and-global-publication'):
                    reserved=m.reserve_source_review_cost(root,review_id=review,binding=source_binding,role_delivery=True)
                    final=m.read_source_review_cost(root,review_id=review,role_delivery=True)
                    self.assertEqual(reserved['previousSettlementSha256'],canonical_digest(settlement))
                    self.assertEqual(reserved['sharedEvidenceSha256'],hashlib.sha256(accepted['evidenceRaw']).hexdigest())
                    self.assertEqual(len(final['reservations']),2);self.assertEqual(len(final['settlements']),1)
                    self.assertTrue(final['rolePrefixesAnchored']);self.assertFalse(final['dispatchReservationQualified'])
                    self.assertFalse(final['allRolesSettled']);self.assertFalse(final['firstNativeBootstrapEligible'])
                    self.assertEqual(final['declaredUnknownHoldsAtFunding'],funding['admittedUnknownHolds'])
                    self.assertTrue(m.read_source_review_request(root,review_id=review,role_id='source-01',require_reservation=True)['reservationRequestMatched'])
                with self.subTest(sourcePrefix='repeat-reservation-refuses-without-charge-or-mutation'):
                    head=m.read_coordinator_cost_head(root)
                    with self.assertRaises(LifecycleError):m.reserve_source_review_cost(root,review_id=review,binding=source_binding,role_delivery=True)
                    self.assertEqual(m.read_coordinator_cost_head(root),head)
                    self.assertEqual(m.read_source_review_cost(root,review_id=review,role_delivery=True),final)
                with self.subTest(sourcePrefix='changed-predecessor-refuses-independent-reconstruction'):
                    path=directory/'role-cost/source-01/reservation.json';raw=path.read_bytes();bad=json.loads(raw);bad['previousSettlementSha256']=None;path.write_bytes(canonical_bytes(bad))
                    try:
                        with self.assertRaises(LifecycleError):m.read_source_review_cost(root,review_id=review,role_delivery=True)
                    finally:path.write_bytes(raw)
                self.assertEqual(m.read_coordinator_cost_head(root)['head']['unknownHolds'],funding['admittedUnknownHolds'])

    def _source_model_fixture(self):
        m=bootstrap_r11
        root,authority,base,inventory,funding,shared,source,directory,binding=self._role_funded_transport_fixture(padding=0)
        binding['threadId']='shared-fixture-thread'
        review=base['reviewId']
        sealed=m.seal_source_review_request(root,review_id=review,binding=binding,exposure_raw=canonical_bytes(shared),model_context_window=1000000)
        m.reserve_source_review_cost(root,review_id=review,binding=binding,role_delivery=True)
        cost=m.read_source_review_cost(root,review_id=review,role_delivery=True)
        worker_dir=m._r11_worker_directory(root,binding)
        m._write(root,worker_dir/'reservation.json',{'costReviewId':review,'costChainSha256':cost['costChainSha256'],'requestSha256':sealed['requestSha256']})
        terminal={'status':'WORKER_PROCESS_FINISHED','heldUnknownTokens':funding['admittedUnknownHolds']}
        m._write(root,worker_dir/'terminal.json',terminal)
        # Narrow financial continuation: controlled terminal and accepted-SHARED
        # boundaries. Actual global prefix writer, private ledger and seal reader.
        with patch.object(m,'read_source_review_worker',return_value=terminal):
            m.settle_source_review_cost(root,review_id=review,binding=binding,role_delivery=True)
            cost=m.read_source_review_cost(root,review_id=review,role_delivery=True);settlement=cost['settlements'][0]
            basis=m._r11_review_cost_basis(root,review,role_delivery=True);subject=sealed['subject']
            body={'schemaVersion':'alk-route-bootstrap-reviewer-body.v6-r11','verdict':'PASS','phase':'PRE_WS01','rb11RuntimeStatus':'NOT_RUN',
                'subjectSha256':canonical_digest(subject),**{k:subject[k] for k in ('baseSha256','roleInventorySha256','fundingBatchSha256','roleId','roleKind','exposureSha256','sharedEvidenceSha256')},
                'sharedContentSeenByThisRole':True,'assignedContentComplete':True,'inheritedCoverageAccepted':True,'interactionScopeComplete':True,
                'approvedIntegrationScopes':[],'closedParentFindingIds':[],'findings':[],'reviewText':'NO_CURRENT_FINDINGS'}
            body_raw=canonical_bytes(body)
            receipt={k:'c'*64 for k in authority['schemas']['sharedEvidence']['properties']}
            receipt.update(schemaVersion='alk-r11-shared-evidence.v1',status='SHARED_ACCEPTED',reviewId=review,
                **{k:basis['identity'][k] for k in ('baseSha256','roleInventorySha256','fundingBatchSha256')},subjectSha256=canonical_digest(subject),
                bodyRawSha256=hashlib.sha256(body_raw).hexdigest(),binding=binding,firstNativeBootstrapEligible=False)
            accepted={'evidenceRaw':canonical_bytes(receipt),'bodyRaw':body_raw}
            return root,authority,base,inventory,funding,shared,source,directory,binding,accepted,terminal

    def _check_source_model_route(self, *, continuation=False, checkpoint=None):
        from contextlib import nullcontext
        from datetime import datetime,timedelta,timezone
        from agent_lifecycle.adapter_sessions.codex_exact_prompt import _file_sha
        m=bootstrap_r11;module_source=Path(m.__file__).read_bytes()
        root,authority,base,inventory,funding,shared,source,directory,binding,accepted,shared_terminal=self._source_model_fixture()
        if checkpoint:checkpoint('financial_predecessor_ready')
        binding.update(shardId='source-01',operationId=inventory['roles'][1]['operationId'])
        review=base['reviewId'];worker=root/m._R11_FIXED_WORKER;worker.parent.mkdir(parents=True,exist_ok=True);worker.write_bytes(module_source)
        for name in m._R11_VALIDATION_ROOTS:(root/name).mkdir(parents=True,exist_ok=True)
        binary=root/'codex';binary.write_bytes(b'fixture selected executable never run');binary.chmod(0o700)
        binding.update(binarySha256=_file_sha(binary),transportSourceSha256=_file_sha(worker),threadId='thread')
        basis=m._r11_review_cost_basis(root,review,role_delivery=True)
        start=datetime.now(timezone.utc);mono=m.time.monotonic_ns();end=start+timedelta(seconds=1800)
        operation={'schemaVersion':'alk-r11-role-operation-start.v1','reviewId':review,'roleId':'source-01',
            'operationId':binding['operationId'],'sharedEvidenceSha256':hashlib.sha256(accepted['evidenceRaw']).hexdigest(),**{k:basis['identity'][k] for k in ('baseSha256','roleInventorySha256','fundingBatchSha256')},
            'startedAtUtc':start.isoformat(),'absoluteDeadlineUtc':end.isoformat(),'startedMonotonicNs':mono,'deadlineMonotonicNs':mono+1800_000_000_000}
        start_path=directory/'role-operations/source-01/start.json';m._write(root,start_path,operation)
        metadata={'status':'ROLE_FRESH_EMPTY_THREAD_MATCHED','metadataOriginQualified':True,'modelRequestsSent':0,'modelDispatchAllowed':False,
            'reviewId':review,'roleId':'source-01','operationId':binding['operationId'],'threadIds':[binding['threadId']],
            'operationStartSha256':canonical_digest(operation),'operationDeadlineUtc':operation['absoluteDeadlineUtc'],
            'operationDeadlineMonotonicNs':operation['deadlineMonotonicNs'],'binarySha256':binding['binarySha256'],
            'transportSourceSha256':binding['transportSourceSha256'],'evidenceSha256':'9'*64,'model':'fixture-model'}
        catalog={'binaryPath':str(binary),'selected':{'catalogWindowTokens':1000000,'model':'fixture-model','binarySha256':binding['binarySha256']},'evidenceSha256':'e'*64}
        rebuilt={'candidate':{'status':'ROLE_RECONSTRUCTION_UNQUALIFIED','roleBasis':{'baseRaw':canonical_bytes(base),
            'roleInventoryRaw':canonical_bytes(inventory),'roleExposureRaw':{'shared-01':canonical_bytes(shared),'source-01':canonical_bytes(source)}}}}
        seal_options=dict(review_id=review,binding=binding,exposure_raw=canonical_bytes(source),model_context_window=1000000,require_metadata_origin=True,shared_evidence_raw=accepted['evidenceRaw'],shared_body_raw=accepted['bodyRaw'])

        from agent_lifecycle.contracts.process_execution_schemas import process_identity_hash
        with patch.object(m,'__file__',str(worker)),patch.object(m,'collect_source_review_threads',return_value=metadata), \
             patch.object(m,'collect_source_review_shared',return_value=accepted),patch.object(m,'read_source_review_worker',return_value=shared_terminal), \
             patch.object(m,'read_source_review_catalog',return_value=catalog),patch.object(m,'reconstruct_source_review',return_value=rebuilt):
            with (self.subTest(sourceModelRoute='actual-origin-seal-reservation-and-live-fixed-input') if not continuation else nullcontext()):
                m.seal_source_review_request(root,**seal_options)
                reserved=m.reserve_source_review_cost(root,review_id=review,binding=binding,role_delivery=True)
                live=m._r11_fixed_worker_basis(root,review_id=review,binding=binding,binary_path=binary,model='fixture-model',timeout_seconds=60)
                if not continuation:
                    self.assertTrue(live['instruction']['metadataThreadOriginQualified']);self.assertFalse(live['instruction']['dispatchAllowed'])
            if checkpoint:checkpoint('origin_seal_reservation_and_live_basis_ready')
            sealed=m.read_source_review_request(root,review_id=review,role_id='source-01',require_reservation=True)
            cost=m.read_source_review_cost(root,review_id=review,role_delivery=True);fit=m.read_source_review_envelope_fit(root,review_id=review)
            instruction=live['instruction'];input_path=directory/'worker-source-01.json';m._write(root,input_path,instruction)
            completed_cost=copy.deepcopy(cost);completed_cost.update(costChainSha256='d'*64,settlements=cost['settlements']+[{'binding':binding,'worker':{'state':'WORKER_PROCESS_FINISHED'}}])
            completed_cost['fundingOrigin']['currentHeadSha256']='f'*64
            completed_fit={**fit,'coordinatorHeadSha256':'f'*64}
            # One actual funding/reservation/fit join above. Subsequent suffix
            # and process/host boundaries are controlled, not actual Codex proof.
            with patch.object(m,'read_source_review_request',return_value=sealed), \
                 patch.object(m,'read_source_review_cost',return_value=cost),patch.object(m,'read_source_review_envelope_fit',return_value=fit):
                worker_dir=m._r11_worker_directory(root,binding)
                if not continuation:
                    with self.subTest(sourceModelRoute='completed-input-reconstructs-original-prefix-after-expiry'), \
                         patch.object(m,'read_source_review_cost',return_value=completed_cost),patch.object(m,'read_source_review_envelope_fit',return_value=completed_fit), \
                         patch.object(m,'datetime',wraps=datetime) as clock:
                        clock.now.return_value=end+timedelta(seconds=1)
                        self.assertEqual(m._r11_read_fixed_worker_input(root,input_path,completed=True),live)
                    with self.subTest(sourceModelRoute='completed-mode-refuses-missing-or-failed-settlement'):
                        for settlements in ([],[{'binding':binding,'worker':{'state':'WORKER_FAILED'}}]):
                            with patch.object(m,'read_source_review_cost',return_value={**completed_cost,'settlements':settlements}):
                                with self.assertRaises(LifecycleError):m._r11_read_fixed_worker_input(root,input_path,completed=True)
                    with self.subTest(sourceModelRoute='original-reservation-prefix-cannot-be-rebased'):
                        bad=copy.deepcopy(cost);bad['fundingOrigin']['currentHeadSha256']='f'*64
                        with patch.object(m,'read_source_review_cost',return_value=bad):
                            with self.assertRaises(LifecycleError):m._r11_read_fixed_worker_input(root,input_path)
                        bad=copy.deepcopy(completed_cost);[row for row in bad['fundingOrigin']['costPrefix']['steps'] if row['recordPath']=='source-01/reservation.json'][0]['recordSha256']='0'*64
                        with patch.object(m,'read_source_review_cost',return_value=bad):
                            with self.assertRaises(LifecycleError):m._r11_read_fixed_worker_input(root,input_path,completed=True)
                    with self.subTest(sourceModelRoute='declared-only-cannot-be-completed-origin'), \
                         patch.object(m,'read_source_review_request',return_value={**sealed,'seal':{k:v for k,v in sealed['seal'].items() if k!='metadataOrigin'}}):
                        with self.assertRaises(LifecycleError):m._r11_read_fixed_worker_input(root,input_path,completed=True)
                    with self.subTest(sourceModel='changed-shared-proof-refuses-source-model-admission'), \
                         patch.object(m,'collect_source_review_shared',return_value={**accepted,'evidenceRaw':accepted['evidenceRaw']+b' '}):
                        with self.assertRaises(LifecycleError):m._r11_role_send_basis(root,binding=binding,request_raw=sealed['requestRaw'],subject=sealed['subject'],binary_path=binary,model='fixture-model')
                    worker_dir=m._r11_worker_directory(root,binding);env={**os.environ,'PYTHONPATH':str(root/'src'),'PYTHONDONTWRITEBYTECODE':'1','PYTHONUNBUFFERED':'1'}
                    with patch.dict(os.environ,env,clear=True),patch.object(m,'_r11_read_fixed_worker_input',return_value=live), \
                         patch.object(m.os,'getpgrp',return_value=os.getpid()),patch.object(m,'_r11_require_fresh_review_catalog',return_value=catalog), \
                         patch.object(m,'_run_source_review_app_server_worker',return_value={'status':'HOST_EXCHANGE_MATCHED'}) as host:
                        expected=m._r11_fixed_supervisor_reservation(root,input_path,live,child=True)
                        m._write(root,worker_dir/'reservation.json',expected)
                        pending={'reservationSha256':canonical_digest(expected),'state':'START_UNCERTAIN'};m._write(root,worker_dir/'dispatch.pending.json',pending)
                        with self.subTest(sourceModelRoute='fixed-child-joins-actual-reservation-and-calls-only-v6'):
                            self.assertEqual(m._run_fixed_source_review_worker(root,instruction_path=input_path),{'status':'HOST_EXCHANGE_MATCHED'})
                            host.assert_called_once_with(root,binding=binding,binary_path=binary,expected_request=live['request'],expected_subject=live['subject'],model='fixture-model',role_delivery=True)
                        host.reset_mock()
                        for key,value in [('absoluteDeadlineMonotonicNs',expected['absoluteDeadlineMonotonicNs']+1),('costChainSha256','0'*64),('environmentSha256','0'*64),('extra',True)]:
                            with self.subTest(sourceModelRoute='child-refuses-changed-supervisor',field=key):
                                (worker_dir/'reservation.json').write_bytes(canonical_bytes({**expected,key:value}))
                                try:
                                    with self.assertRaises(LifecycleError):m._run_fixed_source_review_worker(root,instruction_path=input_path)
                                finally:(worker_dir/'reservation.json').write_bytes(canonical_bytes(expected))
                                host.assert_not_called()
                        with self.subTest(sourceModelRoute='child-refuses-fresh-catalog-drift'),patch.object(m,'_r11_require_fresh_review_catalog',return_value={**catalog,'evidenceSha256':'0'*64}):
                            with self.assertRaises(LifecycleError):m._run_fixed_source_review_worker(root,instruction_path=input_path)
                            host.assert_not_called()
                        with self.subTest(sourceModelRoute='child-refuses-expired-original-clock'),patch.object(m.time,'monotonic_ns',return_value=operation['deadlineMonotonicNs']):
                            with self.assertRaises(LifecycleError):m._run_fixed_source_review_worker(root,instruction_path=input_path)
                            host.assert_not_called()
                    with self.subTest(sourceModelRoute='parent-consumes-one-reservation-and-collects-only-finished-worker'), \
                         patch.object(m,'_r11_read_fixed_worker_input',return_value=live), \
                         patch.object(m,'_supervise_costed_source_review_worker',return_value={'worker':{'status':'WORKER_PROCESS_FINISHED'},'cost':{},'producerQualified':False,'firstNativeBootstrapEligible':False,'retryAuthorized':False}) as supervisor, \
                         patch.object(m,'collect_source_review_host',return_value={'status':'HOST_SUPERVISION_MATCHED','producerQualified':False}) as collector:
                        result=m._supervise_fixed_source_review_worker(root,instruction_path=input_path)
                        self.assertEqual(result['status'],'ROLE_WORKER_COLLECTED');self.assertFalse(result['producerQualified'])
                        self.assertTrue(supervisor.call_args.kwargs['role_delivery']);self.assertEqual(supervisor.call_args.kwargs['expected_instruction_sha256'],canonical_digest(instruction))
                        collector.assert_called_once_with(root,binding=binding,expected_request=live['request'],expected_subject=live['subject'],role_delivery=True)
                        collector.reset_mock();supervisor.return_value['worker']['status']='WORKER_FAILED'
                        self.assertEqual(m._supervise_fixed_source_review_worker(root,instruction_path=input_path)['status'],'WORKER_FAILED');collector.assert_not_called()
                    with self.subTest(sourceModelRoute='declared-only-public-entry-refuses'),patch.object(m.os,'getpgrp',return_value=os.getpid()), \
                         patch.object(m,'_r11_read_fixed_worker_input',return_value={**live,'instruction':{**instruction,'metadataThreadOriginQualified':False}}), \
                         patch.object(m,'_supervise_costed_source_review_worker') as supervisor,patch.object(m,'_run_source_review_app_server_worker') as host:
                        for entry in (m._run_fixed_source_review_worker,m._supervise_fixed_source_review_worker):
                            with self.assertRaises(LifecycleError):entry(root,instruction_path=input_path)
                        supervisor.assert_not_called();host.assert_not_called()
                else:
                    expected=m._r11_fixed_supervisor_reservation(root,input_path,live)
                    m._write(root,worker_dir/'reservation.json',expected)
                    m._write(root,worker_dir/'dispatch.pending.json',{'reservationSha256':canonical_digest(expected),'state':'START_UNCERTAIN'})
                # Generate actual canonical private host-wire + v6 transport IO
                # using the existing sender and a controlled in-memory peer.
                subject=sealed['subject'];body={'schemaVersion':'alk-route-bootstrap-reviewer-body.v6-r11','verdict':'PASS','phase':'PRE_WS01','rb11RuntimeStatus':'NOT_RUN',
                    'subjectSha256':canonical_digest(subject),**{k:subject[k] for k in ('baseSha256','roleInventorySha256','fundingBatchSha256','roleId','roleKind','exposureSha256','sharedEvidenceSha256')},
                    'sharedContentSeenByThisRole':False,'assignedContentComplete':True,'inheritedCoverageAccepted':True,'interactionScopeComplete':True,'approvedIntegrationScopes':subject['requiredIntegrationScopes'],'closedParentFindingIds':[],
                    'findings':[],'reviewText':'NO_CURRENT_FINDINGS'}
                body_raw=canonical_bytes(body);fixture=_R11TransportFixture(methodName='runTest');fixture.root=root;fixture.binding=binding;fixture.request=sealed['requestRaw'];fixture.body_raw=body_raw
                messages=[bytes.fromhex(row['rawHex'])+b'\n' for row in fixture.build() if row['kind']=='RECEIVED'][:-2]
                # The generic raw-message fixture uses id1. SOURCE requests
                # have their inventory-derived id; echo the actual request id.
                messages=[canonical_bytes({**json.loads(raw),'id':json.loads(sealed['requestRaw'])['id']})+b'\n'
                          if 'id' in json.loads(raw) else raw for raw in messages]
                frames=[];sent=[];thread={'id':binding['threadId'],'turns':[],'ephemeral':False,'forkedFromId':None,'historyMode':'legacy','status':{'type':'idle'}}
                class Writer:
                    def write(self,raw):
                        q=json.loads(raw);sent.append(q);method=q['method'];ident=q.get('id')
                        if method=='initialized':return len(raw)
                        if method=='initialize':result={'userAgent':'fixture'}
                        elif method=='model/list':result={'data':[{'model':'fixture-model'}]}
                        elif method=='thread/resume':result={'thread':thread,'model':'fixture-model'}
                        elif method=='thread/read':result=fixture.read(body_raw) if q['params']['includeTurns'] else {'thread':thread}
                        elif method=='turn/start':frames.extend(messages);return len(raw)
                        else:raise AssertionError(method)
                        frames.append(canonical_bytes({'id':ident,'result':result})+b'\n');return len(raw)
                    def flush(self):pass
                real_read=os.read
                def read(fd,size):return frames.pop(0) if fd==987654321 else real_read(fd,size)
                if checkpoint:checkpoint('raw_rpc_start')
                start_ns=m.time.monotonic_ns()
                with patch.object(m.os,'read',side_effect=read),patch.object(m,'_r11_role_send_basis',return_value=instruction['sendBasis']),patch.object(m,'_r11_require_fresh_review_catalog',return_value=catalog):
                    exchange=m._exchange_source_review_rpc(root,binding=binding,expected_request=sealed['requestRaw'],expected_subject=subject,model='fixture-model',binary_path=binary,
                        reader=SimpleNamespace(fileno=lambda:987654321),writer=Writer(),role_delivery=True)
                finish_ns=m.time.monotonic_ns();self.assertEqual(frames,[])
                base_dir=root/m._R11_REVIEW_ROOT/'shards/source-01';pid=12345
                launch={'binding':binding,'argv':[str(binary),'app-server','--listen','stdio://'],'supervisorPid':pid,'processGroupId':pid,'model':'fixture-model','state':'START_UNCERTAIN','retryAuthorized':False}
                finished={**exchange,'hostPid':12346,'hostExitCode':0,'supervisorPid':pid,'processGroupId':pid,'binarySha256':binding['binarySha256']}
                m._write(root,base_dir/'host-process/launch.json',launch);m._write(root,base_dir/'host-process/finished.json',finished)
                worker_result={'status':'WORKER_PROCESS_FINISHED','finishedMonotonicNs':finish_ns,'heldUnknownTokens':funding['admittedUnknownHolds']}
                process={'startedMonotonicNs':start_ns,'absoluteDeadlineMonotonicNs':instruction['deadlineMonotonicNs'],
                    'deadlineMonotonicNs':min(instruction['deadlineMonotonicNs'],start_ns+60_000_000_000),'cleanup':{'mode':'posix-session'},
                    'processReceipt':{'processIdentityHash':process_identity_hash(pid=pid,started_ns=start_ns)}}
                expected=m._r11_fixed_supervisor_reservation(root,input_path,live)
                (worker_dir/'reservation.json').write_bytes(canonical_bytes(expected));(worker_dir/'dispatch.pending.json').unlink()
                m._write(root,worker_dir/'process-result.json',process);m._write(root,worker_dir/'terminal.json',worker_result)
                completed_cost['settlements'][-1].update(reservationSha256=canonical_digest(reserved),worker={
                    'state':'WORKER_PROCESS_FINISHED','evidenceSha256':{name:hashlib.sha256((worker_dir/name).read_bytes()).hexdigest()
                        for name in ('reservation.json','process-result.json','terminal.json')}})
                if checkpoint:checkpoint('raw_host_collectors_start')
                with patch.object(m,'read_source_review_cost',return_value=completed_cost),patch.object(m,'read_source_review_envelope_fit',return_value=completed_fit), \
                     patch.object(m,'_r11_read_fixed_worker_input',return_value=live), \
                     patch.object(m,'read_source_review_worker',return_value=worker_result):
                    options=dict(binding=binding,expected_request=sealed['requestRaw'],expected_subject=subject,role_delivery=True)
                    with self.subTest(sourceModelRoute='independent-completed-v6-host-raw-collector'):
                        matched=m.collect_source_review_host(root,**options)
                        self.assertEqual(matched['status'],'HOST_SUPERVISION_MATCHED');self.assertEqual(matched['transport']['transport']['bodyReadMatch']['roleId'],'source-01')
                        self.assertFalse(matched['producerQualified']);self.assertFalse(matched['firstNativeBootstrapEligible'])
                        self.assertEqual(len([q for q in sent if q['method']=='turn/start']),1)
                    with self.subTest(sourceModel='independent-source-producer-remains-local-no-native'):
                        proof=m.collect_source_review_producer(root,review_id=review,shard_id='source-01',role_delivery=True)
                        self.assertTrue(proof['producerQualified']);self.assertFalse(proof['firstNativeBootstrapEligible'])
                        self.assertFalse(proof['hostContextQualified']);self.assertIsNone(proof['actualModelTokens'])
                        self.assertEqual(proof['costSettlementSha256'],canonical_digest(completed_cost['settlements'][-1]))
                    for key,value in [('startedMonotonicNs',start_ns+1),('absoluteDeadlineMonotonicNs',instruction['deadlineMonotonicNs']+1),('deadlineMonotonicNs',instruction['deadlineMonotonicNs']+1)]:
                        with self.subTest(sourceModelRoute='collector-refuses-clock-or-process-identity',field=key):
                            (worker_dir/'process-result.json').write_bytes(canonical_bytes({**process,key:value}))
                            try:
                                with self.assertRaises(LifecycleError):m.collect_source_review_host(root,**options)
                            finally:(worker_dir/'process-result.json').write_bytes(canonical_bytes(process))
                    with self.subTest(sourceModelRoute='collector-refuses-changed-guard-receipt'):
                        path=base_dir/'host-wire/exchange.json';raw=path.read_bytes();path.write_bytes(canonical_bytes({**exchange,'roleSendBasis':{**instruction['sendBasis'],'coordinatorHeadSha256':'0'*64}}))
                        try:
                            with self.assertRaises(LifecycleError):m.collect_source_review_host(root,**options)
                        finally:path.write_bytes(raw)
                    with self.subTest(sourceModelRoute='v6-cannot-fall-back-to-legacy-host-collector'):
                        with self.assertRaises(LifecycleError):m.collect_source_review_host(root,**{**options,'role_delivery':False})
            self.assertEqual(m.read_coordinator_cost_head(root)['head']['unknownHolds'],funding['admittedUnknownHolds'])


class R1054DisabledDispatchTests(unittest.TestCase):
    def test_transcript_refuses_supplied_writer_before_any_record_or_write(self):
        from unittest.mock import Mock
        from agent_lifecycle.adapter_sessions.source_review_transcript import SourceReviewTranscript
        transcript=object.__new__(SourceReviewTranscript);transcript.model_request_recorded=False;transcript._record=Mock()
        writer=Mock();writer.write.side_effect=lambda raw:len(raw)
        raw=canonical_bytes({'id':1,'method':'turn/start','params':{}})+b'\n'
        with self.assertRaises(LifecycleError) as caught:transcript.send(raw,writer)
        self.assertEqual(caught.exception.code,'r11-experimental-disabled');writer.write.assert_not_called();writer.flush.assert_not_called();transcript._record.assert_not_called()
        self.assertFalse(transcript.model_request_recorded)
    def test_arbitrary_and_subclass_wire_cannot_send_metadata(self):
        from unittest.mock import Mock
        from agent_lifecycle.adapter_sessions import source_review_support as support
        class CallerReplay(support._R11PreparationReplay):
            def __init__(self):self.send_bootstrap=Mock();self.buffer=bytearray()
        tampered=object.__new__(support._R11PreparationReplay)
        tampered.groups=[];tampered.cursor=1;tampered.buffer=bytearray();tampered.send_bootstrap=Mock()
        for wire in (Mock(),CallerReplay(),tampered):
            with self.subTest(kind=type(wire).__name__):
                with self.assertRaises(LifecycleError) as caught:support._r11_empty_thread_exchange(wire,Path('/tmp/alk-replay-only'),'model',1)
                self.assertEqual(caught.exception.code,'r11-experimental-disabled');wire.send_bootstrap.assert_not_called()
    def test_exact_raw_preparation_replay_remains_side_effect_free(self):
        from agent_lifecycle.adapter_sessions import source_review_support as support
        root=Path('/tmp/alk-replay-only');binding={'fixture':'archive'};groups=[{'kind':'SESSION','raw':canonical_bytes(binding)}]
        thread={'id':'archived-thread','ephemeral':False,'forkedFromId':None,'historyMode':'legacy','turns':[],'status':{'type':'idle'}}
        messages=[{'id':1000001,'method':'initialize','params':{'clientInfo':{'name':'agent_lifecycle_kit','title':'Agent Lifecycle Kit','version':'2.16.0'},'capabilities':{'experimentalApi':True}}},
                  {'method':'initialized','params':{}},
                  {'id':1000100,'method':'thread/start','params':{'model':'model','cwd':str(root),'approvalPolicy':'never','sandbox':'read-only','historyMode':'legacy'}},
                  {'id':1000101,'method':'thread/read','params':{'threadId':'archived-thread','includeTurns':True}},
                  {'id':1000102,'method':'thread/read','params':{'threadId':'archived-thread','includeTurns':True}}]
        for msg in messages:
            raw=canonical_bytes(msg)+b'\n';groups.extend([{'kind':'SEND_PENDING','raw':raw},{'kind':'WRITE_ACCEPTED','raw':raw},{'kind':'FLUSHED','raw':canonical_bytes({'sha256':hashlib.sha256(raw).hexdigest()})}])
            if 'id' in msg:
                body={'userAgent':'fixture'} if msg['id']==1000001 else {'thread':thread,'model':'model'}
                groups.append({'kind':'RECEIVED_CHUNK','raw':canonical_bytes({'id':msg['id'],'result':body})+b'\n'})
        wire=support._R11PreparationReplay(groups,binding);result=support._r11_empty_thread_exchange(wire,root,'model',1)
        self.assertEqual(result['threadIds'],['archived-thread']);self.assertEqual(result['modelRequestsSent'],0);self.assertFalse(result['producerQualified']);self.assertEqual(wire.cursor,len(groups))

    def test_initialized_subclass_refused_without_replay_state_mutation(self):
        from agent_lifecycle.adapter_sessions import source_review_support as support

        class ValidSubclass(support._R11PreparationReplay):
            pass

        root=Path('/tmp/alk-replay-only');binding={'fixture':'archive'}
        groups=[{'kind':'SESSION','raw':canonical_bytes(binding)}]
        thread={'id':'archived-thread','ephemeral':False,'forkedFromId':None,'historyMode':'legacy','turns':[],'status':{'type':'idle'}}
        messages=[{'id':1000001,'method':'initialize','params':{'clientInfo':{'name':'agent_lifecycle_kit','title':'Agent Lifecycle Kit','version':'2.16.0'},'capabilities':{'experimentalApi':True}}},
                  {'method':'initialized','params':{}},
                  {'id':1000100,'method':'thread/start','params':{'model':'model','cwd':str(root),'approvalPolicy':'never','sandbox':'read-only','historyMode':'legacy'}},
                  {'id':1000101,'method':'thread/read','params':{'threadId':'archived-thread','includeTurns':True}},
                  {'id':1000102,'method':'thread/read','params':{'threadId':'archived-thread','includeTurns':True}}]
        for message in messages:
            raw=canonical_bytes(message)+b'\n'
            groups.extend([{'kind':'SEND_PENDING','raw':raw},{'kind':'WRITE_ACCEPTED','raw':raw},{'kind':'FLUSHED','raw':canonical_bytes({'sha256':hashlib.sha256(raw).hexdigest()})}])
            if 'id' in message:
                reply={'userAgent':'fixture'} if message['id']==1000001 else {'thread':thread,'model':'model'}
                groups.append({'kind':'RECEIVED_CHUNK','raw':canonical_bytes({'id':message['id'],'result':reply})+b'\n'})
        wire=ValidSubclass(groups,binding)
        before=(wire.cursor,bytes(wire.buffer),[(row['kind'],row['raw']) for row in wire.groups])
        with self.assertRaises(LifecycleError) as caught:
            support._r11_empty_thread_exchange(wire,root,'model',1)
        self.assertEqual(caught.exception.code,'r11-experimental-disabled')
        self.assertEqual((wire.cursor,bytes(wire.buffer),[(row['kind'],row['raw']) for row in wire.groups]),before)

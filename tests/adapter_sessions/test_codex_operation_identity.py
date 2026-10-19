"""Operation storage isolation; synthetic fit/host doubles never qualify Codex."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

from agent_lifecycle.adapter_sessions import attempt_authority as authority
from agent_lifecycle.adapter_sessions import codex_prompt_preparation as prompt
from agent_lifecycle.adapter_sessions import input_lifecycle as inputs
from agent_lifecycle.adapter_sessions import ordinary_audit
from agent_lifecycle.adapter_sessions.private_input import _private_dir, _write_exclusive
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest


class CodexOperationIdentityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.state = {'runId': 'run-1', 'sourceRevision': 'fixture-rev', 'eventLog': 'work/events.jsonl'}
        self.task = {'id': 'task-1', 'attempt': 1, 'status': 'RUNNING'}
        (self.root / 'work').mkdir()
        (self.root / self.state['eventLog']).write_bytes(b'')
        self.manifest = {}
        self.manifest_path = self.root / 'manifest.json'
        self.lock = self.root / 'lock.json'
        self.manifest_path.write_bytes(canonical_bytes(self.manifest))
        self.lock.write_bytes(b'{}')
        self.binary = self.root / 'codex'
        self.binary.write_bytes(b'synthetic binary identity; never executed')
        self.binary.chmod(0o700)
        self.identity = {'status': 'PASS', 'executableContentSha256': self.sha(self.binary.read_bytes()),
                         'resolvedPathSha256': self.sha(str(self.binary).encode())}
        for name in authority._SOURCES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
        for name, value in (
            ('tasks/release-2-16/alk-input-fit-contract.json', {'commonEnvelope': {'reservedOutputEstimatedTokens': 3072}}),
            ('profiles/small-context-profile.v1.json', {}),
            ('work/release-2-16/packet.json', {'plan': {'planDigest': canonical_digest({})}, 'task': {'id': 'task-1'}}),
        ):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(canonical_bytes(value))

    @staticmethod
    def sha(raw):
        return hashlib.sha256(raw).hexdigest()

    def namespace(self, operation):
        return authority._invocation_namespace('run-1', 'task-1', '1', operation)

    def stage(self, operation, request_id):
        packet = 'work/release-2-16/packet.json'
        request = {'routeId': prompt.ROUTE_ID, 'requestedClaim': prompt.CLAIM, 'runId': 'run-1',
                   'taskId': 'task-1', 'planDigest': canonical_digest({}), 'lockDigest': self.sha(b'{}'),
                   'sourceRevision': 'fixture-rev', 'operationId': operation, 'role': 'worker',
                   'packetPath': packet, 'packetSha256': self.sha((self.root / packet).read_bytes()),
                   'selection': {'selected': []}, 'summary': {}, 'selectedSource': [],
                   'instruction': 'synthetic', 'schema': {}}
        return inputs.stage_input_request(self.root, request_id, request)

    def prepare(self, operation, request_id):
        staged = self.stage(operation, request_id)
        final = canonical_bytes({'renderedEnvelope': {}, 'selectedSource': [], 'instruction': 'synthetic', 'schema': {}})
        fit = {'status': 'PASS_ALK_COMPONENTS_ONLY', 'checks': [], 'receiptDigest': 'a' * 64,
               'inputComponentDigests': {'fullAlkModelInput': self.sha(final)}}
        def host(root, request, identity, final_sha, run, task, attempt, executable, env, role, *, operation_id):
            ns = authority._invocation_namespace(run, task, attempt, operation_id)
            private = root / 'work/release-2-16/private-details/codex-exact-prompt' / ns
            for name in ('effective-config.json', 'prompt-input.json'):
                _write_exclusive(private / name, b'{}', root=root)
            home = root / 'work/release-2-16/runtime-private/codex-exact-prompt' / ns / 'codex-home'
            _private_dir(home, boundary=root)
            _write_exclusive(home / 'config.toml', b'model="fixture"', root=root)
            manifest = root / 'work/release-2-16/evidence/codex-exact-prompt' / ns / 'config-snapshot-manifest.json'
            _write_exclusive(manifest, b'{}', root=root)
            return 'fixture', str(home), inputs._snapshot_digest(home, root=root), {}, {}, self.sha(b'{}')
        with patch.object(prompt, 'assess_local_input_fit', return_value=fit), \
                patch.object(prompt, 'render_context', return_value={'envelope': {}}), \
                patch.object(prompt, '_selected_host_evidence', side_effect=host):
            return prompt.prepare_exact_prompt(
                project_root=self.root, input_request=staged, route_id=prompt.ROUTE_ID,
                requested_claim=prompt.CLAIM, state=self.state, task=self.task, manifest=self.manifest,
                lock_path=self.lock, manifest_path=self.manifest_path, source_revision='fixture-rev',
                operation_id=operation, executable_identity=self.identity, executable=str(self.binary), process_env={})

    def no_start(self, prepared):
        prompt.cleanup_prestart_raw(self.root, run_id='run-1', task_id='task-1', attempt_id='1',
                                   operation_id=prepared['operationId'], staging_source=None, proven_no_start=True)
        inputs.record_proven_no_start(self.root, prepared['startReceiptPath'])

    def test_two_operations_share_original_task_attempt_and_cannot_reuse_identity(self):
        before = copy.deepcopy((self.state, self.task))
        first = self.prepare('worker/first', 'first')
        self.no_start(first)
        retained = first['intentPath'].read_bytes()
        second = self.prepare('validator/next', 'second')
        self.assertNotEqual(first['intentPath'], second['intentPath'])
        self.assertEqual(first['attemptId'], second['attemptId'])
        self.assertEqual(first['attemptId'], '1')
        self.assertEqual(first['intentPath'].read_bytes(), retained)
        self.assertEqual(json.loads(second['intentPath'].read_bytes())['operationId'], 'validator/next')
        self.no_start(second)
        with self.assertRaises(LifecycleError) as caught:
            self.prepare('worker/first', 'reused')
        self.assertEqual(caught.exception.code, 'codex-exact-attempt-reused')
        self.assertEqual(first['intentPath'].read_bytes(), retained)
        self.assertEqual((self.state, self.task), before)
        inputs.reconcile_prelaunch_intents(self.root)

    def test_operation_mismatch_and_cross_operation_reservation_are_refused(self):
        staged = self.stage('one', 'mismatch')
        with self.assertRaises(LifecycleError):
            inputs._seal_request(self.root, staged, 'run-1', 'task-1', '1', operation_id='other')
        self.assertTrue(staged.exists())
        inputs.cleanup_no_start(self.root, None, staged)
        first = self.prepare('one', 'one')
        other = self.root / 'work/release-2-16/evidence/codex-exact-prompt' / self.namespace('other')
        _write_exclusive(other / 'prelaunch-intent.json', first['intentPath'].read_bytes(), root=self.root)
        with self.assertRaises(LifecycleError):
            authority.reserve_attempt_result(self.root, intent_path=other / 'prelaunch-intent.json')
        self.assertFalse((other / 'attempt-result-reservation.json').exists())

    def test_retained_legacy_operation_cannot_be_rekeyed_as_a_new_call(self):
        legacy = self.root / authority._ROOT / 'run-1/task-1/1/prelaunch-intent.json'
        intent = {k: 'a' * 64 for k in authority._IDENTITY}
        intent.update(schemaVersion='alk-codex-prelaunch-intent.v1', runId='run-1', taskId='task-1',
                      attemptId='1', operationId='legacy/op', hostLaunchStarted=False, plannedStdinBytes=0,
                      **authority.capture_attempt_authority(self.root, lock_path=self.lock, manifest_path=self.manifest_path))
        _write_exclusive(legacy, canonical_bytes(intent), root=self.root)
        authority.reserve_attempt_result(self.root, intent_path=legacy)
        _write_exclusive(legacy.with_name('process-start.json'), b'', root=self.root)
        inputs.record_proven_no_start(self.root, legacy.with_name('process-start.json'))
        before = legacy.read_bytes()
        with self.assertRaises(LifecycleError) as caught:
            self.prepare('legacy/op', 'legacy-rekey')
        self.assertEqual(caught.exception.code, 'codex-exact-attempt-reused')
        self.assertEqual(legacy.read_bytes(), before)
        self.assertFalse((self.root / authority._ROOT / self.namespace('legacy/op') / 'prelaunch-intent.json').exists())

    def test_unresolved_operation_blocks_another_without_removing_its_raw_input(self):
        first = self.prepare('one', 'one')
        raw = first['sealedRequest'].read_bytes()
        with self.assertRaises(LifecycleError) as caught:
            self.prepare('two', 'two')
        self.assertEqual(caught.exception.code, 'codex-exact-start-uncertain')
        self.assertEqual(first['sealedRequest'].read_bytes(), raw)
        self.assertFalse((first['intentPath'].parent.parent / self.namespace('two').name / 'prelaunch-intent.json').exists())

    def test_operation_cleanup_is_scoped_and_inventory_binds_operation(self):
        first = self.prepare('one', 'one')
        other = self.root / 'work/release-2-16/private-details/codex-exact-prompt' / self.namespace('other') / 'input-request.json'
        _write_exclusive(other, canonical_bytes({'operationId': 'other'}), root=self.root)
        before = other.read_bytes()
        self.assertEqual(prompt.verify_prestart_raw_inventory(
            self.root, inventory_path=first['rawInventoryPath'], pending_path=first['rawCleanupPendingPath'],
            state=self.state, plan_digest=canonical_digest({})), self.sha(first['rawInventoryPath'].read_bytes()))
        self.no_start(first)
        self.assertEqual(other.read_bytes(), before)
        self.assertTrue(first['intentPath'].exists())
        self.assertTrue(first['intentPath'].with_name('attempt-result-reservation.json').exists())

    def test_ordinary_gate_keys_isolate_operations_and_keep_legacy_identity(self):
        identity = {'runId': 'run-1', 'taskId': 'task-1', 'attemptId': '1', 'operationId': 'one'}
        legacy = self.root / authority._ROOT / 'run-1/task-1/1/prelaunch-intent.json'
        one = self.root / authority._ROOT / self.namespace('one') / 'prelaunch-intent.json'
        two = self.root / authority._ROOT / self.namespace('two') / 'prelaunch-intent.json'
        self.assertEqual(ordinary_audit._task_gate_key(identity, legacy), canonical_digest(
            {k: identity[k] for k in ('runId', 'taskId', 'attemptId')}))
        self.assertNotEqual(ordinary_audit._task_gate_key(identity, one),
                            ordinary_audit._task_gate_key({**identity, 'operationId': 'two'}, two))
        self.assertEqual(ordinary_audit._task_gate_key(identity, one), canonical_digest(identity))

    def test_common_sink_cannot_charge_a_prepared_input_to_another_operation(self):
        from agent_lifecycle.adapter_sessions.launch_preflight import _run_exact_managed_process
        runner = Mock()
        verify = Mock()
        context = SimpleNamespace(root=self.root, profile_adapter='codex', timeout_seconds=1,
                                  env_receipt={}, profile_digest='fixture', runner=runner)
        prepared = {'operationId': 'one', 'verifyBeforeStart': verify}
        result = _run_exact_managed_process(context, prepared=prepared, audit={}, session_id='fixture',
                                           risk_profile={}, host_identity={}, operation_id='two')
        self.assertFalse(result['hostLaunchStarted'])
        self.assertEqual(result['blockers'][0]['code'], 'codex-exact-operation-mismatch')
        runner.assert_not_called()
        verify.assert_not_called()

    def test_positive_transport_cannot_splice_another_operation_with_updated_hashes(self):
        from tests.adapter_sessions.test_bootstrap_r11 import PreparedAttemptIntegrationTests
        fixture = PreparedAttemptIntegrationTests(methodName='test_success_is_joined_to_reserved_terminal_and_current_sources')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.assertEqual(fixture.launch()['status'], 'PASS')  # Local Python child, synthetic host fit.
        intent = json.loads(fixture.prepared['intentPath'].read_bytes())
        process_hash = fixture.outcomes[0]['startObservation']['processIdentityHash']
        authority._positive_receipts(fixture.root, fixture.evidence, intent, process_hash)
        input_path = fixture.evidence / 'process-input.json'
        delivered = json.loads(input_path.read_bytes())
        delivered['operationId'] = 'another-operation'
        input_path.write_bytes(canonical_bytes(delivered))
        transport_path = fixture.evidence / 'transport-equivalence.json'
        transport = json.loads(transport_path.read_bytes())
        transport['processInputSha256'] = self.sha(input_path.read_bytes())
        transport_path.write_bytes(canonical_bytes(transport))
        with self.assertRaises(LifecycleError) as caught:
            authority._positive_receipts(fixture.root, fixture.evidence, intent, process_hash)
        self.assertEqual(caught.exception.code, 'r11-result-positive-join')

    def completed_legacy_pending(self):
        """Real legacy-layout inventory/reservation/terminal; synthetic process observations."""
        private = self.root / 'work/release-2-16/private-details/codex-exact-prompt/run-1/task-1/1'
        for name in ('input-request.json', 'effective-config.json', 'prompt-input.json'):
            _write_exclusive(private / name, b'{}', root=self.root)
        home = self.root / 'work/release-2-16/runtime-private/codex-exact-prompt/run-1/task-1/1/codex-home'
        _private_dir(home, boundary=self.root)
        _write_exclusive(home / 'config.toml', b'fixture', root=self.root)
        _, marker, _ = prompt.create_prestart_raw_inventory(
            self.root, run_id='run-1', task_id='task-1', attempt_id='1',
            sealed_request=private / 'input-request.json', state=self.state, plan_digest=canonical_digest({}))
        self.assertNotIn('operationId', json.loads(marker.read_bytes()))
        path = marker.with_name('prelaunch-intent.json')
        intent = {key: 'a' * 64 for key in authority._IDENTITY}
        intent.update(schemaVersion='alk-codex-prelaunch-intent.v1', runId='run-1', taskId='task-1', attemptId='1',
                      operationId='legacy/op', planDigest=canonical_digest({}), lockDigest=self.sha(b'{}'),
                      sourceRevision='fixture-rev', routeId=prompt.ROUTE_ID, requestedClaim=prompt.CLAIM,
                      hostLaunchStarted=False, plannedStdinBytes=3,
                      **authority.capture_attempt_authority(self.root, lock_path=self.lock, manifest_path=self.manifest_path))
        _write_exclusive(path, canonical_bytes(intent), root=self.root)
        authority.reserve_attempt_result(self.root, intent_path=path)
        subject = {k: intent[k] for k in ('runId', 'taskId', 'attemptId', 'finalPromptSha256')}
        start = {**intent, 'schemaVersion': 'alk-codex-process-start.v1', 'hostLaunchStarted': True,
                 'stdinStatus': 'PENDING', 'processIdentityHash': 'f' * 64}
        delivered = {**subject, 'schemaVersion': 'alk-codex-process-input.v1', 'processIdentityHash': 'f' * 64,
                     'status': 'COMPLETE', 'closeSucceeded': True, 'acceptedBytes': 3,
                     'acceptedSha256': intent['finalPromptSha256']}
        transport = {**subject, 'schemaVersion': 'alk-codex-os-pipe-transport.v1', 'status': 'OS_PIPE_ACCEPTED',
                     'processStartSha256': self.sha(canonical_bytes(start)),
                     'processInputSha256': self.sha(canonical_bytes(delivered))}
        for name, value in [('process-start.json', start), ('process-input.json', delivered),
                            ('transport-equivalence.json', transport)]:
            _write_exclusive(path.with_name(name), canonical_bytes(value), root=self.root)
        result = {'processStarted': True, 'status': 'PASS', 'exitCode': 0, 'timedOut': False, 'cancelled': False,
                  'startObservation': {'processIdentityHash': 'f' * 64}, 'deadlineMonotonicNs': 1,
                  'cleanup': {'status': 'PASS'}}
        authority.publish_attempt_result(self.root, intent_path=path, process_result=result)
        authority.require_positive_attempt_result(self.root, intent_path=path)
        return path, marker

    def test_completed_legacy_pending_allows_distinct_operation_without_rewriting_history(self):
        legacy, marker = self.completed_legacy_pending()
        saved = {p: p.read_bytes() for p in legacy.parent.iterdir() if p.is_file()}
        current = self.prepare('distinct/op', 'distinct')
        self.assertEqual(current['attemptId'], '1')
        self.assertNotEqual(current['intentPath'].parent, legacy.parent)
        self.assertEqual({p: p.read_bytes() for p in saved}, saved)
        self.assertEqual(json.loads(marker.read_bytes())['status'], 'PENDING')
        self.no_start(current)
        with self.assertRaises(LifecycleError) as caught:
            self.prepare('legacy/op', 'legacy-reuse')
        self.assertEqual(caught.exception.code, 'codex-exact-attempt-reused')
        self.assertEqual({p: p.read_bytes() for p in saved}, saved)

    def test_namespaced_pending_cannot_use_legacy_missing_operation_binding(self):
        current = self.prepare('current/op', 'current')
        marker = current['rawCleanupPendingPath']
        record = json.loads(marker.read_bytes())
        # A matching start exists; a fake positive callback must not hide the missing operation binding.
        start = {'schemaVersion': 'alk-codex-process-start.v1', 'hostLaunchStarted': True,
                 'runId': 'run-1', 'taskId': 'task-1', 'attemptId': '1', 'operationId': 'current/op'}
        current['startReceiptPath'].write_bytes(canonical_bytes(start))
        with patch.object(inputs, '_complete_started_input', return_value=True):
            inputs._assert_no_cleanup_blockers(self.root)
        for value in (None, 'another/op'):
            changed = {k: v for k, v in record.items() if k != 'operationId'}
            if value is not None:
                changed['operationId'] = value
            marker.write_bytes(canonical_bytes(changed))
            with self.subTest(operationId=value), patch.object(inputs, '_complete_started_input', return_value=True), \
                    self.assertRaises(LifecycleError):
                inputs._assert_no_cleanup_blockers(self.root)

"""Local fixtures test refusal/joins; none qualifies a Codex native success."""
from __future__ import annotations

from contextlib import closing, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent_lifecycle.accounting.host_bridge import BoundedReader
from agent_lifecycle.adapter_sessions import limited_native_evidence as native
from agent_lifecycle.adapter_sessions.attempt_authority import _invocation_namespace
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from tests.adapter_sessions import codex_limited_native_support as producer


class LimitedNativeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source = Path(__file__).resolve().parents[2]
        contract = json.loads((self.source / 'tasks/release-2-16/route-bootstrap-contract.json').read_bytes())
        self.rows = contract['validation']['limitedNativeMatrix']['rows']
        self.put('tasks/release-2-16/route-bootstrap-contract.json', contract)
        self.manifest = {'status': 'FROZEN', 'testFixture': 'local-only-no-native-authority'}
        self.put('tasks/release-2-16/plan.manifest.json', self.manifest)
        self.lock_ref = self.put('tasks/release-2-16/plan.lock.json', {'testFixture': True})
        self.task = {'id': 'task', 'status': 'RUNNING', 'attempt': 1, 'attemptDeadlineAt': '2099-01-01T00:00:00Z'}
        self.state = {'runId': 'run', 'planDigest': canonical_digest(self.manifest), 'sourceRevision': 'fixture',
                      'runDeadlineAt': '2099-01-01T00:00:00Z', 'tasks': [self.task]}
        self.put('work/release-2-16/state.json', self.state)
        history_ref = self.put('work/release-2-16/capacity-history.json', {'localFixtureOnly': True})
        facts = {'status': 'PASS', 'scope': 'ALK_CONTROLLED_SELECTED_INVOCATIONS_104_105',
                 'wholeHostUsageStatus': 'UNAVAILABLE_NOT_ZERO', 'qualifiedPriorStarts': 0,
                 'qualifiedRemainingCapacity': 6, 'planDigest': self.state['planDigest'],
                 'lockSha256': self.lock_ref['sha256'], 'historyRefs': [history_ref]}
        capacity_ref = self.put('work/release-2-16/capacity.json', facts)
        review_path = 'work/release-2-16/evidence/ordinary-audit/capacity-review/report.json'
        report = {'verdict': 'PASS', 'reviewerId': '/fixture-independent',
                  'planDigest': self.state['planDigest'], 'lockSha256': self.lock_ref['sha256'],
                  'coveredFiles': [capacity_ref, history_ref], 'coveredObligations': [native.CAPACITY_OBLIGATION]}
        review_ref = self.put(review_path, report)
        origin_ref = self.put('work/release-2-16/local-origin-fixture.json', {'notAnActualReview': True})
        self.capacity_verified = {'assurance': 'PROCEDURAL_SAME_ACCOUNT', 'nativeAllowed': False,
            'report': report, 'reportSha256': review_ref['sha256'],
            'assignment': {'scopeId': 'HOST_AND_TRANSPORT'}, 'snapshotRefs': [capacity_ref, history_ref, origin_ref]}
        # Explicit unit double for synthetic workflow fixtures. The forged-PASS
        # regression stops this patch and invokes the real origin consumer.
        self.origin_patch = patch.object(native, 'verify_area_report', return_value=self.capacity_verified)
        self.origin_stub = self.origin_patch.start()
        self.addCleanup(self.origin_patch.stop)
        self.admission = {'schemaVersion': 'alk-r69-native-finite-admission.v1', 'status': 'ADMITTED_PREAPPROVED_BY_USER',
            'runId': 'run', 'taskId': 'task', 'attemptId': '1', 'planDigest': self.state['planDigest'],
            'lockSha256': self.lock_ref['sha256'], 'statePath': 'work/release-2-16/state.json',
            'actorId': '/fixture-root', 'capacityQualificationRef': capacity_ref,
            'capacityReviewId': 'capacity-review', 'capacityReviewRef': review_ref,
            'maxSelectedCodexInvocations': 6, 'tokenCap': 1600000, 'protectedCloseoutTokens': 400000,
            'paidResponsesApiAllowed': False, 'retryAuthorized': False, 'costStatus': 'UNAVAILABLE',
            'fullUnknownHoldRetained': True, 'absoluteDeadlineUtc': '2099-01-01T00:00:00Z',
            'localPythonExecutable': str(Path(sys.executable).resolve()), 'selectedExecutable': '/not/a/local/python/codex', 'selectedBinarySha256': 'b' * 64,
            'alkCandidateDigest': 'a' * 64,
            'cases': {r['caseId']: {'operationId': 'native-' + r['caseId']} for r in self.rows}}
        self.admission_ref = self.put(native.ADMISSION_PATH, self.admission)
        self.producer_refs = [self.put(p, (self.source / p).read_bytes()) for p in native.PRODUCERS]

    def put(self, path, value):
        raw = value if isinstance(value, bytes) else canonical_bytes(value)
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return {'path': path, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

    def row(self, polarity='PRELAUNCH_REFUSAL', role='worker'):
        return next(r for r in self.rows if r['role'] == role and r['polarity'] == polarity)

    def fixture_case(self, row):
        path = row['receiptPathTemplate'].format(runId='run', taskId='task', attemptId='1')
        op = self.admission['cases'][row['caseId']]['operationId']
        subject = {k: None for k in row['subjectRequired']}
        subject.update(r69LockSha256=self.lock_ref['sha256'], runId='run', taskId='task', attemptId='1',
                       role=row['role'], requestedClaim='COMPLETE_HOST_INPUT_FIT' if row['polarity'] == 'STRONG_REFUSAL' else native.CLAIM,
                       planDigest=self.state['planDigest'], costStatus='UNAVAILABLE')
        code = 'codex-exact-route-required' if row['polarity'] == 'STRONG_REFUSAL' else 'codex-exact-packet-stale'
        result = {'status': 'BLOCKED', 'hostLaunchStarted': False, 'blockers': [{'code': code}]}
        case = {'schemaVersion': 'alk-r69-native-case.v1', 'status': 'PASS', 'caseId': row['caseId'],
                'executionClass': row['executionClass'], 'subject': subject, 'operationId': op,
                'alkCandidateDigest': 'a' * 64, 'admissionRef': self.admission_ref, 'producerRefs': self.producer_refs,
                'resultRef': self.put(path + '.result.json', result), 'nativeRefs': {},
                'claimRef': self.put(path + '.claim.json', {'schemaVersion': 'alk-r69-native-case-claim.v1',
                    'caseId': row['caseId'], 'operationId': op, 'admissionSha256': self.admission_ref['sha256']}),
                'nativeSuccessEvent': None, 'localFault': False, 'selectedCodexInvocationsStarted': 0,
                'providerModelRequestCount': None, 'completeFinancialRun': False,
                'costStatus': 'UNAVAILABLE', 'fullUnknownHoldRetained': True}
        if row['polarity'] == 'POSITIVE':
            slot_path = (Path(path).parent.parent / 'capacity-slots' / 'slot-0.json').as_posix()
            case['capacitySlotRef'] = self.put(slot_path, {'schemaVersion': 'alk-r69-selected-invocation-slot.v1',
                'slotIndex': 0, 'caseId': row['caseId'], 'operationId': op,
                'admissionSha256': self.admission_ref['sha256'], 'claimSha256': case['claimRef']['sha256']})
        return case, self.put(path, case)

    def verify(self, case, ref, row):
        self.put(ref['path'], case)
        ref = self.put(ref['path'], case)
        with closing(BoundedReader()) as reader:
            return native.verify_limited_native_case(self.root, ref, reader=reader, row=row,
                manifest=self.manifest, state=self.state, task=self.task, candidate_digest='a' * 64,
                admission=self.admission, admission_ref=self.admission_ref, producer_refs=self.producer_refs)

    def test_refusals_reject_cross_role_operation_claim_and_fabricated_fields(self):
        for polarity in ('PRELAUNCH_REFUSAL', 'STRONG_REFUSAL'):
            row = self.row(polarity)
            case, ref = self.fixture_case(row)
            self.assertEqual(self.verify(case, ref, row)['status'], 'PASS')  # fixture refusal only
            mutations = [('subject', 'role', 'auditor'), ('subject', 'attemptId', '2'),
                         ('subject', 'requestedClaim', 'FULL_FINANCIAL'), ('subject', 'selectedModel', 'invented'),
                         ('case', 'operationId', 'other'), ('case', 'selectedCodexInvocationsStarted', False),
                         ('case', 'localFault', True), ('case', 'fullUnknownHoldRetained', False)]
            for where, key, value in mutations:
                with self.subTest(polarity=polarity, field=key):
                    changed = copy.deepcopy(case)
                    (changed['subject'] if where == 'subject' else changed)[key] = value
                    with self.assertRaises(LifecycleError): self.verify(changed, ref, row)

    def test_missing_or_changed_bytes_and_existing_start_never_qualify_refusal(self):
        row = self.row()
        case, ref = self.fixture_case(row)
        ns = _invocation_namespace('run', 'task', '1', case['operationId'])
        start = self.root / 'work/release-2-16/evidence/codex-exact-prompt' / ns / 'process-start.json'
        start.parent.mkdir(parents=True); start.write_bytes(b'{}')
        with self.assertRaises(LifecycleError): self.verify(case, ref, row)
        start.unlink()
        (self.root / case['resultRef']['path']).write_bytes(b'{}')
        with self.assertRaises(LifecycleError): self.verify(case, ref, row)
        (self.root / case['resultRef']['path']).unlink()
        with self.assertRaises((LifecycleError, OSError)): self.verify(case, ref, row)

    def test_completion_requires_observed_native_event_not_exit_zero_or_local_pass(self):
        good = {'status': 'PASS', 'processStarted': True, 'exitCode': 0,
                'stdoutTail': '{"type":"turn.completed","usage":{"input_tokens":17,"output_tokens":3}}\n'}
        self.assertEqual(native.native_success_event(good)['usage']['input_tokens'], 17)
        for change in ({'stdoutTail': ''}, {'processStarted': False}, {'processStarted': 1},
                       {'stdoutTail': good['stdoutTail'] * 2},
                       {'stdoutTail': good['stdoutTail'] + '{"type":"turn.failed"}\n'},
                       {'stdoutTail': '{"status":"PASS"}\n'}):
            with self.subTest(change=change), self.assertRaises(LifecycleError):
                native.native_success_event({**good, **change})

    def test_forged_positive_with_completion_and_fake_transport_has_no_public_terminal(self):
        row = self.row('POSITIVE'); case, ref = self.fixture_case(row)
        case.update(selectedCodexInvocationsStarted=1, nativeSuccessEvent={'type': 'turn.completed'})
        result = {'status': 'PASS', 'hostLaunchStarted': True, 'modelCallsStarted': True,
                  'stdoutTail': '{"type":"turn.completed"}\n'}
        result['exactPrompt'] = {'observedProcessResult': {'status': 'PASS', 'processStarted': True, 'exitCode': 0, 'stdoutTail': result['stdoutTail']}}
        case['resultRef'] = self.put(case['resultRef']['path'], result)
        ns = _invocation_namespace('run', 'task', '1', case['operationId'])
        prefix = 'work/release-2-16/evidence/codex-exact-prompt/' + ns.as_posix() + '/'
        names = {'intent': 'prelaunch-intent.json', 'start': 'process-start.json', 'input': 'process-input.json',
                 'transport': 'transport-equivalence.json', 'terminal': 'attempt-result-terminal.json'}
        case['nativeRefs'] = {key: self.put(prefix + name, {'forged': True}) for key, name in names.items()}
        with patch.object(native, 'require_positive_attempt_result', wraps=native.require_positive_attempt_result) as terminal:
            with self.assertRaises(LifecycleError):
                self.verify(case, ref, row)
            terminal.assert_called_once()

    def test_self_authored_capacity_pass_is_not_independent_review(self):
        # Matching hashes and another actor name cannot prove an invocation.
        self.origin_patch.stop()
        with patch.object(native, 'verify_area_report', wraps=native.verify_area_report) as actual_origin:
            with closing(BoundedReader()) as reader, self.assertRaises(LifecycleError):
                native.read_native_admission(self.root, reader, manifest=self.manifest,
                    state=self.state, task=self.task, live=True)
            actual_origin.assert_called_once_with(self.root, review_id='capacity-review')

    def test_capacity_review_scope_coverage_authority_and_origin_budget(self):
        original = copy.deepcopy(self.capacity_verified)
        for mode in ('assurance', 'native-allowed', 'self-review', 'plan', 'lock', 'scope',
                     'obligation', 'facts', 'history', 'report-hash', 'report-body', 'origin-refs'):
            verified = copy.deepcopy(original)
            report = verified['report']
            if mode == 'assurance': verified['assurance'] = 'CALLER_ASSERTION'
            elif mode == 'native-allowed': verified['nativeAllowed'] = True
            elif mode == 'self-review': report['reviewerId'] = self.admission['actorId']
            elif mode == 'plan': report['planDigest'] = '0' * 64
            elif mode == 'lock': report['lockSha256'] = '0' * 64
            elif mode == 'scope': verified['assignment']['scopeId'] = 'OTHER_SCOPE'
            elif mode == 'obligation': report['coveredObligations'] = []
            elif mode == 'facts': report['coveredFiles'] = report['coveredFiles'][1:]
            elif mode == 'history': report['coveredFiles'] = report['coveredFiles'][:1]
            elif mode == 'origin-refs': verified['snapshotRefs'] = []
            self.admission['capacityReviewRef'] = self.put(self.admission['capacityReviewRef']['path'], report)
            verified['reportSha256'] = self.admission['capacityReviewRef']['sha256']
            if mode == 'report-hash': verified['reportSha256'] = '0' * 64
            elif mode == 'report-body': verified['report'] = {'different': True}
            self.put(native.ADMISSION_PATH, self.admission)
            self.origin_stub.return_value = verified
            with self.subTest(mode=mode), closing(BoundedReader()) as reader, self.assertRaises(LifecycleError):
                native.read_native_admission(self.root, reader, manifest=self.manifest,
                    state=self.state, task=self.task, live=True)
        self.origin_stub.return_value = original
        self.admission['capacityReviewRef'] = self.put(self.admission['capacityReviewRef']['path'], original['report'])
        self.put(native.ADMISSION_PATH, self.admission)
        with closing(BoundedReader()) as reader:
            native.read_native_admission(self.root, reader, manifest=self.manifest, state=self.state, task=self.task, live=True)
            self.assertTrue(all(ref in reader.snapshot_refs(self.root) for ref in original['snapshotRefs']))
            charged = reader.charged_bytes
        with closing(BoundedReader(limit=charged - 1)) as reader, self.assertRaises(LifecycleError):
            native.read_native_admission(self.root, reader, manifest=self.manifest, state=self.state, task=self.task, live=True)
        (self.root / original['snapshotRefs'][-1]['path']).write_bytes(b'changed origin')
        with closing(BoundedReader()) as reader, self.assertRaises(LifecycleError):
            native.read_native_admission(self.root, reader, manifest=self.manifest, state=self.state, task=self.task, live=True)

    def replace_capacity_fixture(self, capacity):
        capacity_ref = self.put(self.admission['capacityQualificationRef']['path'], capacity)
        self.admission['capacityQualificationRef'] = capacity_ref
        report = copy.deepcopy(self.capacity_verified['report'])
        report['coveredFiles'] = [capacity_ref, *capacity['historyRefs']]
        review_ref = self.put(self.admission['capacityReviewRef']['path'], report)
        self.admission['capacityReviewRef'] = review_ref
        self.put(native.ADMISSION_PATH, self.admission)
        self.capacity_verified.update(report=report, reportSha256=review_ref['sha256'],
                                      snapshotRefs=report['coveredFiles'])

    def renewal_capacity_fixture(self, *, qualified_prior=6, aggregate_ceiling=12, **changes):
        capacity = json.loads((self.root / self.admission['capacityQualificationRef']['path']).read_bytes())
        renewal = {
            'schemaVersion': 'alk-r216-native-capacity-renewal.v1',
            'authorizationKind': 'EXPLICIT_EXACT_COUNT_USER_GRANT', 'approved': True,
            'runId': self.state['runId'], 'taskId': self.task['id'], 'attemptId': str(self.task['attempt']),
            'planDigest': self.state['planDigest'], 'lockSha256': self.lock_ref['sha256'],
            'priorSelectedStarts': qualified_prior, 'additionalSelectedStarts': 6,
            'aggregateSelectedStartCeiling': aggregate_ceiling,
            'retryAuthorized': False, 'paidResponsesApiAllowed': False,
            'userText': f'Synthetic local fixture: approve exactly six additional starts; retain prior {qualified_prior}.',
        }
        renewal.update(changes)
        renewal_ref = self.put('work/release-2-16/explicit-native-renewal.json', renewal)
        capacity.update(scope='ALK_CONTROLLED_SELECTED_INVOCATIONS_104_105_AND_EXPLICIT_RENEWAL',
                        qualifiedPriorStarts=qualified_prior, qualifiedRemainingCapacity=6,
                        aggregateSelectedInvocationCeiling=aggregate_ceiling, renewalAuthorizationRef=renewal_ref)
        capacity['historyRefs'] = [r for r in capacity['historyRefs'] if r['path'] != renewal_ref['path']]
        capacity['historyRefs'].append(renewal_ref)
        self.replace_capacity_fixture(capacity)
        return capacity, renewal_ref

    def test_consumed_legacy_capacity_stays_exhausted_without_explicit_renewal(self):
        capacity = json.loads((self.root / self.admission['capacityQualificationRef']['path']).read_bytes())
        capacity.update(qualifiedPriorStarts=6, qualifiedRemainingCapacity=0)
        self.replace_capacity_fixture(capacity)
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with closing(BoundedReader()) as reader, self.assertRaises(LifecycleError):
            native.read_native_admission(self.root, reader, manifest=self.manifest,
                                         state=self.state, task=self.task, live=True)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_exact_current_renewal_preserves_consumed_six_and_charges_authorization(self):
        capacity, renewal_ref = self.renewal_capacity_fixture()
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with closing(BoundedReader()) as reader:
            admitted, _ = native.read_native_admission(self.root, reader, manifest=self.manifest,
                                                       state=self.state, task=self.task, live=True)
            self.assertEqual(admitted['maxSelectedCodexInvocations'], 6)
            self.assertIn(renewal_ref, reader.snapshot_refs(self.root))
        self.assertEqual((capacity['qualifiedPriorStarts'], capacity['qualifiedRemainingCapacity']), (6, 6))
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_renewal_denies_wrong_subject_implicit_grant_reset_or_retry(self):
        mutations = [('approved', False), ('approved', 1), ('runId', 'other-run'),
                     ('taskId', 'other-task'), ('attemptId', '2'), ('planDigest', '0' * 64),
                     ('lockSha256', '0' * 64), ('authorizationKind', 'GOAL_OR_BUDGET_APPROVAL'),
                     ('priorSelectedStarts', 0), ('additionalSelectedStarts', 7),
                     ('additionalSelectedStarts', True), ('aggregateSelectedStartCeiling', 18),
                     ('retryAuthorized', True), ('paidResponsesApiAllowed', True),
                     ('userText', ''), ('unrecognizedField', True)]
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                self.renewal_capacity_fixture(**{field: value})
                with closing(BoundedReader()) as reader, self.assertRaises(LifecycleError):
                    native.read_native_admission(self.root, reader, manifest=self.manifest,
                                                 state=self.state, task=self.task, live=True)

    def test_renewal_does_not_raise_per_admission_six_or_allow_unreviewed_history(self):
        capacity, renewal_ref = self.renewal_capacity_fixture()
        for changes in ({'qualifiedPriorStarts': 0}, {'qualifiedRemainingCapacity': 12},
                        {'aggregateSelectedInvocationCeiling': 18},
                        {'historyRefs': [r for r in capacity['historyRefs'] if r != renewal_ref]}):
            with self.subTest(changes=changes):
                self.replace_capacity_fixture(dict(capacity, **changes))
                with closing(BoundedReader()) as reader, self.assertRaises(LifecycleError):
                    native.read_native_admission(self.root, reader, manifest=self.manifest,
                                                 state=self.state, task=self.task, live=True)
        self.replace_capacity_fixture(capacity)
        self.admission['maxSelectedCodexInvocations'] = 7
        self.put(native.ADMISSION_PATH, self.admission)
        with closing(BoundedReader()) as reader, self.assertRaises(LifecycleError):
            native.read_native_admission(self.root, reader, manifest=self.manifest,
                                         state=self.state, task=self.task, live=True)

    def test_second_exact_renewal_retains_twelve_and_charges_all_history(self):
        previous = self.put('work/release-2-16/previous-twelve.json',
                            {'localFixtureOnly': True, 'priorStarts': 6, 'newStarts': 6})
        facts = json.loads((self.root / self.admission['capacityQualificationRef']['path']).read_bytes())
        facts['historyRefs'].append(previous)
        self.replace_capacity_fixture(facts)
        capacity, renewal_ref = self.renewal_capacity_fixture(qualified_prior=12, aggregate_ceiling=18)
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with closing(BoundedReader()) as reader:
            admitted, _ = native.read_native_admission(self.root, reader, manifest=self.manifest,
                                                       state=self.state, task=self.task, live=True)
            self.assertEqual(admitted['maxSelectedCodexInvocations'], 6)
            self.assertTrue(all(ref in reader.snapshot_refs(self.root)
                                for ref in capacity['historyRefs']))
            self.assertIn(previous, reader.snapshot_refs(self.root))
            self.assertIn(renewal_ref, reader.snapshot_refs(self.root))
            charged = reader.charged_bytes
        self.assertEqual((capacity['qualifiedPriorStarts'], capacity['qualifiedRemainingCapacity'],
                          capacity['aggregateSelectedInvocationCeiling']), (12, 6, 18))
        with closing(BoundedReader(limit=charged - 1)) as reader, self.assertRaises(LifecycleError):
            native.read_native_admission(self.root, reader, manifest=self.manifest,
                                         state=self.state, task=self.task, live=True)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_second_renewal_rejects_reset_mismatch_and_unapproved_third_grant(self):
        mutations = [('priorSelectedStarts', 6), ('priorSelectedStarts', True),
                     ('additionalSelectedStarts', 7), ('additionalSelectedStarts', True),
                     ('aggregateSelectedStartCeiling', 12), ('aggregateSelectedStartCeiling', 24),
                     ('authorizationKind', 'GOAL_OR_BUDGET_APPROVAL'), ('approved', 1),
                     ('retryAuthorized', True), ('paidResponsesApiAllowed', True)]
        for field, value in mutations:
            with self.subTest(grantField=field, value=value):
                self.renewal_capacity_fixture(qualified_prior=12, aggregate_ceiling=18,
                                              **{field: value})
                with closing(BoundedReader()) as reader, self.assertRaises(LifecycleError):
                    native.read_native_admission(self.root, reader, manifest=self.manifest,
                                                 state=self.state, task=self.task, live=True)
        for field, value in [('qualifiedPriorStarts', 0), ('qualifiedPriorStarts', 6),
                             ('qualifiedPriorStarts', 11), ('qualifiedPriorStarts', 13),
                             ('qualifiedPriorStarts', True), ('qualifiedRemainingCapacity', 7),
                             ('qualifiedRemainingCapacity', True),
                             ('aggregateSelectedInvocationCeiling', 12),
                             ('aggregateSelectedInvocationCeiling', 24)]:
            with self.subTest(capacityField=field, value=value):
                capacity, _ = self.renewal_capacity_fixture(qualified_prior=12, aggregate_ceiling=18)
                self.replace_capacity_fixture(dict(capacity, **{field: value}))
                with closing(BoundedReader()) as reader, self.assertRaises(LifecycleError):
                    native.read_native_admission(self.root, reader, manifest=self.manifest,
                                                 state=self.state, task=self.task, live=True)
        self.renewal_capacity_fixture(qualified_prior=18, aggregate_ceiling=24)
        with closing(BoundedReader()) as reader, self.assertRaises(LifecycleError):
            native.read_native_admission(self.root, reader, manifest=self.manifest,
                                         state=self.state, task=self.task, live=True)

    def test_second_renewal_requires_current_reviewed_authorization_and_six_only(self):
        _, renewal_ref = self.renewal_capacity_fixture(qualified_prior=12, aggregate_ceiling=18)
        (self.root / renewal_ref['path']).write_bytes(b'changed authorization')
        with closing(BoundedReader()) as reader, self.assertRaises(LifecycleError):
            native.read_native_admission(self.root, reader, manifest=self.manifest,
                                         state=self.state, task=self.task, live=True)
        capacity, _ = self.renewal_capacity_fixture(qualified_prior=12, aggregate_ceiling=18)
        self.capacity_verified['report']['coveredFiles'] = [self.admission['capacityQualificationRef']]
        self.admission['capacityReviewRef'] = self.put(self.admission['capacityReviewRef']['path'],
                                                       self.capacity_verified['report'])
        self.capacity_verified['reportSha256'] = self.admission['capacityReviewRef']['sha256']
        self.put(native.ADMISSION_PATH, self.admission)
        with closing(BoundedReader()) as reader, self.assertRaises(LifecycleError):
            native.read_native_admission(self.root, reader, manifest=self.manifest,
                                         state=self.state, task=self.task, live=True)
        self.renewal_capacity_fixture(qualified_prior=12, aggregate_ceiling=18)
        self.admission['maxSelectedCodexInvocations'] = 7
        self.put(native.ADMISSION_PATH, self.admission)
        with closing(BoundedReader()) as reader, self.assertRaises(LifecycleError):
            native.read_native_admission(self.root, reader, manifest=self.manifest,
                                         state=self.state, task=self.task, live=True)

    def test_capacity_unknown_stale_self_review_or_overflow_is_denied(self):
        with closing(BoundedReader()) as reader:
            native.read_native_admission(self.root, reader, manifest=self.manifest, state=self.state, task=self.task, live=True)
        for field, value in [('maxSelectedCodexInvocations', 0), ('maxSelectedCodexInvocations', True),
                             ('maxSelectedCodexInvocations', 7), ('tokenCap', 1600001),
                             ('fullUnknownHoldRetained', False), ('absoluteDeadlineUtc', '2000-01-01T00:00:00Z')]:
            changed = copy.deepcopy(self.admission); changed[field] = value
            self.put(native.ADMISSION_PATH, changed)
            with self.subTest(field=field), closing(BoundedReader()) as reader, self.assertRaises(LifecycleError):
                native.read_native_admission(self.root, reader, manifest=self.manifest, state=self.state, task=self.task, live=True)
        self.put(native.ADMISSION_PATH, self.admission)
        path = self.admission['capacityQualificationRef']['path']
        cap = json.loads((self.root / path).read_bytes()); cap['qualifiedRemainingCapacity'] = None
        self.admission['capacityQualificationRef'] = self.put(path, cap)
        self.put(native.ADMISSION_PATH, self.admission)
        with closing(BoundedReader()) as reader, self.assertRaises(LifecycleError):
            native.read_native_admission(self.root, reader, manifest=self.manifest, state=self.state, task=self.task, live=True)

    @unittest.skipUnless(hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW"), "selected native qualification requires durable private directories")
    def test_real_local_fault_retains_start_input_raw_cost_and_forbids_retry(self):
        row = self.row('STARTED_FAILURE')
        selector = row['testSelector']
        # Genuine local Python child; synthetic workflow/capacity fixture only.
        with patch.dict(os.environ, {'ALK_R69_FINITE_ADMISSION': native.ADMISSION_PATH}), \
             patch.object(sys, 'argv', ['unittest', selector, '-q']), redirect_stdout(io.StringIO()), \
             patch.object(producer, '_launch', side_effect=AssertionError('No Codex route in local fault')):
            case = producer.produce_case(self.root, row['caseId'], selector)
            output = row['receiptPathTemplate'].format(runId='run', taskId='task', attemptId='1')
            self.assertTrue((self.root / output).exists())
            before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
            with self.assertRaises((LifecycleError, OSError)):
                producer.produce_case(self.root, row['caseId'], selector)
            self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertTrue(case['localFault']); self.assertEqual(case['selectedCodexInvocationsStarted'], 0)
        self.assertIsNone(case['providerModelRequestCount']); self.assertTrue(case['fullUnknownHoldRetained'])
        wrong = copy.deepcopy(case); wrong['localFault'] = False
        with self.assertRaises(LifecycleError): self.verify(wrong, self.put(output, wrong), row)
        positive = self.row('POSITIVE')
        with self.assertRaises(LifecycleError): self.verify(case, self.put(output, case), positive)

    def test_missing_admission_and_batch_selector_stop_before_any_action(self):
        row = self.row('POSITIVE'); selector = row['testSelector']
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(LifecycleError):
            producer.produce_case(self.root, row['caseId'], selector)
        with patch.dict(os.environ, {'ALK_R69_FINITE_ADMISSION': native.ADMISSION_PATH}), \
             patch.object(sys, 'argv', ['unittest', 'whole.module', '-q']), self.assertRaises(LifecycleError):
            producer.produce_case(self.root, row['caseId'], selector)
        self.assertFalse(any(self.root.rglob('*.claim.json')))

    def test_per_row_command_mapping_missing_skip_and_alias_are_denied(self):
        commands = [{'commandDigest': canonical_digest(r['command']), 'status': 'PASS', 'exitCode': 0,
                     'cases': [{'id': r['caseId'], 'status': 'PASS', 'evidence': {'path': 'missing'}}]} for r in self.rows]
        # Missing native evidence refuses even when unittest exits zero.
        with closing(BoundedReader()) as reader, self.assertRaises((LifecycleError, OSError, KeyError)):
            native.verify_native_observations(self.root, {'commands': commands}, reader=reader,
                manifest=self.manifest, state=self.state, task=self.task, candidate_digest='a' * 64)
        for mode in ('missing', 'duplicate', 'alias'):
            changed = copy.deepcopy(commands)
            if mode == 'missing': changed.pop(0)
            elif mode == 'duplicate': changed.append(copy.deepcopy(changed[0]))
            else: changed[0]['cases'][0]['id'] = 'wrong-alias'
            with patch.object(native, 'verify_limited_native_case', return_value={'selectedCodexInvocationsStarted': 0}), \
                 closing(BoundedReader()) as reader, self.assertRaises(LifecycleError):
                native.verify_native_observations(self.root, {'commands': changed}, reader=reader,
                    manifest=self.manifest, state=self.state, task=self.task, candidate_digest='a' * 64)

    def test_candidate_contract_preserves_85_cases_and_24_unique_commands(self):
        manifest = json.loads((self.source / 'tasks/release-2-16/plan.manifest.json').read_bytes())
        requirements = next(e for e in manifest['acceptance']['evidence']
                            if e['id'] == 'EV216-ACCOUNTING-ENFORCEMENT')['validation']['requirements']
        self.assertEqual(len(requirements['caseIds']), 85)
        self.assertEqual(len(requirements['commandDigests']), 29)
        self.assertEqual(len({r['command'] for r in self.rows}), 24)
        for row in self.rows:
            self.assertIn(row['testSelector'], row['command'])
            self.assertIn(canonical_digest(row['command']), requirements['commandDigests'])

    def test_real_stager_derives_attempt_without_template_attempt_injection(self):
        row = self.row('PRELAUNCH_REFUSAL')
        op = self.admission['cases'][row['caseId']]['operationId']
        template = {'role': row['role'], 'operationId': op, 'runId': 'run', 'taskId': 'task',
                    'attemptId': '1', 'requestedClaim': native.CLAIM, 'routeId': native.ROUTE}
        template_ref = self.put('work/release-2-16/templates/input.json', template)
        launch_ref = self.put('work/release-2-16/templates/launch.json', {
            'inputTemplateRef': template_ref, 'profileRef': self.put('profile.json', {'fixture': True}),
            'riskProfile': {'profileDigest': 'fixture'}, 'immutableInputRequest': {'fixture': True}})
        self.admission['cases'][row['caseId']]['launchSpecRef'] = launch_ref
        def no_dispatch(**kwargs):
            staged = json.loads(kwargs['input_request'].read_bytes())
            self.assertNotIn('attemptId', staged)
            self.assertEqual(staged['operationId'], op)
            self.assertEqual(staged['packetSha256'], '0' * 64)
            self.assertNotIn('OPENAI_API_KEY', kwargs['process_env'])
            return {'status': 'BLOCKED', 'hostLaunchStarted': False, 'blockers': [{'code': 'fixture-no-dispatch'}]}
        with patch.object(producer, 'launch_from_local_profile', side_effect=no_dispatch) as launch, \
             closing(BoundedReader()) as reader:
            result = producer._launch(self.root, row, self.admission, self.state, self.task, reader)
        launch.assert_called_once()
        self.assertFalse(result['hostLaunchStarted'])
        self.assertEqual(json.loads((self.root / template_ref['path']).read_bytes()), template)

    @unittest.skipUnless(hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW"), "selected native qualification requires durable private directories")
    def test_production_observed_argv_shape_reaches_producer_and_consumer(self):
        # Synthetic observations exercise field joins only. The positive terminal
        # consumer is an explicit unit double, not a Codex qualification.
        row = self.row('POSITIVE'); selector = row['testSelector']
        op = self.admission['cases'][row['caseId']]['operationId']
        ns = _invocation_namespace('run', 'task', '1', op)
        prefix = 'work/release-2-16/evidence/codex-exact-prompt/' + ns.as_posix() + '/'
        argv = [self.admission['selectedExecutable'], 'exec', '--json', '-m', 'fixture-model', '-']
        intent = {'role': 'worker', 'planDigest': self.state['planDigest'], 'operationId': op,
                  'finalPromptSha256': 'f' * 64, 'packetSha256': 'd' * 64, 'binarySha256': 'b' * 64,
                  'commandIdentityHash': canonical_digest(argv), 'configManifestSha256': 'c' * 64,
                  'diagnosticObservation': {'rawSha256': 'e' * 64}}
        start = {**intent, 'schemaVersion': 'alk-codex-process-start.v1',
                 'observedArgv': argv, 'hostLaunchStarted': True, 'stdinStatus': 'PENDING'}
        self.assertNotIn('argv', start)
        refs = {'intent': self.put(prefix + 'prelaunch-intent.json', intent),
                'start': self.put(prefix + 'process-start.json', start),
                'input': self.put(prefix + 'process-input.json', {'fixture': 'input'}),
                'transport': self.put(prefix + 'transport-equivalence.json', {'fixture': 'transport'})}
        observed = {'status': 'PASS', 'processStarted': True, 'exitCode': 0,
                    'stdoutTail': '{"type":"turn.completed"}\n'}
        terminal = {'binding': {'operationId': op}, 'processResultSha256': canonical_digest(observed)}
        refs['terminal'] = self.put(prefix + 'attempt-result-terminal.json', terminal)
        public = {'status': 'PASS', 'hostLaunchStarted': True, 'modelCallsStarted': True,
                  'exactPrompt': {'observedProcessResult': observed,
                     'terminalResultSha256': refs['terminal']['sha256'],
                     'startReceiptSha256': refs['start']['sha256'], 'inputReceiptSha256': refs['input']['sha256']}}
        with patch.dict(os.environ, {'ALK_R69_FINITE_ADMISSION': native.ADMISSION_PATH}), \
             patch.object(sys, 'argv', ['unittest', selector, '-q']), redirect_stdout(io.StringIO()), \
             patch.object(producer, '_launch', return_value=public), \
             patch.object(native, 'require_positive_attempt_result', return_value=terminal) as verify_terminal:
            case = producer.produce_case(self.root, row['caseId'], selector)
            self.assertEqual(case['subject']['selectedModel'], 'fixture-model')
            case_path = row['receiptPathTemplate'].format(runId='run', taskId='task', attemptId='1')
            with closing(BoundedReader()) as reader:
                verified = native.verify_limited_native_case(self.root, self.put(case_path, case), reader=reader,
                    row=row, manifest=self.manifest, state=self.state, task=self.task, candidate_digest='a' * 64,
                    admission=self.admission, admission_ref=self.admission_ref, producer_refs=self.producer_refs)
            self.assertEqual(verified['subject']['selectedModel'], 'fixture-model')
            self.assertGreaterEqual(verify_terminal.call_count, 2)
            self.assertEqual(verify_terminal.call_args.kwargs['process_result'], observed)

    @unittest.skipUnless(hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW"), "selected native qualification requires durable private directories")
    def test_two_distinct_producers_with_one_slot_cannot_both_reach_launch(self):
        import threading
        # This deliberately aligns both producers before their separate row
        # claims. The old count-then-claim check lets both reach _launch.
        rows = [self.row('POSITIVE', r) for r in ('worker', 'validator')]
        self.admission['maxSelectedCodexInvocations'] = 1
        self.admission_ref = self.put(native.ADMISSION_PATH, self.admission)
        from agent_lifecycle.adapter_sessions.private_input import _private_dir
        for row in rows:
            path = producer._case_path(self.root, row, self.state, self.task)
            _private_dir(path.parent, boundary=self.root)
        barrier = threading.Barrier(2)
        local = threading.local(); launches = []; errors = []; mutex = threading.Lock()
        original_write = producer._write
        class ThreadArgv(list):
            def __getitem__(self, key):
                if isinstance(key, slice): return [local.selector, '-q']
                return super().__getitem__(key)
        def aligned_write(root, path, value):
            if str(path).endswith('.claim.json'): barrier.wait(timeout=5)
            return original_write(root, path, value)
        def no_dispatch(_root, row, *_args):
            with mutex: launches.append(row['caseId'])
            return {'status': 'BLOCKED', 'hostLaunchStarted': False,
                    'exactPrompt': {'observedProcessResult': {'status': 'BLOCKED', 'processStarted': False}}}
        def invoke(row):
            local.selector = row['testSelector']
            try: producer.produce_case(self.root, row['caseId'], local.selector)
            except Exception as exc:
                with mutex: errors.append(type(exc).__name__ + ':' + str(exc))
        with patch.dict(os.environ, {'ALK_R69_FINITE_ADMISSION': native.ADMISSION_PATH}), \
             patch.object(sys, 'argv', ThreadArgv(['unittest'])), \
             patch.object(producer, '_write', side_effect=aligned_write), \
             patch.object(producer, '_launch', side_effect=no_dispatch), redirect_stdout(io.StringIO()):
            threads = [threading.Thread(target=invoke, args=(row,)) for row in rows]
            for thread in threads: thread.start()
            for thread in threads: thread.join(timeout=10)
            self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(launches), 1, (launches, errors))
        self.assertEqual(len(list(self.root.rglob('*.claim.json'))), 2)
        slots = list(self.root.rglob('capacity-slots/slot-*.json'))
        self.assertEqual(len(slots), 1)
        self.assertEqual(json.loads(slots[0].read_bytes())['caseId'], launches[0])

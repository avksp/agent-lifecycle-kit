"""Private publication and AREA joins; authority/ledger boundaries controlled.

These cases do not qualify final integration, native dispatch or host origin.
The closed schemas below are exact installed r70 plan fixtures.
"""

from datetime import datetime, timedelta, timezone
import copy
import inspect
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time
import unittest
from unittest.mock import patch

from agent_lifecycle.adapter_sessions import ordinary_audit as audit
from agent_lifecycle.adapter_sessions import bootstrap_r11
from agent_lifecycle.adapter_sessions import source_review_preparation_records
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.authority_io import create_authority_bytes


class OrdinaryAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'src/scoped.py'
        self.source.parent.mkdir()
        self.source.write_bytes(b'value = 1\n')
        self.base = self.root / audit._STORE / 'area1'
        self.current = 'b' * 64
        self.authority = {'planDigest': '1' * 64, 'lockSha256': '2' * 64, 'policySha256': '3' * 64,
                          'policy': {'scopes': ['SOURCE_AUTHORITY_AND_PACKING'],
                                     'limits': {'perRoleSeconds': 1800}},
                          'reportSchema': _SCHEMAS['report'], 'inputSchemas': _SCHEMAS['inputs']['$defs']}
        self.addCleanup(patch.stopall)
        patch.object(audit, '_authority', return_value=self.authority).start()
        patch.object(audit, 'read_coordinator_cost_head', side_effect=self.cost).start()
        now = datetime.now(timezone.utc)
        self.tests = canonical_bytes({'schemaVersion': 'test-input-fixture', 'result': 'NOT_NATIVE_PROOF'})
        rows = [{'path': 'src/scoped.py', 'bytes': len(self.source.read_bytes()),
                 'sha256': audit._sha(self.source.read_bytes())}]
        self.assignment = {'schemaVersion': 'alk-ordinary-audit-assignment.v1', 'reviewId': 'area1',
                           'roleId': 'source', 'roleKind': 'AREA', 'scopeId': 'SOURCE_AUTHORITY_AND_PACKING',
                           'authorId': 'author', 'coordinatorId': 'coordinator', 'reviewerId': 'independent',
                           **{key: self.authority[key] for key in ('planDigest', 'lockSha256', 'policySha256')},
                           'sourceSnapshotSha256': canonical_digest(rows), 'files': rows,
                           'obligations': ['source-dependencies'], 'requiredTestEvidenceSha256': audit._sha(self.tests),
                           'predecessorReportDigests': []}
        self.request = b'Review the fixed source and return the assigned ordinary result.'
        self.admission = {'schemaVersion': 'alk-ordinary-audit-admission.v1', 'roleId': 'source',
                          'invocationId': 'host-invocation-1', 'priorHeadSha256': 'a' * 64,
                          'reservedHeadSha256': 'b' * 64, 'initialRequestSha256': audit._sha(self.request),
                          'initialRequestBytes': len(self.request), 'tokenCap': 60000,
                          'protectedCloseoutTokens': 10000, 'workTokens': 50000,
                          'outputReserveTokens': 8192, 'contextSafetyTokens': 16384, 'maxStarts': 1,
                          'admittedAtUtc': (now - timedelta(seconds=60)).isoformat(),
                          'originalDeadlineUtc': (now + timedelta(seconds=600)).isoformat()}
        self._input('assignment.json', canonical_bytes(self.assignment))
        self._input('admission.json', canonical_bytes(self.admission))
        self._input('request.txt', self.request)
        self._input('test-evidence.json', self.tests)

    def _input(self, name, raw):
        create_authority_bytes(self.base / name, raw, root=self.root, private=True)

    def cost(self, _root, *, ancestor_head_sha256=None):
        heads = ['a' * 64, 'b' * 64, 'c' * 64]
        chain = list(reversed(heads[:heads.index(self.current) + 1]))
        head = {'unknownHolds': {'a': 100, 'b': 60100, 'c': 62100}[self.current[0]],
                'exposureLowerBound': {'a': 100, 'b': 60100, 'c': 62100}[self.current[0]]}
        result = {'headSha256': self.current, 'head': head}
        if ancestor_head_sha256 is not None:
            if ancestor_head_sha256 not in chain:
                raise LifecycleError('r11-opening-ancestry', 'controlled missing/forked head')
            balance = {'a': 100, 'b': 60100, 'c': 62100}[ancestor_head_sha256[0]]
            result.update(ancestryHeadSha256s=chain[:chain.index(ancestor_head_sha256) + 1],
                          ancestor={'head': {'unknownHolds': balance, 'exposureLowerBound': balance,
                                             'previousHeadSha256': None if ancestor_head_sha256 == heads[0]
                                             else heads[heads.index(ancestor_head_sha256) - 1]}})
        return result

    def publication(self):
        report = {'schemaVersion': 'alk-ordinary-audit-report.v1', 'assurance': 'PROCEDURAL_SAME_ACCOUNT',
                  **{key: self.assignment[key] for key in ('reviewId', 'roleId', 'roleKind', 'authorId',
                                                         'reviewerId', 'planDigest', 'lockSha256', 'policySha256')},
                  'hostAdapter': 'codex', 'invocationId': self.admission['invocationId'],
                  'subjectSha256': canonical_digest(self.assignment),
                  'scopeSnapshotSha256': self.assignment['sourceSnapshotSha256'],
                  'priorReportDigests': [], 'coveredFiles': copy.deepcopy(self.assignment['files']),
                  'coveredObligations': list(self.assignment['obligations']), 'verdict': 'PASS', 'findings': [],
                  'reviewText': 'The assigned source has been independently reviewed.',
                  'financialHeadSha256': self.current, 'originalDeadlineUtc': self.admission['originalDeadlineUtc'],
                  'actualTokens': None, 'usageStatus': 'UNAVAILABLE',
                  'admissionSha256': audit._sha(canonical_bytes(self.admission)), 'parentFindingDispositions': []}
        raw = canonical_bytes({key: report[key] for key in audit._RESULT_FIELDS})
        observation = {'schemaVersion': 'alk-ordinary-audit-observation.v1', 'adapter': 'codex',
                       'sessionId': 'independent-session', 'invocationId': self.admission['invocationId'],
                       'reviewerId': 'independent', 'subjectSha256': report['subjectSha256'],
                       'rawResultSha256': audit._sha(raw),
                       'assignmentSha256': audit._sha(canonical_bytes(self.assignment))}
        report.update(rawResultSha256=audit._sha(raw),
                      publicationObservationSha256=audit._sha(canonical_bytes(observation)))
        return dict(review_id='area1', report=report, raw_result=raw, observation=observation,
                    author_session_id='author-session', coordinator_session_id='coordinator-session')

    def publish(self):
        return audit.publish_observed_result(self.root, **self.publication())

    def _reset_publication(self):
        shutil.rmtree(self.root / audit._STORE)
        for name, raw in [('assignment.json', canonical_bytes(self.assignment)),
                          ('admission.json', canonical_bytes(self.admission)),
                          ('request.txt', self.request), ('test-evidence.json', self.tests)]:
            self._input(name, raw)

    def _assert_pending_refuses(self):
        self.assertTrue((self.base / 'publication.pending.json').exists())
        self.assertTrue((self.base / 'report.json').exists())
        self.assertTrue((self.root / audit._STORE / 'reservations' / ('b' * 64 + '.json')).exists())
        with self.assertRaisesRegex(LifecycleError, 'pending or uncertain'):
            self.verify()
        with self.assertRaisesRegex(LifecycleError, 'pending or uncertain'):
            audit.verify_integration_report(self.root, review_id='integration1',
                                            area_review_ids=['area1', 'a2', 'a3', 'a4', 'a5', 'a6'])
        self.assertEqual(self.cost(self.root)['head']['unknownHolds'], 60100)

    def verify(self):
        return audit.verify_area_report(self.root, review_id='area1')

    def test_coordinator_observed_review_required(self):
        forged = self.publication()
        forged['report']['reviewText'] = 'Coordinator invented another result.'
        with self.assertRaises(LifecycleError):
            audit.publish_observed_result(self.root, **forged)
        self.assertFalse((self.base / 'report.json').exists())
        result = self.publish()
        self.assertFalse(result['nativeAllowed'])
        self.assertEqual(self.verify()['reportSha256'], result['reportSha256'])
        raw = (self.base / 'raw-result.txt').read_bytes()
        with self.assertRaises(FileExistsError):
            self.publish()
        self.assertEqual(self.verify()['reportSha256'], result['reportSha256'])
        self.assertEqual((self.base / 'raw-result.txt').read_bytes(), raw)
        (self.base / 'observation.json').unlink()
        with self.assertRaises(LifecycleError):
            self.verify()

        # Exercise real storage writes: complete bytes remain visible when
        # either the file fsync or its parent-directory fsync fails.
        real_sync = os.fsync
        for target in ('report.json', 'publication.json'):
            for directory in (False, True):
                with self.subTest(target=target, directory=directory):
                    self._reset_publication()
                    active = [None]
                    def write(path, raw, *, _active=active, **kwargs):
                        _active[0] = path.name
                        try:
                            return create_authority_bytes(path, raw, **kwargs)
                        finally:
                            _active[0] = None
                    def sync(fd, _active=active, _target=target, _directory=directory):
                        if _active[0] == _target and stat.S_ISDIR(os.fstat(fd).st_mode) == _directory:
                            raise OSError('injected final publication sync failure')
                        return real_sync(fd)
                    with patch.object(audit, 'create_authority_bytes', side_effect=write), \
                            patch('agent_lifecycle.contracts.authority_io.os.fsync', side_effect=sync):
                        with self.assertRaises(LifecycleError):
                            self.publish()
                    self._assert_pending_refuses()
                    self.assertEqual(json.loads((self.base / 'report.json').read_bytes())['verdict'], 'PASS')

        self._reset_publication()
        with patch.object(Path, 'unlink', side_effect=OSError('injected marker removal failure')):
            with self.assertRaises(OSError):
                self.publish()
        self._assert_pending_refuses()

        # B has passed its absence checks when A finishes publication. B must
        # lose the permanent claim without recreating A's removed marker.
        self._reset_publication()
        interleave = [True]
        winner = []
        def competing_write(path, raw, **kwargs):
            if path.parent.name == 'reservations' and interleave[0]:
                interleave[0] = False
                winner.append(self.publish())
            return create_authority_bytes(path, raw, **kwargs)
        with patch.object(audit, 'create_authority_bytes', side_effect=competing_write):
            with self.assertRaises(FileExistsError):
                self.publish()
        self.assertEqual(len(winner), 1)
        self.assertFalse((self.base / 'publication.pending.json').exists())
        self.assertEqual(self.verify()['reportSha256'], winner[0]['reportSha256'])

    def test_scope_membership_and_independence(self):
        same_session = self.publication()
        same_session['coordinator_session_id'] = 'independent-session'
        with self.assertRaises(LifecycleError):
            audit.publish_observed_result(self.root, **same_session)
        self.publish()
        assignment = copy.deepcopy(self.assignment)
        assignment['coordinatorId'] = 'independent'
        (self.base / 'assignment.json').write_bytes(canonical_bytes(assignment))
        with self.assertRaises(LifecycleError):
            self.verify()
        assignment['coordinatorId'] = 'coordinator'
        assignment['obligations'].append('unreviewed-obligation')
        (self.base / 'assignment.json').write_bytes(canonical_bytes(assignment))
        with self.assertRaises(LifecycleError):
            self.verify()

    def test_snapshot_and_dependency_change_refuse(self):
        self.publish()
        self.source.write_bytes(b'value = 2\n')
        with self.assertRaises(LifecycleError):
            self.verify()
        self.source.unlink()
        outside = self.root / 'other.py'
        outside.write_bytes(b'value = 1\n')
        self.source.symlink_to(outside)
        with self.assertRaises(LifecycleError):
            self.verify()

    def test_identical_evidence_reuse_and_affected_invalidation(self):
        self.publish()
        first = self.verify()['reportSha256']
        self.current = 'c' * 64  # A legitimate later reservation retains all holds.
        self.assertEqual(self.verify()['reportSha256'], first)
        class Later(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(timezone.utc) + timedelta(days=2)
        with patch.object(audit, 'datetime', Later):
            self.assertEqual(self.verify()['reportSha256'], first)
        (self.base / 'test-evidence.json').write_bytes(b'{"changed":true}')
        with self.assertRaises(LifecycleError):
            self.verify()

    def test_cost_ancestry_and_original_deadline(self):
        unavailable = self.publication()
        unavailable['report']['actualTokens'] = 0
        # Publication retains the returned result; semantic verification denies
        # the inconsistent claim instead of treating unavailable as free.
        audit.publish_observed_result(self.root, **unavailable)
        with self.assertRaises(LifecycleError):
            self.verify()
        admission = copy.deepcopy(self.admission)
        admission['originalDeadlineUtc'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        (self.base / 'admission.json').write_bytes(canonical_bytes(admission))
        expired = self.publication()
        with self.assertRaises(LifecycleError):
            audit.publish_observed_result(self.root, **expired)
        self.current = 'a' * 64
        with self.assertRaises(LifecycleError):
            self.verify()
        self.assertEqual(self.cost(self.root)['head']['unknownHolds'], 100)
        self.current = 'b' * 64
        for target in ('report.json', 'publication.json'):
            with self.subTest(deadline_during=target):
                self._reset_publication()
                deadline = datetime.fromisoformat(self.admission['originalDeadlineUtc'])
                clock = [deadline - timedelta(seconds=1)]
                class Clock(datetime):
                    @classmethod
                    def now(cls, tz=None, _clock=clock):
                        return _clock[0]
                def write(path, raw, *, _target=target, _clock=clock, _deadline=deadline, **kwargs):
                    value = create_authority_bytes(path, raw, **kwargs)
                    if path.name == _target:
                        _clock[0] = _deadline + timedelta(seconds=1)
                    return value
                with patch.object(audit, 'datetime', Clock), \
                        patch.object(audit, 'create_authority_bytes', side_effect=write):
                    with self.assertRaisesRegex(LifecycleError, 'deadline elapsed'):
                        self.publish()
                self._assert_pending_refuses()

    def test_no_old_receipt_or_environment_fallback(self):
        self._input('legacy.json', b'{"status":"VERIFIED","nativeAllowed":true}')
        with patch.dict('os.environ', {'ALK_R11_ALLOW': '1', 'ALK_SKIP_AUDIT': '1'}):
            with self.assertRaises(LifecycleError):
                self.verify()
        with self.assertRaises(LifecycleError):
            audit.verify_area_report(self.root, review_id='../area1')
        self.assertFalse((self.base / 'report.json').exists())

    def integration_fixture(self):
        # AREA parsing/publication is covered by the six tests above. Here the
        # boundary is controlled to isolate frontier and actual test-file joins.
        scopes = ['scope' + str(i) for i in range(6)]
        self.authority['policy']['scopes'] = scopes
        self.authority['requiredSourcePaths'] = ['src/scoped.py']
        self.authority['caseMap'] = {'commands': {
            'C34': {'canonicalDigest': '4' * 64, 'caseIds': ['retained-attempt']},
            'C35': {'canonicalDigest': '5' * 64, 'caseIds': ['observer-timeout']}}}
        self._input('stdout.txt', b'case outcomes observed\n')
        self._input('stderr.txt', b'')
        def reference(name):
            p = self.base / name
            return {'path': p.relative_to(self.root).as_posix(), 'bytes': len(p.read_bytes()),
                    'sha256': audit._sha(p.read_bytes())}
        evidence = {'schemaVersion': 'alk-ordinary-audit-tests.v1',
                    'planDigest': self.authority['planDigest'], 'lockSha256': self.authority['lockSha256'],
                    'sourceSnapshotSha256': self.assignment['sourceSnapshotSha256'], 'commands': []}
        for key, command in self.authority['caseMap']['commands'].items():
            evidence['commands'].append({'id': key, 'commandDigest': command['canonicalDigest'], 'exitCode': 0,
                                         'cases': [{'id': case, 'status': 'PASS'} for case in command['caseIds']],
                                         'stdout': reference('stdout.txt'), 'stderr': reference('stderr.txt')})
        raw = canonical_bytes(evidence)
        create_authority_bytes(self.root / audit._STORE / 'integration1/test-evidence.json', raw,
                               root=self.root, private=True)
        reports = {}
        digests = []
        for i, scope in enumerate(scopes):
            report = self.publication()['report']
            report.update(reviewId='area' + str(i), roleId=scope, invocationId='invocation-' + scope)
            assignment = copy.deepcopy(self.assignment)
            assignment.update(reviewId=report['reviewId'], roleId=scope, scopeId=scope)
            digest = audit._sha(canonical_bytes(report))
            reports[report['reviewId']] = {'report': report, 'assignment': assignment,
                                         'reportSha256': digest, 'currentFinancialHeadSha256': self.current}
            digests.append(digest)
        report = self.publication()['report']
        report.update(reviewId='integration1', roleId='integration', roleKind='INTEGRATION',
                      invocationId='invocation-integration', priorReportDigests=digests,
                      parentFindingDispositions=[{'findingId': 'RB-OBSERVER-TIMEOUT-01',
                                                  'testEvidenceDigests': [audit._sha(raw)],
                                                  'disposition': 'CLOSED_WITH_REGRESSION_EVIDENCE'}])
        assignment = copy.deepcopy(self.assignment)
        assignment.update(reviewId='integration1', roleKind='INTEGRATION', scopeId='END_TO_END',
                          requiredTestEvidenceSha256=audit._sha(raw))
        reports['integration1'] = {'report': report, 'assignment': assignment,
                                  'reportSha256': audit._sha(canonical_bytes(report)),
                                  'currentFinancialHeadSha256': self.current}
        patch.object(audit, '_report', side_effect=lambda _reads, _auth, key: reports[key]).start()
        return reports, ['area' + str(i) for i in range(6)]

    def test_integration_frontier_complete(self):
        reports, ids = self.integration_fixture()
        result = audit.verify_integration_report(self.root, review_id='integration1', area_review_ids=ids)
        self.assertTrue(result['sourceReviewEligible'])
        self.assertFalse(result['nativeAllowed'])
        for bad in (ids[:-1], list(reversed(ids)), ids[:-1] + [ids[0]]):
            with self.subTest(frontier=bad), self.assertRaises(LifecycleError):
                audit.verify_integration_report(self.root, review_id='integration1', area_review_ids=bad)
        reports['area0']['report']['invocationId'] = 'invocation-integration'
        with self.assertRaises(LifecycleError):
            audit.verify_integration_report(self.root, review_id='integration1', area_review_ids=ids)

    def test_parent_failure_needs_new_closure(self):
        reports, ids = self.integration_fixture()
        integration = reports['integration1']['report']
        closure = copy.deepcopy(integration['parentFindingDispositions'])
        for invalid in ([], [{**closure[0], 'disposition': 'OPEN'}],
                        [{**closure[0], 'testEvidenceDigests': ['0' * 64]}]):
            integration['parentFindingDispositions'] = invalid
            with self.subTest(disposition=invalid), self.assertRaises(LifecycleError):
                audit.verify_integration_report(self.root, review_id='integration1', area_review_ids=ids)
        integration['parentFindingDispositions'] = closure
        (self.base / 'stdout.txt').write_bytes(b'replaced output')
        with self.assertRaises(LifecycleError):
            audit.verify_integration_report(self.root, review_id='integration1', area_review_ids=ids)

    def refuse_entry(self, entry):
        positional, keywords = [], {}
        for name, parameter in inspect.signature(entry).parameters.items():
            if parameter.default is not inspect.Parameter.empty:
                continue
            if parameter.kind == inspect.Parameter.POSITIONAL_ONLY:
                positional.append(object())
            elif parameter.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY):
                keywords[name] = object()
        with self.assertRaises(LifecycleError) as caught:
            result = entry(*positional, **keywords)
            if inspect.isgenerator(result):
                next(result)
        self.assertEqual(caught.exception.code, 'r11-experimental-disabled')

    def test_disabled_public_entries_no_side_effects(self):
        with patch.object(bootstrap_r11, '_write') as write, \
             patch.object(bootstrap_r11.subprocess, 'Popen') as start, \
             patch.object(bootstrap_r11, 'advance_coordinator_cost_head') as cost:
            for name in _DISABLED_ENTRIES:
                if not name.startswith('_'):
                    with self.subTest(entry=name):
                        self.refuse_entry(getattr(bootstrap_r11, name))
            write.assert_not_called()
            start.assert_not_called()
            cost.assert_not_called()

    def test_disabled_internal_workers_no_start(self):
        with patch.object(bootstrap_r11, '_write') as write, \
             patch.object(bootstrap_r11.subprocess, 'Popen') as start, \
             patch.object(bootstrap_r11, 'advance_coordinator_cost_head') as cost:
            for name in _DISABLED_ENTRIES:
                if name.startswith('_'):
                    with self.subTest(entry=name):
                        self.refuse_entry(getattr(bootstrap_r11, name))
            pipe = object.__new__(bootstrap_r11._R11AppServerPipe)
            for name in ('record', 'send_bootstrap', 'receive', 'bootstrap_reply'):
                with self.subTest(method=name):
                    self.refuse_entry(getattr(pipe, name))
            write.assert_not_called()
            start.assert_not_called()
            cost.assert_not_called()

    def fresh_fixture(self):
        from agent_lifecycle.adapter_sessions.codex_exact_prompt import ROUTE_ID, CLAIM
        patch.object(source_review_preparation_records, 'verify_attempt_reservation').start()
        # Real current-state/intent checks; existing attempt reservation tests
        # cover its separate durable authority. No native process is launched.
        intent = {key: 'fixture' for key in bootstrap_r11._IDENTITY}
        intent.update(schemaVersion='alk-codex-prelaunch-intent.v1', hostLaunchStarted=False,
                      runId='run1', taskId='WS216-01', attemptId='1', operationId='operation1',
                      routeId=ROUTE_ID, requestedClaim=CLAIM, plannedStdinBytes=4,
                      planDigest=self.authority['planDigest'], lockDigest=self.authority['lockSha256'],
                      requestSha256='6' * 64, finalPromptSha256='7' * 64, commandIdentityHash='8' * 64)
        binary = self.root / 'codex-fixture'
        binary.write_bytes(b'test executable identity only')
        intent['binarySha256'] = audit._sha(binary.read_bytes())
        intent_path = self.root / 'work/release-2-16/evidence/codex-exact-prompt/run1/WS216-01/1/prelaunch-intent.json'
        create_authority_bytes(intent_path, canonical_bytes(intent), root=self.root, private=True)
        state_path = self.root / 'state.json'
        state_path.write_bytes(canonical_bytes({'runId': 'run1', 'sourceRevision': 'fixture',
                                               'tasks': [{'id': 'WS216-01', 'attempt': 1, 'status': 'RUNNING'}]}))
        schema_path = self.root / audit._PLAN / 'ORDINARY-AUDIT-FRESH-GATE.schema.json'
        schema_path.parent.mkdir(parents=True)
        schema_path.write_bytes(canonical_bytes(_FRESH_SCHEMA))
        selection = {'schemaVersion': 'alk-ordinary-audit-selection.v1', 'reviewId': 'integration1',
                     'areaReviewIds': ['area' + str(i) for i in range(6)], 'reportSha256': '9' * 64}
        integration = {'reportSha256': '9' * 64, 'assignment': self.assignment,
                       'areaReportDigests': [audit._sha(str(i).encode()) for i in range(6)],
                       'observedInputDigests': {'src/scoped.py': audit._sha(self.source.read_bytes())},
                       'testEvidenceSha256': audit._sha(self.tests), 'currentFinancialHeadSha256': self.current}
        create_authority_bytes(self.root / audit._STORE / 'integration-selection.json', canonical_bytes(selection),
                               root=self.root, private=True)
        patch.object(audit, 'verify_integration_report', return_value=integration).start()
        self.fresh_integration = integration
        operation = audit.prepare_fresh_metadata_operation(self.root, intent_path=intent_path, state_path=state_path)
        self.current = 'c' * 64
        integration['currentFinancialHeadSha256'] = self.current
        source = {'status': 'ADMITTED_PREAPPROVED_BY_USER', 'modelRequestCount': 0,
                  'tokenCap': 2000, 'protectedCloseoutTokens': 500, 'freshMetadataOperation': operation}
        def metadata_cost(root, *, ancestor_head_sha256=None):
            result = self.cost(root, ancestor_head_sha256=ancestor_head_sha256)
            result['head'].update(previousHeadSha256='b' * 64, sourcePath='window/admission.json', sourceSha256='d' * 64)
            result['source'] = source
            return result
        audit.read_coordinator_cost_head.side_effect = metadata_cost
        self.real_admit_fresh = audit._admit_fresh_metadata
        patch.object(audit, '_admit_fresh_metadata').start()
        identity = {'status': 'PASS', 'resolvedPathSha256': audit._sha(str(binary).encode()),
                    'executableContentSha256': intent['binarySha256']}
        kwargs = {'intent_path': intent_path, 'state_path': state_path, 'plan_digest': intent['planDigest'],
                  'lock_sha256': intent['lockDigest'], 'selected_binary_sha256': intent['binarySha256'],
                  'profile': {'executable': str(binary)}, 'executable_identity': identity, 'process_env': {}}
        return kwargs, source, state_path, binary

    def consume(self, receipt, kwargs):
        audit.verify_fresh_task_gate(self.root, audit=receipt, **{key: kwargs[key] for key in
                                    ('intent_path', 'profile', 'executable_identity', 'process_env')})

    def test_current_task_authority_and_executable_join(self):
        kwargs, _, state_path, binary = self.fresh_fixture()
        # Exercise real request consumption and create-once metadata admission;
        # control only the cumulative ledger boundary, never use the live ledger.
        task = audit._r11_native_task(self.root, kwargs['intent_path'], kwargs['state_path'])
        key = canonical_digest({name: task['identity'][name] for name in ('runId', 'taskId', 'attemptId')})
        request = {'schemaVersion': 'alk-ordinary-fresh-admission-request.v1',
                   **{name: task['identity'][name] for name in ('runId', 'taskId', 'attemptId', 'operationId', 'planDigest')},
                   'lockSha256': kwargs['lock_sha256'], 'profileSha256': canonical_digest(kwargs['profile']),
                   'selectedBinarySha256': kwargs['selected_binary_sha256'], 'integrationReportSha256': '9' * 64,
                   'priorHeadSha256': 'b' * 64, 'sourcePath': 'work/release-2-16/enforcement-decision/r452-native-metadata/admission.json',
                   'tokenCap': 2000, 'protectedCloseoutTokens': 500, 'timeoutSeconds': 120}
        request_path = self.root / audit._STORE / 'tasks' / key / 'admission-request.json'
        create_authority_bytes(request_path, canonical_bytes(request), root=self.root, private=True)
        prior = {'headSha256': 'b' * 64, 'head': {'sourcePath': 'work/release-2-16/enforcement-decision/r451-closed/cost.json',
                                               'unknownHolds': 60100, 'exposureLowerBound': 60100}}
        self.fresh_integration['currentFinancialHeadSha256'] = 'b' * 64
        with patch.object(audit, 'read_coordinator_cost_head', return_value=prior), \
             patch.object(audit, '_r11_coordinator_root', return_value=self.root), \
             patch.object(audit, 'advance_coordinator_cost_head') as advance:
            mismatched = {**request, 'operationId': 'another-operation'}
            request_path.write_bytes(canonical_bytes(mismatched))
            with self.assertRaises(LifecycleError):
                self.real_admit_fresh(self.root, intent_path=kwargs['intent_path'], state_path=state_path,
                                      profile=kwargs['profile'])
            advance.assert_not_called()
            request_path.write_bytes(canonical_bytes(request))
            self.real_admit_fresh(self.root, intent_path=kwargs['intent_path'], state_path=state_path,
                                  profile=kwargs['profile'])
            advance.assert_called_once_with(self.root, source_path=request['sourcePath'])
            admitted = json.loads((self.root / request['sourcePath']).read_bytes())
            self.assertEqual(admitted['unknownHoldsIncludingThisWindow'], 62100)
            self.assertIsNone(admitted['actualTokens'])
            with self.assertRaises(FileExistsError):
                self.real_admit_fresh(self.root, intent_path=kwargs['intent_path'], state_path=state_path,
                                      profile=kwargs['profile'])
            self.assertEqual(advance.call_count, 1)
        self.fresh_integration['currentFinancialHeadSha256'] = 'c' * 64
        receipt = audit.require_fresh_task_gate(self.root, **kwargs)
        self.consume(receipt, kwargs)
        self.assertEqual(receipt['gate']['admission'], 'ALLOW_THIS_ATTEMPT')
        self.assertFalse(receipt['gate']['experimentalR11Allowed'])
        for field in ('plan_digest', 'lock_sha256', 'selected_binary_sha256'):
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                audit._fresh_basis(self.root, **{**kwargs, field: '0' * 64})
        state = state_path.read_bytes()
        changed = json.loads(state)
        changed['tasks'][0]['attempt'] = 2
        state_path.write_bytes(canonical_bytes(changed))
        with self.assertRaises(LifecycleError):
            self.consume(receipt, kwargs)
        state_path.write_bytes(state)
        with self.assertRaises(LifecycleError):
            self.consume(receipt, {**kwargs, 'profile': {**kwargs['profile'], 'model': 'changed'}})
        binary.write_bytes(b'different executable')
        with self.assertRaises(LifecycleError):
            self.consume(receipt, kwargs)

    def test_final_pre_spawn_race_denies(self):
        kwargs, source, _, _ = self.fresh_fixture()
        receipt = audit.require_fresh_task_gate(self.root, **kwargs)
        self.consume(receipt, kwargs)
        with self.assertRaises(FileExistsError):
            audit.require_fresh_task_gate(self.root, **kwargs)
        self.assertEqual(source['freshMetadataOperation'], receipt['context']['operation'])
        original = copy.deepcopy(source['freshMetadataOperation'])
        source['freshMetadataOperation']['deadlineMonotonicNs'] = time.monotonic_ns() - 1
        with self.assertRaises(LifecycleError):
            self.consume(receipt, kwargs)
        source['freshMetadataOperation'] = original
        original_source = self.source.read_bytes()
        self.source.write_bytes(b'mutation after independent integration read')
        with self.assertRaises(LifecycleError):
            self.consume(receipt, kwargs)
        self.source.write_bytes(original_source)
        self.current = 'b' * 64
        with self.assertRaises(LifecycleError):
            self.consume(receipt, kwargs)
        self.current = 'c' * 64
        saved = receipt['gate']['financialHeadSha256']
        receipt['gate']['financialHeadSha256'] = 'a' * 64
        with self.assertRaises(LifecycleError):
            self.consume(receipt, kwargs)
        receipt['gate']['financialHeadSha256'] = saved
        with patch.object(source_review_preparation_records, 'verify_attempt_reservation',
                          side_effect=LifecycleError('r11-result-attempt-reused', 'already consumed')):
            with self.assertRaises(LifecycleError):
                self.consume(receipt, kwargs)


# Exact schema fixture is appended below by the implementation preparation step.

_SCHEMAS = json.loads('{"report":{"type":"object","additionalProperties":false,"properties":{"schemaVersion":{"const":"alk-ordinary-audit-report.v1"},"assurance":{"const":"PROCEDURAL_SAME_ACCOUNT"},"reviewId":{"type":"string","minLength":1,"maxLength":256},"roleId":{"type":"string","minLength":1,"maxLength":256},"roleKind":{"enum":["AREA","INTEGRATION"]},"authorId":{"type":"string","minLength":1,"maxLength":256},"reviewerId":{"type":"string","minLength":1,"maxLength":256},"hostAdapter":{"type":"string","minLength":1,"maxLength":256},"invocationId":{"type":"string","minLength":1,"maxLength":256},"subjectSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"planDigest":{"type":"string","pattern":"^[0-9a-f]{64}$"},"lockSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"policySha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"scopeSnapshotSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"rawResultSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"publicationObservationSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"priorReportDigests":{"type":"array","maxItems":32,"uniqueItems":true,"items":{"type":"string","pattern":"^[0-9a-f]{64}$"}},"coveredFiles":{"type":"array","maxItems":4096,"uniqueItems":true,"items":{"type":"object","additionalProperties":false,"properties":{"path":{"type":"string","minLength":1,"maxLength":1024},"bytes":{"type":"integer","minimum":0,"maximum":8388608},"sha256":{"type":"string","pattern":"^[0-9a-f]{64}$"}},"required":["path","bytes","sha256"]}},"coveredObligations":{"type":"array","maxItems":4096,"uniqueItems":true,"items":{"type":"string","minLength":1,"maxLength":256}},"verdict":{"enum":["PASS","FAIL","INCOMPLETE"]},"findings":{"type":"array","maxItems":128,"items":{"type":"object","additionalProperties":false,"properties":{"id":{"type":"string","minLength":1,"maxLength":256},"severity":{"enum":["HIGH","MEDIUM","LOW"]},"disposition":{"enum":["OPEN","CLOSED","ACCEPTED_LOW"]},"sourcePath":{"type":"string","minLength":1,"maxLength":1024},"evidence":{"type":"string","maxLength":8192}},"required":["id","severity","disposition","sourcePath","evidence"]}},"reviewText":{"type":"string","maxLength":65536},"financialHeadSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"originalDeadlineUtc":{"type":"string","minLength":1,"maxLength":256},"actualTokens":{"anyOf":[{"type":"integer","minimum":0},{"type":"null"}]},"usageStatus":{"enum":["OBSERVED","UNAVAILABLE"]},"admissionSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"parentFindingDispositions":{"type":"array","maxItems":1,"items":{"type":"object","additionalProperties":false,"required":["findingId","testEvidenceDigests","disposition"],"properties":{"findingId":{"const":"RB-OBSERVER-TIMEOUT-01"},"testEvidenceDigests":{"type":"array","minItems":1,"maxItems":128,"uniqueItems":true,"items":{"type":"string","pattern":"^[0-9a-f]{64}$"}},"disposition":{"enum":["OPEN","CLOSED_WITH_REGRESSION_EVIDENCE"]}}}}},"required":["schemaVersion","assurance","reviewId","roleId","roleKind","authorId","reviewerId","hostAdapter","invocationId","subjectSha256","planDigest","lockSha256","policySha256","scopeSnapshotSha256","rawResultSha256","publicationObservationSha256","priorReportDigests","coveredFiles","coveredObligations","verdict","findings","reviewText","financialHeadSha256","originalDeadlineUtc","actualTokens","usageStatus","admissionSha256","parentFindingDispositions"],"$schema":"https://json-schema.org/draft/2020-12/schema","title":"R70 candidate ordinary audit report; semantic/procedural checks mandatory; not active authority"},"inputs":{"$schema":"https://json-schema.org/draft/2020-12/schema","$defs":{"observation":{"type":"object","additionalProperties":false,"required":["schemaVersion","adapter","sessionId","invocationId","reviewerId","subjectSha256","rawResultSha256","assignmentSha256"],"properties":{"schemaVersion":{"const":"alk-ordinary-audit-observation.v1"},"adapter":{"type":"string","minLength":1,"maxLength":256},"sessionId":{"type":"string","minLength":1,"maxLength":256},"invocationId":{"type":"string","minLength":1,"maxLength":256},"reviewerId":{"type":"string","minLength":1,"maxLength":256},"subjectSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"rawResultSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"assignmentSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"}}},"admission":{"type":"object","additionalProperties":false,"required":["schemaVersion","roleId","invocationId","priorHeadSha256","reservedHeadSha256","initialRequestSha256","initialRequestBytes","tokenCap","protectedCloseoutTokens","workTokens","outputReserveTokens","contextSafetyTokens","maxStarts","admittedAtUtc","originalDeadlineUtc"],"properties":{"schemaVersion":{"const":"alk-ordinary-audit-admission.v1"},"roleId":{"type":"string","minLength":1,"maxLength":256},"invocationId":{"type":"string","minLength":1,"maxLength":256},"priorHeadSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"reservedHeadSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"initialRequestSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"initialRequestBytes":{"type":"integer","minimum":1,"maximum":245760},"tokenCap":{"type":"integer","minimum":1,"maximum":360000},"protectedCloseoutTokens":{"type":"integer","minimum":1,"maximum":100000},"workTokens":{"type":"integer","minimum":1,"maximum":260000},"outputReserveTokens":{"const":8192},"contextSafetyTokens":{"const":16384},"maxStarts":{"const":1},"admittedAtUtc":{"type":"string","minLength":1,"maxLength":256},"originalDeadlineUtc":{"type":"string","minLength":1,"maxLength":256}}},"assignment":{"type":"object","additionalProperties":false,"required":["schemaVersion","reviewId","roleId","roleKind","scopeId","authorId","coordinatorId","reviewerId","planDigest","lockSha256","policySha256","sourceSnapshotSha256","files","obligations","requiredTestEvidenceSha256","predecessorReportDigests"],"properties":{"schemaVersion":{"const":"alk-ordinary-audit-assignment.v1"},"reviewId":{"type":"string","minLength":1,"maxLength":256},"roleId":{"type":"string","minLength":1,"maxLength":256},"roleKind":{"enum":["AREA","INTEGRATION"]},"scopeId":{"type":"string","minLength":1,"maxLength":256},"authorId":{"type":"string","minLength":1,"maxLength":256},"coordinatorId":{"type":"string","minLength":1,"maxLength":256},"reviewerId":{"type":"string","minLength":1,"maxLength":256},"planDigest":{"type":"string","pattern":"^[0-9a-f]{64}$"},"lockSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"policySha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"sourceSnapshotSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"files":{"type":"array","maxItems":4096,"uniqueItems":true,"items":{"type":"object","additionalProperties":false,"properties":{"path":{"type":"string","minLength":1,"maxLength":1024},"bytes":{"type":"integer","minimum":0,"maximum":8388608},"sha256":{"type":"string","pattern":"^[0-9a-f]{64}$"}},"required":["path","bytes","sha256"]}},"obligations":{"type":"array","maxItems":4096,"uniqueItems":true,"items":{"type":"string","minLength":1,"maxLength":256}},"requiredTestEvidenceSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"predecessorReportDigests":{"type":"array","maxItems":32,"uniqueItems":true,"items":{"type":"string","pattern":"^[0-9a-f]{64}$"}}}}},"oneOf":[{"$ref":"#/$defs/observation"},{"$ref":"#/$defs/admission"},{"$ref":"#/$defs/assignment"}]}}')

_DISABLED_ENTRIES = ['prepare_source_review_inventory', 'seal_source_review_request', 'reserve_source_review_cost', 'settle_source_review_cost', 'finalize_source_review_assignment', 'publish_source_review_cost_prefix', 'admit_source_review_funding', 'import_source_review_opening', 'capture_source_review_catalog', 'prepare_source_review_threads', 'collect_source_review_threads', 'prepare_source_review_worker', 'collect_source_review_producer', 'collect_source_review_shared', 'collect_source_review_qualified_evidence', 'publish_source_review_composite', 'read_source_review_composite', 'install_source_review_composite', 'require_source_review_fresh_gate', 'verify_source_review_fresh_gate', 'collect_source_review_evidence', 'collect_source_review_accounted_evidence', 'collect_source_review_host', 'collect_source_review_supervised_evidence', 'collect_source_review_origin_bound_evidence', '_run_fixed_source_review_worker', '_supervise_fixed_source_review_worker', '_source_review_worker_main', '_exchange_source_review_rpc', '_run_source_review_app_server_worker', '_supervise_source_review_worker', '_supervise_costed_source_review_worker', '_prepare_source_review_role_thread', '_run_source_review_thread_preparation', '_r11_fresh_exchange', '_r11_seal_live_dispatch', '_r11_write_role_request_files', '_r11_role_request_seal', '_R11AppServerPipe']

_FRESH_SCHEMA = json.loads('{"type":"object","additionalProperties":false,"properties":{"schemaVersion":{"const":"alk-ordinary-audit-fresh-gate.v1"},"assurance":{"const":"PROCEDURAL_SAME_ACCOUNT"},"runId":{"type":"string","minLength":1,"maxLength":256},"taskId":{"type":"string","minLength":1,"maxLength":256},"attemptId":{"type":"string","minLength":1,"maxLength":256},"operationId":{"type":"string","minLength":1,"maxLength":256},"intentSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"stateSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"planDigest":{"type":"string","pattern":"^[0-9a-f]{64}$"},"lockSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"policySha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"profileSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"selectedBinarySha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"sourceSnapshotSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"integrationReportSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"areaReportDigests":{"type":"array","minItems":6,"maxItems":32,"uniqueItems":true,"items":{"type":"string","pattern":"^[0-9a-f]{64}$"}},"testEvidenceSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"financialHeadSha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"deadlineUtc":{"type":"string","minLength":1,"maxLength":256},"admission":{"enum":["ALLOW_THIS_ATTEMPT","DENY"]},"protectedCloseAllowed":{"const":false},"fullHostContextQualified":{"const":false},"experimentalR11Allowed":{"const":false}},"required":["schemaVersion","assurance","runId","taskId","attemptId","operationId","intentSha256","stateSha256","planDigest","lockSha256","policySha256","profileSha256","selectedBinarySha256","sourceSnapshotSha256","integrationReportSha256","areaReportDigests","testEvidenceSha256","financialHeadSha256","deadlineUtc","admission","protectedCloseAllowed","fullHostContextQualified","experimentalR11Allowed"],"$schema":"https://json-schema.org/draft/2020-12/schema","title":"R70 candidate task-bound ordinary procedural gate; last-boundary rereads mandatory"}')

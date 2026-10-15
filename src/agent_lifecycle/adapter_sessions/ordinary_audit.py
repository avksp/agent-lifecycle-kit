"""Procedural independent audit records; no model or native dispatch authority.

The coordinator records a result it actually observed on the existing host.
These same-account records do not attest model-visible bytes or protect against
an actor able to rewrite the evidence store. Native admission remains separate.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import re
import stat
import time
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.authority_io import (
    create_authority_bytes, normalize_authority_path, open_authority_read,
    read_authority_bytes,
)
from agent_lifecycle.freeze.package_integrity import verify_plan_package_integrity
from agent_lifecycle.contracts.bounded_json import (
    load_bounded_json as _r11_json, matches_closed_schema as _r11_role_schema_matches,
)
from agent_lifecycle.adapter_sessions.bootstrap_r11 import (
    _r11_native_task, _r11_coordinator_root,
    advance_coordinator_cost_head, read_coordinator_cost_head,
)

_PLAN = 'tasks/release-2-16/'
_STORE = 'work/release-2-16/evidence/ordinary-audit/'
_REPORT_CAP = 1_048_576
_SOURCE_CAP = 8_388_608
_RESULT_FIELDS = (
    'reviewId', 'roleId', 'roleKind', 'subjectSha256', 'priorReportDigests',
    'coveredFiles', 'coveredObligations', 'verdict', 'findings', 'reviewText',
    'parentFindingDispositions',
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LifecycleError('ordinary-audit-denied', message)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _part(value: str) -> str:
    _require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', value) is not None,
             'review identity is not a portable single path component')
    return value


def _utc(value: str) -> datetime:
    _require(isinstance(value, str) and re.fullmatch(
        r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)', value) is not None,
        'timestamp must be an explicit UTC instant')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise LifecycleError('ordinary-audit-denied', 'invalid UTC instant') from exc


def _schema(value: Any, schema: dict[str, Any]) -> None:
    # The existing strict validator understands enum rather than const. Resolve
    # only that equivalent spelling; unknown schema keywords still fail closed.
    def constants(node: Any) -> Any:
        if isinstance(node, list):
            return [constants(item) for item in node]
        if isinstance(node, dict):
            return {('enum' if key == 'const' else key):
                    ([item] if key == 'const' else constants(item)) for key, item in node.items()}
        return node
    _require(_r11_role_schema_matches(value, constants(schema)), 'closed record schema differs')


class _Reads:
    """A bounded, stable read set, rechecked before publication or acceptance."""

    def __init__(self, root: Path):
        self.root = Path(root).absolute()
        self.records: dict[str, tuple[bytes, int, bool]] = {}
        self.absent: set[str] = set()

    def require_absent(self, relative: str) -> None:
        name = normalize_authority_path(relative)
        try:
            with open_authority_read(self.root / name, root=self.root):
                _require(False, 'publication is pending or uncertain')
        except FileNotFoundError:
            self.absent.add(name)

    def raw(self, relative: str, *, private: bool = False, cap: int = _REPORT_CAP) -> bytes:
        name = normalize_authority_path(relative)
        path = self.root / name
        try:
            if private:
                _require(name.startswith(_STORE), 'private input is outside the fixed audit store')
                with open_authority_read(path, root=self.root) as stream:
                    info = os.fstat(stream.fileno())
                    _require(stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= cap,
                             'private input must be bounded mode0600')
                    raw = stream.read(cap + 1)
                _require(len(raw) <= cap, 'private input exceeds its byte limit')
            else:
                raw = read_authority_bytes(path, root=self.root, max_bytes=cap)
        except OSError as exc:
            raise LifecycleError('ordinary-audit-denied', 'required input is unavailable') from exc
        previous = self.records.get(name)
        _require(previous is None or previous[0] == raw, 'input changed within the read interval')
        self.records[name] = (raw, cap, private)
        return raw

    def json(self, relative: str, *, private: bool = False) -> dict[str, Any]:
        return _r11_json(self.raw(relative, private=private), limit=_REPORT_CAP)

    def recheck(self) -> None:
        for name, (_, cap, private) in list(self.records.items()):
            self.raw(name, private=private, cap=cap)
        for name in list(self.absent):
            self.require_absent(name)


def _authority(reads: _Reads) -> dict[str, Any]:
    manifest = reads.json(_PLAN + 'plan.manifest.json')
    lock = reads.json(_PLAN + 'plan.lock.json')
    policy = reads.json(_PLAN + 'ORDINARY-AUDIT-POLICY.json')
    report_schema = reads.json(_PLAN + 'ORDINARY-AUDIT-REPORT.schema.json')
    inputs = reads.json(_PLAN + 'ORDINARY-AUDIT-INPUTS.schema.json')
    delivery = manifest.get('runtimePolicy', {}).get('reviewDelivery', {})
    _require(manifest.get('status') == 'FROZEN'
             and delivery.get('mode') == 'ORDINARY_INDEPENDENT_SOURCE_AUDIT'
             and policy.get('experimentalRoute') == 'DISABLED'
             and delivery.get('policyPath') == _PLAN + 'ORDINARY-AUDIT-POLICY.json'
             and delivery.get('policySha256') == _sha(reads.records[delivery['policyPath']][0]),
             'reviewed ordinary policy is not current')
    verify_plan_package_integrity(manifest, lock, repository_root=reads.root)
    return {'planDigest': canonical_digest(manifest),
            'lockSha256': _sha(reads.records[_PLAN + 'plan.lock.json'][0]),
            'policySha256': delivery['policySha256'], 'policy': policy,
            'reportSchema': report_schema, 'inputSchemas': inputs['$defs'],
            'caseMap': reads.json(_PLAN + 'ORDINARY-AUDIT-CASES.json'),
            'requiredSourcePaths': manifest['runtimePolicy']['preExecutionBootstrap']['leadTemporaryWritePaths']}


def _snapshot(reads: _Reads, rows: list[dict[str, Any]]) -> str:
    _require(0 < len(rows) <= 4096, 'source assignment is empty or oversized')
    paths = [row['path'] for row in rows]
    _require(paths == sorted(set(paths)), 'source paths must be unique and canonically ordered')
    for row in rows:
        raw = reads.raw(row['path'], cap=_SOURCE_CAP)
        _require(len(raw) == row['bytes'] and _sha(raw) == row['sha256'],
                 'assigned source or dependency changed')
    return canonical_digest(rows)


def _assigned(reads: _Reads, authority: dict[str, Any], review_id: str) -> tuple[dict[str, Any], bytes]:
    raw = reads.raw(_STORE + _part(review_id) + '/assignment.json', private=True)
    assignment = _r11_json(raw, limit=_REPORT_CAP)
    _schema(assignment, authority['inputSchemas']['assignment'])
    _require(assignment['reviewId'] == review_id, 'assignment belongs to another review')
    for key in ('planDigest', 'lockSha256', 'policySha256'):
        _require(assignment[key] == authority[key], 'assignment authority changed')
    _require(assignment['reviewerId'] not in (assignment['authorId'], assignment['coordinatorId']),
             'reviewer is an author or coordinator')
    _require(bool(assignment['obligations'])
             and assignment['sourceSnapshotSha256'] == _snapshot(reads, assignment['files']),
             'scope obligations or source snapshot differ')
    test_raw = reads.raw(_STORE + review_id + '/test-evidence.json', private=True)
    _r11_json(test_raw, limit=_REPORT_CAP)
    _require(_sha(test_raw) == assignment['requiredTestEvidenceSha256'], 'assigned test evidence changed')
    if assignment['roleKind'] == 'AREA':
        _require(assignment['scopeId'] in authority['policy']['scopes']
                 and not assignment['predecessorReportDigests'], 'invalid AREA assignment')
    else:
        _require(assignment['scopeId'] == 'END_TO_END'
                 and 6 <= len(assignment['predecessorReportDigests']) <= 32,
                 'integration requires its complete area frontier')
    return assignment, raw


def _admitted(reads: _Reads, authority: dict[str, Any], review_id: str,
              assignment: dict[str, Any], *, publishing: bool = False) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    raw = reads.raw(_STORE + _part(review_id) + '/admission.json', private=True)
    admission = _r11_json(raw, limit=_REPORT_CAP)
    _schema(admission, authority['inputSchemas']['admission'])
    start, deadline = _utc(admission['admittedAtUtc']), _utc(admission['originalDeadlineUtc'])
    _require(0 < (deadline - start).total_seconds() <= authority['policy']['limits']['perRoleSeconds']
             and (not publishing or start <= datetime.now(timezone.utc) <= deadline),
             'original review admission is outside its finite deadline')
    _require(admission['roleId'] == assignment['roleId']
             and admission['workTokens'] + admission['protectedCloseoutTokens'] <= admission['tokenCap']
             and admission['initialRequestBytes'] + admission['outputReserveTokens'] <= admission['workTokens'],
             'role or finite input/output/closeout allocation differs')
    # The exact initial request is immutable and stays with the admission.
    request = reads.raw(_STORE + review_id + '/request.txt', private=True, cap=245_760)
    _require(len(request) == admission['initialRequestBytes']
             and _sha(request) == admission['initialRequestSha256'], 'admitted initial request differs')
    prior = read_coordinator_cost_head(reads.root, ancestor_head_sha256=admission['priorHeadSha256'])
    reserved = read_coordinator_cost_head(reads.root, ancestor_head_sha256=admission['reservedHeadSha256'])
    _require(prior['headSha256'] == reserved['headSha256']
             and admission['reservedHeadSha256'] in prior['ancestryHeadSha256s']
             and admission['priorHeadSha256'] != admission['reservedHeadSha256'],
             'reservation does not descend from the admitted financial head')
    origin = prior['ancestor']['head']
    funded = reserved['ancestor']['head']
    _require(funded['previousHeadSha256'] == admission['priorHeadSha256']
             and funded['unknownHolds'] >= origin['unknownHolds'] + admission['tokenCap']
             and funded['exposureLowerBound'] >= origin['exposureLowerBound'] + admission['tokenCap'],
             'full unknown usage reservation is absent')
    return admission, raw, reserved


def _report(reads: _Reads, authority: dict[str, Any], review_id: str) -> dict[str, Any]:
    base = _STORE + _part(review_id) + '/'
    reads.require_absent(base + 'publication.pending.json')
    report_raw = reads.raw(base + 'report.json', private=True)
    report = _r11_json(report_raw, limit=_REPORT_CAP)
    _schema(report, authority['reportSchema'])
    assignment, assignment_raw = _assigned(reads, authority, review_id)
    admission, admission_raw, current = _admitted(reads, authority, review_id, assignment)
    reservation = reads.json(_STORE + 'reservations/' + admission['reservedHeadSha256'] + '.json', private=True)
    _require(reservation == {'reviewId': review_id, 'roleId': assignment['roleId'],
                             'invocationId': admission['invocationId'], 'admissionSha256': _sha(admission_raw)},
             'financial reservation belongs to another review invocation')
    publication = reads.json(base + 'publication.json', private=True)
    _require(set(publication) == {'schemaVersion', 'completedAtUtc', 'reportSha256', 'admissionSha256'}
             and publication['schemaVersion'] == 'alk-ordinary-audit-publication.v1'
             and publication['reportSha256'] == _sha(report_raw)
             and publication['admissionSha256'] == _sha(admission_raw)
             and _utc(admission['admittedAtUtc']) <= _utc(publication['completedAtUtc'])
             <= min(_utc(admission['originalDeadlineUtc']), datetime.now(timezone.utc)),
             'publication was not completed within original admission')
    observation_raw = reads.raw(base + 'observation.json', private=True)
    observation = _r11_json(observation_raw, limit=_REPORT_CAP)
    _schema(observation, authority['inputSchemas']['observation'])
    raw = reads.raw(base + 'raw-result.txt', private=True)
    body = _r11_json(raw, limit=_REPORT_CAP)
    _require(all(body.get(key) == report[key] for key in _RESULT_FIELDS),
             'normalized report changes the independently returned result')
    _require(report['reviewId'] == review_id and report['subjectSha256'] == canonical_digest(assignment)
             and observation['subjectSha256'] == report['subjectSha256']
             and observation['assignmentSha256'] == _sha(assignment_raw)
             and report['admissionSha256'] == _sha(admission_raw)
             and report['publicationObservationSha256'] == _sha(observation_raw)
             and report['rawResultSha256'] == observation['rawResultSha256'] == _sha(raw),
             'publication, admission or assignment join differs')
    for key in ('reviewId', 'roleId', 'roleKind', 'authorId', 'reviewerId',
                'planDigest', 'lockSha256', 'policySha256'):
        _require(report[key] == assignment[key], 'report assignment identity differs')
    _require(report['invocationId'] == admission['invocationId'] == observation['invocationId']
             and report['reviewerId'] == observation['reviewerId']
             and report['hostAdapter'] == observation['adapter']
             and report['originalDeadlineUtc'] == admission['originalDeadlineUtc']
             and report['scopeSnapshotSha256'] == assignment['sourceSnapshotSha256']
             and report['coveredFiles'] == assignment['files']
             and report['coveredObligations'] == assignment['obligations']
             and report['priorReportDigests'] == assignment['predecessorReportDigests'],
             'observed invocation, scope, frontier or original deadline differs')
    _require(report['usageStatus'] == 'UNAVAILABLE' and report['actualTokens'] is None
             or report['usageStatus'] == 'OBSERVED' and type(report['actualTokens']) is int
             and 0 <= report['actualTokens'] <= admission['workTokens'], 'usage is missing, inconsistent or over allocation')
    history = read_coordinator_cost_head(reads.root, ancestor_head_sha256=report['financialHeadSha256'])
    _require(history['headSha256'] == current['headSha256']
             and report['financialHeadSha256'] in current['ancestryHeadSha256s'],
             'report financial head does not descend from its reservation')
    _require(report['verdict'] == 'PASS' and bool(report['reviewText'].strip()), 'independent review did not pass')
    finding_ids = [finding['id'] for finding in report['findings']]
    _require(len(finding_ids) == len(set(finding_ids)), 'duplicate finding identity')
    for finding in report['findings']:
        _require(finding['sourcePath'] in {row['path'] for row in assignment['files']}
                 and bool(finding['evidence'].strip())
                 and (finding['disposition'] == 'CLOSED'
                      or finding['severity'] == 'LOW' and finding['disposition'] == 'ACCEPTED_LOW'),
                 'finding remains unresolved or lacks its assigned source/evidence')
    if report['roleKind'] == 'AREA':
        _require(not report['parentFindingDispositions'], 'AREA cannot close the parent integration finding')
    return {'report': report, 'assignment': assignment, 'reportSha256': _sha(report_raw),
            'currentFinancialHeadSha256': current['headSha256']}


def verify_area_report(project_root: Path, *, review_id: str) -> dict[str, Any]:
    """Reopen one immutable AREA result; return no native admission capability."""
    reads = _Reads(project_root)
    authority = _authority(reads)
    result = _report(reads, authority, review_id)
    _require(result['report']['roleKind'] == 'AREA', 'area verification cannot accept integration')
    reads.recheck()
    _require(read_coordinator_cost_head(reads.root)['headSha256'] == result['currentFinancialHeadSha256'],
             'financial head changed during verification')
    return {**result, 'nativeAllowed': False, 'assurance': 'PROCEDURAL_SAME_ACCOUNT',
            'snapshotRefs': [{'path': name, 'bytes': len(raw), 'sha256': _sha(raw)}
                             for name, (raw, _, _) in sorted(reads.records.items())]}


def _tests(reads: _Reads, authority: dict[str, Any], review_id: str,
           assignment: dict[str, Any]) -> str:
    """Reopen declared command/case evidence and its actual output bytes.

    The coordinator records observed test outcomes. As with ordinary review,
    this is a procedural receipt, not protected runner attestation. Aggregate
    unittest OK is insufficient: every exact planned case needs an outcome.
    """
    raw = reads.raw(_STORE + review_id + '/test-evidence.json', private=True)
    evidence = _r11_json(raw, limit=_REPORT_CAP)
    _require(set(evidence) == {'schemaVersion', 'planDigest', 'lockSha256',
                               'sourceSnapshotSha256', 'commands'}
             and evidence['schemaVersion'] == 'alk-ordinary-audit-tests.v1'
             and evidence['sourceSnapshotSha256'] == assignment['sourceSnapshotSha256']
             and _sha(raw) == assignment['requiredTestEvidenceSha256'], 'test receipt source binding differs')
    for key in ('planDigest', 'lockSha256'):
        _require(evidence[key] == authority[key], 'test authority is stale')
    _require(type(evidence['commands']) is list and len(evidence['commands']) == 2,
             'test evidence requires exactly current C34 and C35')
    commands = authority['caseMap']['commands']
    _require([row.get('id') for row in evidence['commands'] if isinstance(row, dict)] == ['C34', 'C35'],
             'test command order or membership differs')
    for observed in evidence['commands']:
        _require(set(observed) == {'id', 'commandDigest', 'exitCode', 'cases', 'stdout', 'stderr'},
                 'test command record is not closed')
        expected = commands[observed['id']]
        _require(observed['commandDigest'] == expected['canonicalDigest']
                 and type(observed['exitCode']) is int and observed['exitCode'] == 0
                 and type(observed['cases']) is list,
                 'test command did not complete successfully under current identity')
        _require([case.get('id') for case in observed['cases'] if isinstance(case, dict)] == expected['caseIds'],
                 'actual test cases differ from the exact planned roster')
        for case in observed['cases']:
            _require(set(case) == {'id', 'status'} and case['status'] == 'PASS',
                     'required test was skipped, failed or incomplete')
        for channel in ('stdout', 'stderr'):
            reference = observed[channel]
            _require(type(reference) is dict and set(reference) == {'path', 'bytes', 'sha256'}
                     and type(reference['bytes']) is int and 0 <= reference['bytes'] <= _REPORT_CAP,
                     'test output reference is not closed or bounded')
            output = reads.raw(reference['path'], private=True)
            _require(len(output) == reference['bytes'] and _sha(output) == reference['sha256'],
                     'actual test output changed')
    return _sha(raw)


def verify_integration_report(project_root: Path, *, review_id: str,
                              area_review_ids: list[str]) -> dict[str, Any]:
    """Check the exact independent AREA frontier and new parent-finding closure.

    This is reusable source-review evidence. A separate fresh task gate and all
    existing native checks are still necessary before any actual child start.
    """
    _part(review_id)
    _require(type(area_review_ids) is list and 6 <= len(area_review_ids) <= 32
             and all(isinstance(value, str) for value in area_review_ids)
             and len(set(area_review_ids)) == len(area_review_ids) and review_id not in area_review_ids,
             'integration area identities are incomplete or duplicated')
    reads = _Reads(project_root)
    authority = _authority(reads)
    areas = [_report(reads, authority, value) for value in area_review_ids]
    integration = _report(reads, authority, review_id)
    report, assignment = integration['report'], integration['assignment']
    _require(report['roleKind'] == 'INTEGRATION'
             and all(area['report']['roleKind'] == 'AREA' for area in areas)
             and {area['assignment']['scopeId'] for area in areas} == set(authority['policy']['scopes'])
             and report['priorReportDigests'] == [area['reportSha256'] for area in areas],
             'integration does not approve the exact complete area frontier')
    all_reports = [area['report'] for area in areas] + [report]
    _require(len({item['invocationId'] for item in all_reports}) == len(all_reports)
             and len({item['roleId'] for item in all_reports}) == len(all_reports),
             'integration or area invocation/role was reused')
    union: dict[str, dict[str, Any]] = {}
    for area in areas:
        _require(area['currentFinancialHeadSha256'] == integration['currentFinancialHeadSha256'],
                 'financial head changed across the review frontier')
        for row in area['assignment']['files']:
            _require(row['path'] not in union or union[row['path']] == row, 'area source assignments conflict')
            union[row['path']] = row
    _require(assignment['files'] == [union[name] for name in sorted(union)]
             and set(authority['requiredSourcePaths']) <= set(union),
             'integration omits assigned dependencies or required bootstrap implementation')
    test_digest = _tests(reads, authority, review_id, assignment)
    # Each AREA reopens its own assigned test inputs in _assigned. Do not demand
    # equality with the integration-wide digest: an unrelated regression update
    # must not discard an otherwise byte-identical area review.
    _require(report['parentFindingDispositions'] == [{
        'findingId': 'RB-OBSERVER-TIMEOUT-01', 'testEvidenceDigests': [test_digest],
        'disposition': 'CLOSED_WITH_REGRESSION_EVIDENCE'}],
        'immutable parent failure lacks new regression and independent closure')
    reads.recheck()
    _require(read_coordinator_cost_head(reads.root)['headSha256'] == integration['currentFinancialHeadSha256'],
             'financial head changed during integration verification')
    return {**integration, 'areaReportDigests': [area['reportSha256'] for area in areas],
            'testEvidenceSha256': test_digest, 'sourceReviewEligible': True,
            'observedInputDigests': {name: _sha(raw) for name, (raw, _, _) in reads.records.items()},
            'nativeAllowed': False, 'assurance': 'PROCEDURAL_SAME_ACCOUNT'}


def _selection(reads: _Reads) -> tuple[dict[str, Any], dict[str, Any]]:
    selection = reads.json(_STORE + 'integration-selection.json', private=True)
    _require(set(selection) == {'schemaVersion', 'reviewId', 'areaReviewIds', 'reportSha256'}
             and selection['schemaVersion'] == 'alk-ordinary-audit-selection.v1',
             'current independent integration selection is unavailable')
    result = verify_integration_report(reads.root, review_id=selection['reviewId'],
                                       area_review_ids=selection['areaReviewIds'])
    _require(selection['reportSha256'] == result['reportSha256'], 'selected integration report differs')
    return selection, result


def prepare_fresh_metadata_operation(project_root: Path, *, intent_path: Path,
                                     state_path: Path, timeout_seconds: int = 120) -> dict[str, Any]:
    """Build a bounded task-specific admission input; this grants no authority.

    The coordinator must persist this as freshMetadataOperation in a NEW finite
    admission.json and advance the existing cumulative ledger before requiring
    the gate. Reusing an ordinary review/work admission is not accepted.
    """
    _require(type(timeout_seconds) is int and 1 <= timeout_seconds <= 120, 'metadata timeout exceeds bound')
    start = datetime.now(timezone.utc)
    mono = time.monotonic_ns()
    reads = _Reads(project_root)
    task = _r11_native_task(reads.root, Path(intent_path).absolute(), Path(state_path).absolute())
    selection, result = _selection(reads)
    reads.recheck()
    operation = {'schemaVersion': 'alk-ordinary-fresh-operation.v1',
            'taskSha256': canonical_digest(task), 'selectionSha256': canonical_digest(selection),
            'integrationReportSha256': result['reportSha256'],
            'priorHeadSha256': result['currentFinancialHeadSha256'],
            'startedAtUtc': start.isoformat(), 'absoluteDeadlineUtc': (start + timedelta(seconds=timeout_seconds)).isoformat(),
            'startedMonotonicNs': mono, 'deadlineMonotonicNs': mono + timeout_seconds * 1_000_000_000,
            'timeoutSeconds': timeout_seconds, 'modelRequestsAuthorized': 0, 'retryAuthorized': False}
    _metadata_clock(operation)
    return operation


def _metadata(reads: _Reads, task: dict[str, Any], selection: dict[str, Any],
              result: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    head = read_coordinator_cost_head(reads.root)
    source = head['source']
    operation = source.get('freshMetadataOperation')
    _require(isinstance(operation, dict) and set(operation) == {
        'schemaVersion', 'taskSha256', 'selectionSha256', 'integrationReportSha256', 'priorHeadSha256',
        'startedAtUtc', 'absoluteDeadlineUtc', 'startedMonotonicNs', 'deadlineMonotonicNs',
        'timeoutSeconds', 'modelRequestsAuthorized', 'retryAuthorized'}, 'exact metadata admission is required')
    _require(source.get('status') == 'ADMITTED_PREAPPROVED_BY_USER'
             and Path(head['head']['sourcePath']).name == 'admission.json'
             and type(source.get('modelRequestCount')) is int and source['modelRequestCount'] == 0
             and type(source.get('tokenCap')) is int and 0 < source['tokenCap'] <= 360000
             and type(source.get('protectedCloseoutTokens')) is int
             and 0 < source['protectedCloseoutTokens'] < source['tokenCap']
             and operation['schemaVersion'] == 'alk-ordinary-fresh-operation.v1'
             and operation['taskSha256'] == canonical_digest(task)
             and operation['selectionSha256'] == canonical_digest(selection)
             and operation['integrationReportSha256'] == result['reportSha256']
             and head['headSha256'] == result['currentFinancialHeadSha256']
             and type(operation['modelRequestsAuthorized']) is int and operation['modelRequestsAuthorized'] == 0
             and operation['retryAuthorized'] is False, 'metadata admission identity or finite cost differs')
    prior = read_coordinator_cost_head(reads.root, ancestor_head_sha256=operation['priorHeadSha256'])
    _require(prior['headSha256'] == head['headSha256']
             and head['head']['previousHeadSha256'] == operation['priorHeadSha256']
             and head['head']['unknownHolds'] >= prior['ancestor']['head']['unknownHolds'] + source['tokenCap']
             and head['head']['exposureLowerBound'] >= prior['ancestor']['head']['exposureLowerBound'] + source['tokenCap'],
             'metadata is not a separately funded immediate ledger descendant')
    _metadata_clock(operation)
    return operation, head


def _metadata_clock(operation: dict[str, Any]) -> None:
    duration = operation['timeoutSeconds']
    start, end = _utc(operation['startedAtUtc']), _utc(operation['absoluteDeadlineUtc'])
    _require(type(duration) is int and 1 <= duration <= 120
             and end == start + timedelta(seconds=duration)
             and type(operation['startedMonotonicNs']) is int and operation['startedMonotonicNs'] > 0
             and type(operation['deadlineMonotonicNs']) is int
             and operation['deadlineMonotonicNs'] == operation['startedMonotonicNs'] + duration * 1_000_000_000
             and start <= datetime.now(timezone.utc) < end
             and operation['startedMonotonicNs'] <= time.monotonic_ns() < operation['deadlineMonotonicNs'],
             'original metadata clock expired or moved backwards; no renewal')


def _task_gate_key(identity: dict[str, Any], intent_path: Path) -> str:
    from agent_lifecycle.adapter_sessions.attempt_authority import _invocation_namespace
    operation = _invocation_namespace(identity['runId'], identity['taskId'], identity['attemptId'],
                                      identity['operationId'])
    keys = ('runId', 'taskId', 'attemptId')
    if tuple(Path(intent_path).parent.parts[-len(operation.parts):]) == operation.parts:
        keys += ('operationId',)
    return canonical_digest({name: identity[name] for name in keys})


def _admit_fresh_metadata(project_root: Path, *, intent_path: Path, state_path: Path,
                          profile: dict[str, Any]) -> None:
    """Consume a previously authorized request after the actual intent exists.

    The request fixes the next coordinator window, task and maximum allocation
    before launch. The original clocks and actual intent digest are filled once
    here. No default budget, automatic retry, previous-window close or refund.
    """
    reads = _Reads(project_root)
    task = _r11_native_task(reads.root, Path(intent_path).absolute(), Path(state_path).absolute())
    identity = task['identity']
    key = _task_gate_key(identity, intent_path)
    request = reads.json(_STORE + 'tasks/' + key + '/admission-request.json', private=True)
    _require(set(request) == {'schemaVersion', 'runId', 'taskId', 'attemptId', 'operationId', 'planDigest',
                              'lockSha256', 'profileSha256', 'selectedBinarySha256', 'integrationReportSha256',
                              'priorHeadSha256', 'sourcePath', 'tokenCap', 'protectedCloseoutTokens', 'timeoutSeconds'}
             and request['schemaVersion'] == 'alk-ordinary-fresh-admission-request.v1',
             'preauthorized finite task admission request is missing')
    for name in ('runId', 'taskId', 'attemptId', 'operationId', 'planDigest'):
        _require(request[name] == identity[name], 'admission request belongs to another task/operation')
    _require(request['lockSha256'] == identity['lockDigest']
             and request['profileSha256'] == canonical_digest(profile)
             and request['selectedBinarySha256'] == identity['binarySha256']
             and type(request['tokenCap']) is int and 1 < request['tokenCap'] <= 300000
             and type(request['protectedCloseoutTokens']) is int
             and 0 < request['protectedCloseoutTokens'] < request['tokenCap'],
             'preauthorized task inputs or allocation differ')
    operation = prepare_fresh_metadata_operation(reads.root, intent_path=intent_path, state_path=state_path,
                                                 timeout_seconds=request['timeoutSeconds'])
    _require(operation['priorHeadSha256'] == request['priorHeadSha256']
             and operation['integrationReportSha256'] == request['integrationReportSha256'],
             'preauthorized financial head or independent report changed')
    prior = read_coordinator_cost_head(reads.root)
    source_path = normalize_authority_path(request['sourcePath'])
    _require(re.fullmatch(r'work/release-2-16/enforcement-decision/r[1-9][0-9]*-[a-z0-9-]+/admission\.json', source_path)
             is not None and Path(prior['head']['sourcePath']).name == 'cost.json'
             and prior['headSha256'] == request['priorHeadSha256']
             and int(Path(source_path).parent.name.split('-', 1)[0][1:])
             > int(Path(prior['head']['sourcePath']).parent.name.split('-', 1)[0][1:]),
             'metadata requires a new explicitly named window after a closed predecessor')
    admission = {'status': 'ADMITTED_PREAPPROVED_BY_USER', 'tokenCap': request['tokenCap'],
                 'protectedCloseoutTokens': request['protectedCloseoutTokens'],
                 'priorUnknownHolds': prior['head']['unknownHolds'],
                 'unknownHoldsIncludingThisWindow': prior['head']['unknownHolds'] + request['tokenCap'],
                 'priorLedgerLowerBound': prior['head']['exposureLowerBound'],
                 'ledgerLowerBoundIncludingThisHold': prior['head']['exposureLowerBound'] + request['tokenCap'],
                 'actualInputTokens': None, 'actualTokens': None, 'costStatus': 'UNAVAILABLE',
                 'priorBudgetResumed': False, 'priorUnknownHoldsReleased': 0, 'modelRequestCount': 0,
                 'freshMetadataOperation': operation, 'admissionRequestSha256': canonical_digest(request)}
    reads.recheck()
    _metadata_clock(operation)
    primary = _r11_coordinator_root(reads.root)
    create_authority_bytes(primary / source_path, canonical_bytes(admission), root=primary, private=True)
    advance_coordinator_cost_head(reads.root, source_path=source_path)


def _fresh_basis(project_root: Path, *, intent_path: Path, state_path: Path,
                 plan_digest: str, lock_sha256: str, selected_binary_sha256: str,
                 profile: dict[str, Any], executable_identity: dict[str, Any],
                 process_env: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    from agent_lifecycle.adapter_sessions.codex_input_diagnostics import _selected_binary_path
    reads = _Reads(project_root)
    authority = _authority(reads)
    task = _r11_native_task(reads.root, Path(intent_path).absolute(), Path(state_path).absolute())
    identity = task['identity']
    _require(identity['planDigest'] == plan_digest == authority['planDigest']
             and identity['lockDigest'] == lock_sha256 == authority['lockSha256']
             and identity['binarySha256'] == selected_binary_sha256
             == executable_identity.get('executableContentSha256'), 'current task authority or binary differs')
    binary = _selected_binary_path(str(profile.get('executable', '')), executable_identity, process_env)
    selection, result = _selection(reads)
    operation, head = _metadata(reads, task, selection, result)
    # Carry the independently reopened report/source/test read set into the
    # final boundary. A mutation after integration verification must not hide
    # behind the unchanged report digest or a cached successful callback.
    footprint = result.get('observedInputDigests')
    _require(isinstance(footprint, dict) and bool(footprint), 'integration lacks its actual read set')
    for path, digest in footprint.items():
        _require(_sha(reads.raw(path, private=path.startswith(_STORE),
                               cap=_REPORT_CAP if path.startswith(_STORE) else _SOURCE_CAP)) == digest,
                 'source, report or regression input changed after integration verification')
    receipt = {'schemaVersion': 'alk-ordinary-audit-fresh-gate.v1', 'assurance': 'PROCEDURAL_SAME_ACCOUNT',
               **{key: identity[key] for key in ('runId', 'taskId', 'attemptId', 'operationId')},
               'intentSha256': task['intentSha256'], 'stateSha256': task['stateSha256'],
               **{key: authority[key] for key in ('planDigest', 'lockSha256', 'policySha256')},
               'profileSha256': canonical_digest(profile), 'selectedBinarySha256': selected_binary_sha256,
               'sourceSnapshotSha256': result['assignment']['sourceSnapshotSha256'],
               'integrationReportSha256': result['reportSha256'], 'areaReportDigests': result['areaReportDigests'],
               'testEvidenceSha256': result['testEvidenceSha256'], 'financialHeadSha256': head['headSha256'],
               'deadlineUtc': operation['absoluteDeadlineUtc'], 'admission': 'ALLOW_THIS_ATTEMPT',
               'protectedCloseAllowed': False, 'fullHostContextQualified': False, 'experimentalR11Allowed': False}
    _schema(receipt, reads.json(_PLAN + 'ORDINARY-AUDIT-FRESH-GATE.schema.json'))
    reads.recheck()
    _require(_r11_native_task(reads.root, Path(intent_path).absolute(), Path(state_path).absolute()) == task
             and read_coordinator_cost_head(reads.root)['headSha256'] == head['headSha256']
             and _selected_binary_path(str(profile.get('executable', '')), executable_identity, process_env) == binary,
             'task, binary or financial inputs changed during fresh verification')
    _metadata_clock(operation)
    return receipt, {'statePath': task['statePath'], 'intentPath': task['intentPath'],
                     'operation': operation, 'metadataAdmissionSourceSha256': head['head']['sourceSha256']}


def require_fresh_task_gate(project_root: Path, **kwargs: Any) -> dict[str, Any]:
    """Publish one current task receipt; a prior gate cannot be refreshed/reused."""
    _admit_fresh_metadata(project_root, intent_path=kwargs['intent_path'], state_path=kwargs['state_path'],
                          profile=kwargs['profile'])
    receipt, context = _fresh_basis(project_root, **kwargs)
    root = Path(project_root).absolute()
    key = _task_gate_key(receipt, kwargs['intent_path'])
    directory = root / _STORE / 'tasks' / key
    create_authority_bytes(directory / 'context.json', canonical_bytes(context), root=root, private=True)
    _metadata_clock(context['operation'])
    create_authority_bytes(directory / 'fresh-gate.json', canonical_bytes(receipt), root=root, private=True)
    return {'schemaVersion': 'alk-ordinary-task-audit.v1', 'auditSha256': canonical_digest(receipt),
            'gate': receipt, 'context': context}


def verify_fresh_task_gate(project_root: Path, *, audit: dict[str, Any], intent_path: Path,
                           profile: dict[str, Any], executable_identity: dict[str, Any],
                           process_env: dict[str, str]) -> None:
    """Last common pre-spawn reread; never call this after claiming the attempt."""
    _require(isinstance(audit, dict) and set(audit) == {'schemaVersion', 'auditSha256', 'gate', 'context'}
             and audit['schemaVersion'] == 'alk-ordinary-task-audit.v1', 'ordinary task receipt required')
    reads = _Reads(project_root)
    gate, context = audit['gate'], audit['context']
    _require(isinstance(gate, dict) and isinstance(context, dict), 'gate/context must be objects')
    _schema(gate, reads.json(_PLAN + 'ORDINARY-AUDIT-FRESH-GATE.schema.json'))
    _require(set(context) == {'statePath', 'intentPath', 'operation', 'metadataAdmissionSourceSha256'},
             'fresh context fields differ')
    _require(Path(intent_path).absolute() == reads.root / normalize_authority_path(context['intentPath'])
             and audit['auditSha256'] == canonical_digest(gate), 'receipt belongs to another reserved attempt')
    key = _task_gate_key(gate, intent_path)
    base = _STORE + 'tasks/' + key + '/'
    _require(reads.json(base + 'fresh-gate.json', private=True) == gate
             and reads.json(base + 'context.json', private=True) == context, 'persisted task receipt changed')
    actual, actual_context = _fresh_basis(reads.root, intent_path=intent_path,
        state_path=reads.root / normalize_authority_path(context['statePath']), plan_digest=gate['planDigest'],
        lock_sha256=gate['lockSha256'], selected_binary_sha256=gate['selectedBinarySha256'],
        profile=profile, executable_identity=executable_identity, process_env=process_env)
    _require(actual == gate and actual_context == context, 'current gate inputs differ; no native start')
    reads.recheck()
    _metadata_clock(context['operation'])


def publish_observed_result(project_root: Path, *, review_id: str, report: dict[str, Any],
                            raw_result: bytes, observation: dict[str, Any],
                            author_session_id: str, coordinator_session_id: str) -> dict[str, Any]:
    """Persist an actually observed result with a sticky pending marker.

    Only the coordinator handling the real host result should call this. This
    function checks procedural joins; its arguments are not host attestation.
    Failed/incomplete results are retained but cannot pass verify_area_report.
    """
    reads = _Reads(project_root)
    authority = _authority(reads)
    assignment, assignment_raw = _assigned(reads, authority, review_id)
    admission, admission_raw, current = _admitted(reads, authority, review_id, assignment, publishing=True)
    _schema(observation, authority['inputSchemas']['observation'])
    _schema(report, authority['reportSchema'])
    _require(isinstance(author_session_id, str) and bool(author_session_id)
             and isinstance(coordinator_session_id, str) and bool(coordinator_session_id)
             and observation['sessionId'] not in (author_session_id, coordinator_session_id),
             'reviewer session is an author or coordinator session')
    body = _r11_json(raw_result, limit=_REPORT_CAP)
    _require(all(body.get(key) == report[key] for key in _RESULT_FIELDS), 'returned result differs from report')
    _require(observation['reviewerId'] == assignment['reviewerId'] == report['reviewerId']
             and observation['invocationId'] == admission['invocationId'] == report['invocationId']
             and observation['subjectSha256'] == canonical_digest(assignment) == report['subjectSha256']
             and observation['assignmentSha256'] == _sha(assignment_raw)
             and observation['rawResultSha256'] == _sha(raw_result) == report['rawResultSha256']
             and report['publicationObservationSha256'] == _sha(canonical_bytes(observation))
             and report['admissionSha256'] == _sha(admission_raw)
             and report['financialHeadSha256'] == current['headSha256'], 'observed publication joins differ')
    reads.recheck()
    _require(read_coordinator_cost_head(reads.root)['headSha256'] == current['headSha256'],
             'financial head changed before publication')
    base = reads.root / _STORE / _part(review_id)
    _require(_utc(admission['admittedAtUtc']) <= datetime.now(timezone.utc)
             <= _utc(admission['originalDeadlineUtc']),
             'original review deadline elapsed before publication')
    reservation = {'reviewId': review_id, 'roleId': assignment['roleId'],
                   'invocationId': admission['invocationId'], 'admissionSha256': _sha(admission_raw)}
    for name in ('report.json', 'publication.json'):
        try:
            with open_authority_read(base / name, root=reads.root):
                pass
        except FileNotFoundError:
            continue
        raise FileExistsError('publication output already exists')
    pending = base / 'publication.pending.json'
    # One finite coordinator admission funds at most one review invocation.
    # This conservative route never silently splits or reuses an outer hold.
    # Claim permanently before creating the transient marker: a duplicate
    # publisher must never recreate a winner's already removed marker.
    create_authority_bytes(reads.root / _STORE / 'reservations' / (admission['reservedHeadSha256'] + '.json'),
                           canonical_bytes(reservation), root=reads.root, private=True)
    create_authority_bytes(pending, canonical_bytes(reservation), root=reads.root, private=True)
    # Partial publication remains unusable and is preserved for diagnosis.
    for name, raw in [('raw-result.txt', raw_result), ('observation.json', canonical_bytes(observation)),
                      ('report.json', canonical_bytes(report))]:
        _require(len(raw) <= _REPORT_CAP, 'published artifact exceeds byte limit')
        create_authority_bytes(base / name, raw, root=reads.root, private=True)
    # Timestamp the durable payload, not the beginning of its writes. A second
    # clock check below includes the publication record's own synchronization.
    completed = datetime.now(timezone.utc)
    _require(_utc(admission['admittedAtUtc']) <= completed <= _utc(admission['originalDeadlineUtc']),
             'original review deadline elapsed during publication')
    publication = {'schemaVersion': 'alk-ordinary-audit-publication.v1',
                   'completedAtUtc': completed.isoformat(),
                   'reportSha256': _sha(canonical_bytes(report)), 'admissionSha256': _sha(admission_raw)}
    create_authority_bytes(base / 'publication.json', canonical_bytes(publication),
                           root=reads.root, private=True)
    reads.recheck()
    _require(read_coordinator_cost_head(reads.root)['headSha256'] == current['headSha256'],
             'financial head changed during publication')
    _require(completed <= datetime.now(timezone.utc) <= _utc(admission['originalDeadlineUtc']),
             'original review deadline elapsed before publication commit')
    pending.unlink()
    # As with retained attempt terminals, marker removal makes no crash-durable
    # claim. A reappearing marker conservatively refuses; no fallible sync is
    # performed after removal that could turn a failed commit into acceptance.
    return {'reviewId': review_id, 'reportSha256': _sha(canonical_bytes(report)),
            'verdict': report['verdict'], 'nativeAllowed': False, 'assurance': 'PROCEDURAL_SAME_ACCOUNT'}


__all__ = ['publish_observed_result', 'verify_area_report', 'verify_integration_report',
           'prepare_fresh_metadata_operation', 'require_fresh_task_gate', 'verify_fresh_task_gate']

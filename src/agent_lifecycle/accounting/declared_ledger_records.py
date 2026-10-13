"""Closed decoders for the preserved declared accounting wire formats. No host or file access."""

from __future__ import annotations

from datetime import datetime
import hashlib
import re
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.bounded_json import (
    load_bounded_json as _r11_json, matches_closed_schema as _r11_role_schema_matches,
)


_R11_ROLE_CONTRACT_SHA256 = '03d77c4fd3fcfcd3fd316d48ff119e20549ad42d8d9a325e7983bb46ab9e1247'


def _r11_role_identity(*, authority: dict[str, Any], base_raw: bytes,
                       inventory_raw: bytes, funding_raw: bytes) -> dict[str, Any]:
    """Check the immutable, acyclic preparation DAG; never admit or spend funds.

    Fresh authority and independently rebuilt source/support leaves are required
    by the caller. A correctly shaped funded schedule is not durable admission,
    ledger ancestry, hold-reuse evidence, or permission to dispatch a model.
    """
    schemas = authority['schemas']
    base, inventory, funding = (_r11_json(raw, limit=131_072)
                                for raw in (base_raw, inventory_raw, funding_raw))
    for name, value in (('base', base), ('roleInventory', inventory), ('fundingBatch', funding)):
        _require(_r11_role_schema_matches(value, schemas[name]),
                 'r11-role-identity', 'immutable role ancestor has an invalid closed shape')
    _require(base['planLockSha256'] == authority['lockSha256']
             and base['limits'] == authority['contract']['limits']
             and inventory['baseSha256'] == funding['baseSha256'] == canonical_digest(base)
             and funding['roleInventorySha256'] == canonical_digest(inventory)
             and base['reviewId'] == inventory['reviewId'] == funding['reviewId'],
             'r11-role-identity', 'immutable ancestry, installed lock or review identity differs')
    roles = inventory['roles']
    ids = ['shared-01'] + [f'source-{number:02d}' for number in range(1, len(roles))]
    empty = canonical_digest([])
    _require([role['roleId'] for role in roles] == ids
             and [role['roleKind'] for role in roles] == ['SHARED'] + ['SOURCE'] * (len(roles) - 1)
             and len({role['operationId'] for role in roles}) == len(roles)
             and roles[0]['exposureSha256'] == base['sharedExposureSha256']
             and all(roles[0][name] == empty for name in (
                 'sourceRangeSha256', 'callProjectionSha256', 'staticPairAssignmentSha256'))
             and not roles[0]['requiredIntegrationScopes'],
             'r11-role-identity', 'roles are not exact, ordered, uniquely operated or correctly exposed')
    scopes = [scope for role in roles for scope in role['requiredIntegrationScopes']]
    _require(sorted(scopes) == sorted(authority['contract']['roles']['integrationPrimaryScopes'])
             and all(role['requiredIntegrationScopes'] == sorted(role['requiredIntegrationScopes']) for role in roles),
             'r11-role-identity', 'both integration scopes need one primary each')
    limits = base['limits']
    count = len(roles)
    reused = funding['reusedFirstHold']
    credit = 0 if reused is None else reused['tokenCap']
    _require(reused is None or (reused['operationId'] == roles[0]['operationId']
             and reused['priorHeadSha256'] == funding['priorHeadSha256']),
             'r11-role-funding', 'reused hold is not bound to the preassigned shared operation/head')
    start = datetime.fromisoformat(funding['admittedAtUtc'].replace('Z', '+00:00'))
    end = datetime.fromisoformat(funding['absoluteDeadlineUtc'].replace('Z', '+00:00'))
    _require([slot['roleId'] for slot in funding['slots']] == ids
             and funding['tokenCap'] == count * limits['perRoleTokenCap']
             and funding['protectedCloseoutTokens'] == count * limits['perRoleProtectedCloseoutTokens']
             and funding['priorExposureLowerBound'] >= funding['priorUnknownHolds'] >= credit
             and funding['admittedUnknownHolds'] == funding['priorUnknownHolds'] + funding['tokenCap'] - credit
             and funding['admittedExposureLowerBound'] == funding['priorExposureLowerBound'] + funding['tokenCap'] - credit
             and 0 < (end - start).total_seconds() <= limits['batchMaxElapsedSeconds'],
             'r11-role-funding', 'funding schedule loses holds, slots, reserve or original deadline')
    return {'base': base, 'inventory': inventory, 'funding': funding,
            'baseSha256': canonical_digest(base), 'roleInventorySha256': canonical_digest(inventory),
            'fundingBatchSha256': canonical_digest(funding), 'fundingAdmitted': False,
            'firstNativeBootstrapEligible': False}


def _r11_role_subject(identity: dict[str, Any], role_id: str,
                      shared_evidence_sha256: str | None, schemas: dict[str, Any]) -> dict[str, Any]:
    """Build a subject from checked ancestors, never from completed-assignment claims."""
    matches = [(i, role) for i, role in enumerate(identity['inventory']['roles']) if role['roleId'] == role_id]
    _require(len(matches) == 1, 'r11-role-subject', 'role is absent from the immutable inventory')
    index, role = matches[0]
    _require((role['roleKind'] == 'SHARED') == (shared_evidence_sha256 is None),
             'r11-role-subject', 'shared receipt nullability differs from role kind')
    subject = {'schemaVersion': 'alk-r11-role-subject.v1', 'reviewId': identity['base']['reviewId'],
               **{key: identity[key] for key in ('baseSha256', 'roleInventorySha256', 'fundingBatchSha256')},
               'slotSha256': canonical_digest(identity['funding']['slots'][index]),
               **{key: value for key, value in role.items() if key != 'operationId'},
               'sharedEvidenceSha256': shared_evidence_sha256, 'phase': 'PRE_WS01', 'rb11RuntimeStatus': 'NOT_RUN'}
    _require(_r11_role_schema_matches(subject, schemas['roleSubject']),
             'r11-role-subject', 'constructed subject differs from the reviewed shape')
    return subject


def _r11_transport_binding(binding: dict[str, Any]) -> None:
    _require(isinstance(binding, dict) and set(binding) == {
                 'operationId', 'shardId', 'threadId', 'binarySha256', 'transportSourceSha256'}
             and all(isinstance(value, str) and 0 < len(value) <= 256 for value in binding.values())
             and re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,63}', binding['shardId']) is not None
             and all(re.fullmatch('[0-9a-f]{64}', binding[key]) is not None
                     for key in ('binarySha256', 'transportSourceSha256')),
             'r11-transport-binding', 'complete bounded transport identity is required')


def _r11_cost_reservation(basis: dict[str, Any], index: int,
                           previous_settlement: bytes | None, *,
                           dispatch: dict[str, Any] | None = None,
                           prefix: dict[str, str] | None = None) -> dict[str, Any]:
    _require('identity' in basis, 'r11-v5-runtime-retired', 'reservation requires the immutable v6 role basis')
    identity = basis['identity']; funding = identity['funding']
    roles = identity['inventory']['roles']
    _require(type(index) is int and 0 <= index < len(roles) and isinstance(dispatch, dict)
             and set(dispatch) == {'binding', 'requestSha256', 'sharedEvidenceSha256',
                                   'reservedAtUtc', 'absoluteDeadlineUtc'}
             and isinstance(prefix, dict) and bool(prefix),
             'r11-role-cost-reservation', 'one actual dispatch and immutable preceding prefix required')
    role, slot = roles[index], funding['slots'][index]
    binding = dispatch['binding']; _r11_transport_binding(binding)
    _require(binding['operationId'] == role['operationId'] and binding['shardId'] == role['roleId']
             and binding['threadId'] != 'U' * 256
             and all(len(value.encode('utf-8')) <= 256 for value in binding.values())
             and _r11_role_schema_matches(dispatch['requestSha256'], {'type': 'string', 'pattern': '^[0-9a-f]{64}$'})
             and all(_r11_role_schema_matches(dispatch[key], {'type': 'string', 'format': 'date-time', 'maxLength': 40})
                     for key in ('reservedAtUtc', 'absoluteDeadlineUtc')),
             'r11-role-cost-reservation', 'role operation, actual thread, request digest or deadline is invalid')
    subject = _r11_role_subject(identity, role['roleId'], dispatch['sharedEvidenceSha256'], basis['schemas'])
    times = [datetime.fromisoformat(value.replace('Z', '+00:00')) for value in (
        funding['admittedAtUtc'], dispatch['reservedAtUtc'], dispatch['absoluteDeadlineUtc'], funding['absoluteDeadlineUtc'])]
    _require(times[0] <= times[1] < times[2] <= times[3]
             and (times[2] - times[1]).total_seconds() <= slot['maxElapsedSeconds'],
             'r11-role-cost-deadline', 'role resets or exceeds its original batch/role deadline')
    return {'schemaVersion': 'alk-r11-role-cost-reservation.v1', 'reviewId': funding['reviewId'],
            'roleId': role['roleId'], **dispatch,
            **{key: identity[key] for key in ('baseSha256', 'roleInventorySha256', 'fundingBatchSha256')},
            'subjectSha256': canonical_digest(subject), 'slotSha256': canonical_digest(slot),
            'previousCostPrefixSha256': canonical_digest(prefix),
            'previousSettlementSha256': hashlib.sha256(previous_settlement).hexdigest() if previous_settlement is not None else None,
            'tokenCap': slot['tokenCap'], 'protectedCloseoutTokens': slot['protectedCloseoutTokens'],
            'workTokens': slot['workTokens'], 'holdIncrement': 0,
            'heldUnknownTokens': funding['admittedUnknownHolds'],
            'accountedExposureLowerBound': funding['admittedExposureLowerBound'],
            'costStatus': 'UNAVAILABLE', 'actualModelTokens': None, 'retryAuthorized': False}


_R11_COORDINATOR_BASE = 'work/release-2-16/enforcement-decision'


def _r11_role_funding_record(value: dict[str, Any], relative: str) -> dict[str, Any]:
    """Verify a self-contained, pinned accounting archive; not live plan/host proof."""
    strings = ('roleContractRaw', 'baseRaw', 'inventoryRaw', 'fundingRaw', 'coordinatorCursor')
    _require(all(isinstance(value.get(key), str) for key in strings)
             and isinstance(value.get('roleSchemasRaw'), dict)
             and set(value['roleSchemasRaw']) == {'base', 'roleInventory', 'fundingBatch'}
             and all(isinstance(raw, str) for raw in value['roleSchemasRaw'].values()),
             'r11-role-funding-record', 'exact raw funding/authority archive required')
    try:
        raw = {key: value[key].encode('utf-8') for key in strings}
        for encoded in value['roleSchemasRaw'].values():
            encoded.encode('utf-8')
    except UnicodeError as exc:
        raise LifecycleError('r11-role-funding-record', 'funding archive is not valid UTF-8') from exc
    _require(hashlib.sha256(raw['roleContractRaw']).hexdigest() == _R11_ROLE_CONTRACT_SHA256,
             'r11-role-funding-record', 'archived role contract differs from the reviewed pin')
    contract = _r11_json(raw['roleContractRaw'], limit=131_072)
    schemas = {}
    for name, encoded in value['roleSchemasRaw'].items():
        schema_raw = encoded.encode('utf-8')
        _require(hashlib.sha256(schema_raw).hexdigest() == contract['runtimeSchemaByLayout'][name]['sha256'],
                 'r11-role-funding-record', 'archived funding schema differs from pinned contract')
        schemas[name] = _r11_json(schema_raw, limit=131_072)
    base = _r11_json(raw['baseRaw'], limit=131_072)
    identity = _r11_role_identity(authority={'schemas': schemas, 'contract': contract,
        'lockSha256': base.get('planLockSha256')}, base_raw=raw['baseRaw'],
        inventory_raw=raw['inventoryRaw'], funding_raw=raw['fundingRaw'])
    funding = identity['funding']
    _require(all(raw[key] == canonical_bytes(identity[field]) for key, field in (
                ('baseRaw', 'base'), ('inventoryRaw', 'inventory'), ('fundingRaw', 'funding')))
             and funding['reusedFirstHold'] is None
             and relative == _R11_COORDINATOR_BASE + '/role-funding/' + identity['fundingBatchSha256'] + '/admission.json'
             and re.fullmatch(re.escape(_R11_COORDINATOR_BASE) + r'/r[1-9][0-9]*-[a-z0-9-]+/cost\.json', value['coordinatorCursor']) is not None,
             'r11-role-funding-record', 'noncanonical ancestors, unproved credit, source path or coordinator cursor')
    expected = {key: value[key] for key in (*strings, 'roleSchemasRaw')}
    expected.update(schemaVersion='alk-r11-global-role-funding.v1', status='ADMITTED_ROLE_BATCH_FULL_HOLD',
        tokenCap=funding['tokenCap'], protectedCloseoutTokens=funding['protectedCloseoutTokens'],
        priorUnknownHolds=funding['priorUnknownHolds'], unknownHoldsIncludingThisWindow=funding['admittedUnknownHolds'],
        priorLedgerLowerBound=funding['priorExposureLowerBound'], ledgerLowerBoundIncludingThisHold=funding['admittedExposureLowerBound'],
        actualInputTokens=None, actualTokens=None, costStatus='UNAVAILABLE', priorBudgetResumed=False,
        priorUnknownHoldsReleased=0)
    _require(canonical_bytes(value) == canonical_bytes(expected), 'r11-role-funding-record',
             'closed role funding archive has changed fields, balances, measured usage or release')
    return identity


def _r11_role_prefix_record(value: dict[str, Any], relative: str) -> tuple[str, bytes]:
    """Validate one zero-charge archive envelope; complete ordering needs history."""
    keys = {'schemaVersion', 'status', 'reviewId', 'fundingBatchSha256', 'recordPath', 'recordRaw',
            'roleSubjectSchemaRaw', 'priorHeadSha256', 'previousCostPrefixSha256', 'costPrefixSha256',
            'coordinatorCursor', 'tokenCap', 'protectedCloseoutTokens', 'priorUnknownHolds',
            'unknownHoldsIncludingThisWindow', 'priorLedgerLowerBound', 'ledgerLowerBoundIncludingThisHold',
            'actualInputTokens', 'actualTokens', 'costStatus', 'priorBudgetResumed', 'priorUnknownHoldsReleased'}
    hashes = ('fundingBatchSha256', 'priorHeadSha256', 'previousCostPrefixSha256', 'costPrefixSha256')
    _require(set(value) == keys and value['schemaVersion'] == 'alk-r11-global-role-prefix.v1'
             and value['status'] == 'ROLE_COST_PREFIX_RECORDED'
             and all(isinstance(value[key], str) and re.fullmatch('[0-9a-f]{64}', value[key]) is not None for key in hashes)
             and isinstance(value['reviewId'], str) and re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,63}', value['reviewId']) is not None
             and isinstance(value['recordPath'], str) and re.fullmatch(
                 r'(shared-01|source-(0[1-9]|[12][0-9]|3[0-2]))/(reservation|settlement)\.json', value['recordPath']) is not None
             and isinstance(value['recordRaw'], str) and isinstance(value['roleSubjectSchemaRaw'], str)
             and isinstance(value['coordinatorCursor'], str) and re.fullmatch(re.escape(_R11_COORDINATOR_BASE)
                 + r'/r[1-9][0-9]*-[a-z0-9-]+/cost\.json', value['coordinatorCursor']) is not None,
             'r11-role-prefix-record', 'closed typed role-prefix envelope or identity is invalid')
    try:
        record_raw = value['recordRaw'].encode('utf-8');value['roleSubjectSchemaRaw'].encode('utf-8')
    except UnicodeError as exc:
        raise LifecycleError('r11-role-prefix-record', 'role-prefix archive is not valid UTF-8') from exc
    record = _r11_json(record_raw, limit=131_072)
    zeros = ('tokenCap', 'protectedCloseoutTokens', 'priorUnknownHoldsReleased')
    balances = ('priorUnknownHolds', 'unknownHoldsIncludingThisWindow', 'priorLedgerLowerBound', 'ledgerLowerBoundIncludingThisHold')
    _require(record_raw == canonical_bytes(record) and record.get('reviewId') == value['reviewId']
             and all(type(value[key]) is int and value[key] == 0 for key in zeros)
             and all(type(value[key]) is int and value[key] >= 0 for key in balances)
             and value['priorUnknownHolds'] == value['unknownHoldsIncludingThisWindow']
             <= value['priorLedgerLowerBound'] == value['ledgerLowerBoundIncludingThisHold']
             and value['actualInputTokens'] is None and value['actualTokens'] is None
             and value['costStatus'] == 'UNAVAILABLE' and value['priorBudgetResumed'] is False
             and relative == _R11_COORDINATOR_BASE + '/role-prefixes/' + value['fundingBatchSha256']
                 + '/' + value['costPrefixSha256'] + '/record.json',
             'r11-role-prefix-record', 'role-prefix archive changes holds, usage, identity or canonical path')
    return value['recordPath'], record_raw


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise LifecycleError(code, message)

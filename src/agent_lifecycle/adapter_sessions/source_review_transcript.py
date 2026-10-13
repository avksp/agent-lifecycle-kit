"""Owned source review transcript helpers."""
from __future__ import annotations
from typing import Any
from agent_lifecycle.contracts import LifecycleError
from pathlib import Path
from agent_lifecycle.contracts.bounded_json import load_bounded_json as _r11_json
from agent_lifecycle.contracts.bounded_json import matches_closed_schema as _r11_role_schema_matches
from agent_lifecycle.accounting.declared_ledger_records import _r11_transport_binding
from agent_lifecycle.adapter_sessions.attempt_authority import _read
from agent_lifecycle.accounting.declared_ledger_records import _require
from agent_lifecycle.accounting.declared_ledger import _sync_directory
from agent_lifecycle.adapter_sessions.attempt_authority import _write
from agent_lifecycle.contracts import canonical_bytes
from agent_lifecycle.contracts import canonical_digest
import hashlib
import json
from agent_lifecycle.contracts.authority_io import normalize_authority_path
import re
from agent_lifecycle.contracts.authority_io import read_authority_bytes
import time
from agent_lifecycle.adapter_sessions.source_review_contracts import _R11_REQUEST_CAP
from agent_lifecycle.adapter_sessions.source_review_contracts import _R11_REVIEW_INSTRUCTION
from agent_lifecycle.adapter_sessions.source_review_contracts import _R11_REVIEW_SCHEMA_SHA256
from agent_lifecycle.adapter_sessions.source_review_contracts import _R11_TRANSPORT_RECORD_CAP
from agent_lifecycle.adapter_sessions.source_review_contracts import _r11_fresh_start
from agent_lifecycle.adapter_sessions.source_review_contracts import _r11_notification_envelope
from agent_lifecycle.adapter_sessions.source_review_contracts import _r11_role_authority
from agent_lifecycle.adapter_sessions.source_review_roles import _r11_role_body
from agent_lifecycle.adapter_sessions.source_review_history import read_source_review_request


def verify_source_review_body_and_reads(
    project_root: Path, *, expected_request: bytes, request_raw: bytes,
    expected_subject: dict[str, Any], body_raw: bytes,
    first_read_raw: bytes, second_read_raw: bytes, turn_id: str, role_delivery: bool = False,
) -> dict[str, Any]:
    """Join exact input/body with two stable completed, tool-free read results.

    This is one collector predicate. It does NOT attest request writes, matching
    RPC responses, read order/freshness, cost, support, parent or source authority.
    The caller must independently reconstruct expected_request/expected_subject
    and qualify those remaining raw-evidence joins before any composite PASS.
    """
    from .codex_source_subject import _matches_closed_schema, _review_findings_match_v4, _single_turn_projection

    _require(type(role_delivery) is bool, 'r11-review-mode', 'explicit role delivery mode required')
    root = Path(project_root).absolute()
    request = _r11_json(request_raw, limit=_R11_REQUEST_CAP)
    _require(isinstance(expected_request, bytes) and request_raw == expected_request
             and request_raw == canonical_bytes(request) + b'\n'
             and set(request) == {'id', 'method', 'params'}
             and type(request['id']) is int and request['id'] > 0 and request['method'] == 'turn/start',
             'r11-review-request', 'request differs from the reconstructed exact request')
    params = request['params']
    _require(isinstance(params, dict) and set(params) == {
                 'threadId', 'cwd', 'approvalPolicy', 'sandboxPolicy', 'input', 'outputSchema'}
             and params['cwd'] == str(root) and params['approvalPolicy'] == 'never'
             and params['sandboxPolicy'] == {'type': 'readOnly'}
             and isinstance(params['threadId'], str) and bool(params['threadId'])
             and isinstance(turn_id, str) and bool(turn_id),
             'r11-review-request', 'assigned one-turn read-only request is required')
    if role_delivery:
        authority = _r11_role_authority(root)
        _require(_r11_role_schema_matches(expected_subject, authority['schemas']['roleSubject'])
                 and params['outputSchema'] == authority['schemas']['reviewerBody']
                 and all(0 < len(value.encode('utf-8')) <= 256 for value in (params['threadId'], turn_id)),
                 'r11-role-review-subject', 'bounded role identity and pinned v6 output schema required')
        sealed = read_source_review_request(root, review_id=expected_subject['reviewId'],
            role_id=expected_subject['roleId'], require_reservation=True)
        _require(sealed['requestRaw'] == expected_request and sealed['subject'] == expected_subject,
                 'r11-role-review-request', 'review differs from independently reconstructed reserved request')
        body_match = _r11_role_body(body_raw, subject=expected_subject, schemas=authority['schemas'])
        projections = [_single_turn_projection(_r11_json(raw, limit=2_097_152),
                       thread_id=params['threadId'], turn_id=turn_id, request=request)
                       for raw in (first_read_raw, second_read_raw)]
        _require(projections[0] == projections[1] and projections[0]['bodyText'].encode('utf-8') == body_raw,
                 'r11-review-unstable', 'completed role turn/body differs between stable reads')
        _require(_r11_role_authority(root) == authority
                 and read_source_review_request(root, review_id=expected_subject['reviewId'],
                     role_id=expected_subject['roleId'], require_reservation=True) == sealed,
                 'r11-role-review-stale', 'role authority, reserved request or ledger changed during validation')
        return {'schemaVersion': 'alk-r11-body-read-match.v1', 'status': 'BODY_READS_MATCHED',
                'threadId': params['threadId'], 'turnId': turn_id, 'bodyItemId': projections[0]['bodyItemId'],
                'requestSha256': hashlib.sha256(request_raw).hexdigest(),
                'bodySha256': hashlib.sha256(body_raw).hexdigest(), 'subjectSha256': canonical_digest(expected_subject),
                'sourceCoverageSha256': expected_subject['sourceRangeSha256'],
                'readResultSha256': [hashlib.sha256(raw).hexdigest() for raw in (first_read_raw, second_read_raw)],
                'stableProjectionSha256': canonical_digest(projections[0]), 'closedParentFindingIds': [],
                'roleId': expected_subject['roleId'], 'roleKind': expected_subject['roleKind'],
                'approvedIntegrationScopes': body_match['approvedIntegrationScopes'],
                'sealedRequestSha256': sealed['sealSha256'], 'reservationRequestMatched': True,
                'sharedEvidenceAccepted': False, 'transportVerified': False, 'firstNativeBootstrapEligible': False}
    schema_path = root / 'tasks/release-2-16/REVIEWER-BODY-v5-R11.schema.json'
    schema_raw = read_authority_bytes(schema_path, root=root, max_bytes=65_536)
    schema = _r11_json(schema_raw, limit=65_536)
    _require(hashlib.sha256(schema_raw).hexdigest() == _R11_REVIEW_SCHEMA_SHA256
             and params['outputSchema'] == schema,
             'r11-review-schema', 'request does not use the pinned closed v5 schema')
    inputs = params['input']
    _require(isinstance(inputs, list) and len(inputs) == 1 and isinstance(inputs[0], dict)
             and set(inputs[0]) == {'type', 'text'} and inputs[0]['type'] == 'text'
             and isinstance(inputs[0]['text'], str) and isinstance(expected_subject, dict),
             'r11-review-request', 'one exact source text element is required')
    subject_sha = canonical_digest(expected_subject)
    prefix = _R11_REVIEW_INSTRUCTION + '\nASSIGNED_SUBJECT_SHA256=' + subject_sha + '\n'
    prompt = inputs[0]['text']
    _require(prompt.startswith(prefix), 'r11-review-subject', 'assigned subject digest differs')
    payload = _r11_json(prompt[len(prefix):].encode('utf-8'), limit=_R11_REQUEST_CAP)
    _require(set(payload) == {'subject', 'sourceContent', 'callsRequiringInteractionReview'}
             and payload['subject'] == expected_subject and isinstance(payload['sourceContent'], list)
             and isinstance(payload['callsRequiringInteractionReview'], list),
             'r11-review-subject', 'reviewed source subject differs from reconstruction')
    coverage = []
    for part in payload['sourceContent']:
        _require(isinstance(part, dict) and set(part) == {'extent', 'content'}
                 and isinstance(part['extent'], dict) and isinstance(part['content'], str),
                 'r11-review-content', 'literal source CONTENT is required')
        row = part['extent']
        raw = part['content'].encode('utf-8')
        _require(set(row) == {'version', 'path', 'start', 'end', 'sha256'}
                 and isinstance(row['version'], str) and row['version'] in {'CURRENT', 'PARENT'}
                 and isinstance(row['path'], str)
                 and normalize_authority_path(row['path']) == row['path']
                 and type(row['start']) is int and type(row['end']) is int
                 and 0 <= row['start'] < row['end'] and row['end'] - row['start'] == len(raw)
                 and row['sha256'] == hashlib.sha256(raw).hexdigest(),
                 'r11-review-content', 'delivered source extent differs from its literal bytes')
        coverage.append(row)
    _require(canonical_digest(coverage) == expected_subject.get('coveredPathRangeSha256'),
             'r11-review-content', 'delivered source coverage differs from assigned coverage')
    projections = [_single_turn_projection(_r11_json(raw, limit=2_097_152),
                   thread_id=params['threadId'], turn_id=turn_id, request=request)
                   for raw in (first_read_raw, second_read_raw)]
    _require(projections[0] == projections[1]
             and projections[0]['bodyText'].encode('utf-8') == body_raw,
             'r11-review-unstable', 'completed turn/body differs between saved stable reads')
    body = _r11_json(body_raw, limit=65_536)
    # v5 adds one schema keyword to the existing closed-schema interpreter.
    # Preserve its semantics explicitly; the pinned schema forbids other changes.
    checked_schema = json.loads(schema_raw)
    unique = checked_schema['properties']['closedParentFindingIds'].pop('uniqueItems')
    _require(unique is True and _matches_closed_schema(body, checked_schema),
             'r11-review-body', 'reviewer body does not match the closed v5 schema')
    closed = body['closedParentFindingIds']
    _require(len(closed) == len(set(closed)), 'r11-review-body', 'duplicate parent finding closure')
    bindings = {'subjectSha256': subject_sha, **{key: expected_subject.get(key) for key in (
        'parentSubjectSha256', 'currentSubjectSha256', 'shardId',
        'shardInventorySha256', 'coveredPathRangeSha256')}}
    _require(all(isinstance(value, str) and bool(value) and body[key] == value for key, value in bindings.items()),
             'r11-review-body', 'reviewer body belongs to another source subject or shard')
    _require(body['verdict'] == 'PASS' and body['inheritedCoverageAccepted'] is True
             and body['interactionScopeComplete'] is True and _review_findings_match_v4(body),
             'r11-review-not-pass', 'shard failed, is incomplete, or has unresolved coverage/findings')
    _require(read_authority_bytes(schema_path, root=root, max_bytes=65_536) == schema_raw,
             'r11-review-schema', 'reviewer schema changed during validation')
    return {'schemaVersion': 'alk-r11-body-read-match.v1', 'status': 'BODY_READS_MATCHED',
            'threadId': params['threadId'], 'turnId': turn_id, 'bodyItemId': projections[0]['bodyItemId'],
            'requestSha256': hashlib.sha256(request_raw).hexdigest(),
            'bodySha256': hashlib.sha256(body_raw).hexdigest(), 'subjectSha256': subject_sha,
            'sourceCoverageSha256': canonical_digest(coverage),
            'readResultSha256': [hashlib.sha256(raw).hexdigest() for raw in (first_read_raw, second_read_raw)],
            'stableProjectionSha256': canonical_digest(projections[0]), 'closedParentFindingIds': closed,
            'transportVerified': False, 'firstNativeBootstrapEligible': False}

class SourceReviewTranscript:
    """Durable, exclusive records around an externally owned bounded RPC pipe.

    The launcher owns process/deadline and authenticates the selected binary.
    This recorder never starts a process. After any ambiguous send/record error
    it cannot send again; its saved pending request remains uncertain evidence.
    A new instance cannot overwrite or resume the same transcript directory.
    """

    def __init__(self, project_root: Path, *, binding: dict[str, str]) -> None:
        _r11_transport_binding(binding)
        self.root = Path(project_root).absolute()
        self.directory = self.root / ('work/release-2-16/evidence/route-bootstrap/shards/'
                                      + binding['shardId'] + '/transport')
        self.sequence = 0
        self.failed = False
        self.last_ns = 0
        self.total_bytes = 0
        self.model_request_recorded = False
        self._record('SESSION', binding=dict(binding))
        try:
            ancestor = self.directory.parent
            while True:
                _sync_directory(ancestor)
                if ancestor == self.root:
                    break
                ancestor = ancestor.parent
        except BaseException:
            self.failed = True
            raise

    def _record(self, kind: str, **fields: Any) -> None:
        _require(not self.failed, 'r11-transport-uncertain', 'transcript failed; retry is not authorized')
        try:
            now = time.monotonic_ns()
            _require(now >= self.last_ns, 'r11-transport-clock', 'monotonic clock moved backwards')
            record = {'sequence': self.sequence, 'monotonicNs': now, 'kind': kind, **fields}
            raw = canonical_bytes(record)
            _require(self.sequence < 65_536 and len(raw) <= _R11_TRANSPORT_RECORD_CAP
                     and self.total_bytes + len(raw) + 1 <= 16_777_216,
                     'r11-transport-records', 'transport record/total byte bound exceeded')
            path = self.directory / f'{self.sequence:08d}.json'
            if len(raw) <= 100_000:
                _write(self.root, path, record)
            else:
                # Reuse the existing 128 KiB private exclusive writer; do not
                # raise limits for unrelated launch/request artifacts.
                parts = []
                for index, offset in enumerate(range(0, len(raw), 32_768)):
                    part = {'dataHex': raw[offset:offset + 32_768].hex()}
                    part_name = f'{self.sequence:08d}.{index:04d}.json'
                    _write(self.root, self.directory / part_name, part)
                    parts.append(hashlib.sha256(canonical_bytes(part)).hexdigest())
                _write(self.root, path, {'schemaVersion': 'alk-r11-transport-record-parts.v1',
                       'recordBytes': len(raw), 'recordSha256': hashlib.sha256(raw).hexdigest(), 'parts': parts})
            _sync_directory(self.directory)
        except BaseException:
            self.failed = True
            raise
        self.sequence += 1
        self.last_ns = now
        self.total_bytes += len(raw) + 1

    def send(self, request_raw: bytes, writer: Any) -> None:
        """Live review transport is disabled, including caller-supplied writers."""
        raise LifecycleError('r11-experimental-disabled',
                             'Experimental R11 review route is disabled; use ordinary independent audit')

    def receive(self, message_raw: bytes) -> None:
        """Called at the launcher's bounded raw-response boundary, before projection."""
        try:
            if not isinstance(message_raw, bytes) or len(message_raw) > 2_097_152:
                self._record('RECEIVE_REFUSED', rawHex=(message_raw[:2_097_152].hex()
                             if isinstance(message_raw, bytes) else ''), rawComplete=False)
                raise LifecycleError('r11-transport-records', 'received frame is unavailable or exceeds its bound')
            # Capture bytes before decoding, including malformed JSON/UTF-8.
            self._record('RECEIVED', rawHex=message_raw.hex())
            _r11_json(message_raw, limit=2_097_152)
        except BaseException:
            self.failed = True
            raise

    def read_records(self) -> bytes:
        # Also readable after failure: incomplete evidence must be retained.
        chunks = []
        for index in range(self.sequence):
            _, raw = _read(self.root, self.directory / f'{index:08d}.json')
            value = _r11_json(raw, limit=131_072)
            if value.get('schemaVersion') == 'alk-r11-transport-record-parts.v1':
                _require(set(value) == {'schemaVersion', 'recordBytes', 'recordSha256', 'parts'}
                         and type(value['recordBytes']) is int and 100_000 < value['recordBytes'] <= _R11_TRANSPORT_RECORD_CAP
                         and isinstance(value['parts'], list) and len(value['parts']) == (value['recordBytes'] + 32767) // 32768,
                         'r11-transport-records', 'invalid private record part inventory')
                assembled = []
                for part_index, digest in enumerate(value['parts']):
                    _, part_raw = _read(self.root, self.directory / f'{index:08d}.{part_index:04d}.json')
                    part = _r11_json(part_raw, limit=131_072)
                    _require(hashlib.sha256(part_raw).hexdigest() == digest and set(part) == {'dataHex'}
                             and isinstance(part['dataHex'], str)
                             and re.fullmatch('[0-9a-f]{2,65536}', part['dataHex']) is not None
                             and len(part['dataHex']) % 2 == 0,
                             'r11-transport-records', 'private transport part changed')
                    assembled.append(bytes.fromhex(part['dataHex']))
                raw = b''.join(assembled)
                _require(len(raw) == value['recordBytes'] and hashlib.sha256(raw).hexdigest() == value['recordSha256'],
                         'r11-transport-records', 'private transport record changed')
                _r11_json(raw, limit=_R11_TRANSPORT_RECORD_CAP)
            chunks.append(raw + b'\n')
        return b''.join(chunks)

def _r11_require_transport_record(record: dict[str, Any], fields: set[str]) -> None:
    _require(set(record) == {'sequence', 'monotonicNs', 'kind'} | fields, 'r11-transport-records', 'record has missing or unexpected fields')

def _r11_receive_transport_record(record, ordinal, pending, requests, replies, read_results, thread_id, turn_id, started, completed, snapshots, sequence_points, telemetry_turns, started_items, completed_items):
    _r11_require_transport_record(record, {'rawHex'})
    _require(isinstance(record['rawHex'], str) and len(record['rawHex']) <= 4194304 and (len(record['rawHex']) % 2 == 0) and (re.fullmatch('[0-9a-f]*', record['rawHex']) is not None) and requests and (pending is None or pending['flushed']), 'r11-transport-order', 'message was recorded before request flush')
    raw = bytes.fromhex(record['rawHex'])
    message = _r11_json(raw, limit=2097152)
    _require('jsonrpc' not in message or message['jsonrpc'] == '2.0', 'r11-transport-rpc', 'unsupported RPC framing')
    if 'id' in message:
        _require(set(message) <= {'id', 'result', 'jsonrpc'} and pending is not None and (type(message['id']) is int) and (message['id'] == pending['id']) and isinstance(message.get('result'), dict), 'r11-transport-rpc', 'RPC error, server request, duplicate or unmatched response')
        result = message['result']
        if pending['number'] == 1:
            turn = result.get('turn')
            _require(isinstance(turn, dict) and isinstance(turn.get('id'), str) and bool(turn['id']) and (turn.get('status') in {'inProgress', 'completed'}) and (turn.get('error') is None) and (turn_id is None or turn_id == turn['id']), 'r11-transport-turn', 'turn/start response did not identify the assigned turn')
            turn_id = turn['id']
            snapshots.append(turn)
            sequence_points['turnResponse'] = ordinal
        else:
            read_results.append(canonical_bytes(result))
            sequence_points['readResponses'].append(ordinal)
        replies.append(raw)
        pending = None
        return (pending, turn_id, started, completed)
    _require(_r11_notification_envelope(message), 'r11-transport-rpc', 'complete raw RPC notification is required')
    method, params = (message['method'], message['params'])
    if method == 'thread/started':
        _require(_r11_fresh_start({'thread': params.get('thread'), 'model': 'metadata'}, 'metadata') == thread_id, 'r11-transport-turn', 'late start notification belongs to another/nonempty thread')
        return (pending, turn_id, started, completed)
    if method in {'account/rateLimits/updated', 'account/updated', 'deprecationNotice', 'mcpServer/startupStatus/updated', 'remoteControl/status/changed'}:
        return (pending, turn_id, started, completed)
    _require(params.get('threadId') == thread_id, 'r11-transport-turn', 'notification belongs to another thread')
    if method in {'thread/tokenUsage/updated', 'thread/status/changed'}:
        _require('turnId' not in params or turn_id is None or params['turnId'] == turn_id, 'r11-transport-turn', 'telemetry belongs to another turn')
        if 'turnId' in params:
            telemetry_turns.append(params['turnId'])
        return (pending, turn_id, started, completed)
    if method in {'turn/started', 'turn/completed'}:
        turn = params.get('turn')
        _require(isinstance(turn, dict) and isinstance(turn.get('id'), str) and bool(turn['id']) and (turn_id is None or turn['id'] == turn_id) and (turn.get('error') is None), 'r11-transport-turn', 'notification has a conflicting/error turn')
        turn_id = turn['id']
        if method == 'turn/started':
            _require(not started and (not completed) and (turn.get('status') == 'inProgress'), 'r11-transport-order', 'turn start is repeated or out of order')
            started = True
        else:
            _require(started and (not completed) and (turn.get('status') == 'completed') and completed_items and (completed_items[-1].get('type') == 'agentMessage') and (len(started_items) == len(completed_items)), 'r11-transport-order', 'turn ended before every item completed or ended twice')
            completed = True
            sequence_points['turnCompleted'] = ordinal
        snapshots.append(turn)
        return (pending, turn_id, started, completed)
    _require(started and (not completed) and (params.get('turnId') == turn_id), 'r11-transport-order', 'item event is outside the assigned active turn')
    if method in {'item/started', 'item/completed'}:
        item = params.get('item')
        _require(isinstance(item, dict) and isinstance(item.get('id'), str) and bool(item['id']) and isinstance(item.get('type'), str) and (item['type'] in {'userMessage', 'reasoning', 'agentMessage'}), 'r11-transport-item', 'tool or unknown item in supposedly tool-free review')
        ident = item['id']
        if method == 'item/started':
            _require(ident not in started_items, 'r11-transport-item', 'duplicate started item')
            started_items[ident] = item['type']
        else:
            _require(started_items.get(ident) == item['type'] and ident not in {value['id'] for value in completed_items}, 'r11-transport-item', 'item completion is missing its start or is duplicated')
            completed_items.append(item)
    elif method in {'item/agentMessage/delta', 'item/reasoning/textDelta', 'item/reasoning/summaryTextDelta', 'item/reasoning/summaryPartAdded'}:
        ident = params.get('itemId')
        _require(isinstance(ident, str) and started_items.get(ident) == ('agentMessage' if method == 'item/agentMessage/delta' else 'reasoning') and (ident not in {value['id'] for value in completed_items}), 'r11-transport-item', 'delta belongs to an unknown/finished item')
    else:
        raise LifecycleError('r11-transport-rpc', 'unrecognized review notification: ' + method)
    return (pending, turn_id, started, completed)

def verify_source_review_transport_records(project_root: Path, *, expected_binding: dict[str, str], expected_request: bytes, expected_subject: dict[str, Any], body_raw: bytes, transcript_raw: bytes, role_delivery: bool=False) -> dict[str, Any]:
    """Match durable send/receive records and compose the exact body/read predicate.

    This proves consistency/order of the supplied records, not their provenance.
    Binary/producer qualification, current source/parent/support/test/cost/terminal
    authority and the fresh-first-native read remain collector obligations.
    """
    _require(type(role_delivery) is bool, 'r11-review-mode', 'explicit role delivery mode required')
    _r11_transport_binding(expected_binding)
    _require(isinstance(transcript_raw, bytes) and 0 < len(transcript_raw) <= 16777216 and transcript_raw.endswith(b'\n'), 'r11-transport-records', 'complete bounded JSONL transport records are required')
    lines = transcript_raw.splitlines()
    _require(1 <= len(lines) <= 65536 and all(lines), 'r11-transport-records', 'empty or excessive transport records')
    records = [_r11_json(line, limit=_R11_TRANSPORT_RECORD_CAP) for line in lines]
    last_ns = 0
    pending: dict[str, Any] | None = None
    requests: list[bytes] = []
    replies: list[bytes] = []
    read_results: list[bytes] = []
    request_ids: set[int] = set()
    turn_id: str | None = None
    started = False
    completed = False
    started_items: dict[str, str] = {}
    completed_items: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    sequence_points: dict[str, Any] = {'readRequests': [], 'readResponses': []}
    telemetry_turns: list[str] = []
    thread_id = expected_binding['threadId']
    _require(isinstance(expected_subject, dict) and expected_subject.get('roleId' if role_delivery else 'shardId') == expected_binding['shardId'], 'r11-transport-binding', 'subject and transport shard differ')
    for ordinal, record in enumerate(records):
        _require(type(record.get('sequence')) is int and record['sequence'] == ordinal and (type(record.get('monotonicNs')) is int) and (record['monotonicNs'] >= last_ns), 'r11-transport-order', 'record order or monotonic time is invalid')
        last_ns = record['monotonicNs']
        kind = record.get('kind')
        if ordinal == 0:
            _r11_require_transport_record(record, {'binding'})
            _require(kind == 'SESSION' and record['binding'] == expected_binding, 'r11-transport-binding', 'transcript belongs to another session/binary/producer')
            continue
        if kind == 'REQUEST_SAVED':
            _r11_require_transport_record(record, {'raw'})
            _require(pending is None and len(requests) < 3 and isinstance(record['raw'], str), 'r11-transport-order', 'unexpected/concurrent/repeated RPC request')
            raw = record['raw'].encode('utf-8')
            request = _r11_json(raw, limit=_R11_REQUEST_CAP)
            ident = request.get('id')
            _require(raw == canonical_bytes(request) + b'\n' and type(ident) is int and (ident > 0) and (ident not in request_ids), 'r11-transport-request', 'request ID or exact framing is invalid')
            if not requests:
                _require(raw == expected_request and request.get('method') == 'turn/start' and isinstance(request.get('params'), dict) and (request.get('params', {}).get('threadId') == thread_id), 'r11-transport-request', 'sent model request differs from reconstruction')
            else:
                _require(completed and len(replies) == len(requests) and (request == {'id': ident, 'method': 'thread/read', 'params': {'threadId': thread_id, 'includeTurns': True}}), 'r11-transport-order', 'stable read must follow completed turn and previous RPC response')
                sequence_points['readRequests'].append(ordinal)
            request_ids.add(ident)
            requests.append(raw)
            pending = {'id': ident, 'raw': raw, 'accepted': 0, 'flushed': False, 'number': len(requests)}
        elif kind == 'WRITE_ACCEPTED':
            _r11_require_transport_record(record, {'requestId', 'offset', 'acceptedBytes', 'chunkSha256', 'prefixSha256'})
            _require(pending is not None and (not pending['flushed']) and (type(record['requestId']) is int) and (record['requestId'] == pending['id']) and (type(record['offset']) is int) and (record['offset'] == pending['accepted']) and (type(record['acceptedBytes']) is int) and (record['acceptedBytes'] > 0), 'r11-transport-write', 'accepted-byte evidence is missing, reordered or duplicated')
            start, end = (pending['accepted'], pending['accepted'] + record['acceptedBytes'])
            raw = pending['raw']
            _require(end <= len(raw) and record['chunkSha256'] == hashlib.sha256(raw[start:end]).hexdigest() and (record['prefixSha256'] == hashlib.sha256(raw[:end]).hexdigest()), 'r11-transport-write', 'accepted-byte length or digest differs from exact request')
            pending['accepted'] = end
        elif kind == 'FLUSHED':
            _r11_require_transport_record(record, {'requestId', 'requestBytes', 'requestSha256'})
            _require(pending is not None and (not pending['flushed']) and (type(record['requestId']) is int) and (record['requestId'] == pending['id']) and (type(record['requestBytes']) is int) and (record['requestBytes'] == len(pending['raw'])) and (pending['accepted'] == len(pending['raw'])) and (record['requestSha256'] == hashlib.sha256(pending['raw']).hexdigest()), 'r11-transport-write', 'complete accepted write and successful flush are required')
            pending['flushed'] = True
        elif kind == 'RECEIVED':
            pending, turn_id, started, completed = _r11_receive_transport_record(record, ordinal, pending, requests, replies, read_results, thread_id, turn_id, started, completed, snapshots, sequence_points, telemetry_turns, started_items, completed_items)
            continue
        else:
            raise LifecycleError('r11-transport-records', 'unknown transport record kind')
    _require(pending is None and len(requests) == len(replies) == 3 and (len(read_results) == 2) and started and completed and (turn_id is not None), 'r11-transport-incomplete', 'request/write/response/turn/two-read evidence is incomplete')
    _require(all((value == turn_id for value in telemetry_turns)), 'r11-transport-turn', 'early telemetry belongs to a different turn')
    matched = verify_source_review_body_and_reads(project_root, expected_request=expected_request, request_raw=requests[0], expected_subject=expected_subject, body_raw=body_raw, first_read_raw=read_results[0], second_read_raw=read_results[1], turn_id=turn_id, role_delivery=role_delivery)
    if role_delivery:
        sealed = read_source_review_request(Path(project_root).absolute(), review_id=expected_subject['reviewId'], role_id=expected_subject['roleId'], require_reservation=True)
        _require(sealed['seal']['binding'] == expected_binding and sealed['requestRaw'] == expected_request, 'r11-role-transport-binding', 'transcript operation/binary/thread differs from reserved seal')
    final_items = _r11_json(read_results[0], limit=2097152)['thread']['turns'][0]['items']
    _require(completed_items == final_items, 'r11-transport-item', 'completed event items differ from stable reads')
    by_id = {item['id']: item for item in final_items}
    for snapshot in snapshots:
        items = snapshot.get('items')
        _require(isinstance(items, list) and all((isinstance(item, dict) and isinstance(item.get('id'), str) and (by_id.get(item['id']) == item) for item in items)), 'r11-transport-item', 'turn snapshot conflicts with completed source/body items')
    return {'schemaVersion': 'alk-r11-transport-record-match.v1', 'status': 'TRANSPORT_RECORDS_MATCHED', 'binding': dict(expected_binding), 'bodyReadMatch': matched, 'transcriptSha256': hashlib.sha256(transcript_raw).hexdigest(), 'recordCount': len(records), 'requestSha256': [hashlib.sha256(raw).hexdigest() for raw in requests], 'responseSha256': [hashlib.sha256(raw).hexdigest() for raw in replies], 'sequencePoints': sequence_points, 'producerQualified': False, 'costQualified': False, 'firstNativeBootstrapEligible': False}

def _r11_transcript_snapshot(root: Path, directory: Path) -> dict[str, bytes]:
    """Read the entire private directory, including unacknowledged record tails."""
    from .private_input import _read_private

    def names() -> set[str]:
        found: set[str] = set()
        for path in directory.iterdir():
            _require(re.fullmatch(r'[0-9]{8}(?:\.[0-9]{4})?\.json', path.name) is not None,
                     'r11-transport-inventory', 'unexpected file in private transport directory')
            found.add(path.name)
            _require(len(found) <= 66_560, 'r11-transport-inventory', 'transport file count exceeds bound')
        return found

    try:
        # Check all private ancestors before enumerating a potentially replaced
        # directory. The first record must exist even for an incomplete session.
        first = _read_private(directory / '00000000.json', root=root)
        before = names()
        snapshot = {}
        size = 0
        for name in sorted(before):
            raw = _read_private(directory / name, root=root)
            size += len(raw)
            _require(size <= 41_943_040, 'r11-transport-inventory', 'transport storage exceeds bound')
            snapshot[name] = raw
        _require(snapshot.get('00000000.json') == first and names() == before,
                 'r11-transport-inventory', 'transport directory changed during read')
        return snapshot
    except OSError as exc:
        raise LifecycleError('r11-transport-inventory', 'private transport file is unavailable') from exc

def _r11_reassemble_transcript(snapshot: dict[str, bytes]) -> bytes:
    """Account for every main/part file; no caller-supplied count or prefix."""
    mains = sorted(name for name in snapshot if re.fullmatch(r'[0-9]{8}\.json', name))
    _require(0 < len(mains) <= 65_536
             and mains == [f'{index:08d}.json' for index in range(len(mains))],
             'r11-transport-inventory', 'transport sequence is missing or has a gap')
    consumed: set[str] = set()
    records = []
    total = 0
    for index, name in enumerate(mains):
        consumed.add(name)
        raw = snapshot[name]
        value = _r11_json(raw, limit=131_072)
        _require(canonical_bytes(value) == raw, 'r11-transport-inventory', 'record file is not canonical')
        if value.get('schemaVersion') == 'alk-r11-transport-record-parts.v1':
            _require(set(value) == {'schemaVersion', 'recordBytes', 'recordSha256', 'parts'}
                     and type(value['recordBytes']) is int
                     and 100_000 < value['recordBytes'] <= _R11_TRANSPORT_RECORD_CAP
                     and isinstance(value['parts'], list)
                     and len(value['parts']) == (value['recordBytes'] + 32767) // 32768,
                     'r11-transport-inventory', 'invalid transport part manifest')
            chunks = []
            for part_index, digest in enumerate(value['parts']):
                part_name = f'{index:08d}.{part_index:04d}.json'
                _require(part_name in snapshot, 'r11-transport-inventory', 'transport part is missing')
                part_raw = snapshot[part_name]
                part = _r11_json(part_raw, limit=131_072)
                expected_bytes = min(32_768, value['recordBytes'] - part_index * 32_768)
                _require(hashlib.sha256(part_raw).hexdigest() == digest
                         and canonical_bytes(part) == part_raw and set(part) == {'dataHex'}
                         and isinstance(part['dataHex'], str)
                         and len(part['dataHex']) == 2 * expected_bytes
                         and re.fullmatch('[0-9a-f]+', part['dataHex']) is not None,
                         'r11-transport-inventory', 'transport part bytes or digest differ')
                chunks.append(bytes.fromhex(part['dataHex']))
                consumed.add(part_name)
            raw = b''.join(chunks)
            _require(len(raw) == value['recordBytes']
                     and hashlib.sha256(raw).hexdigest() == value['recordSha256'],
                     'r11-transport-inventory', 'assembled record differs from manifest')
            value = _r11_json(raw, limit=_R11_TRANSPORT_RECORD_CAP)
            _require(canonical_bytes(value) == raw,
                     'r11-transport-inventory', 'assembled transport record is not canonical')
        else:
            _require(len(raw) <= 100_000, 'r11-transport-inventory', 'large record lacks required parts')
        _require(type(value.get('sequence')) is int and value['sequence'] == index,
                 'r11-transport-inventory', 'record identity differs from its filename')
        total += len(raw) + 1
        _require(total <= 16_777_216, 'r11-transport-inventory', 'assembled transcript exceeds bound')
        records.append(raw + b'\n')
    _require(consumed == set(snapshot), 'r11-transport-inventory', 'orphan or unreferenced transport part')
    return b''.join(records)

def collect_source_review_transport(
    project_root: Path, *, expected_binding: dict[str, str], expected_request: bytes,
    expected_subject: dict[str, Any], body_raw: bytes, role_delivery: bool = False,
) -> dict[str, Any]:
    """Reopen complete durable evidence independently of recorder memory.

    Every private file must participate in one contiguous transcript, whose
    complete RPC/body/two-read semantics are checked before a stable reread.
    This is a procedural archive join, not proof of the process that wrote it.
    Expected request/subject/binding must still come from the outer collector's
    current-source reconstruction. No producer/cost/native authority is granted.
    """
    _require(type(role_delivery) is bool, 'r11-review-mode', 'explicit role delivery mode required')
    _r11_transport_binding(expected_binding)
    root = Path(project_root).absolute()
    directory = root / ('work/release-2-16/evidence/route-bootstrap/shards/'
                         + expected_binding['shardId'] + '/transport')
    before = _r11_transcript_snapshot(root, directory)
    transcript = _r11_reassemble_transcript(before)
    matched = verify_source_review_transport_records(root, expected_binding=expected_binding,
                expected_request=expected_request, expected_subject=expected_subject,
                body_raw=body_raw, transcript_raw=transcript, role_delivery=role_delivery)
    _require(_r11_transcript_snapshot(root, directory) == before,
             'r11-transport-inventory', 'transport files changed during collection')
    inventory = [{'path': (directory / name).relative_to(root).as_posix(),
                  'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                 for name, raw in sorted(before.items())]
    return {'schemaVersion': 'alk-r11-transport-archive-match.v1', 'status': 'TRANSPORT_ARCHIVE_MATCHED',
            'transport': matched, 'privateFileInventory': inventory,
            'privateFileInventorySha256': canonical_digest(inventory),
            'producerQualified': False, 'costQualified': False, 'firstNativeBootstrapEligible': False}

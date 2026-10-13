"""Owned source review shards helpers."""
from __future__ import annotations
from typing import Any
from pathlib import Path
from agent_lifecycle.accounting.declared_ledger_legacy import _R11_REVIEW_ROOT
from agent_lifecycle.accounting.declared_ledger_legacy import _r11_review_private
from agent_lifecycle.contracts.bounded_json import matches_closed_schema as _r11_role_schema_matches
from agent_lifecycle.accounting.declared_ledger_records import _r11_transport_binding
from agent_lifecycle.accounting.declared_ledger_records import _require
from agent_lifecycle.contracts import canonical_bytes
from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.accounting.declared_ledger_legacy import capture_review_validation_sources
from datetime import datetime
import hashlib
from agent_lifecycle.accounting.declared_ledger import read_coordinator_cost_head
from datetime import timezone
from agent_lifecycle.adapter_sessions.source_review_contracts import _r11_coverage_contains
from agent_lifecycle.adapter_sessions.source_review_contracts import _r11_coverage_rows
from agent_lifecycle.adapter_sessions.source_review_inputs import _r11_parent_snapshot
from agent_lifecycle.adapter_sessions.source_review_contracts import _r11_python_index
from agent_lifecycle.adapter_sessions.source_review_contracts import _r11_ranges
from agent_lifecycle.adapter_sessions.source_review_history import _r11_reconstruct_review_basis
from agent_lifecycle.adapter_sessions.source_review_history import _r11_review_authorities
from agent_lifecycle.adapter_sessions.source_review_history import _r11_review_cost_basis
from agent_lifecycle.adapter_sessions.source_review_contracts import _r11_review_directory
from agent_lifecycle.adapter_sessions.source_review_inputs import _r11_review_parent_sources
from agent_lifecycle.adapter_sessions.source_review_contracts import _r11_role_authority
from agent_lifecycle.adapter_sessions.source_review_roles import _r11_role_body
from agent_lifecycle.adapter_sessions.source_review_roles import _r11_role_call_index
from agent_lifecycle.adapter_sessions.source_review_roles import _r11_role_envelope_fit
from agent_lifecycle.adapter_sessions.source_review_roles import _r11_role_integration_closure
from agent_lifecycle.adapter_sessions.source_review_contracts import _r11_role_original_deadline
from agent_lifecycle.adapter_sessions.source_review_roles import _r11_role_project_calls
from agent_lifecycle.adapter_sessions.source_review_roles import _r11_role_request_candidate
from agent_lifecycle.adapter_sessions.source_review_roles import _r11_role_source_basis
from agent_lifecycle.adapter_sessions.source_review_roles import _r11_role_source_content
from agent_lifecycle.adapter_sessions.source_review_roles import _r11_role_source_projection
from agent_lifecycle.adapter_sessions.source_review_roles import _r11_role_wire_request
from agent_lifecycle.adapter_sessions.source_review_inputs import collect_source_review_parent
from agent_lifecycle.adapter_sessions.source_review_contracts import collect_source_review_producer
from agent_lifecycle.adapter_sessions.source_review_contracts import collect_source_review_shared
from agent_lifecycle.adapter_sessions.source_review_history import read_source_review_catalog
from agent_lifecycle.adapter_sessions.source_review_history import read_source_review_cost
from agent_lifecycle.adapter_sessions.source_review_history import read_source_review_request
from agent_lifecycle.adapter_sessions.source_review_contracts import _R11_ENTRYPOINT_PATH


def read_source_review_envelope_fit(project_root: Path, *, review_id: str) -> dict[str, Any]:
    """Independently join all-role bounds to current source/support and catalog.

    This opens no process or model. The selected catalog remains a limited
    bundled diagnostic; fresh live host/thread and accepted SHARED are separate
    sender obligations. A stored/caller-provided fit flag is never consulted.
    """
    root = Path(project_root).absolute();snapshot = capture_review_validation_sources(root)
    basis = _r11_review_cost_basis(root, review_id, role_delivery=True)
    current = read_source_review_cost(root, review_id=review_id, role_delivery=True)
    catalog = read_source_review_catalog(root, review_id=review_id)
    _require(current.get('fundingAdmitted') is True and current.get('rolePrefixesAnchored') is True,
             'r11-role-envelope-funding', 'complete globally admitted budget and matching prefix required')
    identity = basis['identity'];window = catalog['selected']['catalogWindowTokens']
    rebuilt = reconstruct_source_review(root, review_id=review_id, role_delivery=True,
        model_context_window=window, operation_ids=[role['operationId'] for role in identity['inventory']['roles']])
    candidate = rebuilt['candidate']
    _require(candidate.get('status') == 'ROLE_RECONSTRUCTION_UNQUALIFIED' and isinstance(candidate.get('roleBasis'), dict),
             'r11-role-envelope-source', 'current complete source/support reconstruction refused; no model start')
    role_basis = candidate['roleBasis']
    _require(role_basis.get('baseRaw') == canonical_bytes(identity['base'])
             and role_basis.get('roleInventoryRaw') == canonical_bytes(identity['inventory']),
             'r11-role-envelope-source', 'stored base/inventory differ from independent current source/support')
    fit = _r11_role_envelope_fit(root, base_raw=role_basis['baseRaw'], inventory_raw=role_basis['roleInventoryRaw'],
        funding_raw=canonical_bytes(identity['funding']), exposure_raw_by_role=role_basis['roleExposureRaw'],
        model_context_window=window)
    _require(fit['completeEnvelopeFit'], 'r11-role-envelope-overflow', 'at least one complete worst-case role envelope exceeds limits')
    _require(capture_review_validation_sources(root) == snapshot
             and _r11_review_cost_basis(root, review_id, role_delivery=True) == basis
             and read_source_review_cost(root, review_id=review_id, role_delivery=True) == current
             and read_source_review_catalog(root, review_id=review_id) == catalog,
             'r11-role-envelope-stale', 'source/support/role basis/catalog or financial head changed during fit')
    return {**fit, 'status': 'ALL_ROLE_ENVELOPES_FIT_CURRENT_BASIS', 'sourceFreshnessQualified': True,
            'fundingAdmitted': True, 'catalogEvidenceSha256': catalog['evidenceSha256'],
            'validationSourcesSha256': canonical_digest(snapshot),
            'coordinatorHeadSha256': current['fundingOrigin']['currentHeadSha256'],
            'fitScope': 'ALL_ROLE_DECLARED_ALK_INPUT_PLUS_OUTPUT_RESERVE_IN_BUNDLED_CATALOG_LIMIT',
            'hostHiddenInput': 'UNPROVEN', 'actualChildWindow': 'UNPROVEN'}

def _r11_shard_source_content(selected: dict, sources, calls) -> dict[str, Any]:
    return {'sourceContent': _r11_role_source_content(sources, _r11_coverage_rows(sources, selected)), 'callProjection': _r11_role_project_calls(calls, selected)['groups']}

def _r11_shard_lower_bound(content: dict[str, Any]) -> int:
    return len(canonical_bytes({'input': [{'type': 'text', 'text': canonical_bytes(content).decode('utf-8')}]}))

def _r11_shard_packing_size(selected: dict, root, sources, calls, review_id, scopes, pair_rows, closure, limits, authority) -> int:
    content = _r11_shard_source_content(selected, sources, calls)
    if review_id is None:
        return _r11_shard_lower_bound(content)
    contains = lambda target: all((_r11_coverage_contains(selected, key, spans) for key, spans in target.items()))
    assigned_scopes = sorted((name for name, selection in scopes.items() if contains(selection)))
    content.update(staticPairAssignment=[rows for pair, rows in pair_rows if contains(pair)], requiredIntegrationScopes=assigned_scopes, integrationClosureContent={name: closure[name] for name in assigned_scopes}, sharedDecisionView=None, sharedContentSeenByThisRole=False)
    subject = {name: '0' * 64 for name in ('baseSha256', 'roleInventorySha256', 'fundingBatchSha256', 'slotSha256', 'exposureSha256', 'sourceRangeSha256', 'callProjectionSha256', 'staticPairAssignmentSha256', 'sharedEvidenceSha256')}
    subject.update(schemaVersion='alk-r11-role-subject.v1', reviewId=review_id, roleId='source-32', roleKind='SOURCE', requiredIntegrationScopes=assigned_scopes, phase='PRE_WS01', rb11RuntimeStatus='NOT_RUN')
    wire = _r11_role_wire_request(root, index=32, thread_id='\x00' * limits['maxHostIdUtf8Bytes'], subject=subject, content=content, schema=authority['schemas']['reviewerBody'])
    return len(wire) + 2 * limits['sourceSharedDecisionViewMaxRawUtf8Bytes'] - 4

def build_source_review_shards(project_root: Path, *, model_context_window: int, role_delivery: bool=False, review_id: str | None=None, operation_ids: list[str] | None=None, **legacy_inputs: Any) -> dict[str, Any]:
    """Rebuild and pack v6 SOURCE content; never dispatch or declare full fit.

    Historical v5 request/receipt validators remain readable, but its builder
    cannot create a current assignment. With a review ID, first-fit includes a
    conservative complete SOURCE envelope, every contained pair/scope, closure
    text and future shared-view allowance. Without one, source-only diagnostics
    remain unqualified. SHARED and the actual batch still need the full gate.
    """
    _require(type(role_delivery) is bool and role_delivery and (not legacy_inputs), 'r11-role-version', 'current assembly requires explicit v6, without v5 subject/thread inputs')
    _require(type(model_context_window) is int and model_context_window > 0, 'r11-role-context', 'positive declared context required; this does not qualify a host')
    root = Path(project_root).absolute()
    _require((review_id is None) == (operation_ids is None), 'r11-role-operations', 'review and preassigned operations must be supplied together')
    if review_id is not None:
        _r11_review_directory(root, review_id)
        _require(isinstance(operation_ids, list) and 2 <= len(operation_ids) <= 33 and all((_r11_role_schema_matches(value, {'type': 'string', 'minLength': 1, 'maxLength': 256}) for value in operation_ids)) and (len(set(operation_ids)) == len(operation_ids)), 'r11-role-operations', 'distinct bounded shared/source operation IDs required')
    snapshot = capture_review_validation_sources(root)
    basis = _r11_role_source_basis(root)
    sources, required = (basis['sources'], basis['required'])
    dependencies, scopes = (basis['dependencies'], basis['integrationScopes'])
    authority = _r11_role_authority(root)
    limits = authority['contract']['limits']
    cap = min(limits['requestMaxUtf8Bytes'], limits['perRoleWorkTokens'] - limits['structuredOutputReserveTokens'], model_context_window - limits['structuredOutputReserveTokens'] - limits['contextSafetyTokens'])
    calls = _r11_role_call_index(sources, dependencies)
    metrics = {'schemaVersion': 'alk-r11-role-source-assembly.v1', 'sourceBasisSubject': basis['subject'], 'sourceContentByteCeiling': cap, 'modelContextWindow': model_context_window, 'maxSourceRoles': limits['maxSourceRoles'], 'completeEnvelopeFit': False, 'hostContextQualified': False, 'fundingAdmitted': False, 'sharedEvidenceAccepted': False, 'dispatchAllowed': False, 'firstNativeBootstrapEligible': False}

    def finish(status: str, **details: Any) -> dict[str, Any]:
        _require(capture_review_validation_sources(root) == snapshot and _r11_role_authority(root) == authority and (collect_source_review_parent(root) == basis['parent']) and (_r11_review_parent_sources(root, basis['partition']) == {name: raw for (version, name), raw in sources.items() if version == 'PARENT'}), 'r11-role-assembly-stale', 'source, locked authority or retained parent changed during packing')
        return {**metrics, 'status': status, **details}

    def deny(code: str, **details: Any) -> dict[str, Any]:
        return finish('DENY', reasonCode=code, refusalStage='PRE_SEND', sourceProjection=None, sourceContent=[], **details)

    def merge(left: dict, right: dict) -> dict:
        return {key: _r11_ranges(left.get(key, []) + right.get(key, [])) for key in sorted(left.keys() | right.keys())}
    scope_sizes = {name: _r11_shard_lower_bound(_r11_shard_source_content(selection, sources, calls)) for name, selection in sorted(scopes.items())}
    metrics['mandatoryScopeLowerBoundBytes'] = scope_sizes
    if cap <= 0 or any((size > cap for size in scope_sizes.values())):
        return deny('r11-role-mandatory-scope-overflow')
    closure = {}
    if review_id is not None:
        parent_raw = _r11_parent_snapshot(root)[0]['review-body.raw'].decode('utf-8')
        terminal = _r11_review_authorities(root, role_delivery=True)['terminalContractContent']
        closure = _r11_role_integration_closure(parent_raw, terminal, authority, sorted(scopes))
    pair_rows = [(pair, _r11_coverage_rows(sources, pair)) for pair in basis['staticPairs']]
    metrics['packingFitScope'] = 'COMPLETE_SOURCE_ENVELOPE_UPPER_BOUND' if review_id is not None else 'SOURCE_ONLY_LOWER_BOUND'
    if any((_r11_shard_packing_size(selection, root, sources, calls, review_id, scopes, pair_rows, closure, limits, authority) > cap for selection in scopes.values())):
        return deny('r11-role-mandatory-envelope-overflow')
    seeds = list(scopes.values()) + basis['staticPairs']
    for key in sorted(required):
        raw = sources[key]
        units = _r11_python_index(raw, key[1])['units'] if key[1].endswith('.py') else []
        boundaries = sorted({0, len(raw), *(u['start'] for u in units), *(u['end'] for u in units)})
        for start, end in required[key]:
            cuts = [start] + [point for point in boundaries if start < point < end] + [end]
            seeds.extend(({key: [(a, b)]} for a, b in zip(cuts, cuts[1:])))
    selections: list[dict] = []
    for seed in seeds:
        if any((all((_r11_coverage_contains(part, key, spans) for key, spans in seed.items())) for part in selections)):
            continue
        if _r11_shard_packing_size(seed, root, sources, calls, review_id, scopes, pair_rows, closure, limits, authority) > cap:
            return deny('r11-role-complete-unit-or-pair-overflow')
        for index, part in enumerate(selections):
            combined = merge(part, seed)
            if _r11_shard_packing_size(combined, root, sources, calls, review_id, scopes, pair_rows, closure, limits, authority) <= cap:
                selections[index] = combined
                break
        else:
            if len(selections) == limits['maxSourceRoles']:
                return deny('r11-role-packing-exceeds-policy', packingAlgorithm='SORTED_FIRST_FIT')
            selections.append(seed)
    primaries = {name: next((f'source-{i + 1:02d}' for i, part in enumerate(selections) if all((_r11_coverage_contains(part, key, spans) for key, spans in scope.items())))) for name, scope in scopes.items()}
    projection = _r11_role_source_projection(sources, required, dependencies, [_r11_coverage_rows(sources, part) for part in selections], primaries)
    content = [{'roleId': role['roleId'], **_r11_shard_source_content(part, sources, calls), 'staticPairAssignment': role['staticPairAssignment'], 'requiredIntegrationScopes': role['requiredIntegrationScopes']} for role, part in zip(projection['roles'], selections)]
    sizes = [_r11_shard_lower_bound(row) for row in content]
    if any((size > cap for size in sizes)):
        return deny('r11-role-assigned-content-overflow', assignedContentLowerBoundBytes=sizes)
    if review_id is not None:
        envelope_sizes = [_r11_shard_packing_size(part, root, sources, calls, review_id, scopes, pair_rows, closure, limits, authority) for part in selections]
        if any((size > cap for size in envelope_sizes)):
            return deny('r11-role-assigned-envelope-overflow', assignedCompleteEnvelopeUpperBoundBytes=envelope_sizes)
        metrics['assignedCompleteEnvelopeUpperBoundBytes'] = envelope_sizes
        role_basis = _r11_reconstruct_review_basis(root, review_id, source_basis=basis, projection=projection, source_content=content, operation_ids=operation_ids)
        return finish('ROLE_RECONSTRUCTION_UNQUALIFIED', sourceProjection=projection, sourceContent=content, assignedContentLowerBoundBytes=sizes, roleBasis=role_basis)
    return finish('ROLE_SOURCE_ASSEMBLY_UNQUALIFIED', sourceProjection=projection, sourceContent=content, assignedContentLowerBoundBytes=sizes, missingEnvelopeParts=['sharedSupportAndReceipt', 'integrationClosureContent', 'subjectFundingAndProtocol', 'worstCaseTemplates', 'selectedHostProof'])

def reconstruct_source_review(project_root: Path, *, review_id: str,
                              model_context_window: int, thread_ids: list[str] | None = None,
                              role_delivery: bool = False, operation_ids: list[str] | None = None) -> dict[str, Any]:
    """Reconstruct a v6 immutable preparation candidate or pre-send refusal.

    Caller-authored source/subjects and early thread bindings are not accepted.
    Raw SHARED support is prepared here, never accepted as reviewer evidence.
    """
    _require(type(role_delivery) is bool and role_delivery and thread_ids is None
             and operation_ids is not None,
             'r11-role-version', 'explicit v6 with preassigned operations and no legacy threads required')
    candidate = build_source_review_shards(project_root, role_delivery=True,
        model_context_window=model_context_window, review_id=review_id, operation_ids=operation_ids)
    return {'schemaVersion': 'alk-r11-reconstructed-role-review.v1', 'reviewId': review_id,
            'status': candidate['status'], 'candidate': candidate,
            'hostContextQualified': False, 'producerQualified': False,
            'dispatchAllowed': False, 'firstNativeBootstrapEligible': False}

def _r11_role_send_basis(root: Path, *, binding: dict[str, str], request_raw: bytes,
                          subject: dict[str, Any], binary_path: Path, model: str,
                          completed: bool = False) -> dict[str, Any]:
    """Reopen every pre-model input; private sender guard, not producer approval."""
    from .codex_input_diagnostics import _file_sha
    _require(type(completed) is bool, 'r11-role-send-mode', 'explicit completed read mode required')
    _r11_transport_binding(binding)
    _require(isinstance(subject, dict), 'r11-role-send', 'role subject required')
    _require(subject.get('roleKind') in {'SHARED', 'SOURCE'}
             and subject.get('roleId') == binding['shardId'],
             'r11-role-send', 'exact assigned role subject required')
    review_id = subject.get('reviewId')
    sealed = read_source_review_request(root, review_id=review_id, role_id=binding['shardId'], require_reservation=True)
    shared = collect_source_review_shared(root, review_id=review_id) if subject['roleKind'] == 'SOURCE' else None
    if shared is not None:
        _require(sealed['seal'].get('schemaVersion') == 'alk-r11-role-request-seal.v2-origin'
                 and sealed['seal'].get('metadataOrigin', {}).get('sharedEvidenceSha256')
                     == subject['sharedEvidenceSha256'] == hashlib.sha256(shared['evidenceRaw']).hexdigest(),
                 'r11-role-shared-unqualified', 'SOURCE sender requires original metadata and exact accepted SHARED')
    fit = read_source_review_envelope_fit(root, review_id=review_id)
    catalog = read_source_review_catalog(root, review_id=review_id)
    _require(sealed['seal']['binding'] == binding and sealed['requestRaw'] == request_raw
             and sealed['subject'] == subject and fit['catalogEvidenceSha256'] == catalog['evidenceSha256']
             and str(binary_path) == catalog['binaryPath'] and catalog['selected']['model'] == model
             and catalog['selected']['binarySha256'] == binding['binarySha256'] == _file_sha(binary_path)
             and binding['transportSourceSha256'] == _file_sha(_R11_ENTRYPOINT_PATH)
             and fit['completeEnvelopeFit'] is True,
             'r11-role-send', 'exact reserved request, current all-envelope fit or selected binary/model differs')
    rows = [row for row in fit['rows'] if row['roleId'] == binding['shardId']]
    _require(len(rows) == 1 and len(request_raw) <= rows[0]['requestUtf8ByteUpperBound'],
             'r11-role-send-fit', 'actual role request exceeds its complete pre-model upper bound')
    current = read_source_review_cost(root, review_id=review_id, role_delivery=True)
    metadata_origin = sealed['seal'].get('metadataOrigin')
    evidence_fit = dict(fit);chain_sha = current['costChainSha256'];head_sha = current['fundingOrigin']['currentHeadSha256']
    if metadata_origin is not None:
        reservations = [row for row in current['reservations'] if row['binding'] == binding]
        steps = [row for row in current['fundingOrigin']['costPrefix']['steps']
                 if row['recordPath'] == binding['shardId'] + '/reservation.json']
        _require(len(reservations) == 1 and reservations[0]['binding'] == binding and len(steps) == 1
                 and steps[0]['recordSha256'] == canonical_digest(reservations[0])
                 and metadata_origin['model'] == model,
                 'r11-role-send-prefix', 'unique original reserved role prefix and metadata model required')
        chain_sha, head_sha = steps[0]['costChainSha256'], steps[0]['headSha256']
        if completed:
            settlements = [row for row in current['settlements'] if row.get('binding') == binding]
            _require(len(settlements) == 1 and settlements[0]['worker']['state'] == 'WORKER_PROCESS_FINISHED',
                     'r11-role-send-completed', 'completed collection requires independently settled successful worker')
            # All current immutable fit/source/catalog values are reopened; only
            # the globally proven original reservation head replaces its suffix.
            evidence_fit['coordinatorHeadSha256'] = head_sha
        else:
            _require(current['costChainSha256'] == chain_sha and current['fundingOrigin']['currentHeadSha256'] == head_sha,
                     'r11-role-send-prefix', 'origin-bound dispatch must use its original reservation head, without interleaved windows')
            _r11_role_original_deadline(metadata_origin, 1)
    else:
        _require(not completed, 'r11-role-send-completed', 'declared-only request cannot qualify completed model origin')
    if not completed:
        cost = _r11_cost_before_start(root, review_id, binding, current['declaredUnknownHoldsAtFunding'], 1, role_delivery=True)
        _require(cost == current and fit['coordinatorHeadSha256'] == current['fundingOrigin']['currentHeadSha256'],
                 'r11-role-send-stale', 'cost prefix changed during pre-model qualification')
    _require(read_source_review_cost(root, review_id=review_id, role_delivery=True) == current,
             'r11-role-send-stale', 'financial evidence changed during reconstruction')
    if shared is not None:
        _require(collect_source_review_shared(root, review_id=review_id) == shared,
                 'r11-role-shared-stale', 'SHARED changed before SOURCE model admission')
    return {**({'sharedEvidenceSha256': subject['sharedEvidenceSha256']} if shared is not None else {}),
            **({'metadataOriginSha256': canonical_digest(metadata_origin),
                'operationStartSha256': metadata_origin['operationStartSha256'],
                'absoluteDeadlineUtc': metadata_origin['absoluteDeadlineUtc'],
                'deadlineMonotonicNs': metadata_origin['deadlineMonotonicNs']} if metadata_origin is not None else {}),
            'reviewId': review_id, 'requestSealSha256': sealed['sealSha256'],
            'envelopeFitSha256': canonical_digest(evidence_fit), 'catalogEvidenceSha256': catalog['evidenceSha256'],
            'costChainSha256': chain_sha,
            'coordinatorHeadSha256': head_sha,
            'producerQualified': False, 'firstNativeBootstrapEligible': False}

def _r11_cost_before_start(root: Path, review_id: str, binding: dict[str, str],
                           held: int, timeout: int, *, role_delivery: bool = False) -> dict[str, Any]:
    _require(role_delivery is True, 'r11-v5-runtime-retired',
             'current review execution requires explicit v6 role delivery')
    from datetime import timezone
    _require(type(role_delivery) is bool, 'r11-cost-mode', 'explicit cost delivery mode required')
    cost = read_source_review_cost(root, review_id=review_id, role_delivery=role_delivery)
    _require(cost.get('fundingAdmitted') is True and cost.get('rolePrefixesAnchored') is True
             and cost['reservations'] and len(cost['reservations']) == len(cost['settlements']) + 1
             and cost['reservations'][-1]['binding'] == binding
             and type(held) is int and cost['declaredUnknownHoldsAtFunding'] == held
             and type(timeout) is int and 0 < timeout <= 1800,
             'r11-role-cost-admission', 'one current funded role, exact hold and bounded timeout required')
    sealed = read_source_review_request(root, review_id=review_id, role_id=binding['shardId'], require_reservation=True)
    _require(sealed['seal']['binding'] == binding and sealed['requestSha256'] == cost['reservations'][-1]['requestSha256'],
             'r11-role-cost-admission', 'worker differs from independently reopened sealed reservation')
    prior = read_coordinator_cost_head(root)
    _require(prior['headSha256'] == cost['fundingOrigin']['currentHeadSha256']
             and (prior['source'].get('schemaVersion') in {'alk-r11-global-role-funding.v1', 'alk-r11-global-role-prefix.v1'}
                  or Path(prior['head']['sourcePath']).name == 'cost.json')
             and read_source_review_cost(root, review_id=review_id, role_delivery=True) == cost,
             'r11-role-cost-stale', 'global prefix changed or coordinator window remains open')
    now = datetime.now(timezone.utc)
    reserved = cost['reservations'][-1]
    _require(datetime.fromisoformat(reserved['reservedAtUtc'].replace('Z', '+00:00')) <= now
             and timeout < (datetime.fromisoformat(reserved['absoluteDeadlineUtc'].replace('Z', '+00:00')) - now).total_seconds(),
             'r11-role-cost-deadline', 'worker would reset/exceed original role deadline or clock moved backwards')
    if 'metadataOrigin' in sealed['seal']:
        _r11_role_original_deadline(sealed['seal']['metadataOrigin'], timeout)
    return cost

def _r11_completed_assignment(root: Path, review_id: str, *, role_delivery: bool = False,
                              with_evidence: bool = False) -> dict[str, Any]:
    """Rebuild all realized v6 roles from their raw proof, never assignment claims.

    Historical per-role success remains readable after a later failure. This
    all-role join requires a complete current batch and grants no native entry.
    """
    _require(type(role_delivery) is bool and role_delivery and type(with_evidence) is bool,
             'r11-role-version', 'explicit v6 completed-assignment mode required')
    root = Path(root).absolute()
    basis = _r11_review_cost_basis(root, review_id, role_delivery=True)
    identity = basis['identity'];roles = identity['inventory']['roles']
    cost = read_source_review_cost(root, review_id=review_id, role_delivery=True)
    _require(cost.get('fundingAdmitted') is True and cost.get('rolePrefixesAnchored') is True
             and cost['allRolesSettled'] is True and not cost['unreservedRoleIds']
             and len(cost['reservations']) == len(cost['settlements']) == len(roles)
             and [row['roleId'] for row in cost['reservations']] == [role['roleId'] for role in roles]
             and [row['binding']['shardId'] for row in cost['settlements']] == [role['roleId'] for role in roles]
             and all(row['worker']['state'] == 'WORKER_PROCESS_FINISHED' for row in cost['settlements']),
             'r11-role-assignment-incomplete', 'all exact roles require successful globally anchored settlements')
    deadline = datetime.fromisoformat(identity['funding']['absoluteDeadlineUtc'].replace('Z', '+00:00'))
    _require(datetime.now(timezone.utc) < deadline, 'r11-role-batch-expired', 'completed batch is no longer current')
    catalog = read_source_review_catalog(root, review_id=review_id)
    fit = read_source_review_envelope_fit(root, review_id=review_id)
    options = {'review_id': review_id, 'role_delivery': True,
               'model_context_window': catalog['selected']['catalogWindowTokens'],
               'operation_ids': [role['operationId'] for role in roles]}
    rebuilt = reconstruct_source_review(root, **options);candidate = rebuilt['candidate']
    _require(candidate.get('status') == 'ROLE_RECONSTRUCTION_UNQUALIFIED'
             and candidate['roleBasis']['baseRaw'] == canonical_bytes(identity['base'])
             and candidate['roleBasis']['roleInventoryRaw'] == canonical_bytes(identity['inventory'])
             and set(candidate['roleBasis']['roleExposureRaw']) == {role['roleId'] for role in roles}
             and candidate['sourceBasisSubject']['parentVerdict'] == 'FAIL'
             and fit['completeEnvelopeFit'] is True and fit['sourceFreshnessQualified'] is True
             and fit['catalogEvidenceSha256'] == catalog['evidenceSha256']
             and fit['coordinatorHeadSha256'] == cost['fundingOrigin']['currentHeadSha256'],
             'r11-role-assignment-source', 'current complete source/support/catalog/ledger reconstruction required')
    shared = collect_source_review_shared(root, review_id=review_id)
    shared_sha = hashlib.sha256(shared['evidenceRaw']).hexdigest()
    _require(shared['sharedEvidenceAccepted'] is True
             and shared['evidenceRaw'] == canonical_bytes(shared['receipt']),
             'r11-role-assignment-shared', 'independently accepted exact SHARED receipt required')

    def read_role(index: int) -> tuple[dict[str, Any], dict[str, Any]]:
        role = roles[index];role_id = role['roleId']
        sealed = read_source_review_request(root, review_id=review_id, role_id=role_id, require_reservation=True)
        binding = sealed['seal']['binding']
        expected = _r11_role_request_candidate(root, base_raw=candidate['roleBasis']['baseRaw'],
            inventory_raw=candidate['roleBasis']['roleInventoryRaw'], funding_raw=canonical_bytes(identity['funding']),
            role_id=role_id, exposure_raw=candidate['roleBasis']['roleExposureRaw'][role_id],
            thread_id=binding['threadId'], model_context_window=options['model_context_window'],
            shared_evidence_raw=None if index == 0 else shared['evidenceRaw'],
            shared_body_raw=None if index == 0 else shared['bodyRaw'])
        reservation, settlement = cost['reservations'][index], cost['settlements'][index]
        _require(binding['shardId'] == role_id and binding['operationId'] == role['operationId']
                 and sealed['seal'].get('schemaVersion') == 'alk-r11-role-request-seal.v2-origin'
                 and sealed['subject'] == expected['subject'] and sealed['requestRaw'] == expected['requestRaw']
                 and sealed['requestSha256'] == expected['requestSha256'] == reservation['requestSha256']
                 and reservation['subjectSha256'] == canonical_digest(expected['subject'])
                 and reservation['binding'] == settlement['binding'] == binding
                 and settlement['reservationSha256'] == canonical_digest(reservation)
                 and reservation['sharedEvidenceSha256'] == (None if index == 0 else shared_sha),
                 'r11-role-assignment-request', 'actual original request/subject/operation or settled slot differs')
        producer = collect_source_review_producer(root, review_id=review_id, shard_id=role_id, role_delivery=True)
        body_raw = _r11_review_private(root, root / _R11_REVIEW_ROOT / 'shards' / role_id / 'review-body.raw')
        body = _r11_role_body(body_raw, subject=expected['subject'], schemas=basis['schemas'])
        matched = producer['transport']['transport']['bodyReadMatch']
        _require(producer['producerQualified'] is True and producer['binding'] == binding
                 and producer['requestSha256'] == expected['requestSha256']
                 and producer['costReservationSha256'] == canonical_digest(reservation)
                 and producer['costSettlementSha256'] == canonical_digest(settlement)
                 and producer['workerEvidenceSha256'] == canonical_digest(settlement['worker']['evidenceSha256'])
                 and matched['subjectSha256'] == body['subjectSha256']
                 and matched['bodySha256'] == body['bodyRawSha256']
                 and matched['roleId'] == role_id and matched['roleKind'] == role['roleKind']
                 and matched['threadId'] == binding['threadId']
                 and matched['approvedIntegrationScopes'] == body['approvedIntegrationScopes']
                 and matched['closedParentFindingIds'] == [],
                 'r11-role-assignment-producer', 'exact body/transport/worker/settlement proof differs')
        if index == 0:
            _require(producer == shared['producer'] and body_raw == shared['bodyRaw']
                     and shared['receipt']['binding'] == binding,
                     'r11-role-assignment-shared', 'realized SHARED differs from the accepted SOURCE predecessor')
        evidence = {'roleId': role_id, 'roleKind': role['roleKind'], 'subject': expected['subject'],
                    'requestSha256': expected['requestSha256'], 'requestSealSha256': sealed['sealSha256'],
                    'bodyMatch': body, 'producer': producer}
        row = {'roleId': role_id, 'roleKind': role['roleKind'], 'subjectSha256': body['subjectSha256'],
               'requestSha256': expected['requestSha256'], 'reservationSha256': canonical_digest(reservation),
               'settlementSha256': canonical_digest(settlement), 'evidenceSha256': canonical_digest(evidence),
               'binding': binding}
        return row, evidence

    collected = [read_role(index) for index in range(len(roles))]
    rows, evidence = [item[0] for item in collected], [item[1] for item in collected]
    _require(all(len({row['binding'][key] for row in rows}) == len(rows) for key in ('threadId', 'operationId')),
             'r11-role-assignment-reused', 'realized roles reuse a model thread or operation')
    approvals = [{'scope': scope, 'roleId': item['roleId'], 'roleEvidenceSha256': row['evidenceSha256']}
                 for row, item in collected for scope in item['bodyMatch']['approvedIntegrationScopes']]
    _require(sorted(item['scope'] for item in approvals) == ['COLLECTOR_FIRST_NATIVE', 'OBSERVER_TERMINAL']
             and all(item['roleId'] != 'shared-01' for item in approvals),
             'r11-role-parent-closure', 'both exact designated SOURCE scope approvals required after every role PASS')
    assignment = {'schemaVersion': 'alk-r11-role-assignment.v2', 'reviewId': review_id,
        **{key: identity[key] for key in ('baseSha256', 'roleInventorySha256', 'fundingBatchSha256')},
        'sharedEvidenceSha256': shared_sha, 'roles': rows}
    _require(_r11_role_schema_matches(assignment, basis['schemas']['completedAssignment']),
             'r11-role-assignment-shape', 'realized assignment violates the pinned closed schema')
    _require(_r11_review_cost_basis(root, review_id, role_delivery=True) == basis
             and read_source_review_cost(root, review_id=review_id, role_delivery=True) == cost
             and read_source_review_catalog(root, review_id=review_id) == catalog
             and read_source_review_envelope_fit(root, review_id=review_id) == fit
             and reconstruct_source_review(root, **options) == rebuilt
             and collect_source_review_shared(root, review_id=review_id) == shared
             and [read_role(index) for index in range(len(roles))] == collected
             and read_source_review_cost(root, review_id=review_id, role_delivery=True) == cost
             and datetime.now(timezone.utc) < deadline,
             'r11-role-assignment-stale', 'earlier role/source/support/SHARED/ledger changed during all-role collection')
    if not with_evidence:
        return assignment
    return {'schemaVersion': 'alk-r11-review-evidence-match.v2-role', 'status': 'ROLE_EVIDENCE_MATCHED',
        'assignment': assignment, 'roleEvidence': evidence, 'sharedEvidence': shared['receipt'],
        'orderedRoleEvidenceSha256': canonical_digest(evidence),
        'integrationApprovals': sorted(approvals, key=lambda row: row['scope']),
        'coverageUnionSha256': candidate['sourceProjection']['coverageUnionSha256'],
        'callExpansionSha256': candidate['sourceBasisSubject']['callExpansionSha256'],
        'sourceBasisSubject': candidate['sourceBasisSubject'], 'cost': cost,
        'openingOrigin': basis['openingOrigin'], 'catalogEvidenceSha256': catalog['evidenceSha256'],
        'parentVerdict': 'FAIL', 'eligibleParentFindingIds': ['RB-OBSERVER-TIMEOUT-01'],
        'parentClosureEligible': True, 'producerQualified': False, 'hostContextQualified': False, 'actualModelTokens': None,
        'firstNativeBootstrapEligible': False}

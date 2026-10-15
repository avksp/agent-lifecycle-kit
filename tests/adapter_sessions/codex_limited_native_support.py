"""Opt-in release qualification producer, separate from normal unit fixtures.

Positive rows call the public managed launcher without test replacements. All
rows are create-once within the existing task attempt. This module never closes
or renews a coordinator/ordinary admission and never creates a workflow run.
"""
from __future__ import annotations

import hashlib
from contextlib import closing
import json
import os
import sys
from pathlib import Path

from agent_lifecycle.accounting.host_bridge import ARTIFACT_BYTES, BoundedReader, _json
from agent_lifecycle.adapter_sessions.attempt_authority import _invocation_namespace, _sync_directory
from agent_lifecycle.adapter_sessions.codex_exact_prompt import stage_input_request
from agent_lifecycle.adapter_sessions.launch_preflight import launch_from_local_profile, _original_attempt_deadline
from agent_lifecycle.adapter_sessions.limited_native_evidence import (
    ADMISSION_PATH, CLAIM, LOCAL_FAULT_CODE, PRODUCERS, ROUTE, native_rows,
    native_success_event, read_native_admission, read_ref, require, _verify_case,
)
from agent_lifecycle.adapter_sessions.private_input import _write_exclusive
from agent_lifecycle.adapter_sessions.process import run_process
from agent_lifecycle.contracts import canonical_bytes
from agent_lifecycle.contracts.paths import normalize_repo_path


def _ref(root: Path, path: Path) -> dict:
    raw = path.read_bytes()
    return {'path': path.relative_to(root).as_posix(), 'bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest()}


def _write(root: Path, path: Path, value: dict | bytes) -> dict:
    _write_exclusive(path, value if isinstance(value, bytes) else canonical_bytes(value), root=root)
    # Persist each newly created directory link as well as the already fsynced
    # file. An uncertain write never reaches dispatch and never releases credit.
    current = path.parent
    while current.is_relative_to(root):
        _sync_directory(current)
        if current == root: break
        current = current.parent
    return _ref(root, path)


def _case_path(root: Path, row: dict, state: dict, task: dict) -> Path:
    relative = row['receiptPathTemplate'].format(runId=state['runId'], taskId=task['id'], attemptId=str(task['attempt']))
    return root / normalize_repo_path(relative, label='native case')


def _read_context(root: Path, reader: BoundedReader) -> tuple[dict, dict, dict, dict, dict]:
    manifest = _json(reader.read(root, 'tasks/release-2-16/plan.manifest.json', ARTIFACT_BYTES))
    # Read just the admission pointer to locate the current state. The complete
    # admission and its original capacity are checked before any claim/action.
    pointer = _json(reader.read(root, ADMISSION_PATH, ARTIFACT_BYTES))
    state_path = normalize_repo_path(pointer['statePath'], label='native workflow state')
    state = _json(reader.read(root, state_path, ARTIFACT_BYTES))
    task = next(t for t in state['tasks'] if t['id'] == pointer['taskId'])
    admission, admission_ref = read_native_admission(root, reader, manifest=manifest, state=state, task=task, live=True)
    require(admission['localPythonExecutable'] == str(Path(sys.executable).resolve()), 'Supported local Python differs')
    return manifest, state, task, admission, admission_ref


def _launch(root: Path, row: dict, admission: dict, state: dict, task: dict, reader: BoundedReader) -> dict:
    spec = admission['cases'][row['caseId']]
    launch = _json(read_ref(root, spec['launchSpecRef'], reader))
    template = _json(read_ref(root, launch['inputTemplateRef'], reader))
    require(template['role'] == row['role'] and template['operationId'] == spec['operationId']
            and template['runId'] == state['runId'] and template['taskId'] == task['id']
            and template['attemptId'] == str(task['attempt']) and template['requestedClaim'] == CLAIM,
            'Input template is not this operation')
    profile_raw = read_ref(root, launch['profileRef'], reader)
    # No direct API key route. Existing private account authentication stays in
    # the independently prepared per-operation CODEX_HOME and is never printed.
    require(not any(key in profile_raw.decode().upper() for key in ('OPENAI_API_KEY', 'CODEX_API_KEY')),
            'API-key launch profiles are excluded')
    if row['polarity'] == 'PRELAUNCH_REFUSAL':
        template['packetSha256'] = '0' * 64
    requested = 'COMPLETE_HOST_INPUT_FIT' if row['polarity'] == 'STRONG_REFUSAL' else CLAIM
    staged = stage_input_request(root, spec['operationId'], {k: v for k, v in template.items() if k != 'attemptId'})
    env = {k: v for k, v in os.environ.items() if k not in {'OPENAI_API_KEY', 'CODEX_API_KEY'}}
    return launch_from_local_profile(
        profile_path=root / launch['profileRef']['path'], operation='managedTask', adapter_id='codex',
        session_id='native69-' + row['caseId'], project_root=root, explicit_launch=True,
        state_path=root / admission['statePath'], manifest_path=root / 'tasks/release-2-16/plan.manifest.json',
        lock_path=root / 'tasks/release-2-16/plan.lock.json', task_id=task['id'],
        operation_id=spec['operationId'], source_revision=state['sourceRevision'],
        risk_profile=launch['riskProfile'], immutable_input_request=launch['immutableInputRequest'],
        route_id=ROUTE, requested_claim=requested, input_request=staged, process_env=env,
    )



def _reserve_selected_slot(root: Path, output: Path, *, row: dict, admission: dict,
                           admission_ref: dict, claim_ref: dict) -> dict:
    """Each selected invocation owns one of at most six create-exclusive slots."""
    for index in range(admission['maxSelectedCodexInvocations']):
        path = output.parent.parent / 'capacity-slots' / f'slot-{index}.json'
        body = {'schemaVersion': 'alk-r69-selected-invocation-slot.v1', 'slotIndex': index,
                'caseId': row['caseId'], 'operationId': admission['cases'][row['caseId']]['operationId'],
                'admissionSha256': admission_ref['sha256'], 'claimSha256': claim_ref['sha256']}
        try:
            return _write(root, path, body)
        except Exception as exc:
            # _write_exclusive wraps the actual O_EXCL collision. Other IO or
            # durability failures must stop, including after a partial write.
            if isinstance(exc.__cause__, FileExistsError):
                continue
            raise
    require(False, 'Selected invocation capacity exhausted; claims and unknown holds retained')


def produce_case(root: Path, case_id: str, selector: str) -> dict:
    """Run exactly one explicitly selected row; missing authority never defaults."""
    root = root.resolve()
    require(os.environ.get('ALK_R69_FINITE_ADMISSION') == ADMISSION_PATH,
            'Explicit canonical native admission required')
    require(sys.argv[1:] == [selector, '-q'], 'Only the exact one-row frozen unittest command is permitted')
    with closing(BoundedReader()) as reader:
        manifest, state, task, admission, admission_ref = _read_context(root, reader)
        rows = native_rows(root, reader)
        require(set(admission['cases']) == {r['caseId'] for r in rows}, 'Native admission row set differs')
        row = next(r for r in rows if r['caseId'] == case_id)
        require(selector == row['testSelector'], 'Selected native method differs from frozen row')
        output = _case_path(root, row, state, task)
        spec = admission['cases'][case_id]
        # Claims are reserved before any model/local child action and survive
        # errors, timeout and overrun. A repeat never acquires new credit.
        claim_ref = _write(root, Path(str(output) + '.claim.json'), {
            'schemaVersion': 'alk-r69-native-case-claim.v1', 'caseId': case_id,
            'operationId': spec['operationId'], 'admissionSha256': admission_ref['sha256']})
        slot_ref = (_reserve_selected_slot(root, output, row=row, admission=admission,
                     admission_ref=admission_ref, claim_ref=claim_ref) if row['polarity'] == 'POSITIVE' else None)
        producer_refs = [_ref(root, root / p) for p in PRODUCERS]
        subject = {key: None for key in row['subjectRequired']}
        subject.update(r69LockSha256=admission['lockSha256'], runId=state['runId'], taskId=task['id'],
                       attemptId=str(task['attempt']), role=row['role'], planDigest=state['planDigest'],
                       requestedClaim='COMPLETE_HOST_INPUT_FIT' if row['polarity'] == 'STRONG_REFUSAL' else CLAIM,
                       costStatus='UNAVAILABLE')
        native_refs = {}
        event = None
        if row['polarity'] == 'STARTED_FAILURE':
            raw = canonical_bytes({'runId': state['runId'], 'taskId': task['id'], 'attemptId': str(task['attempt']),
                                   'role': row['role'], 'operationId': spec['operationId'], 'controlledExit': 7})
            native_refs['rawInput'] = _write(root, Path(str(output) + '.local-stdin.bin'), raw)
            start_path = Path(str(output) + '.local-start.json')
            input_path = Path(str(output) + '.local-input.json')
            result = run_process(
                [admission['localPythonExecutable'], '-c', LOCAL_FAULT_CODE], env={}, cwd=root,
                stdin_text=raw.decode(), timeout_seconds=10, max_input_bytes=65536,
                absolute_deadline_monotonic_ns=_original_attempt_deadline(state, task),
                operation_id=spec['operationId'], attempt_id=str(task['attempt']), adapter_id='local-fault-only',
                on_started=lambda e: _write(root, start_path, e),
                on_input=lambda e: _write(root, input_path, e))
            result_ref = _write(root, Path(str(output) + '.result.json'), result)
            native_refs.update(start=_ref(root, start_path), input=_ref(root, input_path))
            subject.update(finalPromptSha256=hashlib.sha256(raw).hexdigest(),
                           argvDigest=result['startObservation']['commandIdentityHash'])
        else:
            result = _launch(root, row, admission, state, task, reader)
            result_ref = _write(root, Path(str(output) + '.result.json'), result)
            if row['polarity'] == 'POSITIVE':
                event = native_success_event(result['exactPrompt']['observedProcessResult'])
                ns = _invocation_namespace(state['runId'], task['id'], str(task['attempt']), spec['operationId'])
                directory = root / 'work/release-2-16/evidence/codex-exact-prompt' / ns
                names = {'intent': 'prelaunch-intent.json', 'start': 'process-start.json', 'input': 'process-input.json',
                         'transport': 'transport-equivalence.json', 'terminal': 'attempt-result-terminal.json'}
                native_refs = {k: _ref(root, directory / name) for k, name in names.items()}
                intent = json.loads((directory / names['intent']).read_bytes())
                argv = json.loads((directory / names['start']).read_bytes())['observedArgv']
                subject.update(finalPromptSha256=intent['finalPromptSha256'], packetSha256=intent['packetSha256'],
                    selectedBinarySha256=intent['binarySha256'], selectedModel=argv[argv.index('-m') + 1],
                    argvDigest=intent['commandIdentityHash'], configSourceSha256=intent['configManifestSha256'],
                    diagnosticCandidateSha256=intent['diagnosticObservation']['rawSha256'])
        case = {'schemaVersion': 'alk-r69-native-case.v1', 'status': 'PASS', 'caseId': case_id,
                'executionClass': row['executionClass'], 'subject': subject, 'operationId': spec['operationId'],
                'alkCandidateDigest': admission['alkCandidateDigest'], 'producerRefs': producer_refs,
                'admissionRef': admission_ref, 'claimRef': claim_ref, 'capacitySlotRef': slot_ref, 'resultRef': result_ref, 'nativeRefs': native_refs,
                'nativeSuccessEvent': event, 'localFault': row['polarity'] == 'STARTED_FAILURE',
                'selectedCodexInvocationsStarted': int(row['polarity'] == 'POSITIVE'),
                'providerModelRequestCount': None, 'completeFinancialRun': False,
                'costStatus': 'UNAVAILABLE', 'fullUnknownHoldRetained': True}
        # Persist a candidate even if its requested outcome failed; failure must
        # retain the actual result and claim. Only a verified row gets PASS.
        case['status'] = 'OBSERVED_NOT_YET_VERIFIED'
        provisional = Path(str(output) + '.observed.json')
        _write(root, provisional, case)
        case['status'] = 'PASS'
        raw = canonical_bytes(case)
        final_ref = {'path': output.relative_to(root).as_posix(), 'bytes': len(raw),
                     'sha256': hashlib.sha256(raw).hexdigest()}
        try:
            _verify_case(root, final_ref, case=case, reader=reader, row=row, manifest=manifest,
                state=state, task=task, candidate_digest=admission['alkCandidateDigest'], admission=admission,
                admission_ref=admission_ref, producer_refs=producer_refs)
        except Exception:
            _write(root, Path(str(output) + '.verification-failed.json'), {'status': 'FAIL', 'caseId': case_id})
            raise
        _write(root, output, raw)
        print(json.dumps({'caseId': case_id, 'status': 'PASS', 'evidence': final_ref}, sort_keys=True))
        return case

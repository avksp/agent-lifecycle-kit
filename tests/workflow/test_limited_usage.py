"""Local declared-ledger fixtures; no provider, native or financial-close proof."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from agent_lifecycle.accounting.source_usage_context import load_source_usage_context
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.scoped_usage_schemas import (
    SOURCE_USAGE_MODE, SOURCE_USAGE_METRICS, SOURCE_USAGE_ROLES,
    validate_source_usage_receipt_shape,
)
from agent_lifecycle.adapter_sessions.bootstrap_r11 import (
    advance_coordinator_cost_head, read_coordinator_cost_head,
)
from agent_lifecycle.freeze.package_integrity import build_plan_lock_v2
from agent_lifecycle.workflow.limited_usage import (
    load_frozen_source_policy, current_source_snapshot, emit_registry_artifact,
    validate_limited_source_usage, require_snapshot_current,
    refresh_committed_source_assurance, aggregate_source_usage_assurance,
    require_task_source_frontier_current,
)
from agent_lifecycle.workflow.model_usage import (
    validate_task_model_usage_receipt, validate_attempt_model_route,
)
from tests.workflow.helpers import _model_route, _model_usage_receipt, _write_state

BASE = 'work/release-2-16/enforcement-decision'
# Exact immutable seed bytes, installed only inside the temporary real Git fixture.
SEED_RAW = b'{\n  "status": "UNAVAILABLE_FULL_HOLD_RETAINED",\n  "tokenCap": 40000,\n  "protectedCloseoutTokens": 10000,\n  "actualInputTokens": null,\n  "actualTokens": null,\n  "costStatus": "UNAVAILABLE",\n  "priorUnknownHolds": 112770000,\n  "unknownHoldsIncludingThisWindow": 112810000,\n  "priorLedgerLowerBound": 116626844,\n  "ledgerLowerBoundIncludingThisHold": 116666844,\n  "priorUnreconciledObserverTurn": "UNAVAILABLE_NOT_ZERO",\n  "priorBudgetResumed": false,\n  "scope": "Independent raw host-wire/prelude, transcript and supervisor identity/deadline joins; combine with per-shard held cost. Local fixtures only, no model/native call.",\n  "modelRequestCount": 0,\n  "priorUnknownHoldsReleased": 0,\n  "goalComplete": false\n}\n'


def raw(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def put(root, path, value):
    data = value if isinstance(value, bytes) else raw(value)
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(data)
    return {'path': path, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def put_artifact(root, path, value):
    return put(root, path, raw(value) + b'\n')


class DeclaredFixture:
    def __init__(self, root, *, ordinary=False, with_full_task=False, max_attempts=1,
                 registry_capacity=False, initial_cap=1000):
        self.root = root
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        subprocess.run(['git', 'config', 'user.email', 'fixture@example.invalid'], cwd=root, check=True)
        subprocess.run(['git', 'config', 'user.name', 'Local Fixture'], cwd=root, check=True)
        put(root, '.gitignore', b'work/\ntasks/\nrun.state.json\nevents.jsonl\nprofiles/\nadapters/\n')
        put(root, 'src/example.py', b'value = 1\n')
        subprocess.run(['git', 'add', '.gitignore', 'src/example.py'], cwd=root, check=True)
        subprocess.run(['git', 'commit', '-qm', 'fixture'], cwd=root, check=True)
        self.revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
        seed_path = BASE + '/r396-r11-host-supervision-join/cost.json'
        self.seed_ref = put(root, seed_path, SEED_RAW)
        advance_coordinator_cost_head(root, source_path=seed_path)
        opening = read_coordinator_cost_head(root)
        opening_ref = put(root, 'tasks/strategy/opening.json', opening['headRaw'])
        self.prefix = {'schemaVersion': 'alk-source-usage-registry-prefix.v1',
            'openingHeadSha256': opening_ref['sha256'], 'requiredRoles': list(SOURCE_USAGE_ROLES),
            'ownerBindings': [{'actorId': '/root', 'role': 'coordinator'}],
            'historicalSourceRefs': [self.seed_ref],
            'unknownIntervals': [{'kind': 'UNAVAILABLE_ORIGINAL_ATTRIBUTION', 'originalSourceRef': self.seed_ref,
                                  'originalWindowId': BASE + '/r396-r11-host-supervision-join'}]}
        prefix_ref = put(root, 'tasks/strategy/prefix.json', self.prefix)
        self.policy = {'schemaVersion': 'alk-source-usage-completion-policy.v1',
            'mode': SOURCE_USAGE_MODE, 'adapterId': 'codex', 'adapterHost': 'codex',
            'taskIds': ['WS-01'], 'allowedModelClasses': ['standard-code', 'strong-reasoning'],
            'accountingKind': 'EXISTING_DECLARED_COORDINATOR_LEDGER',
            'openingRef': opening_ref, 'sourceAuthoringRegistryRef': prefix_ref,
            'actualCapConformance': 'UNAVAILABLE', 'financialClosureAllowed': False}
        self.manifest = {'schemaVersion': 'agent-plan-manifest.v1', 'status': 'FROZEN', 'planRevision': 1,
            'package': {'id': 'release-2-16', 'planArtifactRoot': 'tasks/strategy'},
            'baseRevision': {'sha': self.revision},
            'packageIntegrity': {'required': True, 'allowedUnlistedFiles': ['plan.lock.json']},
            'planFiles': ['tasks/strategy/opening.json', 'tasks/strategy/plan.manifest.json', 'tasks/strategy/prefix.json'],
            'runtimePolicy': {'sourceUsageCompletion': self.policy},
            'workstreams': [{'id': 'WS-01', 'owner': '/root', 'writes': ['src'], 'dependsOn': []}],
            'acceptance': {'criteria': []},
            'specification': {'tier': 'S2', 'requirements': [{'id': 'REQ-FOUNDATION', 'description': 'Local fixture'}],
                'tierResolutionRequest': {'riskFlags': {'architecture': True}, 'capabilityHints': []}}}
        if registry_capacity:
            capacity_path = 'tasks/strategy/source-usage-registry-capacity.json'
            put(root, capacity_path, {
                'schemaVersion': 'alk-source-usage-registry-capacity-amendment.v1',
                'originalCurrentRegistryMaxBytes': 65536,
                'currentRegistryMaxBytes': 1048576,
                'frozenOpeningAndPrefixMaxBytes': 65536,
                'usageReceiptMaxBytes': 65536,
            })
            self.manifest['planFiles'] = sorted([*self.manifest['planFiles'], capacity_path])
        self.state_path = _write_state(root, phase='RUNNING', max_attempts=max_attempts)
        self.state = json.loads(self.state_path.read_text())
        self.state.update(packageId=self.manifest['package']['id'], sourceRevision=self.revision, manifestPath='tasks/strategy/plan.manifest.json',
                          runStartedAt=datetime.now(UTC).isoformat())
        self.task = self.state['tasks'][0]
        self.task.update(owner='/root', adapterId='codex', attempt=1, status='RUNNING',
                         startedAt=datetime.now(UTC).isoformat(), modelRoute=_model_route())
        if with_full_task:
            self.manifest['workstreams'].append({'id': 'WS-02', 'owner': '/root', 'writes': ['src'], 'dependsOn': []})
            extra = deepcopy(self.task)
            extra.update(id='WS-02', attempt=1, status='ACCEPTED')
            extra['artifactPaths'] = {key: value.replace('WS-01', 'WS-02') for key, value in extra['artifactPaths'].items()}
            self.state['tasks'].append(extra)
        self.task['attemptModelRoute'] = deepcopy(self.task['modelRoute'])
        self.task['attemptRiskExecutionProfile'] = {'usageMode': SOURCE_USAGE_MODE,
                                                   'sourceUsagePolicyDigest': canonical_digest(self.policy)}
        self.freeze()
        if ordinary:
            self.prepare_strategy()
        self.admission_ref = self.append_window(397, bound=True, cap=initial_cap)
        self.receipt = self.make_receipt() if not ordinary else None

    def prepare_strategy(self):
        from tests.workflow.test_task_transitions import _load_repo_json
        from agent_lifecycle.policy.execution_strategy import resolve_execution_strategy
        inputs = {}
        for key, path in [('risk_policy', 'profiles/risk-execution-policy.v1.json'),
                          ('routing_profile', 'profiles/model-routing-profile.v1.json'),
                          ('baseline_profile', 'profiles/lifecycle-baselines.v1.json'),
                          ('host_profile', 'profiles/hosts/codex-live-profile.v1.json'),
                          ('descriptor', 'adapters/codex/adapter.descriptor.json'),
                          ('capability_manifest', 'adapters/codex/capabilities.manifest.json')]:
            inputs[key] = _load_repo_json(path)
            put(self.root, path, inputs[key])
        self.task.update(status='READY', attempt=0)
        for key in ('attemptRiskExecutionProfile', 'attemptModelRoute', 'modelRoute'):
            self.task.pop(key, None)
        put(self.root, 'run.state.json', self.state)
        strategy = resolve_execution_strategy(manifest=self.manifest,
            lock=json.loads((self.root / 'tasks/strategy/plan.lock.json').read_bytes()),
            state=self.state, task_id='WS-01', adapter_id='codex', adapter_host='codex',
            operation_id='start-strategy', expected_revision=1, source_revision=self.revision,
            requested_risk='auto', target_attempt=1, repository_root=self.root,
            source_usage_context=load_source_usage_context(
                self.root, self.manifest, self.state, self.task, 'codex', 'codex'),
            descriptor_path='adapters/codex/adapter.descriptor.json',
            capability_manifest_path='adapters/codex/capabilities.manifest.json',
            project_profile_path='.alk/project-profile.json', **inputs)
        self.strategy = strategy
        put_artifact(self.root, 'work/WS-01/execution-strategy.json', strategy)
        # A prospective original admission uses the chosen route; start_task
        # independently recomputes and adopts it before the source work begins.
        self.task['modelRoute'] = deepcopy(strategy['modelRoute'])

    def freeze(self):
        put(self.root, 'tasks/strategy/plan.manifest.json', self.manifest)
        put(self.root, 'tasks/strategy/plan.lock.json', build_plan_lock_v2(self.manifest, repository_root=self.root))
        self.state['planDigest'] = canonical_digest(self.manifest)
        put(self.root, 'run.state.json', self.state)

    def append_window(self, number, *, bound=False, cap=1000, operation=None, repair_fields=None):
        current = read_coordinator_cost_head(self.root)
        if Path(current['head']['sourcePath']).name == 'admission.json':
            self.close_window()
            current = read_coordinator_cost_head(self.root)
        window = BASE + '/r' + str(number) + '-fixture'
        start = datetime.now(UTC)
        value = {'status': 'ADMITTED_PREAPPROVED_BY_USER', 'tokenCap': cap,
            'protectedCloseoutTokens': cap // 4, 'actualInputTokens': None, 'actualTokens': None,
            'costStatus': 'UNAVAILABLE', 'priorUnknownHolds': current['head']['unknownHolds'],
            'unknownHoldsIncludingThisWindow': current['head']['unknownHolds'] + cap,
            'priorLedgerLowerBound': current['head']['exposureLowerBound'],
            'ledgerLowerBoundIncludingThisHold': current['head']['exposureLowerBound'] + cap,
            'priorBudgetResumed': False, 'admittedAtUtc': start.isoformat(),
            'absoluteDeadlineUtc': (start + timedelta(minutes=1)).isoformat()}
        if bound:
            value['sourceUsageBinding'] = {'schemaVersion': 'alk-source-usage-window-binding.v1',
                'bindingKind': 'DECLARED_COORDINATOR_WORK_WINDOW',
                'semanticOperationId': operation or self.task['modelRoute']['operationId'],
                'runId': self.state['runId'], 'packageId': 'release-2-16', 'taskId': 'WS-01', 'attempt': 1,
                'planDigest': self.state['planDigest'], 'sourceRevision': self.revision,
                'routeDecisionDigest': self.task['modelRoute']['decisionDigest'],
                'sourceUsagePolicyDigest': canonical_digest(self.policy), 'actorId': '/root',
                'role': 'coordinator', 'originalWindowId': window,
                'originalCostScope': 'COORDINATOR_FINITE_SOURCE_AUTHORING_WINDOW',
                'sourceInputSubjectDigest': hashlib.sha256((self.root / 'src/example.py').read_bytes()).hexdigest()}
        if repair_fields:
            value.update(repair_fields)
        ref = put(self.root, window + '/admission.json', value)
        advance_coordinator_cost_head(self.root, source_path=ref['path'])
        return ref

    def close_window(self, mutate=None):
        current = read_coordinator_cost_head(self.root)
        value = deepcopy(current['source'])
        value.update(status='UNAVAILABLE_FULL_HOLD_RETAINED', priorUnknownHoldsReleased=0,
                     closedAtUtc=datetime.now(UTC).isoformat())
        if mutate:
            mutate(value)
        path = str(Path(current['head']['sourcePath']).with_name('cost.json'))
        put(self.root, path, value)
        advance_coordinator_cost_head(self.root, source_path=path)

    def selection(self):
        return load_frozen_source_policy(self.root, self.state, self.task)

    def snapshot(self):
        return current_source_snapshot(self.selection())

    def make_receipt(self):
        current = read_coordinator_cost_head(self.root)
        return {'schemaVersion': 'agent-lifecycle-model-usage-receipt.v2',
            'operationId': self.task['modelRoute']['operationId'], 'host': 'codex',
            'modelClass': self.task['modelRoute']['modelClass'], 'providerModelHash': 'unavailable-provider-label',
            'lineage': {'runId': 'run', 'packageId': 'release-2-16', 'taskId': 'WS-01', 'attempt': 1,
                'planDigest': self.state['planDigest'], 'sourceRevision': self.revision,
                'routeDecisionDigest': self.task['modelRoute']['decisionDigest']},
            'attestation': {'source': 'alk-declared', 'status': 'UNAVAILABLE'},
            'usage': {key: None for key in SOURCE_USAGE_METRICS},
            'metricStates': {key: 'UNAVAILABLE' for key in SOURCE_USAGE_METRICS},
            'usageMode': SOURCE_USAGE_MODE, 'policyDigest': canonical_digest(self.policy),
            'sourceAuthoringRegistryDigest': self.policy['sourceAuthoringRegistryRef']['sha256'],
            'ledgerRef': {'path': BASE + '/COORDINATOR-COST-HEAD.json',
                          'sha256': current['headSha256'], 'bytes': len(current['headRaw'])},
            'currentAdmissionRef': self.admission_ref, 'actorId': '/root',
            'sourceContextRefs': [self.seed_ref],
            'currentRegistryRef': emit_registry_artifact(self.root, self.state, self.task)}

    def validate(self, receipt=None):
        return validate_task_model_usage_receipt(self.state, self.task, receipt or self.receipt,
                                                repository_root=self.root)



def derive_fixture_risk(fixture, *, task_id='WS-01', operation_id='start-strategy'):
    from agent_lifecycle.policy.risk_execution import derive_risk_execution_profile
    from tests.workflow.test_task_transitions import _load_repo_json
    from agent_lifecycle.accounting.source_usage_context import load_source_usage_context
    return derive_risk_execution_profile(manifest=fixture.manifest, state=fixture.state,
        task_id=task_id, adapter_id='codex', adapter_host='codex', operation_id=operation_id,
        source_revision=fixture.revision, requested_risk='auto', repository_root=fixture.root,
        source_usage_context=load_source_usage_context(
            fixture.root, fixture.manifest, fixture.state,
            next(task for task in fixture.state['tasks'] if task['id'] == task_id), 'codex', 'codex'),
        risk_policy=_load_repo_json('profiles/risk-execution-policy.v1.json'),
        routing_profile=_load_repo_json('profiles/model-routing-profile.v1.json'),
        baseline_profile=_load_repo_json('profiles/lifecycle-baselines.v1.json'),
        host_profile=_load_repo_json('profiles/hosts/codex-live-profile.v1.json'))


def start_and_commit_fixture(f):
    from agent_lifecycle.workflow import start_task, commit_task_result
    from tests.workflow.test_task_transitions import _strategy_start_inputs
    from tests.workflow.helpers import _fresh_result
    start_task(f.state_path, task_id='WS-01', operation_id='start-strategy', expected_revision=1,
        source_revision=f.revision, strategy_path='work/WS-01/execution-strategy.json',
        strategy_inputs=_strategy_start_inputs(), reason='local regression fixture')
    f.state = json.loads(f.state_path.read_bytes()); f.task = f.state['tasks'][0]
    put(f.root, 'src/example.py', b'value = 2\n')
    result = _fresh_result(f.root, f.state_path, attempt=1)
    result.update(planDigest=f.state['planDigest'], actor='/root', actorRunId='source-regression-fixture')
    result_path = 'work/WS-01/attempt-1/task-result.json'
    put_artifact(f.root, result_path, result)
    f.receipt = f.make_receipt(); put_artifact(f.root, 'work/WS-01/attempt-1/model-usage.json', f.receipt)
    commit_task_result(f.state_path, task_id='WS-01', operation_id='commit-local', expected_revision=2,
        source_revision=f.revision, result_path=result_path,
        model_usage_receipt_path='work/WS-01/attempt-1/model-usage.json', reason='local regression fixture')
    f.state = json.loads(f.state_path.read_bytes()); f.task = f.state['tasks'][0]
    return result

class LimitedUsageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.f = DeclaredFixture(Path(self.directory.name).resolve())

    def denied(self, callback, code=None):
        with self.assertRaises(LifecycleError) as caught:
            callback()
        if code:
            self.assertEqual(code, caught.exception.code)
        self.observedRefusalCode = caught.exception.code
        return caught.exception.code

    def test_current_registry_capacity_preserves_large_original_interval(self):
        def extend(fixture):
            for number in range(398, 448):
                fixture.append_window(number)

        extend(self.f)
        with self.subTest(case='old-frozen-plan-retains-original-64k-bound'):
            self.denied(self.f.snapshot, 'scoped-usage-registry-bound')
        with tempfile.TemporaryDirectory() as directory:
            f = DeclaredFixture(Path(directory).resolve(), registry_capacity=True)
            before = read_coordinator_cost_head(f.root)
            extend(f)
            after = read_coordinator_cost_head(f.root)
            snapshot = f.snapshot()
            projection = snapshot['projection']
            with self.subTest(case='large-frozen-selected-registry-complete'):
                self.assertGreater(len(snapshot['projectionBytes']), 65536)
                self.assertLessEqual(len(snapshot['projectionBytes']), 1048576)
                self.assertEqual(102, len(projection['records']))
                self.assertEqual(51, len(projection['windowPools']))
                self.assertEqual(100, len(projection['unknownIntervals']))
                self.assertEqual(before['head']['exposureLowerBound'] + 50000,
                                 projection['balances']['currentExposureLowerBound'])
                self.assertEqual(before['head']['unknownHolds'] + 50000,
                                 projection['balances']['currentUnknownHolds'])
                self.assertEqual(after['head']['exposureLowerBound'],
                                 projection['balances']['currentExposureLowerBound'])
                self.assertIsNone(projection['balances']['actualTokens'])
                expected_ids = sorted({
                    'prefix:' + projection['frozenPrefixRawSha256'] + ':0',
                    *('legacy:' + row['sourceRef']['sha256'] for row in projection['records'][1:]
                      if row['binding'] is None),
                })
                self.assertEqual(list(SOURCE_USAGE_ROLES),
                                 [row['role'] for row in projection['roleDispositions']])
                self.assertTrue(all(row['unknownContextIds'] == expected_ids
                                    for row in projection['roleDispositions']))
                for row in projection['records']:
                    original = (f.root / row['sourceRef']['path']).read_bytes()
                    self.assertEqual(hashlib.sha256(original).hexdigest(), row['sourceRef']['sha256'])
                    self.assertEqual(len(original), row['sourceRef']['bytes'])
            f.receipt = f.make_receipt()
            with self.subTest(case='large-emitter-validator-and-idempotent-reuse'):
                self.assertGreater(f.receipt['currentRegistryRef']['bytes'], 65536)
                self.assertEqual('PASS', f.validate()['status'])
                self.assertEqual(f.receipt['currentRegistryRef'], emit_registry_artifact(f.root, f.state, f.task))
            with self.subTest(case='large-artifact-tampering-still-refuses'):
                path = f.root / f.receipt['currentRegistryRef']['path']
                original = path.read_bytes()
                altered = json.loads(original)
                altered['balances']['actualTokens'] = 0
                path.write_bytes(raw(altered))
                self.denied(f.validate)
                path.write_bytes(original)
                self.assertEqual(after['headRaw'], read_coordinator_cost_head(f.root)['headRaw'])
    def test_legacy_v1_full_receipt_accepts(self):
        receipt = _model_usage_receipt(self.f.task['modelRoute'])
        receipt['packageId'] = 'release-2-16'
        receipt.update(planDigest=self.f.state['planDigest'], sourceRevision=self.f.revision)
        self.assertEqual('PASS', validate_task_model_usage_receipt(self.f.state, self.f.task, receipt)['status'])

    def test_current_attempt_actor_operation_route_joins_required(self):
        for key, value in [('actorId', 'worker'), ('operationId', 'other'), ('modelClass', 'budget')]:
            with self.subTest(field=key):
                changed = deepcopy(self.f.receipt)
                changed[key] = value
                self.denied(lambda: self.f.validate(changed))
        changed = deepcopy(self.f.receipt)
        changed['lineage']['attempt'] = 2
        self.denied(lambda: self.f.validate(changed))

    def test_old_source_authoring_context_not_current_executor(self):
        result = self.f.validate()
        self.assertEqual('/root', result['usageAssurance']['actorId'])
        self.assertNotEqual(self.f.seed_ref, result['usageAssurance']['currentAdmissionRef'])
        self.assertEqual(self.f.seed_ref, self.f.receipt['sourceContextRefs'][0])

    def test_unqualified_raw_counters_never_actual_cap_pass(self):
        self.assertEqual('UNAVAILABLE', self.f.validate()['usageAssurance']['actualCapConformance'])
        receipt = deepcopy(self.f.receipt)
        receipt['usage']['billableTokens'] = 0
        self.denied(lambda: self.f.validate(receipt))

    def test_opening_prefix_head_ref_tamper_or_reset_refuses(self):
        for path in ['tasks/strategy/opening.json', 'tasks/strategy/prefix.json', BASE + '/COORDINATOR-COST-HEAD.json']:
            with self.subTest(path=path):
                original = (self.f.root / path).read_bytes()
                (self.f.root / path).write_bytes(original + b' ')
                self.denied(self.f.validate)
                (self.f.root / path).write_bytes(original)

    def test_every_ledger_parent_and_monotonic_balance_verified(self):
        with self.subTest(case='complete-stable-current-chain'):
            self.assertEqual('PASS', self.f.validate()['status'])
        with self.subTest(case='valid-exact-current-projection-serializer-and-emitter'):
            self.assertEqual(self.f.receipt['currentRegistryRef'], emit_registry_artifact(self.f.root, self.f.state, self.f.task))
        with self.subTest(case='older-valid-head-containing-current-admission-but-omitting-later-overrun'):
            snapshot = self.f.snapshot()
            self.f.append_window(398, cap=2000)
            self.denied(self.f.validate, 'scoped-usage-frontier-stale')
            self.denied(lambda: require_snapshot_current(self.f.selection(), snapshot), 'scoped-usage-frontier-stale')
        with self.subTest(case='head-or-registry-changes-during-validation'):
            from unittest.mock import patch
            from agent_lifecycle.workflow import limited_usage
            original_projection = limited_usage._projection
            def derive_then_advance(selection, current):
                projected = original_projection(selection, current)
                # Advance the real temporary financial ledger between actual A/B
                # reads. No fake reader return or manufactured PASS is supplied.
                self.f.append_window(399, cap=1000)
                return projected
            with patch.object(limited_usage, '_projection', side_effect=derive_then_advance):
                self.denied(self.f.snapshot, 'scoped-usage-frontier-stale')
        self.f.receipt = self.f.make_receipt()
        with self.subTest(case='wrong-current-registry-namespace-or-path'):
            changed = deepcopy(self.f.receipt)
            changed['currentRegistryRef']['path'] = 'tasks/strategy/prefix.json'
            self.denied(lambda: self.f.validate(changed))
        with self.subTest(case='frozen-prefix-hash-used-as-live-projection-hash'):
            changed = deepcopy(self.f.receipt)
            changed['currentRegistryRef']['sha256'] = changed['sourceAuthoringRegistryDigest']
            self.denied(lambda: self.f.validate(changed))
        with self.subTest(case='different-projection-record-order-or-terminal-identity'):
            path = self.f.root / self.f.receipt['currentRegistryRef']['path']
            original = path.read_bytes()
            value = json.loads(original)
            value['records'].reverse()
            path.write_bytes(raw(value))
            self.denied(self.f.validate)
            path.write_bytes(original)
        with self.subTest(case='missing-parent-or-nonmonotonic-hold'):
            head = read_coordinator_cost_head(self.f.root)
            archive = self.f.root / BASE / 'coordinator-cost-head-history' / (head['head']['previousHeadSha256'] + '.json')
            archive.unlink()
            self.denied(self.f.validate)

    def test_same_operation_duplicate_not_double_charged_conflict_refuses(self):
        before = self.f.snapshot()['projection']['balances']['currentExposureLowerBound']
        self.f.close_window()
        projection = self.f.snapshot()['projection']
        with self.subTest(case='one-window-admission-and-close-shared-pool'):
            self.assertEqual(1, len(projection['windowPools']))
            self.assertEqual(before, projection['balances']['currentExposureLowerBound'])
        with self.subTest(case='conflicting-duplicate-actor-amount-binding'):
            with tempfile.TemporaryDirectory() as directory:
                fixture = DeclaredFixture(Path(directory).resolve())
                fixture.close_window(mutate=lambda value: value['sourceUsageBinding'].update(actorId='different'))
                self.denied(fixture.snapshot, 'scoped-usage-window-conflict')
        with self.subTest(case='current-op-binds-two-original-windows'):
            self.f.append_window(398, bound=True)
            self.denied(self.f.snapshot, 'scoped-usage-window-conflict')

    def test_all_seven_role_dispositions_and_original_scopes_preserved(self):
        projection = self.f.snapshot()['projection']
        with self.subTest(case='all-seven-enumerated-roles-original-scope-or-unavailable'):
            self.assertEqual(list(SOURCE_USAGE_ROLES), [row['role'] for row in projection['roleDispositions']])
            self.assertEqual('RECORDED_ORIGINAL_WINDOW', projection['roleDispositions'][0]['status'])
            self.assertTrue(all(row['status'] == 'UNAVAILABLE_UNALLOCATED_POOL' for row in projection['roleDispositions'][1:]))
        with self.subTest(case='missing-role-or-fake-zero-partition'):
            path = self.f.root / self.f.receipt['currentRegistryRef']['path']
            original = path.read_bytes()
            for mutation in ('missing', 'zero'):
                value = json.loads(original)
                if mutation == 'missing':
                    value['roleDispositions'].pop()
                else:
                    value['roleDispositions'][1]['actualTokens'] = 0
                path.write_bytes(raw(value))
                self.denied(self.f.validate)
                path.write_bytes(original)
        with self.subTest(case='legacy-window-without-current-binding-used-as-executor'):
            self.f.admission_ref = self.f.append_window(398)
            self.f.receipt = self.f.make_receipt()
            self.denied(self.f.validate, 'scoped-usage-current-admission-unbound')

    def test_original_hold_survives_timeout_compact_semantic_completion(self):
        before = self.f.snapshot()['projection']['balances']
        self.f.close_window()
        after = self.f.snapshot()['projection']['balances']
        self.assertEqual(before, after)
        self.assertIsNone(after['actualTokens'])

    def test_recorded_excess_is_once_preserved_without_repeating_valid_source_check(self):
        before = self.f.snapshot()['projection']['balances']['currentExposureLowerBound']
        self.f.append_window(398, cap=2000)
        projection = self.f.snapshot()['projection']
        self.assertEqual(before + 2000, projection['balances']['currentExposureLowerBound'])
        self.f.close_window()
        self.assertEqual(projection['balances'], self.f.snapshot()['projection']['balances'])

    def test_absent_new_finite_current_admission_refuses(self):
        receipt = deepcopy(self.f.receipt)
        receipt['currentAdmissionRef'] = self.f.seed_ref
        self.denied(lambda: self.f.validate(receipt), 'scoped-usage-current-admission-unbound')

    def test_stale_manifest_lock_source_revision_refuses(self):
        original_state = self.f.state_path.read_bytes()
        with self.subTest(case='wrong-source-revision'):
            self.f.state['sourceRevision'] = 'different'
            self.denied(self.f.validate, 'scoped-usage-plan-stale')
            self.assertEqual(original_state, self.f.state_path.read_bytes())
            self.f.state['sourceRevision'] = self.f.revision
        for case, path, field, value in [
            ('stale-manifest', 'tasks/strategy/plan.manifest.json', 'status', 'DRAFT'),
            ('stale-lock', 'tasks/strategy/plan.lock.json', 'manifestHash', '0' * 64),
        ]:
            with self.subTest(case=case):
                file = self.f.root / path
                original = file.read_bytes()
                changed = json.loads(original)
                changed[field] = value
                file.write_bytes(raw(changed))
                self.denied(self.f.validate)
                self.assertEqual(original_state, self.f.state_path.read_bytes())
                file.write_bytes(original)

    def test_quality_floor_model_class_and_local_critical_guards_preserved(self):
        route = deepcopy(self.f.task['modelRoute'])
        route.update(modelClass='local-compact', criticalReview=True)
        self.denied(lambda: validate_attempt_model_route({'modelRoute': route}), 'model-route-critical-downgrade')

    def test_current_source_applicability_does_not_claim_new_native_execution(self):
        result = self.f.validate()
        self.assertNotIn('nativeExecution', result)
        self.assertEqual('LIMITED_DECLARED_SOURCE_ACCOUNTING', result['usageAssurance']['guarantee'])

    def test_semantic_result_after_overrun_preserved_without_claiming_affordable_next_call(self):
        from agent_lifecycle.workflow.artifacts import artifact_identity
        validation = self.f.validate()
        path = 'work/WS-01/attempt-1/model-usage.json'
        put_artifact(self.f.root, path, self.f.receipt)
        self.f.task['modelUsageReceipt'] = {**artifact_identity(self.f.root, path, self.f.receipt),
            'validation': validation, 'usageAssurance': validation['usageAssurance']}
        self.f.task['status'] = 'VERIFYING'
        original = (self.f.root / path).read_bytes()
        self.f.append_window(398, cap=3000)
        assurance = refresh_committed_source_assurance(self.f.root, self.f.state, self.f.task)
        self.assertEqual(original, (self.f.root / path).read_bytes())
        self.assertEqual('OPEN_UNAVAILABLE', assurance['financialClosure'])
        self.assertEqual(read_coordinator_cost_head(self.f.root)['headSha256'], assurance['ledgerRef']['sha256'])

    def test_final_proof_explicit_partial_assurance_and_open_resources(self):
        self.f.task['status'] = 'ACCEPTED'
        assurance = aggregate_source_usage_assurance(self.f.root, self.f.state)
        self.assertEqual('LIMITED_DECLARED_SOURCE_ACCOUNTING', assurance['guarantee'])
        self.assertEqual('OPEN_UNAVAILABLE', assurance['financialClosure'])
        self.assertIsNone(assurance['actualTokens'])
        self.assertEqual('HISTORICAL_UNAVAILABLE_SOURCE_CONTEXT_NOT_CURRENT_EXECUTOR', assurance['tasks'][0]['assurance']['assuranceBasis'])

    def test_ordinary_scoped_adoption_result_acceptance_and_final_proof(self):
        from agent_lifecycle.workflow import start_task, commit_task_result, accept_task, finalize_run
        from agent_lifecycle.audit.implementation import build_implementation_audit_report
        from tests.workflow.test_task_transitions import _strategy_start_inputs
        from tests.workflow.helpers import _fresh_result, _review, _final_audit
        with tempfile.TemporaryDirectory() as directory:
            f = DeclaredFixture(Path(directory).resolve(), ordinary=True)
            with self.subTest(case='mutated-adoption-identity'):
                strategy = deepcopy(f.strategy)
                strategy['lineage']['sourceRevision'] = 'different'
                strategy['strategyDigest'] = canonical_digest({k: v for k, v in strategy.items() if k != 'strategyDigest'})
                put_artifact(f.root, 'work/WS-01/execution-strategy.json', strategy)
                before = f.state_path.read_bytes()
                self.denied(lambda: start_task(f.state_path, task_id='WS-01', operation_id='start-strategy',
                    expected_revision=1, source_revision=f.revision,
                    strategy_path='work/WS-01/execution-strategy.json', strategy_inputs=_strategy_start_inputs(), reason='local'))
                self.assertEqual(before, f.state_path.read_bytes())
            put_artifact(f.root, 'work/WS-01/execution-strategy.json', f.strategy)
            with self.subTest(case='valid-current-policy'):
                start_task(f.state_path, task_id='WS-01', operation_id='start-strategy', expected_revision=1,
                    source_revision=f.revision, strategy_path='work/WS-01/execution-strategy.json',
                    strategy_inputs=_strategy_start_inputs(), reason='local fixture')
                f.state = json.loads(f.state_path.read_bytes())
                f.task = f.state['tasks'][0]
                self.assertEqual(SOURCE_USAGE_MODE, f.task['attemptExecutionStrategy']['usageMode'])
                put(f.root, 'src/example.py', b'value = 2\n')
                result = _fresh_result(f.root, f.state_path, attempt=1)
                result.update(planDigest=f.state['planDigest'], actor='/root', actorRunId='coordinator-fixture')
                result_path = 'work/WS-01/attempt-1/task-result.json'
                put_artifact(f.root, result_path, result)
                f.receipt = f.make_receipt()
                usage_path = 'work/WS-01/attempt-1/model-usage.json'
                put_artifact(f.root, usage_path, f.receipt)
                commit_task_result(f.state_path, task_id='WS-01', operation_id='commit-local', expected_revision=2,
                    result_path=result_path, model_usage_receipt_path=usage_path,
                    source_revision=f.revision, reason='local fixture')
                f.state = json.loads(f.state_path.read_bytes())
                f.task = f.state['tasks'][0]
                self.assertEqual('VERIFYING', f.task['status'])
                review = _review(attempt=1, result_hash=canonical_digest(result))
                review.update(planDigest=f.state['planDigest'])
                review['acceptanceChecks'] = []
                review_path = 'work/WS-01/attempt-1/task-review.json'
                put_artifact(f.root, review_path, review)
                report = build_implementation_audit_report(manifest_path=f.root / f.state['manifestPath'],
                    state_path=f.state_path, task_id='WS-01', result_path=result_path, review_path=review_path)
                self.assertEqual('PASS', report['status'], report['blockers'])
                audit_path = 'work/WS-01/attempt-1/implementation-audit.json'
                put_artifact(f.root, audit_path, report)
                accept_task(f.state_path, task_id='WS-01', operation_id='accept-local', expected_revision=3,
                    review_path=review_path, implementation_audit_path=audit_path, reason='local fixture')
                f.state = json.loads(f.state_path.read_bytes())
                f.task = f.state['tasks'][0]
                self.assertEqual('ACCEPTED', f.task['status'])
                self.assertEqual('OPEN_UNAVAILABLE', f.task['sourceUsageAssurance']['financialClosure'])
                # Legacy FINAL_AUDIT fixture exercises the ordinary finalizer;
                # it is not a v4/native/release acceptance claim.
                f.state['phase'] = 'FINAL_AUDIT'
                put(f.root, 'run.state.json', f.state)
                audit = _final_audit()
                audit['completionSignal']['packageId'] = 'release-2-16'
                audit['planDigest'] = f.state['planDigest']
                audit['completionSignal'].update(planDigest=f.state['planDigest'], sourceRevision=f.revision)
                put_artifact(f.root, 'work/final-audit.json', audit)
                finalize_run(f.state_path, operation_id='final-local', expected_revision=4,
                    source_revision=f.revision, final_audit_path='work/final-audit.json',
                    proof_path='work/final-proof.json', reason='local fixture')
                proof = json.loads((f.root / 'work/final-proof.json').read_bytes())
                self.assertEqual('LIMITED_DECLARED_SOURCE_ACCOUNTING', proof['usageAssurance']['guarantee'])
                self.assertIsNone(proof['usageAssurance']['actualTokens'])

    def test_limited_result_commit_keeps_semantic_native_ownership_review_audit_guards(self):
        from agent_lifecycle.workflow import commit_task_result
        from tests.workflow.helpers import _fresh_result
        put(self.f.root, 'src/example.py', b'value = 2\n')
        result = _fresh_result(self.f.root, self.f.state_path, attempt=1)
        result.update(planDigest=self.f.state['planDigest'], actor='other')
        path = 'work/WS-01/attempt-1/task-result.json'
        put(self.f.root, path, result)
        put(self.f.root, 'work/WS-01/attempt-1/model-usage.json', self.f.receipt)
        before = self.f.state_path.read_bytes()
        self.denied(lambda: commit_task_result(self.f.state_path, task_id='WS-01', operation_id='bad-owner',
            expected_revision=1, result_path=path, model_usage_receipt_path='work/WS-01/attempt-1/model-usage.json',
            source_revision=self.f.revision, reason='local'))
        self.assertEqual(before, self.f.state_path.read_bytes())

    def test_legacy_final_proof_and_task_wire_compatibility(self):
        from agent_lifecycle.workflow.finalization import _proof_body
        state = deepcopy(self.f.state)
        state['tasks'] = []
        args = {key: None for key in ('completion_check_receipt', 'completion_gate', 'goal_record',
            'follow_up_register', 'proof_integrity', 'final_implementation_audit', 'release_full_validation',
            'review_mesh_quorum', 'lifecycle_control_stop')}
        proof = _proof_body(state, operation_id='local', final_audit={}, finalization_gate_receipts=[], reason='local', **args)
        self.assertNotIn('usageAssurance', proof)

    def test_financial_close_and_cleanup_still_refuse_open_unknown_scope(self):
        from agent_lifecycle.accounting.journal import Journal, JournalUnavailable
        from agent_lifecycle.accounting.contracts import RunClosure
        from tests.accounting.test_journal import open_scope, operation, PROOF
        with Journal(self.f.root / 'work/financial-fixture.sqlite', PROOF) as journal:
            open_scope(journal)
            journal.reserve(operation(), expected_revision=1)
            now = datetime.now(UTC).isoformat()
            closure = RunClosure('closure', 'run', 'reportedTokens:fixture:v1', now,
                                 (('run', 2),), PROOF, PROOF)
            with self.assertRaises(JournalUnavailable):
                journal.close_run(closure, now)
            with self.assertRaises(JournalUnavailable):
                journal.collect_closed_run('run', now)
            self.assertIsNone(journal.closed_run('run'))

    def test_old_run_attempt_clocks_not_renewed(self):
        from agent_lifecycle.contracts.deadlines import evaluate_original_duration
        for kind in ('RUN_WALL_BUDGET', 'ATTEMPT_WALL_BUDGET'):
            with self.subTest(kind=kind):
                rule = {'kind': kind,
                    'originAt': '2026-09-30T00:00:00.000000Z', 'limitSeconds': 60,
                    'originalDeadlineAt': '2026-09-30T00:01:00.000000Z',
                    'replacement': 'RETAIN_ORIGINAL', 'comparison': 'LT'}
                original = deepcopy(rule)
                outcome = evaluate_original_duration(rule, '2026-10-01T00:00:00.000000Z')
                self.assertEqual('REFUSED', outcome['disposition'])
                self.assertEqual(original, rule)
                self.assertFalse(outcome['nativePermissionGranted'])

    def test_r564_v1_limited_marker_injection_refuses_before_start_and_usage(self):
        from agent_lifecycle.workflow import start_task
        from agent_lifecycle.workflow.risk_execution_gate import validate_task_risk_profile, apply_task_risk_profile
        with tempfile.TemporaryDirectory() as directory:
            f = DeclaredFixture(Path(directory).resolve(), ordinary=True)
            profile = derive_fixture_risk(f)
            profile['schemaVersion'] = 'agent-risk-execution-profile.v1'
            profile['usageEvidence'] = {'required': True, 'hostAttestationRequired': True,
                'requiredMetrics': ['billableTokens', 'invocations', 'wallSeconds'], 'estimatesAccepted': False}
            clean = {k: v for k, v in profile.items() if k not in {'usageMode', 'sourceUsagePolicyDigest'}}
            clean['profileDigest'] = canonical_digest({k: v for k, v in clean.items() if k != 'profileDigest'})
            self.assertEqual('PASS', validate_task_risk_profile(f.state, f.task, clean,
                operation_id='start-strategy', source_revision=f.revision, repository_root=f.root)['status'])
            profile['profileDigest'] = canonical_digest({k: v for k, v in profile.items() if k != 'profileDigest'})
            put_artifact(f.root, 'work/WS-01/forged-v1-risk.json', profile)
            before = f.state_path.read_bytes()
            self.denied(lambda: start_task(f.state_path, task_id='WS-01', operation_id='start-strategy',
                expected_revision=1, source_revision=f.revision, risk_profile_path='work/WS-01/forged-v1-risk.json',
                reason='must refuse'), 'risk-profile-reserved-limited-fields')
            self.assertEqual(before, f.state_path.read_bytes())
            apply_task_risk_profile(self.f.task, clean, {})
            self.f.task['attemptRiskExecutionProfile'] = deepcopy(self.f.task['riskExecutionProfile'])
            self.assertNotIn('usageMode', self.f.task['attemptRiskExecutionProfile'])
            self.denied(self.f.validate, 'scoped-usage-policy-context-required')

    def test_r564_opening_admission_closure_preserves_binding_clocks_and_single_hold(self):
        for mutation in ('none', 'binding', 'clock'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                f = DeclaredFixture(Path(directory).resolve())
                current = read_coordinator_cost_head(f.root)
                f.policy['openingRef'] = put(f.root, 'tasks/strategy/opening.json', current['headRaw'])
                f.prefix['openingHeadSha256'] = f.policy['openingRef']['sha256']
                f.policy['sourceAuthoringRegistryRef'] = put(f.root, 'tasks/strategy/prefix.json', f.prefix)
                f.freeze()
                exposure = current['head']['exposureLowerBound']
                def change(value):
                    if mutation == 'binding':
                        value['sourceUsageBinding']['actorId'] = 'another-original-actor'
                    elif mutation == 'clock':
                        value['absoluteDeadlineUtc'] = (datetime.fromisoformat(value['absoluteDeadlineUtc']) + timedelta(minutes=1)).isoformat()
                f.close_window(mutate=change)
                if mutation == 'none':
                    projection = f.snapshot()['projection']
                    self.assertEqual([], projection['windowPools'])
                    self.assertEqual(exposure, projection['balances']['currentExposureLowerBound'])
                else:
                    self.denied(f.snapshot, 'scoped-usage-window-conflict')

    def test_r564_full_v1_with_empty_intervals_keeps_positive_unknown_source_assurance(self):
        from agent_lifecycle.workflow.artifacts import artifact_identity
        self.f.prefix['unknownIntervals'] = []
        self.f.policy['sourceAuthoringRegistryRef'] = put(self.f.root, 'tasks/strategy/prefix.json', self.f.prefix)
        self.f.freeze()
        receipt = _model_usage_receipt(self.f.task['modelRoute'])
        receipt['packageId'] = 'release-2-16'
        receipt.update(planDigest=self.f.state['planDigest'], sourceRevision=self.f.revision)
        validated = validate_task_model_usage_receipt(self.f.state, self.f.task, receipt)
        self.assertEqual('PASS', validated['status'])
        path = 'work/WS-01/attempt-1/full-usage.json';put_artifact(self.f.root, path, receipt)
        self.f.task['modelUsageReceipt'] = {**artifact_identity(self.f.root, path, receipt), 'validation': validated}
        self.f.task['status'] = 'ACCEPTED'
        assurance = aggregate_source_usage_assurance(self.f.root, self.f.state)
        self.assertEqual('LIMITED_DECLARED_SOURCE_ACCOUNTING', assurance['guarantee'])
        self.assertEqual('OPEN_UNAVAILABLE', assurance['financialClosure'])
        self.assertGreater(self.f.snapshot()['projection']['balances']['currentUnknownHolds'], 0)
        self.assertEqual([], self.f.snapshot()['projection']['unknownIntervals'])

    def test_r564_mixed_selected_and_full_v1_tasks_finalize_with_partial_source_context(self):
        from agent_lifecycle.workflow import finalize_run
        from agent_lifecycle.workflow.artifacts import artifact_identity
        from tests.workflow.helpers import _final_audit
        with tempfile.TemporaryDirectory() as directory:
            f = DeclaredFixture(Path(directory).resolve(), with_full_task=True)
            limited = f.validate()
            path = 'work/WS-01/attempt-1/model-usage.json';put_artifact(f.root, path, f.receipt)
            f.task['modelUsageReceipt'] = {**artifact_identity(f.root, path, f.receipt),
                'validation': limited, 'usageAssurance': limited['usageAssurance']}
            f.task['status'] = 'ACCEPTED'
            other = f.state['tasks'][1]
            profile = derive_fixture_risk(f, task_id='WS-02', operation_id='full-task-route')
            self.assertEqual('agent-risk-execution-profile.v1', profile['schemaVersion'])
            self.assertTrue(profile['usageEvidence']['hostAttestationRequired'])
            other['modelRoute'] = deepcopy(profile['modelRoute'])
            receipt = _model_usage_receipt(other['modelRoute'])
            receipt['packageId'] = 'release-2-16'
            receipt.update(taskId='WS-02', planDigest=f.state['planDigest'], sourceRevision=f.revision)
            validation = validate_task_model_usage_receipt(f.state, other, receipt)
            self.assertEqual('PASS', validation['status'])
            path = 'work/WS-02/attempt-1/full-usage.json';put_artifact(f.root, path, receipt)
            other['modelUsageReceipt'] = {**artifact_identity(f.root, path, receipt), 'validation': validation}
            f.state['phase'] = 'FINAL_AUDIT';put(f.root, 'run.state.json', f.state)
            audit = _final_audit();audit['planDigest'] = f.state['planDigest']
            audit['completionSignal']['packageId'] = 'release-2-16'
            audit['completionSignal'].update(planDigest=f.state['planDigest'], sourceRevision=f.revision)
            put_artifact(f.root, 'work/mixed-audit.json', audit)
            finalize_run(f.state_path, operation_id='mixed-final', expected_revision=1,
                source_revision=f.revision, final_audit_path='work/mixed-audit.json',
                proof_path='work/mixed-proof.json', reason='local accepted-state fixture, not native proof')
            proof = json.loads((f.root / 'work/mixed-proof.json').read_bytes())
            self.assertEqual('LIMITED_DECLARED_SOURCE_ACCOUNTING', proof['usageAssurance']['guarantee'])
            self.assertEqual(2, len(proof['usageAssurance']['tasks']))
            self.assertNotIn('currentAdmissionRef', other.get('sourceUsageAssurance', {}))

    def test_r564_rework_archives_limited_assurance_then_full_v1_attempt_commits(self):
        from agent_lifecycle.workflow import rework_task, start_task, commit_task_result
        from tests.workflow.helpers import _review, _fresh_result
        with tempfile.TemporaryDirectory() as directory:
            f = DeclaredFixture(Path(directory).resolve(), ordinary=True, max_attempts=2)
            f.state['budgets']['remediationMode'] = 'ask'
            put(f.root, 'run.state.json', f.state)
            result = start_and_commit_fixture(f)
            original_assurance = deepcopy(f.task['sourceUsageAssurance'])
            original_hold = read_coordinator_cost_head(f.root)['head']['unknownHolds']
            review = _review(attempt=1, result_hash=canonical_digest(result));review.update(planDigest=f.state['planDigest'], verdict='REWORK')
            review['acceptanceChecks'] = []
            review['findings'] = [{'id': 'F-1', 'severity': 'MEDIUM', 'status': 'open', 'description': 'local regression correction'}]
            review['itemReviews'][0].update(verdict='REWORK', findingIds=['F-1'])
            review_path = 'work/WS-01/attempt-1/task-review.json';put_artifact(f.root, review_path, review)
            rework_task(f.state_path, task_id='WS-01', operation_id='rework-local', expected_revision=3,
                source_revision=f.revision, review_path=review_path, finding_ids=['F-1'], reason='local regression fixture')
            f.state = json.loads(f.state_path.read_bytes());f.task = f.state['tasks'][0]
            self.assertNotIn('sourceUsageAssurance', f.task)
            self.assertEqual(original_assurance, f.task['attemptHistory'][0]['sourceUsageAssurance'])
            self.assertEqual(original_hold, read_coordinator_cost_head(f.root)['head']['unknownHolds'])
            full_profile = derive_fixture_risk(f, operation_id='start-full')
            full_profile['schemaVersion'] = 'agent-risk-execution-profile.v1'
            full_profile.pop('usageMode');full_profile.pop('sourceUsagePolicyDigest')
            full_profile['usageEvidence'] = {'required': True, 'hostAttestationRequired': True,
                'requiredMetrics': ['billableTokens', 'invocations', 'wallSeconds'], 'estimatesAccepted': False}
            full_profile['profileDigest'] = canonical_digest({k: v for k, v in full_profile.items() if k != 'profileDigest'})
            put_artifact(f.root, 'work/WS-01/full-risk.json', full_profile)
            start_task(f.state_path, task_id='WS-01', operation_id='start-full', expected_revision=4,
                source_revision=f.revision, risk_profile_path='work/WS-01/full-risk.json', reason='fresh full-v1 attempt')
            f.state = json.loads(f.state_path.read_bytes());f.task = f.state['tasks'][0]
            self.assertEqual(2, f.task['attempt']);self.assertNotIn('sourceUsageAssurance', f.task)
            result = _fresh_result(f.root, f.state_path, attempt=2)
            result.update(planDigest=f.state['planDigest'], actor='/root', actorRunId='full-local-fixture')
            path = 'work/WS-01/attempt-2/task-result.json';put_artifact(f.root, path, result)
            receipt = _model_usage_receipt(f.task['modelRoute'])
            receipt['packageId'] = 'release-2-16'
            receipt.update(attempt=2, planDigest=f.state['planDigest'], sourceRevision=f.revision)
            receipt['usage']['invocations'] = 1
            usage_path = 'work/WS-01/attempt-2/full-usage.json';put_artifact(f.root, usage_path, receipt)
            commit_task_result(f.state_path, task_id='WS-01', operation_id='commit-full', expected_revision=5,
                result_path=path, model_usage_receipt_path=usage_path, source_revision=f.revision, reason='local full-v1 fixture')
            f.state = json.loads(f.state_path.read_bytes());f.task = f.state['tasks'][0]
            self.assertNotIn('sourceUsageAssurance', f.task)
            self.assertNotIn('usageAssurance', f.task['modelUsageReceipt'])
            self.assertEqual(original_assurance, f.task['attemptHistory'][0]['sourceUsageAssurance'])



def recovery_fixture(root):
    """Synthetic local authority only; no live controller/native qualification."""
    f = DeclaredFixture(root, initial_cap=100000)
    old_receipt = deepcopy(f.receipt)
    f.append_window(398, bound=True, cap=30000)
    f.close_window()
    originals = []
    windows = []
    for number in (397, 398):
        window = BASE + '/r' + str(number) + '-fixture'
        refs = []
        for name in ('admission.json', 'cost.json'):
            p = window + '/' + name
            data = (root / p).read_bytes()
            refs.append({'path': p, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)})
        originals.extend(refs)
        windows.append({'windowId': window, 'admissionRef': refs[0], 'costRef': refs[1]})
    identity = {key: json.loads((root / originals[0]['path']).read_bytes())['sourceUsageBinding'][key]
                for key in ('runId', 'packageId', 'taskId', 'attempt', 'semanticOperationId')}
    basis = put(root, 'work/recovery/basis.json', {'verdict': 'CHANGES_REQUIRED'})
    opening_ref = f.policy['openingRef']
    specification = {'schemaVersion': 'alk-source-window-conflict-recovery-specification.v2',
        'exactConflict': {'identityTuple': identity, 'originalWindowIds': [w['windowId'] for w in windows], 'originalRecords': originals},
        'wireContracts': {'disposition': {'basisReviewRef': basis}}}
    repair_dir = 'tasks/repair'
    spec_ref = put(root, repair_dir + '/spec.json', specification)
    spec_review_ref = put(root, repair_dir + '/spec-review.json', {'verdict': 'READY_FOR_PLAN_DRAFT'})
    inventory_ref = put(root, repair_dir + '/before.json', {'assurance': 'SYNTHETIC_IDENTITY_ONLY'})
    plan = {'schemaVersion': 'agent-plan-manifest.v1', 'status': 'FROZEN', 'planRevision': 1,
        'package': {'id': 'repair-fixture', 'planArtifactRoot': repair_dir},
        'packageIntegrity': {'required': True, 'allowedUnlistedFiles': ['plan.lock.json']},
        'planFiles': sorted([repair_dir + '/plan.manifest.json', spec_ref['path'], spec_review_ref['path'], inventory_ref['path'], repair_dir + '/review.json'])}
    plan_ref = put(root, repair_dir + '/plan.manifest.json', plan)
    review_ref = put(root, repair_dir + '/review.json', {'schemaVersion': 'agent-plan-review.v1',
        'verdict': 'READY_TO_FREEZE', 'fullReview': True, 'findings': [], 'reviewedPlanHash': canonical_digest(plan),
        'packageId': 'repair-fixture', 'planRevision': 1, 'reviewer': {'id': 'independent-fixture', 'independent': True}})
    lock_ref = put(root, repair_dir + '/plan.lock.json', build_plan_lock_v2(plan, repository_root=root))
    repair_fields = {'repairOperationId': 'repair-fixture-operation', 'inputSubjectDigest': 'a' * 64}
    admission_ref = f.append_window(399, repair_fields=repair_fields)
    admitted = read_coordinator_cost_head(root)
    financial_ref = put(root, 'work/recovery/admitted-head.json', admitted['headRaw'])
    before_refs = [put(root, 'src/before-' + str(i) + '.txt', b'before') for i in range(4)]
    admission = json.loads((root / admission_ref['path']).read_bytes())
    grant = {'schemaVersion': 'alk-source-conflict-controller-repair-grant.v1', 'grantId': 'grant-fixture',
        'actorId': '/root', 'independentReviewerId': 'independent-fixture', 'repairPackageId': 'repair-fixture',
        'repairOperationId': repair_fields['repairOperationId'], 'specificationRef': spec_ref,
        'specificationReviewRef': spec_review_ref, 'planRef': plan_ref, 'inventoryRef': inventory_ref,
        'lockRef': lock_ref, 'planReviewRef': review_ref, 'sourceRevision': f.revision,
        'sourceBeforeRefs': before_refs, 'oldRunStateRef': put(root, 'work/recovery/old-state.json', {'phase': 'BLOCKED'}),
        'onlyWritePaths': [r['path'] for r in before_refs], 'workArtifactRoot': 'work/recovery',
        'permittedWorkArtifacts': ['grant.json'], 'admissionRef': admission_ref,
        'authorizingFinancialHeadRef': financial_ref, 'inputSubjectDigest': repair_fields['inputSubjectDigest'],
        'tokenCap': admission['tokenCap'], 'protectedCloseoutTokens': admission['protectedCloseoutTokens'],
        'absoluteDeadlineUtc': admission['absoluteDeadlineUtc'], 'maxAffectedValidationCommands': 3,
        'maxIndependentSourceReviews': 1, 'maxNativeInvocations': 0, 'requiresNonrunningWorkspace': True,
        'sourceAssurance': 'CONTROLLER_REPAIR_SOURCE_ONLY_UNAVAILABLE', 'taskAccepted': False, 'releaseReady': False}
    grant_ref = put(root, 'work/recovery/grant.json', grant)
    disposition = {'schemaVersion': 'alk-source-window-conflict-disposition.v1',
        'dispositionId': 'r605-r606-source-window-conflict', 'identityTuple': identity, 'originalWindows': windows,
        'basisReviewRef': basis, 'authorizingReviewRef': review_ref, 'authorizingGrantRef': grant_ref,
        'originalOpeningRef': opening_ref, 'authorizingFinancialHeadRef': financial_ref,
        'classification': 'HISTORICAL_INELIGIBLE'}
    disp_ref = put(root, 'tasks/strategy/disposition.json', disposition)
    recovery_ref = put(root, 'tasks/strategy/source-usage-conflict-recovery.json', {
        'schemaVersion': 'alk-source-usage-conflict-recovery-policy.v1', 'originalOpeningRef': opening_ref,
        'dispositionRef': disp_ref})
    f.manifest['planFiles'] = sorted(f.manifest['planFiles'] + [disp_ref['path'], recovery_ref['path']])
    f.freeze()
    f.task['modelRoute']['operationId'] = 'fresh-recovery-source'
    f.task['attemptModelRoute']['operationId'] = 'fresh-recovery-source'
    f.admission_ref = f.append_window(400, bound=True, operation='fresh-recovery-source')
    f.receipt = f.make_receipt()
    f.recovery_disposition = disposition
    f.recovery_disposition_ref = disp_ref
    f.recovery_old_receipt = old_receipt
    f.recovery_original_refs = originals
    return f


class AccountingOnlyClockTests(unittest.TestCase):
    def fixture(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        f = DeclaredFixture(Path(directory.name).resolve())
        now = datetime.now(UTC).isoformat()
        self.prior = read_coordinator_cost_head(f.root)['head']
        self.bookkeeping = f.append_window(398, cap=7699, repair_fields={
            'accountingOnly': True, 'maxModelInvocations': 0,
            'maxTestInvocations': 0, 'maxNativeInvocations': 0,
            'admittedAtUtc': now, 'absoluteDeadlineUtc': now})
        self.original_admission = (f.root / self.bookkeeping['path']).read_bytes()
        f.close_window()
        cost_path = self.bookkeeping['path'].replace('/admission.json', '/cost.json')
        self.original_cost = (f.root / cost_path).read_bytes()
        self.cost_ref = {'path': cost_path, 'sha256': hashlib.sha256(self.original_cost).hexdigest(),
                         'bytes': len(self.original_cost)}
        f.task['modelRoute']['operationId'] = 'new-accounting-clock-current'
        f.task['attemptModelRoute'] = deepcopy(f.task['modelRoute'])
        f.admission_ref = f.append_window(399, bound=True)
        return f

    def test_accounting_only_zero_duration_preserves_complete_financial_context(self):
        f = self.fixture()
        snapshot = f.snapshot()
        projection = snapshot['projection']
        refs = [row['sourceRef'] for row in projection['records']]
        self.assertIn(self.bookkeeping, refs)
        self.assertIn(self.cost_ref, refs)
        self.assertLess(refs.index(self.bookkeeping), refs.index(self.cost_ref))
        self.assertEqual(self.original_admission, (f.root / self.bookkeeping['path']).read_bytes())
        self.assertEqual(self.original_cost, (f.root / self.cost_ref['path']).read_bytes())
        self.assertEqual(self.prior['unknownHolds'] + 7699 + 1000,
                         snapshot['current']['head']['unknownHolds'])
        self.assertEqual(self.prior['exposureLowerBound'] + 7699 + 1000,
                         snapshot['current']['head']['exposureLowerBound'])
        pool = next(row for row in projection['windowPools'] if row['admissionRef'] == self.bookkeeping)
        self.assertIsNone(pool['binding'])
        for role in projection['roleDispositions']:
            self.assertNotIn(pool['windowId'], role['windowIds'])
        self.assertEqual('PASS', f.validate(f.make_receipt())['status'])

    def test_accounting_only_cannot_authorize_current_receipt_frontier_or_refresh(self):
        f = self.fixture()
        receipt = f.make_receipt()
        receipt['currentAdmissionRef'] = deepcopy(self.bookkeeping)
        f.task['sourceUsageAssurance'] = {key: deepcopy(receipt[key]) for key in
                                        ('ledgerRef', 'currentRegistryRef', 'currentAdmissionRef')}
        path = 'work/accounting-only-not-work.json'
        identity = put_artifact(f.root, path, receipt)
        identity['sha256'] = canonical_digest(receipt)
        f.task.update(status='VERIFYING', modelUsageReceipt={**identity,
            'usageAssurance': {'usageMode': SOURCE_USAGE_MODE},
            'validation': {'receiptDigest': canonical_digest(receipt)}})
        for consumer in (lambda: f.validate(receipt),
                         lambda: require_task_source_frontier_current(f.root, f.state, f.task),
                         lambda: refresh_committed_source_assurance(f.root, f.state, f.task)):
            with self.subTest(consumer=consumer.__code__.co_firstlineno):
                with self.assertRaises(LifecycleError) as caught:
                    consumer()
                self.assertEqual('scoped-usage-current-admission-unbound', caught.exception.code)

    def test_accounting_only_clock_exception_requires_no_execution_authority(self):
        from agent_lifecycle.workflow.limited_usage import _window
        f = self.fixture()
        original = json.loads(self.original_admission)
        for stage in ('ADMISSION', 'COST'):
            base = original if stage == 'ADMISSION' else json.loads(self.original_cost)
            self.assertIsNone(_window(base, BASE + '/r398-fixture', stage))
            changes = [('missing-accounting-flag', {'accountingOnly': None}),
                       ('false-accounting-flag', {'accountingOnly': False}),
                       ('integer-accounting-flag', {'accountingOnly': 1}),
                       ('write-authority', {'productWriteAuthority': True}),
                       ('null-write-authority', {'productWriteAuthority': None}),
                       ('typed-binding', {'sourceUsageBinding': f.make_receipt()['lineage']})]
            for key in ('maxModelInvocations', 'maxTestInvocations', 'maxNativeInvocations'):
                for value in (None, 1, False, '0'):
                    changes.append((key + '-' + repr(value), {key: value}))
            for name, change in changes:
                with self.subTest(stage=stage, case=name):
                    value = {**deepcopy(base), **deepcopy(change)}
                    with self.assertRaises(LifecycleError) as caught:
                        _window(value, BASE + '/r398-fixture', stage)
                    self.assertEqual('scoped-usage-window-invalid', caught.exception.code)
            for key in ('maxModelInvocations', 'maxTestInvocations', 'maxNativeInvocations'):
                with self.subTest(stage=stage, missing=key):
                    value = deepcopy(base)
                    value.pop(key)
                    with self.assertRaises(LifecycleError) as caught:
                        _window(value, BASE + '/r398-fixture', stage)
                    self.assertEqual('scoped-usage-window-invalid', caught.exception.code)

    def test_work_clocks_utc_order_and_original_holds_remain_strict(self):
        from agent_lifecycle.workflow.limited_usage import _window
        f = self.fixture()
        accounting = json.loads(self.original_admission)
        work = json.loads((f.root / f.admission_ref['path']).read_bytes())
        self.assertEqual(work['sourceUsageBinding'], _window(work, BASE + '/r399-fixture', 'ADMISSION'))
        for name, value in [('untyped-work-zero', {**work, 'sourceUsageBinding': None,
                                                 'absoluteDeadlineUtc': work['admittedAtUtc']}),
                            ('typed-work-zero', {**work, 'absoluteDeadlineUtc': work['admittedAtUtc']}),
                            ('typed-accounting-work', {**work, 'accountingOnly': True,
                                'absoluteDeadlineUtc': work['admittedAtUtc'],
                                'maxModelInvocations': 0, 'maxTestInvocations': 0, 'maxNativeInvocations': 0}),
                            ('bookkeeping-backwards', {**accounting,
                                'absoluteDeadlineUtc': (datetime.fromisoformat(accounting['admittedAtUtc'])
                                                       - timedelta(seconds=1)).isoformat()}),
                            ('bookkeeping-naive', {**accounting, 'admittedAtUtc': '2026-10-02T18:49:34',
                                                  'absoluteDeadlineUtc': '2026-10-02T18:49:34'}),
                            ('bookkeeping-non-utc', {**accounting, 'admittedAtUtc': '2026-10-02T18:49:34+03:00',
                                                    'absoluteDeadlineUtc': '2026-10-02T18:49:34+03:00'}),
                            ('bookkeeping-hold-reset', {**accounting,
                                'unknownHoldsIncludingThisWindow': accounting['priorUnknownHolds']})]:
            with self.subTest(case=name):
                with self.assertRaises(LifecycleError) as caught:
                    _window(value, value.get('sourceUsageBinding', {}).get('originalWindowId',
                            BASE + '/r398-fixture') if value.get('sourceUsageBinding') else
                            BASE + '/r398-fixture', 'ADMISSION')
                self.assertEqual('scoped-usage-window-invalid', caught.exception.code)



class SourceConflictRecoveryTests(unittest.TestCase):
    def fixture(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return recovery_fixture(Path(directory.name).resolve())

    def test_recovery_original_v1_still_denies(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        f = DeclaredFixture(Path(directory.name).resolve())
        f.append_window(398, bound=True)
        with self.assertRaises(LifecycleError) as caught:
            f.snapshot()
        self.assertEqual('scoped-usage-window-conflict', caught.exception.code)

    def test_recovery_exact_four_record_disposition(self):
        f = self.fixture(); projection = f.snapshot()['projection']
        self.assertEqual('alk-source-usage-current-registry.v2', projection['schemaVersion'])
        self.assertEqual('PASS', f.validate()['status'])
        self.assertEqual(2, sum(p['eligibility'] == 'HISTORICAL_INELIGIBLE' for p in projection['windowPools']))
        self.assertEqual(1, len(projection['conflictDispositions']))
        self.assertIsNone(projection['balances']['actualTokens'])
        self.assertEqual('OPEN_UNAVAILABLE', f.validate()['usageAssurance']['financialClosure'])

    def test_recovery_original_cost_clock_binding_retained(self):
        f = self.fixture(); projection = f.snapshot()['projection']
        for reference in f.recovery_original_refs:
            self.assertEqual(1, sum(r['sourceRef'] == reference for r in projection['records']))
            original = json.loads((f.root / reference['path']).read_bytes())
            row = next(r for r in projection['records'] if r['sourceRef'] == reference)
            self.assertEqual(original['sourceUsageBinding'], row['binding'])
        source = f.root / f.recovery_original_refs[0]['path']; original = source.read_bytes()
        value = json.loads(original); value['absoluteDeadlineUtc'] = '2099-01-01T00:00:00+00:00'
        source.write_bytes(raw(value))
        with self.assertRaises(LifecycleError):f.snapshot()
        source.write_bytes(original)

    def test_recovery_unknown_or_edited_disposition_denied(self):
        f = self.fixture(); path = f.root / f.recovery_disposition_ref['path']; saved = path.read_bytes()
        for mutate in (lambda d:d.update(extra=True), lambda d:d['originalWindows'].pop(),
                       lambda d:d['originalWindows'].append(deepcopy(d['originalWindows'][0])),
                       lambda d:d['identityTuple'].update(attempt=True),
                       lambda d:d.update(classification='CURRENT_ELIGIBLE')):
            with self.subTest(mutation=mutate.__code__.co_firstlineno):
                value = json.loads(saved); mutate(value); path.write_bytes(raw(value))
                with self.assertRaises(LifecycleError):f.snapshot()
                path.write_bytes(saved)

    def test_recovery_new_eligible_duplicate_denied(self):
        f = self.fixture(); f.append_window(401, bound=True, operation='fresh-recovery-source')
        with self.assertRaises(LifecycleError):f.snapshot()
        other = self.fixture(); other.append_window(401, bound=True,
            operation=other.recovery_disposition['identityTuple']['semanticOperationId'])
        with self.assertRaises(LifecycleError):other.snapshot()

    def test_recovery_prospective_new_operation_only(self):
        f = self.fixture()
        from agent_lifecycle.contracts.scoped_usage_schemas import validate_source_conflict_grant_shape
        grant = json.loads((f.root / f.recovery_disposition['authorizingGrantRef']['path']).read_bytes())
        for key, bad in [('maxNativeInvocations', 1), ('maxIndependentSourceReviews', 2),
                         ('protectedCloseoutTokens', grant['tokenCap']), ('taskAccepted', True)]:
            with self.subTest(key=key):
                value = deepcopy(grant); value[key] = bad
                with self.assertRaises(LifecycleError):validate_source_conflict_grant_shape(value)
        self.assertNotEqual(f.recovery_disposition['identityTuple']['semanticOperationId'], f.receipt['operationId'])
        self.assertNotIn('sourceUsageBinding', json.loads((f.root / grant['admissionRef']['path']).read_bytes()))

    def test_recovery_no_retroactive_r606_authority(self):
        f = self.fixture(); original = deepcopy(f.receipt)
        for window in f.recovery_disposition['originalWindows']:
            receipt = deepcopy(original); receipt['currentAdmissionRef'] = window['admissionRef']
            with self.assertRaises(LifecycleError) as caught:f.validate(receipt)
            self.assertEqual('scoped-usage-current-admission-unbound', caught.exception.code)
        with self.assertRaises(LifecycleError):f.validate(f.recovery_old_receipt)
        self.assertEqual(f.recovery_old_receipt['operationId'], f.recovery_disposition['identityTuple']['semanticOperationId'])

    def test_recovery_complete_financial_interval_retained(self):
        f = self.fixture(); snapshot = f.snapshot(); p = snapshot['projection']
        self.assertEqual(list(reversed(snapshot['current']['ancestryHeadSha256s'])), [r['headRef']['sha256'] for r in p['records']])
        self.assertEqual(f.policy['openingRef']['sha256'], p['openingHeadSha256'])
        self.assertEqual(snapshot['current']['head']['unknownHolds'], p['balances']['currentUnknownHolds'])
        self.assertEqual(snapshot['current']['head']['exposureLowerBound'], p['balances']['currentExposureLowerBound'])
        self.assertEqual(list(SOURCE_USAGE_ROLES), [r['role'] for r in p['roleDispositions']])
        self.assertTrue(p['unknownIntervals'])
        f.append_window(401)
        with self.assertRaises(LifecycleError):require_snapshot_current(f.selection(), snapshot)


class SourceRecoveryConsumerRefusalTests(unittest.TestCase):
    fixture = SourceConflictRecoveryTests.fixture
    """Named semantic mutations re-freeze selectors, rather than only stale hashes."""
    def reselect(self, f, disposition=None, policy_mutation=None):
        disposition = deepcopy(disposition or f.recovery_disposition)
        reference = put(f.root, 'tasks/strategy/disposition.json', disposition)
        policy = {'schemaVersion': 'alk-source-usage-conflict-recovery-policy.v1',
                  'originalOpeningRef': f.policy['openingRef'], 'dispositionRef': reference}
        if policy_mutation:policy_mutation(policy)
        put(f.root, 'tasks/strategy/source-usage-conflict-recovery.json', policy)
        f.freeze()
        return disposition

    def consumers_refuse(self, f):
        receipt = deepcopy(f.receipt)
        identity = put_artifact(f.root, 'work/WS-01/attempt-1/model-usage.json', receipt)
        f.task['status'] = 'VERIFYING'
        f.task['modelUsageReceipt'] = {**identity, 'validation': {'receiptDigest': canonical_digest(receipt)},
                                      'usageAssurance': {'financialClosure': 'OPEN_UNAVAILABLE'}}
        checks = {'snapshot': f.snapshot, 'emit-or-reuse': lambda:emit_registry_artifact(f.root,f.state,f.task),
                  'receipt': lambda:f.validate(receipt),
                  'committed-refresh': lambda:refresh_committed_source_assurance(f.root,f.state,f.task)}
        for name, check in checks.items():
            with self.subTest(consumer=name):
                with self.assertRaises((LifecycleError, FileNotFoundError)):check()
        self.assertEqual(raw(receipt)+b'\n', (f.root / identity['path']).read_bytes())
        return checks

    def test_recovery_legacy_output_bytes_unchanged(self):
        import types
        self.assertEqual('74b8228431932f36503961e207b089b195bbe6322d18aa796632e58b53a8ab6c',hashlib.sha256(RECOVERY_LEGACY_SOURCE.encode()).hexdigest())
        before=types.ModuleType('limited_usage_before_fixture')
        exec(compile(RECOVERY_LEGACY_SOURCE,'<exact-original-limited-usage-fixture>','exec'),before.__dict__)
        with tempfile.TemporaryDirectory() as directory:
            f=DeclaredFixture(Path(directory).resolve())
            old_selection=before.load_frozen_source_policy(f.root,f.state,f.task)
            self.assertEqual(before.current_source_snapshot(old_selection)['projectionBytes'], f.snapshot()['projectionBytes'])
            self.assertEqual(before.validate_limited_source_usage(f.root,f.state,f.task,f.receipt), f.validate())

    def test_recovery_all_original_metadata_and_130000_hold_retained(self):
        f=self.fixture();p=f.snapshot()['projection']
        pools=[row for row in p['windowPools'] if row['eligibility']=='HISTORICAL_INELIGIBLE']
        self.assertEqual([100000,30000],[json.loads((f.root/row['admissionRef']['path']).read_bytes())['tokenCap'] for row in pools])
        self.assertEqual(130000,sum(json.loads((f.root/row['admissionRef']['path']).read_bytes())['tokenCap'] for row in pools))
        for reference in f.recovery_original_refs:
            source=f.root/reference['path'];saved=source.read_bytes();original=json.loads(saved)
            record=next(row for row in p['records'] if row['sourceRef']==reference)
            self.assertEqual(original['sourceUsageBinding'],record['binding'])
            for key in ['tokenCap','protectedCloseoutTokens','admittedAtUtc','absoluteDeadlineUtc',
                        'unknownHoldsIncludingThisWindow','ledgerLowerBoundIncludingThisHold','sourceUsageBinding']:
                if key not in original:continue
                with self.subTest(stage=reference['path'],field=key):
                    mutated=deepcopy(original)
                    if key=='sourceUsageBinding':mutated[key]['semanticOperationId']='changed-original'
                    elif isinstance(mutated[key],int):mutated[key]+=1
                    else:mutated[key]='2099-01-01T00:00:00+00:00'
                    source.write_bytes(raw(mutated))
                    with self.assertRaises(LifecycleError):f.snapshot()
                    source.write_bytes(saved)
            self.assertEqual(reference,{'path':reference['path'],'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'bytes':len(source.read_bytes())})
        first=[next(i for i,r in enumerate(p['records']) if r['sourceRef']==ref) for ref in f.recovery_original_refs]
        self.assertEqual(sorted(first),first)

    def test_recovery_named_semantic_authority_mutations_refuse(self):
        mutations=['missing-raw-reference','missing-cost','third-tuple-member','duplicate-disposition',
                   'unknown-conflict-group','malformed-policy','malformed-grant','unlisted-lock-member',
                   'unknown-field','cyclic-authority','missing-authority','edited-authorizing-head']
        for name in mutations:
            with self.subTest(case=name):
                f=self.fixture();d=deepcopy(f.recovery_disposition)
                if name=='missing-raw-reference':(f.root/d['originalWindows'][0]['admissionRef']['path']).unlink()
                elif name=='missing-cost':(f.root/d['originalWindows'][1]['costRef']['path']).unlink()
                elif name=='third-tuple-member':f.append_window(401,bound=True,operation=d['identityTuple']['semanticOperationId'])
                elif name=='duplicate-disposition':d['originalWindows'].append(deepcopy(d['originalWindows'][0]));self.reselect(f,d)
                elif name=='unknown-conflict-group':d['identityTuple']['semanticOperationId']='unreviewed-group';self.reselect(f,d)
                elif name=='malformed-policy':self.reselect(f,policy_mutation=lambda p:p.update(ignoreUnknown=True))
                elif name=='unknown-field':d['ignoreUnknown']=True;self.reselect(f,d)
                elif name=='unlisted-lock-member':
                    f.manifest['planFiles'].remove('tasks/strategy/source-usage-conflict-recovery.json');f.freeze()
                elif name=='missing-authority':(f.root/d['authorizingGrantRef']['path']).unlink()
                else:
                    grant=json.loads((f.root/d['authorizingGrantRef']['path']).read_bytes())
                    if name=='malformed-grant':grant['nativeAuthority']=True
                    elif name=='cyclic-authority':grant['planRef']=d['authorizingGrantRef']
                    else:
                        head=json.loads((f.root/d['authorizingFinancialHeadRef']['path']).read_bytes())
                        head['sourcePath']=d['originalWindows'][0]['admissionRef']['path']
                        headref=put(f.root,'work/recovery/edited-head.json',head)
                        d['authorizingFinancialHeadRef']=headref;grant['authorizingFinancialHeadRef']=headref
                    d['authorizingGrantRef']=put(f.root,'work/recovery/grant.json',grant);self.reselect(f,d)
                self.consumers_refuse(f)

    def test_recovery_all_consumers_refuse_both_duplicate_groups(self):
        for operation in ['fresh-recovery-source','original-conflict']:
            with self.subTest(operation=operation):
                f=self.fixture()
                f.append_window(401,bound=True,operation=operation if operation!='original-conflict' else f.recovery_disposition['identityTuple']['semanticOperationId'])
                self.consumers_refuse(f)

    def test_recovery_old_receipts_cannot_gain_current_authority(self):
        f=self.fixture();old_bytes=raw(f.recovery_old_receipt)+b'\n'
        old_path='work/historical-r605/model-usage.json';put(f.root,old_path,old_bytes)
        self.assertFalse((f.root/'work/historical-r606/model-usage.json').exists())
        for row in f.recovery_disposition['originalWindows']:
            with self.subTest(window=row['windowId']):
                f.admission_ref=row['admissionRef'];receipt=f.make_receipt()
                with self.assertRaises(LifecycleError):f.validate(receipt)
                identity=put_artifact(f.root,'work/WS-01/attempt-1/model-usage.json',receipt)
                f.task['status']='VERIFYING'
                f.task['modelUsageReceipt']={**identity,'validation':{'receiptDigest':canonical_digest(receipt)},'usageAssurance':{'financialClosure':'OPEN_UNAVAILABLE'}}
                with self.assertRaises(LifecycleError):refresh_committed_source_assurance(f.root,f.state,f.task)
                self.assertEqual(old_bytes,(f.root/old_path).read_bytes())
        self.assertFalse((f.root/'work/historical-r606/model-usage.json').exists())
        self.assertIsNone(f.snapshot()['projection']['balances']['actualTokens'])
        self.assertNotEqual('ACCEPTED',f.task['status'])

    def test_recovery_bounds_missing_ancestry_and_unstable_head_refuse(self):
        from unittest.mock import patch
        f=self.fixture();selection=f.selection();a=read_coordinator_cost_head(f.root,ancestor_head_sha256=f.policy['openingRef']['sha256'])
        f.append_window(401);b=read_coordinator_cost_head(f.root,ancestor_head_sha256=f.policy['openingRef']['sha256'])
        with self.subTest(case='actual-two-descendant-heads-unstable-read'):
            self.assertNotEqual(a['headRaw'],b['headRaw'])
            with patch('agent_lifecycle.accounting.declared_ledger.read_declared_ledger',side_effect=[a,b]) as ledger_reader:
                with self.assertRaises(LifecycleError) as caught:current_source_snapshot(selection)
                self.assertEqual('scoped-usage-frontier-stale',caught.exception.code)
                self.assertEqual(2,ledger_reader.call_count)
        other=self.fixture();h=read_coordinator_cost_head(other.root,ancestor_head_sha256=other.policy['openingRef']['sha256'])
        path=other.root/BASE/'coordinator-cost-head-history'/ (h['ancestryHeadSha256s'][2]+'.json')
        with self.subTest(case='missing-ancestry'):path.unlink();self.consumers_refuse(other)
        large=self.fixture()
        for number in range(401,435):large.append_window(number)
        with self.subTest(case='complete-recovery-interval-exceeds-original-64k-bound'):
            with self.assertRaises(LifecycleError) as caught:large.snapshot()
            self.assertEqual('scoped-usage-registry-bound',caught.exception.code)

    def test_recovery_frontier_guard_rejects_both_historical_admissions(self):
        f = self.fixture()
        receipt = f.make_receipt()
        current = {key: deepcopy(receipt[key]) for key in
                   ('ledgerRef', 'currentRegistryRef', 'currentAdmissionRef')}
        f.task['sourceUsageAssurance'] = current
        require_task_source_frontier_current(f.root, f.state, f.task)
        for row in f.recovery_disposition['originalWindows']:
            with self.subTest(window=row['windowId']):
                f.task['sourceUsageAssurance'] = {**deepcopy(current),
                    'currentAdmissionRef': deepcopy(row['admissionRef'])}
                self.assertEqual(current['ledgerRef'], f.make_receipt()['ledgerRef'])
                self.assertEqual(current['currentRegistryRef'], f.make_receipt()['currentRegistryRef'])
                with self.assertRaises(LifecycleError) as caught:
                    require_task_source_frontier_current(f.root, f.state, f.task)
                self.assertEqual('scoped-usage-current-admission-unbound', caught.exception.code)

    def test_recovery_frontier_guard_current_and_context_only_remain_valid(self):
        f = self.fixture()
        receipt = f.make_receipt()
        for selected in (True, False):
            with self.subTest(admission_selected=selected):
                keys = ('ledgerRef', 'currentRegistryRef', 'currentAdmissionRef') if selected else (
                    'ledgerRef', 'currentRegistryRef')
                f.task['sourceUsageAssurance'] = {key: deepcopy(receipt[key]) for key in keys}
                self.assertIsNone(require_task_source_frontier_current(f.root, f.state, f.task))

    def test_recovery_frontier_guard_untyped_and_absent_admissions_refuse(self):
        f = self.fixture()
        receipt = f.make_receipt()
        projection = f.snapshot()['projection']
        untyped = next(row['admissionRef'] for row in projection['windowPools']
                       if row['binding'] is None)
        absent = {**deepcopy(receipt['currentAdmissionRef']), 'sha256': '0' * 64}
        for name, reference in [('untyped', untyped), ('absent', absent)]:
            with self.subTest(case=name):
                f.task['sourceUsageAssurance'] = {key: deepcopy(receipt[key]) for key in
                                               ('ledgerRef', 'currentRegistryRef')}
                f.task['sourceUsageAssurance']['currentAdmissionRef'] = reference
                with self.assertRaises(LifecycleError) as caught:
                    require_task_source_frontier_current(f.root, f.state, f.task)
                self.assertEqual('scoped-usage-current-admission-unbound', caught.exception.code)

    def test_recovery_frontier_guard_v1_eligibility_default_remains_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            f = DeclaredFixture(Path(directory).resolve())
            receipt = f.make_receipt()
            pool = next(row for row in f.snapshot()['projection']['windowPools']
                        if row['admissionRef'] == receipt['currentAdmissionRef'])
            self.assertNotIn('eligibility', pool)
            self.assertIsNotNone(pool['binding'])
            f.task['sourceUsageAssurance'] = {key: deepcopy(receipt[key]) for key in
                                           ('ledgerRef', 'currentRegistryRef', 'currentAdmissionRef')}
            self.assertIsNone(require_task_source_frontier_current(f.root, f.state, f.task))



def controller_gate_fixture(directory):
    """Exact frozen gate bytes with a separate synthetic local authority/real ledger.

    Parameterize checkout roots at import, never mutate the actual grant or run.
    Plan-review observations here are fixture data, not independent-review proof.
    """
    import shutil,os,sys
    base=Path(directory).resolve();primary=base/'primary';primary.mkdir()
    f=recovery_fixture(primary);f.close_window()
    old=base/'old';repair=base/'repair'
    for checkout in [old,repair]:
        subprocess.run(['git','worktree','add','--detach','--quiet',str(checkout),f.revision],cwd=primary,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    actual_root=Path(__file__).resolve().parents[2]
    shutil.copytree(actual_root/'src',old/'src',dirs_exist_ok=True)
    package='tasks/release-2-16-source-conflict-repair'
    gate_ref=put(repair,package+'/controller_repair_gate.py',RECOVERY_GATE_SOURCE.encode())
    if hashlib.sha256(RECOVERY_GATE_SOURCE.encode()).hexdigest()!=RECOVERY_GATE_SHA256:
        raise AssertionError('exact independently frozen gate fixture changed')
    cfg={'sourceRevision':f.revision,'onlyWritePaths':list(RECOVERY_GATE_WRITE_PATHS),
         'permittedWorkArtifacts':list(RECOVERY_GATE_ARTIFACTS),
         'actualPlanFinalPath':'work/controller-fixture/actual-final.json',
         'actualPlanObservationPath':'work/controller-fixture/observation.json'}
    d=f.recovery_disposition
    spec={'bootstrap':{'onlyWritePaths':cfg['onlyWritePaths'],'grantSchema':{'closedKeys':list(RECOVERY_GRANT_KEYS)}},
          'exactConflict':{'identityTuple':d['identityTuple'],'originalWindowIds':[r['windowId'] for r in d['originalWindows']],'originalRecords':f.recovery_original_refs},
          'wireContracts':{'disposition':{'originalOpeningRef':f.policy['openingRef'],'basisReviewRef':d['basisReviewRef']}}}
    put(repair,package+'/SPECIFICATION.json',spec)
    put(repair,package+'/SPECIFICATION-REVIEW.json',{'verdict':'READY_FOR_PLAN_DRAFT','findings':[],'fixtureOnly':True})
    cfg['oldStateRef']=put(old,'work/release-2-16/run.state.json',{'phase':'BLOCKED','stateRevision':9,'runId':'release-2-16-r76-20261002'})
    refs=[];snapshots=[]
    for path in cfg['onlyWritePaths']:
        before=put(repair,path,b'fixture before\n');refs.append(before)
        snapshot=put(repair,package+'/source-before/'+path,b'fixture before\n')
        snapshots.append({'originalPath':path,'beforeRef':before,'snapshotRef':snapshot})
    cfg['sourceSnapshots']=snapshots
    cfg['wipBeforeInventoryRef']=put(repair,package+'/SOURCE-BEFORE.json',{'sourceRevision':f.revision,'sourceSnapshots':snapshots,'wipBeforeRefs':refs})
    deprefs=[]
    for path in sorted(p for p in (old/'src').rglob('*') if p.is_file()):
        data=path.read_bytes();deprefs.append({'path':str(path.relative_to(old)),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
    put(repair,package+'/old-finance-dependencies.json',{'references':deprefs})
    put(repair,package+'/repair-authority-inputs.json',cfg)
    names=['plan.manifest.json','controller_repair_gate.py','SPECIFICATION.json','SPECIFICATION-REVIEW.json',
           'SOURCE-BEFORE.json','old-finance-dependencies.json','repair-authority-inputs.json','independent-s2-review.json']
    plan_files=sorted([package+'/'+name for name in names]+[row['snapshotRef']['path'] for row in snapshots])
    m={'schemaVersion':'agent-plan-manifest.v1','status':'FROZEN','planRevision':1,
       'package':{'id':'fixture-controller-repair','planArtifactRoot':package},
       'baseRevision':{'sha':f.revision},'packageIntegrity':{'required':True,'allowedUnlistedFiles':['plan.lock.json']},
       'planFiles':plan_files,'planReview':{'report':package+'/independent-s2-review.json'},
       'workstreams':[{'id':'controller-repair','writes':cfg['onlyWritePaths']}]}
    put(repair,package+'/plan.manifest.json',m)
    report={'schemaVersion':'agent-plan-review.v1','verdict':'READY_TO_FREEZE','fullReview':True,'findings':[],
            'reviewedPlanHash':canonical_digest(m),'reviewedRevision':1,'planRevision':1,
            'packageId':m['package']['id'],'reviewer':{'id':'fixture-independent-not-live','independent':True}}
    put(repair,m['planReview']['report'],report)
    lock=build_plan_lock_v2(m,repository_root=repair);put(repair,package+'/plan.lock.json',lock)
    final=raw(report);final_ref=put(primary,cfg['actualPlanFinalPath'],final)
    put(primary,cfg['actualPlanObservationPath'],{'status':'ACTUAL_COMPLETE_FINAL_OBSERVED','exitCode':0,'timely':True,'processStopped':True,'actualFinalSha256':final_ref['sha256'],'fixtureOnly':True})
    shutil.copytree(repair/package,primary/package,dirs_exist_ok=True)
    window=primary/BASE/'r700-controller-repair'
    wrapper=base/'invoke_gate.py'
    wrapper.write_text("""import importlib.util,sys,pathlib,datetime,os,types
s=importlib.util.spec_from_file_location('fixture_gate',sys.argv[1]);g=importlib.util.module_from_spec(s);s.loader.exec_module(g)
g.OLD=pathlib.Path(sys.argv[2]);g.PRIMARY=pathlib.Path(sys.argv[3]);root=pathlib.Path(sys.argv[4]);window=pathlib.Path(sys.argv[5]);action=sys.argv[6];hook=sys.argv[7]
if hook=='future':g.NOW=lambda:datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=1)
if hook=='interrupt-after-financial-advance':
 original=g.write_new
 def interrupted(p,v):
  if p.name=='GRANT.json':raise ValueError('fixture interruption after actual financial advance')
  return original(p,v)
 g.write_new=interrupted
if hook=='unstable-replacement-input':
 original_read=g.safe_read
 def unstable(root,path,limit=8388608):
  if path!='SOURCE-REPLACEMENTS.json':return original_read(root,path,limit)
  original_stat=os.fstat;count=[0]
  def changed(fd):
   st=original_stat(fd);count[0]+=1
   return types.SimpleNamespace(st_dev=st.st_dev,st_ino=st.st_ino,st_size=st.st_size,st_mtime_ns=st.st_mtime_ns+(count[0]>1),st_mode=st.st_mode)
  os.fstat=changed
  try:return original_read(root,path,limit)
  finally:os.fstat=original_stat
 g.safe_read=unstable
try:
 if action=='issue':g.issue(root,window)
 elif action=='apply':g.apply(root,window,window/'SOURCE-REPLACEMENTS.json')
 else:g.pre_effect(root,window,'TEST')
except Exception as e:print(type(e).__name__+': '+str(e),file=sys.stderr);sys.exit(2)
""")
    def call(action='issue',hook='',target=None):
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1');env.pop('PYTHONPATH',None)
        return subprocess.run([sys.executable,str(wrapper),str(repair/package/'controller_repair_gate.py'),str(old),str(primary),str(repair),str(target or window),action,hook],env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45)
    return {'f':f,'primary':primary,'old':old,'root':repair,'package':package,'window':window,'cfg':cfg,'call':call}


class ControllerRepairGateRefusalTests(unittest.TestCase):
    """Actual gate function executions in isolated fixtures; no runtime assurance."""
    def test_recovery_prospective_gate_negatives_preserve_effect_boundary(self):
        import sys,shutil
        names=['no-independent-freeze','stale-source-before','expired-admission','reused-operation',
            'concurrent-grant','running-repair-workspace','out-of-scope-product-input',
            'edited-admission-grant-disposition','invocation-excess','edited-original-financial-record',
            'changed-preserved-state','old-financial-dependency-changed','unchanged-records-missing-original-ancestry',
            'second-window-after-expiration','second-window-after-cost-closure','missing-primary-mirror',
            'different-primary-mirror','oversized-replacement-input','unstable-replacement-input',
            'failure-after-financial-advance-then-second-window']
        after_issue={'expired-admission','out-of-scope-product-input','edited-admission-grant-disposition',
            'invocation-excess','second-window-after-expiration','second-window-after-cost-closure',
            'oversized-replacement-input','unstable-replacement-input'}
        for name in names:
            with self.subTest(case=name),tempfile.TemporaryDirectory() as directory:
                g=controller_gate_fixture(directory);f=g['f'];root=g['root'];old=g['old'];primary=g['primary'];window=g['window'];package=g['package'];call=g['call'];action='issue';hook='';target=None
                if name in after_issue:
                    issued=call();self.assertEqual(0,issued.returncode,issued.stderr)
                    action='pre-effect'
                if name=='no-independent-freeze':
                    m=json.loads((root/package/'plan.manifest.json').read_bytes());m['status']='DRAFT';put(root,package+'/plan.manifest.json',m)
                elif name=='stale-source-before':put(root,g['cfg']['onlyWritePaths'][0],b'changed before')
                elif name=='expired-admission':hook='future'
                elif name=='reused-operation':f.append_window(401,repair_fields={'repairOperationId':window.name+'-controller-repair'})
                elif name=='concurrent-grant':
                    put(primary,BASE+'/r799-other/GRANT.json',{'schemaVersion':'alk-source-conflict-controller-repair-grant.v1','repairPackageId':'other','planRef':{'sha256':'b'*64},'absoluteDeadlineUtc':(datetime.now(UTC)+timedelta(days=1)).isoformat()})
                elif name=='running-repair-workspace':put(root,'work/release-2-16/run.state.json',{'phase':'RUNNING'})
                elif name=='out-of-scope-product-input':
                    action='apply';put(primary,str(window.relative_to(primary))+'/SOURCE-REPLACEMENTS.json',{'sourceChanges':[{'path':'src/example.py','beforeSha256':'0'*64,'afterText':'unauthorized'}]})
                elif name=='edited-admission-grant-disposition':
                    (window/'DISPOSITION.json').write_bytes((window/'DISPOSITION.json').read_bytes()+b' ')
                elif name=='invocation-excess':
                    (window/'GATE-CHECKS.jsonl').write_bytes(b'{"kind":"TEST"}\n'*3)
                elif name=='edited-original-financial-record':
                    p=primary/f.recovery_original_refs[0]['path'];p.write_bytes(p.read_bytes()+b' ')
                elif name=='changed-preserved-state':put(old,'work/release-2-16/run.state.json',{'phase':'RUNNING'})
                elif name=='old-financial-dependency-changed':
                    p=old/'src/agent_lifecycle/__init__.py';p.write_bytes(p.read_bytes()+b'\n# changed fixture\n')
                elif name=='unchanged-records-missing-original-ancestry':
                    h=read_coordinator_cost_head(primary,ancestor_head_sha256=f.policy['openingRef']['sha256'])
                    (primary/BASE/'coordinator-cost-head-history'/(h['ancestryHeadSha256s'][2]+'.json')).unlink()
                elif name.startswith('second-window-'):
                    target=window.with_name('r701-second-controller-repair');action='issue'
                    if name.endswith('expiration'):hook='future'
                    else:put(primary,str(window.relative_to(primary))+'/cost.json',{'fixtureClosed':True})
                elif name=='missing-primary-mirror':(primary/package/'SPECIFICATION.json').unlink()
                elif name=='different-primary-mirror':
                    p=primary/package/'SPECIFICATION.json';p.write_bytes(p.read_bytes()+b' ')
                elif name=='oversized-replacement-input':
                    action='apply';(window/'SOURCE-REPLACEMENTS.json').write_bytes(b' '*(8388608+1))
                elif name=='unstable-replacement-input':
                    action='apply';hook=name
                    put(primary,str(window.relative_to(primary))+'/SOURCE-REPLACEMENTS.json',{'sourceChanges':[{'path':g['cfg']['onlyWritePaths'][0],'beforeSha256':hashlib.sha256((root/g['cfg']['onlyWritePaths'][0]).read_bytes()).hexdigest(),'afterText':'change'}]})
                elif name=='failure-after-financial-advance-then-second-window':
                    before=read_coordinator_cost_head(primary)['headSha256']
                    interrupted=call(hook='interrupt-after-financial-advance');self.assertEqual(2,interrupted.returncode)
                    after=read_coordinator_cost_head(primary);self.assertNotEqual(before,after['headSha256'])
                    self.assertTrue((window/'ISSUANCE-CLAIM.json').exists());self.assertFalse((window/'GRANT.json').exists())
                    target=window.with_name('r701-second-controller-repair')
                observed_before={p:(root/p).read_bytes() for p in g['cfg']['onlyWritePaths']}
                financial_path=primary/BASE/'COORDINATOR-COST-HEAD.json';financial_before=financial_path.read_bytes()
                old_state=(old/'work/release-2-16/run.state.json').read_bytes()
                result=call(action,hook,target)
                self.assertEqual(2,result.returncode,result.stdout+result.stderr)
                self.assertTrue('CONTROLLER_REPAIR_DENIED' in result.stderr or (name=='unchanged-records-missing-original-ancestry' and 'LifecycleError: archived predecessor is unavailable' in result.stderr) or (name=='missing-primary-mirror' and 'FileNotFoundError: ' in result.stderr),result.stderr)
                self.assertEqual(financial_before,financial_path.read_bytes())
                self.assertEqual(old_state,(old/'work/release-2-16/run.state.json').read_bytes())
                self.assertEqual(observed_before,{p:(root/p).read_bytes() for p in g['cfg']['onlyWritePaths']})
                if target:self.assertFalse(target.exists())

# Byte-pinned fixture inputs; synthetic local reviews do not confer live authority.
RECOVERY_LEGACY_SOURCE = '"""Frozen, source-only usage validation against the existing declared ledger.\n\nThe financial selector is independent of producer references. Returned PASS\nmeans the selected limited contract matched, never measured cap conformance.\n"""\n\nfrom __future__ import annotations\n\nimport hashlib\nimport json\nimport re\nfrom datetime import datetime, timezone\nfrom pathlib import Path\nfrom typing import Any\n\nfrom agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object\nfrom agent_lifecycle.contracts.authority_io import create_authority_bytes, read_authority_bytes\nfrom agent_lifecycle.contracts.paths import normalize_repo_path\nfrom agent_lifecycle.contracts.scoped_usage_schemas import (\n    MAX_CURRENT_SOURCE_REGISTRY_BYTES, MAX_SAFE_INTEGER,\n    MAX_SOURCE_USAGE_BINDINGS, MAX_SOURCE_USAGE_BYTES,\n    SOURCE_CURRENT_REGISTRY, SOURCE_USAGE_MODE, SOURCE_USAGE_ROLES,\n    validate_source_ref_shape, validate_source_registry_prefix_shape,\n    validate_source_usage_policy_shape, validate_source_usage_receipt_shape,\n    validate_source_window_binding,\n)\nfrom agent_lifecycle.freeze.package_integrity import verify_plan_package_integrity\nfrom agent_lifecycle.workflow.artifacts import artifact_identity, artifact_path\n\n_HEAD_PATH = "work/release-2-16/enforcement-decision/COORDINATOR-COST-HEAD.json"\n_WINDOW = re.compile(r"(work/release-2-16/enforcement-decision/r([1-9][0-9]*)-[a-z0-9-]+)/(admission|cost)\\.json")\n\n\ndef _require(condition: bool, code: str, message: str) -> None:\n    if not condition:\n        raise LifecycleError(code, message)\n\n\ndef _ref(path: str, raw: bytes) -> dict[str, Any]:\n    return {"path": path, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}\n\n\ndef _read_ref(root: Path, ref: dict[str, Any], *, limit: int) -> bytes:\n    validate_source_ref_shape(ref)\n    _require(ref["bytes"] <= limit, "scoped-usage-ref-invalid", "reference exceeds its bound")\n    raw = read_authority_bytes(root / ref["path"], root=root, max_bytes=limit)\n    _require(_ref(ref["path"], raw) == ref, "scoped-usage-ref-invalid", "reference bytes differ")\n    return raw\n\n\ndef _load_frozen_source_context(\n    repository_root: Path, state: dict[str, Any],\n) -> dict[str, Any] | None:\n    """Select opt-in from actual adopted package bytes, not receipt or state mode."""\n\n    root = Path(repository_root).absolute()\n    manifest_path = state.get("manifestPath")\n    if not manifest_path:\n        return None\n    path = normalize_repo_path(manifest_path, label="current frozen manifest")\n    raw_manifest = read_authority_bytes(root / path, root=root, max_bytes=1_048_576)\n    manifest = load_json_object(raw_manifest, label="current frozen manifest")\n    runtime = manifest.get("runtimePolicy")\n    if not isinstance(runtime, dict) or "sourceUsageCompletion" not in runtime:\n        return None\n    policy = validate_source_usage_policy_shape(runtime["sourceUsageCompletion"])\n    lock_path = str(Path(path).with_name("plan.lock.json"))\n    lock = load_json_object(read_authority_bytes(root / lock_path, root=root, max_bytes=1_048_576),\n                            label="current frozen lock")\n    verify_plan_package_integrity(manifest, lock, repository_root=root)\n    package = manifest.get("package", {})\n    _require(manifest.get("status") == "FROZEN"\n             and state.get("planDigest") == canonical_digest(manifest)\n             and state.get("planRevision") == manifest.get("planRevision")\n             and state.get("packageId") == package.get("id")\n             and state.get("sourceRevision") == manifest.get("baseRevision", {}).get("sha"),\n             "scoped-usage-plan-stale", "current frozen plan lineage differs")\n    entries = {entry["path"]: entry for entry in lock["entries"]}\n    for key in ("openingRef", "sourceAuthoringRegistryRef"):\n        ref = policy[key]\n        _require(entries.get(ref["path"]) == ref, "scoped-usage-policy-unbound",\n                 "limited policy input is outside the exact frozen inventory")\n    opening_raw = _read_ref(root, policy["openingRef"], limit=MAX_SOURCE_USAGE_BYTES)\n    prefix_raw = _read_ref(root, policy["sourceAuthoringRegistryRef"], limit=MAX_SOURCE_USAGE_BYTES)\n    opening = load_json_object(opening_raw, label="frozen financial opening")\n    prefix = validate_source_registry_prefix_shape(load_json_object(prefix_raw, label="frozen source prefix"))\n    _require(prefix["openingHeadSha256"] == policy["openingRef"]["sha256"],\n             "scoped-usage-opening-mismatch", "registry prefix selects another opening")\n    registry_byte_limit = MAX_SOURCE_USAGE_BYTES\n    capacity_path = str(Path(path).with_name("source-usage-registry-capacity.json"))\n    if capacity_path in entries:\n        _require(capacity_path in manifest.get("planFiles", []),\n                 "scoped-usage-policy-unbound", "registry capacity is outside the frozen inventory")\n        capacity_raw = _read_ref(root, entries[capacity_path], limit=MAX_SOURCE_USAGE_BYTES)\n        capacity = load_json_object(capacity_raw, label="frozen registry capacity")\n        _require(capacity.get("schemaVersion") == "alk-source-usage-registry-capacity-amendment.v1"\n                 and capacity.get("originalCurrentRegistryMaxBytes") == MAX_SOURCE_USAGE_BYTES\n                 and capacity.get("currentRegistryMaxBytes") == MAX_CURRENT_SOURCE_REGISTRY_BYTES\n                 and capacity.get("frozenOpeningAndPrefixMaxBytes") == MAX_SOURCE_USAGE_BYTES\n                 and capacity.get("usageReceiptMaxBytes") == MAX_SOURCE_USAGE_BYTES,\n                 "scoped-usage-capacity-invalid", "frozen registry capacity differs from its contract")\n        registry_byte_limit = MAX_CURRENT_SOURCE_REGISTRY_BYTES\n    return {"root": root, "manifest": manifest, "lock": lock, "policy": policy,\n            "policyDigest": canonical_digest(policy), "opening": opening,\n            "prefix": prefix, "prefixRaw": prefix_raw, "registryByteLimit": registry_byte_limit}\n\n\ndef load_frozen_source_policy(\n    repository_root: Path, state: dict[str, Any], task: dict[str, Any], *,\n    adapter_id: str | None = None, adapter_host: str | None = None,\n) -> dict[str, Any] | None:\n    """Select task eligibility separately from shared historical context."""\n\n    selected = _load_frozen_source_context(repository_root, state)\n    if selected is None:\n        return None\n    policy, manifest = selected["policy"], selected["manifest"]\n    _require(task.get("id") in policy["taskIds"]\n             and any(row.get("id") == task.get("id") for row in manifest.get("workstreams", [])\n                     if isinstance(row, dict)), "scoped-usage-policy-scope-mismatch",\n             "task is outside the frozen limited scope")\n    if adapter_id is not None:\n        _require(policy["adapterId"] == adapter_id, "scoped-usage-policy-scope-mismatch",\n                 "adapter differs from frozen policy")\n    if adapter_host is not None:\n        _require(policy["adapterHost"] == adapter_host, "scoped-usage-policy-scope-mismatch",\n                 "host differs from frozen policy")\n    return selected\n\n\ndef _window(value: dict[str, Any], window_id: str, stage: str) -> dict[str, Any] | None:\n    """Check original finite admission metadata without rewriting its format."""\n\n    _require({"status", "costStatus", "actualTokens", "actualInputTokens", "priorBudgetResumed",\n              "admittedAtUtc", "absoluteDeadlineUtc"} <= set(value),\n             "scoped-usage-window-invalid", "original window fields are missing")\n    expected = "ADMITTED_PREAPPROVED_BY_USER" if stage == "ADMISSION" else "UNAVAILABLE_FULL_HOLD_RETAINED"\n    _require(value.get("status") == expected and value.get("costStatus") == "UNAVAILABLE"\n             and value.get("actualTokens") is None and value.get("actualInputTokens") is None\n             and value.get("priorBudgetResumed") is False,\n             "scoped-usage-window-invalid", "original window claims invalid measured usage or status")\n    for key in ("tokenCap", "protectedCloseoutTokens", "priorLedgerLowerBound", "priorUnknownHolds",\n                "ledgerLowerBoundIncludingThisHold", "unknownHoldsIncludingThisWindow"):\n        n = value.get(key)\n        _require(type(n) is int and 0 <= n <= MAX_SAFE_INTEGER,\n                 "scoped-usage-window-invalid", "original financial counter is invalid")\n    _require(0 < value["protectedCloseoutTokens"] < value["tokenCap"] <= 300_000\n             and value["priorUnknownHolds"] <= value["priorLedgerLowerBound"]\n             and value["ledgerLowerBoundIncludingThisHold"] == value["priorLedgerLowerBound"] + value["tokenCap"]\n             and value["unknownHoldsIncludingThisWindow"] == value["priorUnknownHolds"] + value["tokenCap"],\n             "scoped-usage-window-invalid", "original financial hold was reset or altered")\n    try:\n        start = datetime.fromisoformat(value["admittedAtUtc"])\n        end = datetime.fromisoformat(value["absoluteDeadlineUtc"])\n        _require(start.utcoffset() == end.utcoffset() == timezone.utc.utcoffset(start) and start < end,\n                 "scoped-usage-window-invalid", "window clocks must be original aware UTC timestamps")\n        if stage == "COST":\n            closed = datetime.fromisoformat(value["closedAtUtc"])\n            _require(closed.utcoffset() == timezone.utc.utcoffset(closed) and closed >= start\n                     and value.get("priorUnknownHoldsReleased") == 0,\n                     "scoped-usage-window-invalid", "closure drops a hold or changes original time")\n    except (KeyError, ValueError, TypeError) as exc:\n        raise LifecycleError("scoped-usage-window-invalid", "original window clocks are missing") from exc\n    binding = value.get("sourceUsageBinding")\n    if binding is not None:\n        validate_source_window_binding(binding)\n        _require(binding["originalWindowId"] == window_id,\n                 "scoped-usage-window-invalid", "binding changes original window identity")\n    return binding\n\n\ndef _projection(selection: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:\n    """Derive the complete bounded opening-to-current interval, oldest first."""\n\n    from agent_lifecycle.adapter_sessions.bootstrap_r11 import _r11_coordinator_source\n\n    policy, prefix = selection["policy"], selection["prefix"]\n    primary = Path(current["primaryCheckout"])\n    chain = list(reversed(current["ancestryHeadSha256s"]))\n    opening_sha, terminal_sha = chain[0], chain[-1]\n    records, pools, legacy = [], {}, []\n    original_windows = {}\n    for index, head_sha in enumerate(chain):\n        if head_sha == terminal_sha:\n            head_path, head_raw = _HEAD_PATH, current["headRaw"]\n        elif index == 0:\n            head_path = policy["openingRef"]["path"]\n            head_raw = _read_ref(selection["root"], policy["openingRef"], limit=MAX_SOURCE_USAGE_BYTES)\n        else:\n            head_path = str(Path(_HEAD_PATH).parent / "coordinator-cost-head-history" / (head_sha + ".json"))\n            head_raw = read_authority_bytes(primary / head_path, root=primary, max_bytes=131_072)\n        _require(hashlib.sha256(head_raw).hexdigest() == head_sha,\n                 "scoped-usage-frontier-stale", "financial ancestor changed while projecting")\n        head = load_json_object(head_raw, label="verified financial head")\n        value, source_raw = _r11_coordinator_source(primary, head["sourcePath"])\n        source_ref = _ref(head["sourcePath"], source_raw)\n        _require(source_ref["sha256"] == head["sourceSha256"],\n                 "scoped-usage-frontier-stale", "original source changed while projecting")\n        match = _WINDOW.fullmatch(head["sourcePath"])\n        binding, window_id = None, None\n        if match and not value.get("schemaVersion"):\n            window_id = match[1]\n            stage = "ADMISSION" if match[3] == "admission" else "COST"\n            # Pre-opening data remains original historical context. New ordinary\n            # windows must meet the exact finite format selected by this policy.\n            binding = _window(value, window_id, stage) if index else value.get("sourceUsageBinding")\n            if binding is not None:\n                validate_source_window_binding(binding)\n            kind = "ORDINARY_WINDOW"\n            if stage == "ADMISSION":\n                _require(window_id not in original_windows, "scoped-usage-window-conflict",\n                         "original admission repeated")\n                original_windows[window_id] = value\n            elif stage == "COST" and window_id in original_windows:\n                original = original_windows[window_id]\n                unchanged = ("tokenCap", "admittedAtUtc", "absoluteDeadlineUtc", "protectedCloseoutTokens",\n                             "priorUnknownHolds", "priorLedgerLowerBound",\n                             "ledgerLowerBoundIncludingThisHold", "unknownHoldsIncludingThisWindow")\n                _require(original.get("sourceUsageBinding") == binding\n                         and all(key in original and value[key] == original[key] for key in unchanged),\n                         "scoped-usage-window-conflict", "closure changes original opening identity or clocks")\n            if index and stage == "ADMISSION":\n                _require(window_id not in pools, "scoped-usage-window-conflict", "window admission repeated")\n                pools[window_id] = {"windowId": window_id, "admissionRef": source_ref,\n                    "closeRef": None, "binding": binding, "tokenCap": value["tokenCap"],\n                    "originalCostScope": binding["originalCostScope"] if binding else "UNAVAILABLE_LEGACY_DECLARED_WINDOW"}\n            elif stage == "COST" and window_id in pools:\n                pool = pools[window_id]\n                _require(pool["binding"] == binding and pool["tokenCap"] == value["tokenCap"]\n                         and pool["closeRef"] is None, "scoped-usage-window-conflict",\n                         "closure changes original admission identity")\n                unchanged = ("admittedAtUtc", "absoluteDeadlineUtc", "protectedCloseoutTokens",\n                             "priorUnknownHolds", "priorLedgerLowerBound",\n                             "ledgerLowerBoundIncludingThisHold", "unknownHoldsIncludingThisWindow")\n                _require(all(value[key] == original_windows[window_id][key] for key in unchanged),\n                         "scoped-usage-window-conflict", "closure changes original clocks or hold")\n                pool["closeRef"] = source_ref\n        else:\n            kind, stage = "LEGACY_ROLE_SOURCE", value.get("schemaVersion")\n        records.append({"headRef": _ref(head_path, head_raw), "sourceRef": source_ref,\n                        "recordKind": kind, "windowId": window_id, "stage": stage, "binding": binding})\n        if index and binding is None:\n            legacy.append({"kind": "UNAVAILABLE_ORIGINAL_ATTRIBUTION", "originalSourceRef": source_ref,\n                           "originalWindowId": window_id})\n    ordered = sorted(pools.values(), key=lambda pool: (int(_WINDOW.fullmatch(pool["windowId"] + "/admission.json")[2]), pool["windowId"]))\n    _require(sum(pool["binding"] is not None for pool in ordered) <= MAX_SOURCE_USAGE_BINDINGS,\n             "scoped-usage-registry-bound", "too many typed original work windows")\n    operations = set()\n    for pool in ordered:\n        binding = pool["binding"]\n        if binding:\n            operation = (binding["runId"], binding["packageId"], binding["taskId"], binding["attempt"],\n                         binding["semanticOperationId"])\n            _require(operation not in operations, "scoped-usage-window-conflict", "operation binds two windows")\n            operations.add(operation)\n    prefix_sha = policy["sourceAuthoringRegistryRef"]["sha256"]\n    unknown_ids = sorted({f"prefix:{prefix_sha}:{index}" for index in range(len(prefix["unknownIntervals"]))}\n                         | {"legacy:" + row["originalSourceRef"]["sha256"] for row in legacy})\n    dispositions = []\n    for role in SOURCE_USAGE_ROLES:\n        window_ids = sorted(pool["windowId"] for pool in ordered\n                            if pool["binding"] and pool["binding"]["role"] == role)\n        status = "RECORDED_ORIGINAL_WINDOW" if window_ids else (\n            "UNAVAILABLE_UNALLOCATED_POOL" if unknown_ids else "NOT_PLANNED")\n        dispositions.append({"role": role, "status": status, "windowIds": window_ids,\n                             "unknownContextIds": unknown_ids})\n    result = {"schemaVersion": SOURCE_CURRENT_REGISTRY, "openingHeadSha256": opening_sha,\n        "terminalHeadSha256": terminal_sha, "terminalSourceRef": records[-1]["sourceRef"],\n        "frozenPrefixRawSha256": prefix_sha, "records": records, "windowPools": ordered,\n        "roleDispositions": dispositions, "unknownIntervals": prefix["unknownIntervals"] + legacy,\n        "balances": {"openingExposureLowerBound": selection["opening"]["exposureLowerBound"],\n            "openingUnknownHolds": selection["opening"]["unknownHolds"],\n            "currentExposureLowerBound": current["head"]["exposureLowerBound"],\n            "currentUnknownHolds": current["head"]["unknownHolds"],\n            "actualTokens": None, "actualInputTokens": None},\n        "guarantee": "DECLARED_DERIVED_SOURCE_EVIDENCE_ONLY"}\n    _require(len(_projection_bytes(result)) <= selection["registryByteLimit"],\n             "scoped-usage-registry-bound", "derived registry exceeds its byte bound")\n    return result\n\n\ndef _projection_bytes(value: dict[str, Any]) -> bytes:\n    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),\n                      allow_nan=False).encode("utf-8")\n\n\ndef current_source_snapshot(selection: dict[str, Any]) -> dict[str, Any]:\n    """Observe independently selected A/B financial heads; no automatic retry."""\n\n    from agent_lifecycle.adapter_sessions.bootstrap_r11 import read_coordinator_cost_head\n\n    kwargs = {"ancestor_head_sha256": selection["policy"]["openingRef"]["sha256"]}\n    current = read_coordinator_cost_head(selection["root"], **kwargs)\n    projection = _projection(selection, current)\n    after = read_coordinator_cost_head(selection["root"], **kwargs)\n    _require(current["headRaw"] == after["headRaw"]\n             and current["ancestryHeadSha256s"] == after["ancestryHeadSha256s"],\n             "scoped-usage-frontier-stale", "financial frontier changed during validation")\n    return {"current": current, "projection": projection,\n            "projectionBytes": _projection_bytes(projection)}\n\n\ndef require_snapshot_current(selection: dict[str, Any], snapshot: dict[str, Any]) -> None:\n    current = current_source_snapshot(selection)\n    _require(current["current"]["headRaw"] == snapshot["current"]["headRaw"]\n             and current["projectionBytes"] == snapshot["projectionBytes"],\n             "scoped-usage-frontier-stale", "declared frontier changed before durable operation")\n\n\ndef _registry_ref(task: dict[str, Any], raw: bytes) -> dict[str, Any]:\n    parent = Path(artifact_path(task, "result", int(task["attempt"]))).parent\n    path = (parent / ("source-usage-registry-" + hashlib.sha256(raw).hexdigest() + ".json")).as_posix()\n    return _ref(normalize_repo_path(path), raw)\n\n\ndef emit_registry_artifact(repository_root: Path, state: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:\n    """Create immutable evidence only; the live financial selector remains authoritative."""\n\n    selection = load_frozen_source_policy(repository_root, state, task)\n    _require(selection is not None, "scoped-usage-policy-missing", "frozen source usage policy is absent")\n    return _emit_registry_for_context(selection, task)\n\n\ndef _emit_registry_for_context(selection: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:\n    """Emit historical context without granting task limited-mode eligibility."""\n\n    snapshot = current_source_snapshot(selection)\n    raw = snapshot["projectionBytes"]\n    ref = _registry_ref(task, raw)\n    try:\n        create_authority_bytes(selection["root"] / ref["path"], raw, root=selection["root"])\n    except FileExistsError:\n        _read_ref(selection["root"], ref, limit=selection["registryByteLimit"])\n    require_snapshot_current(selection, snapshot)\n    return ref\n\n\ndef validate_limited_source_usage(\n    repository_root: Path, state: dict[str, Any], task: dict[str, Any], receipt: dict[str, Any],\n) -> dict[str, Any]:\n    validate_source_usage_receipt_shape(receipt)\n    selection = load_frozen_source_policy(repository_root, state, task,\n                                          adapter_id=task.get("adapterId"), adapter_host=receipt["host"])\n    _require(selection is not None, "scoped-usage-policy-missing", "receipt cannot select limited mode")\n    policy = selection["policy"]\n    route = task.get("attemptModelRoute") or task.get("modelRoute") or {}\n    adopted = (task.get("attemptRiskExecutionProfile") or task.get("riskExecutionProfile")\n               or task.get("attemptExecutionStrategy") or task.get("executionStrategy") or {})\n    _require(adopted.get("sourceUsagePolicyDigest") == selection["policyDigest"]\n             and adopted.get("usageMode") == SOURCE_USAGE_MODE,\n             "scoped-usage-policy-context-required", "limited usage requires actual selected attempt authority")\n    lineage = {"runId": state.get("runId"), "packageId": state.get("packageId"),\n               "taskId": task.get("id"), "attempt": task.get("attempt"),\n               "planDigest": state.get("planDigest"), "sourceRevision": state.get("sourceRevision"),\n               "routeDecisionDigest": route.get("decisionDigest")}\n    _require(receipt["lineage"] == lineage and receipt["operationId"] == route.get("operationId")\n             and receipt["modelClass"] == route.get("modelClass")\n             and receipt["modelClass"] in policy["allowedModelClasses"],\n             "scoped-usage-current-identity-mismatch", "current operation, route or lineage differs")\n    _require(receipt["policyDigest"] == selection["policyDigest"]\n             and receipt["sourceAuthoringRegistryDigest"] == policy["sourceAuthoringRegistryRef"]["sha256"],\n             "scoped-usage-policy-mismatch", "receipt selects different frozen source inputs")\n    _require((receipt["actorId"], "coordinator") in {\n        (owner["actorId"], owner["role"]) for owner in selection["prefix"]["ownerBindings"]},\n        "scoped-usage-current-identity-mismatch", "actor is not the frozen source coordinator")\n    snapshot = current_source_snapshot(selection)\n    current, projection = snapshot["current"], snapshot["projection"]\n    _require(receipt["ledgerRef"] == _ref(_HEAD_PATH, current["headRaw"]),\n             "scoped-usage-frontier-stale", "receipt omits the actual current financial frontier")\n    expected_registry = _registry_ref(task, snapshot["projectionBytes"])\n    _require(receipt["currentRegistryRef"] == expected_registry, "scoped-usage-frontier-stale",\n             "registry reference differs from the actual current derived projection")\n    _require(_read_ref(selection["root"], expected_registry, limit=selection["registryByteLimit"])\n             == snapshot["projectionBytes"], "scoped-usage-frontier-stale", "registry artifact bytes differ")\n    pools = [pool for pool in projection["windowPools"] if pool["admissionRef"] == receipt["currentAdmissionRef"]]\n    _require(len(pools) == 1 and pools[0]["binding"] is not None,\n             "scoped-usage-current-admission-unbound", "current operation has no original typed admission")\n    binding = pools[0]["binding"]\n    expected = {**lineage, "semanticOperationId": receipt["operationId"],\n                "sourceUsagePolicyDigest": selection["policyDigest"], "actorId": receipt["actorId"]}\n    _require(all(binding[key] == value for key, value in expected.items()),\n             "scoped-usage-current-identity-mismatch", "original admission belongs to another actor or attempt")\n    primary = Path(current["primaryCheckout"])\n    original_refs = projection["records"]\n    known_refs = [row["sourceRef"] for row in original_refs] + selection["prefix"]["historicalSourceRefs"]\n    result_path = artifact_path(task, "result", int(task["attempt"]))\n    for ref in receipt["sourceContextRefs"]:\n        if ref in known_refs:\n            _read_ref(primary, ref, limit=131_072)\n        else:\n            _require(ref["path"] == result_path, "scoped-usage-ref-invalid",\n                     "context is outside original history or the current result")\n            _read_ref(selection["root"], ref, limit=MAX_SOURCE_USAGE_BYTES)\n    require_snapshot_current(selection, snapshot)\n    return {"schemaVersion": "agent-lifecycle-model-usage-validation.v2", "status": "PASS",\n            "operationId": receipt["operationId"], "host": receipt["host"], "modelClass": receipt["modelClass"],\n            "receiptDigest": canonical_digest(receipt), "routeDecisionDigest": route["decisionDigest"],\n            "usageAssurance": {"usageMode": SOURCE_USAGE_MODE, "policyDigest": selection["policyDigest"],\n                "guarantee": "LIMITED_DECLARED_SOURCE_ACCOUNTING", "actualCapConformance": "UNAVAILABLE",\n                "actualTokens": None, "financialClosure": "OPEN_UNAVAILABLE",\n                "ledgerRef": receipt["ledgerRef"], "currentRegistryRef": receipt["currentRegistryRef"],\n                "sourceAuthoringRegistryDigest": receipt["sourceAuthoringRegistryDigest"],\n                "currentAdmissionRef": receipt["currentAdmissionRef"], "actorId": receipt["actorId"],\n                "observedSnapshot": "DECLARED_FRONTIER_NOT_PROVIDER_ATOMIC"}}\n\n\ndef refresh_committed_source_assurance(\n    repository_root: Path, state: dict[str, Any], task: dict[str, Any],\n) -> dict[str, Any] | None:\n    """Observe a newer descendant without changing the committed source result.\n\n    An old receipt is historical input here, never the live frontier selector.\n    Only an already committed, validated v2 receipt can use this route. The\n    controller derives current declared evidence; no model call is admitted.\n    """\n\n    stored = task.get("modelUsageReceipt")\n    if not isinstance(stored, dict) or not isinstance(stored.get("usageAssurance"), dict):\n        return None\n    _require(task.get("status") in {"VERIFYING", "ACCEPTED"},\n             "scoped-usage-committed-context-required", "source result must already be committed")\n    root = Path(repository_root).absolute()\n    path = normalize_repo_path(stored["path"], label="committed source usage receipt")\n    receipt = load_json_object(read_authority_bytes(root / path, root=root, max_bytes=MAX_SOURCE_USAGE_BYTES),\n                               label="committed source usage receipt")\n    identity = artifact_identity(root, path, receipt)\n    _require(all(stored.get(key) == identity[key] for key in ("path", "sha256", "bytes"))\n             and stored.get("validation", {}).get("receiptDigest") == canonical_digest(receipt),\n             "scoped-usage-committed-context-invalid", "committed usage artifact was changed")\n    validate_source_usage_receipt_shape(receipt)\n    selection = load_frozen_source_policy(root, state, task, adapter_id=task.get("adapterId"),\n                                          adapter_host=receipt["host"])\n    _require(selection is not None, "scoped-usage-policy-missing", "current frozen limited policy is absent")\n    snapshot = current_source_snapshot(selection)\n    original_registry = load_json_object(_read_ref(root, receipt["currentRegistryRef"],\n                                                   limit=selection["registryByteLimit"]), label="original source registry")\n    _require(receipt["ledgerRef"]["path"] == _HEAD_PATH\n             and receipt["ledgerRef"]["sha256"] in snapshot["current"]["ancestryHeadSha256s"]\n             and original_registry.get("terminalHeadSha256") == receipt["ledgerRef"]["sha256"]\n             and original_registry.get("frozenPrefixRawSha256") == selection["policy"]["sourceAuthoringRegistryRef"]["sha256"],\n             "scoped-usage-frontier-stale", "committed observation is not an original current-ledger ancestor")\n    _require(receipt["currentRegistryRef"] == _registry_ref(task, _projection_bytes(original_registry)),\n             "scoped-usage-ref-invalid", "original registry does not use its deterministic artifact path")\n    # This is a fresh ALK-declared observation of the same original work window,\n    # not a rewritten receipt, expenditure, executor or source-input binding.\n    current_view = {**receipt, "ledgerRef": _ref(_HEAD_PATH, snapshot["current"]["headRaw"]),\n                    "currentRegistryRef": emit_registry_artifact(root, state, task)}\n    validation = validate_limited_source_usage(root, state, task, current_view)\n    require_snapshot_current(selection, snapshot)\n    assurance = validation["usageAssurance"]\n    assurance["originalReceiptDigest"] = canonical_digest(receipt)\n    assurance["assuranceBasis"] = "FRESH_CONTROLLER_DERIVATION_FROM_COMMITTED_SOURCE_RECEIPT"\n    return assurance\n\n\ndef require_task_source_frontier_current(\n    repository_root: Path, state: dict[str, Any], task: dict[str, Any],\n) -> None:\n    assurance = task.get("sourceUsageAssurance")\n    if not isinstance(assurance, dict):\n        return\n    selection = _load_frozen_source_context(repository_root, state)\n    _require(selection is not None, "scoped-usage-policy-missing", "current source policy is absent")\n    if "currentAdmissionRef" in assurance:\n        load_frozen_source_policy(repository_root, state, task)\n    snapshot = current_source_snapshot(selection)\n    _require(assurance["ledgerRef"] == _ref(_HEAD_PATH, snapshot["current"]["headRaw"])\n             and assurance["currentRegistryRef"] == _registry_ref(task, snapshot["projectionBytes"]),\n             "scoped-usage-frontier-stale", "observed source frontier changed before durable commit")\n\n\ndef aggregate_source_usage_assurance(\n    repository_root: Path, state: dict[str, Any],\n) -> dict[str, Any] | None:\n    observations = []\n    historical = _load_frozen_source_context(repository_root, state)\n    for task in state.get("tasks", []):\n        if task.get("status") != "ACCEPTED":\n            continue\n        assurance = refresh_committed_source_assurance(repository_root, state, task)\n        if assurance is None:\n            selection = historical\n            if selection is not None:\n                snapshot = current_source_snapshot(selection)\n                # The selected source ledger has null actuals even when the\n                # producer supplied no explicit interval descriptors. Full-v1\n                # executor receipts cannot erase that historical source limit.\n                if snapshot["projection"]["guarantee"] == "DECLARED_DERIVED_SOURCE_EVIDENCE_ONLY":\n                    assurance = {"usageMode": SOURCE_USAGE_MODE, "policyDigest": selection["policyDigest"],\n                        "guarantee": "LIMITED_DECLARED_SOURCE_ACCOUNTING", "actualCapConformance": "UNAVAILABLE",\n                        "actualTokens": None, "financialClosure": "OPEN_UNAVAILABLE",\n                        "ledgerRef": _ref(_HEAD_PATH, snapshot["current"]["headRaw"]),\n                        "currentRegistryRef": _emit_registry_for_context(selection, task),\n                        "sourceAuthoringRegistryDigest": selection["policy"]["sourceAuthoringRegistryRef"]["sha256"],\n                        "assuranceBasis": "HISTORICAL_UNAVAILABLE_SOURCE_CONTEXT_NOT_CURRENT_EXECUTOR"}\n                    require_snapshot_current(selection, snapshot)\n        if assurance is not None:\n            task["sourceUsageAssurance"] = assurance\n            observations.append({"taskId": task["id"], "attempt": task["attempt"], "assurance": assurance})\n    if not observations:\n        return None\n    return {"guarantee": "LIMITED_DECLARED_SOURCE_ACCOUNTING", "actualCapConformance": "UNAVAILABLE",\n            "financialClosure": "OPEN_UNAVAILABLE", "actualTokens": None, "tasks": observations}\n'
RECOVERY_GATE_SOURCE = '"""Finite, procedural controller repair gate; no Source/native assurance.\n\nThis candidate is inactive until actual independent review, lock and issuance.\nAuthority checking uses stdlib; only the existing financial read/advance API\nis loaded from the unchanged preserved source76, never the repaired consumer.\n"""\nfrom pathlib import Path, PurePosixPath\nfrom datetime import datetime, timezone, timedelta\nimport argparse, hashlib, json, os, re, stat, subprocess, sys\n\nOLD=Path(\'' + ("/" + "Volumes/") + "Work/Work/1.My/agent-lifecycle-kit-r216-source76')\nPRIMARY=Path('" + ("/" + "Volumes/") + "Work/Work/1.My/agent-lifecycle-kit')\nPACKAGE='tasks/release-2-16-source-conflict-repair'\nCAP=200000\nRESERVE=50000\nNOW=lambda:datetime.now(timezone.utc)\n\ndef require(ok,message):\n    if not ok: raise ValueError('CONTROLLER_REPAIR_DENIED: '+message)\ndef raw(v): return json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()\ndef digest(v): return hashlib.sha256(raw(v)).hexdigest()\ndef safe_read(root,path,limit=8388608):\n    p=PurePosixPath(path)\n    require(path==p.as_posix() and not p.is_absolute() and '..' not in p.parts and p.parts,'path')\n    cursor=root\n    for part in p.parts:\n        cursor=cursor/part\n        require(not cursor.is_symlink(),'symlink')\n    fd=os.open(cursor,os.O_RDONLY|os.O_NOFOLLOW)\n    try:\n        before=os.fstat(fd);require(stat.S_ISREG(before.st_mode) and before.st_size<=limit,'file bound')\n        with os.fdopen(fd,'rb',closefd=False) as f: b=f.read(limit+1)\n        after=os.fstat(fd)\n        require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns) and len(b)<=limit,'changed read')\n        require(cursor.stat().st_ino==after.st_ino and not cursor.is_symlink(),'changed name')\n        return b\n    finally: os.close(fd)\ndef reference(root,path):\n    b=safe_read(root,path);return dict(path=path,sha256=hashlib.sha256(b).hexdigest(),bytes=len(b))\ndef checked(root,ref):\n    require(set(ref)=={'path','sha256','bytes'},'reference fields')\n    b=safe_read(root,ref['path']);require(reference(root,ref['path'])==ref,'reference changed');return b\ndef read(root,path):return json.loads(safe_read(root,path))\ndef write_new(path,value):\n    path.parent.mkdir(parents=True,exist_ok=True)\n    with path.open('xb') as f:f.write(raw(value)+b'\\n');f.flush();os.fsync(f.fileno())\ndef git(root,*args):return subprocess.check_output(['git',*args],cwd=root,text=True).strip()\ndef finance(root):\n    expected=read(root,PACKAGE+'/old-finance-dependencies.json')['references']\n    def identities():\n        actual=sorted(str(p.relative_to(OLD)) for p in (OLD/'src').rglob('*') if p.is_file())\n        require(actual==[r['path'] for r in expected],'old financial dependency set changed')\n        for r in expected:checked(OLD,r)\n        for name,module in list(sys.modules.items()):\n            if name.startswith('agent_lifecycle') and getattr(module,'__file__',None):\n                require(Path(module.__file__).resolve().is_relative_to(OLD/'src'),'foreign financial module')\n    identities()\n    sys.path.insert(0,str(OLD/'src'))\n    from agent_lifecycle.adapter_sessions.bootstrap_r11 import read_coordinator_cost_head,advance_coordinator_cost_head\n    identities()\n    def observed(*args,**kwargs):\n        identities();out=read_coordinator_cost_head(*args,**kwargs);identities();return out\n    def advanced(*args,**kwargs):\n        identities();out=advance_coordinator_cost_head(*args,**kwargs);identities();return out\n    return observed,advanced\n\ndef original_interval(snapshot,spec):\n    records=[]\n    for head_sha in reversed(snapshot['ancestryHeadSha256s']):\n        if head_sha==snapshot['headSha256']:head=snapshot['head']\n        elif head_sha==snapshot['ancestor']['headSha256']:head=snapshot['ancestor']['head']\n        else:head=read(PRIMARY,'work/release-2-16/enforcement-decision/coordinator-cost-head-history/'+head_sha+'.json')\n        source_ref=reference(PRIMARY,head['sourcePath'])\n        require(source_ref['sha256']==head['sourceSha256'],'original source/head join')\n        records.append(dict(headSha256=head_sha,sourceRef=source_ref))\n    positions=[]\n    for original in spec['exactConflict']['originalRecords']:\n        found=[i for i,r in enumerate(records) if r['sourceRef']==original]\n        require(len(found)==1,'original record absent or repeated in ancestry')\n        positions.append(found[0])\n    require(positions==sorted(positions) and len(set(positions))==4,'original pair order')\n    last_cost=json.loads(checked(PRIMARY,spec['exactConflict']['originalRecords'][-1]))\n    require(snapshot['head']['unknownHolds']>=last_cost['unknownHoldsIncludingThisWindow'] and snapshot['head']['exposureLowerBound']>=last_cost['ledgerLowerBoundIncludingThisHold'],'original liabilities dropped')\n    return records\n\ndef authority(root):\n    require(root.resolve()==root and root!=OLD and root!=PRIMARY,'separate canonical workspace')\n    require(Path(__file__).resolve()==root/PACKAGE/'controller_repair_gate.py','exact gate location')\n    m=read(root,PACKAGE+'/plan.manifest.json');lock=read(root,PACKAGE+'/plan.lock.json')\n    require(m['status']=='FROZEN' and lock['schemaVersion']=='agent-plan-lock.v2','freeze missing')\n    require(lock['manifestHash']==digest(m) and lock['planRevision']==m['planRevision'] and lock['packageId']==m['package']['id'],'freeze lineage')\n    entries=lock['entries'];require([r['path'] for r in entries]==sorted(m['planFiles']) and len({r['path'] for r in entries})==len(entries),'exact inventory')\n    require(lock['planFilesHash']==digest(dict(schemaVersion='agent-plan-file-inventory.v1',entries=entries)),'inventory digest')\n    for r in entries:checked(root,r)\n    report=read(root,m['planReview']['report'])\n    require(report['schemaVersion']=='agent-plan-review.v1' and report['verdict']=='READY_TO_FREEZE' and report['fullReview'] is True and report['findings']==[],'independent plan review')\n    require(report['reviewedPlanHash']==digest(m) and report['reviewedRevision']==m['planRevision'] and report['reviewer']['independent'] is True and report['reviewer']['id']!='/root','review lineage')\n    cfg=read(root,PACKAGE+'/repair-authority-inputs.json')\n    before_inventory=json.loads(checked(root,cfg['wipBeforeInventoryRef']))\n    cfg['wipBeforeRefs']=before_inventory['wipBeforeRefs']\n    observation=read(PRIMARY,cfg['actualPlanObservationPath'])\n    actual=safe_read(PRIMARY,cfg['actualPlanFinalPath'])\n    require(observation['status']=='ACTUAL_COMPLETE_FINAL_OBSERVED' and observation['exitCode']==0 and observation['timely'] and observation['processStopped'],'actual completed reviewer')\n    require(hashlib.sha256(actual).hexdigest()==observation['actualFinalSha256'] and json.loads(actual)==report,'actual report join')\n    spec=read(root,PACKAGE+'/SPECIFICATION.json')\n    require(cfg['onlyWritePaths']==spec['bootstrap']['onlyWritePaths']==m['workstreams'][0]['writes'],'owned paths differ')\n    spec_review=read(root,PACKAGE+'/SPECIFICATION-REVIEW.json')\n    require(spec_review['verdict']=='READY_FOR_PLAN_DRAFT' and spec_review['findings']==[],'spec closure')\n    require(git(root,'rev-parse','HEAD')==m['baseRevision']['sha']==cfg['sourceRevision'],'source revision')\n    old=read(OLD,cfg['oldStateRef']['path']);checked(OLD,cfg['oldStateRef'])\n    require(old['phase']=='BLOCKED' and old['stateRevision']==9 and old['runId']=='release-2-16-r76-20261002','old state changed')\n    for p in ['run.state.json','work/release-2-16/run.state.json','work/release-2-16-source-conflict-repair/run.state.json']:\n        require(not (root/p).exists() and not (root/p).is_symlink(),'running repair workspace')\n    for r in spec['exactConflict']['originalRecords']:checked(PRIMARY,r)\n    for r in cfg['sourceSnapshots']:\n        checked(root,r['snapshotRef'])\n    return m,lock,cfg,spec\n\ndef workspace(root,cfg,current=None):\n    allowed=set(cfg['onlyWritePaths']);expected={r['path']:r for r in cfg['wipBeforeRefs']}\n    if current:\n        require(set(current)==allowed,'after scope')\n        expected.update(current)\n    for path,ref in expected.items():checked(root,ref)\n    status=subprocess.check_output(['git','status','--porcelain=v1','-z','--untracked-files=all'],cwd=root)\n    paths=[x[3:].decode() for x in status.split(b'\\0') if x]\n    require(len(paths)==len(set(paths)) and set(paths)<=set(expected),'extra source writes/renames')\n\ndef issue_locked(root,window):\n    m,lock,cfg,spec=authority(root);workspace(root,cfg)\n    for entry in lock['entries']:\n        require(checked(PRIMARY,entry)==checked(root,entry),'primary mirror member differs')\n    require(safe_read(PRIMARY,PACKAGE+'/plan.lock.json')==safe_read(root,PACKAGE+'/plan.lock.json'),'primary mirror lock differs')\n    require(window.parent==PRIMARY/'work/release-2-16/enforcement-decision' and re.fullmatch(r'r[1-9][0-9]*-[a-z0-9-]+',window.name) and not window.exists(),'fresh work window')\n    for candidate in window.parent.glob('r*/ISSUANCE-CLAIM.json'):\n        claim=json.loads(candidate.read_bytes())\n        require(claim.get('repairPackageId')!=m['package']['id'] and claim.get('planRef',{}).get('sha256')!=reference(root,PACKAGE+'/plan.manifest.json')['sha256'],'permanent issuance claim, including incomplete/closed/expired window')\n    for candidate in window.parent.glob('r*/GRANT.json'):\n        value=json.loads(candidate.read_bytes())\n        if value.get('schemaVersion')=='alk-source-conflict-controller-repair-grant.v1':\n            require(value.get('repairPackageId')!=m['package']['id'] and value.get('planRef',{}).get('sha256')!=reference(root,PACKAGE+'/plan.manifest.json')['sha256'],'repair package already issued, including closed/expired grant')\n            require((candidate.parent/'cost.json').exists() or NOW()>=datetime.fromisoformat(value['absoluteDeadlineUtc']),'concurrent controller grant')\n    rd,advance=finance(root);prior=rd(OLD,ancestor_head_sha256=spec['wireContracts']['disposition']['originalOpeningRef']['sha256'])\n    interval=original_interval(prior,spec)\n    operation=window.name+'-controller-repair'\n    for head_sha in prior['ancestryHeadSha256s']:\n        if head_sha==prior['headSha256']:h=prior['head']\n        else:h=read(PRIMARY,'work/release-2-16/enforcement-decision/coordinator-cost-head-history/'+head_sha+'.json')\n        source=read(PRIMARY,h['sourcePath'])\n        require(source.get('repairOperationId')!=operation and source.get('sourceUsageBinding',{}).get('semanticOperationId')!=operation,'operation reused')\n    subject=dict(planRef=reference(root,PACKAGE+'/plan.manifest.json'),lockRef=reference(root,PACKAGE+'/plan.lock.json'),specificationRef=reference(root,PACKAGE+'/SPECIFICATION.json'),specificationReviewRef=reference(root,PACKAGE+'/SPECIFICATION-REVIEW.json'),planReviewRef=reference(root,m['planReview']['report']),sourceBeforeRefs={p:reference(root,p) for p in cfg['onlyWritePaths']},oldRunStateRef=cfg['oldStateRef'],originalRecords=spec['exactConflict']['originalRecords'],openingRef=spec['wireContracts']['disposition']['originalOpeningRef'],preAdmissionFinancialHeadSha256=prior['headSha256'])\n    subject['verifiedOriginalInterval']=interval\n    now=NOW();deadline=(now+timedelta(minutes=90)).isoformat()\n    admission=dict(status='ADMITTED_PREAPPROVED_BY_USER',tokenCap=CAP,protectedCloseoutTokens=RESERVE,reviewerAllocationTokens=80000,actualInputTokens=None,actualTokens=None,costStatus='UNAVAILABLE',priorBudgetResumed=False,priorUnknownHolds=prior['head']['unknownHolds'],priorLedgerLowerBound=prior['head']['exposureLowerBound'],unknownHoldsIncludingThisWindow=prior['head']['unknownHolds']+CAP,ledgerLowerBoundIncludingThisHold=prior['head']['exposureLowerBound']+CAP,priorUnknownHoldsReleased=0,admittedAtUtc=now.isoformat(),absoluteDeadlineUtc=deadline,repairOperationId=operation,inputSubjectDigest=digest(subject),workspace=str(root),currentWindowExecutorClaim=False,maxModelInvocations=1,maxTestInvocations=3,maxNativeInvocations=0,scope='Exact independently reviewed controller repair only; no current Source executor/host/native/task assurance.')\n    window.mkdir();write_new(window/'INPUT-SUBJECT.json',subject)\n    # One immutable consumed-package claim precedes even a failed reservation.\n    # It is never removed, refunded or reopened after issuance interruption.\n    claim=dict(schemaVersion='alk-controller-repair-issuance-claim.v1',repairPackageId=m['package']['id'],planRef=subject['planRef'],repairOperationId=operation,inputSubjectDigest=digest(subject),workArtifactRoot=str(window.relative_to(PRIMARY)),declaredAdmissionSha256=hashlib.sha256(raw(admission)+b'\\n').hexdigest())\n    write_new(window/'ISSUANCE-CLAIM.json',claim)\n    write_new(window/'admission.json',admission)\n    advance(OLD,source_path=str((window/'admission.json').relative_to(PRIMARY)))\n    admitted=rd(OLD,ancestor_head_sha256=prior['headSha256']);(window/'COMPLETE-FINANCIAL-SNAPSHOT.json').write_bytes(admitted['headRaw'])\n    financial_ref=reference(PRIMARY,str((window/'COMPLETE-FINANCIAL-SNAPSHOT.json').relative_to(PRIMARY)))\n    grant=dict(schemaVersion='alk-source-conflict-controller-repair-grant.v1',grantId=operation+'-grant',actorId='/root',independentReviewerId=read(root,m['planReview']['report'])['reviewer']['id'],repairPackageId=m['package']['id'],repairOperationId=operation,specificationRef=subject['specificationRef'],specificationReviewRef=subject['specificationReviewRef'],planRef=subject['planRef'],inventoryRef=reference(root,PACKAGE+'/SOURCE-BEFORE.json'),lockRef=subject['lockRef'],planReviewRef=subject['planReviewRef'],sourceRevision=cfg['sourceRevision'],sourceBeforeRefs=list(subject['sourceBeforeRefs'].values()),oldRunStateRef=cfg['oldStateRef'],onlyWritePaths=cfg['onlyWritePaths'],workArtifactRoot=str(window.relative_to(PRIMARY)),permittedWorkArtifacts=cfg['permittedWorkArtifacts'],admissionRef=reference(PRIMARY,str((window/'admission.json').relative_to(PRIMARY))),authorizingFinancialHeadRef=financial_ref,inputSubjectDigest=digest(subject),tokenCap=CAP,protectedCloseoutTokens=RESERVE,absoluteDeadlineUtc=deadline,maxAffectedValidationCommands=3,maxIndependentSourceReviews=1,maxNativeInvocations=0,requiresNonrunningWorkspace=True,sourceAssurance='CONTROLLER_REPAIR_SOURCE_ONLY_UNAVAILABLE',taskAccepted=False,releaseReady=False)\n    require(set(grant)==set(spec['bootstrap']['grantSchema']['closedKeys']),'grant closed shape')\n    write_new(window/'GRANT.json',grant)\n    records=spec['exactConflict']['originalRecords'];windows=spec['exactConflict']['originalWindowIds']\n    disposition=dict(schemaVersion='alk-source-window-conflict-disposition.v1',dispositionId='r605-r606-source-window-conflict',identityTuple=spec['exactConflict']['identityTuple'],originalWindows=[dict(windowId=w,admissionRef=records[2*i],costRef=records[2*i+1]) for i,w in enumerate(windows)],basisReviewRef=spec['wireContracts']['disposition']['basisReviewRef'],authorizingReviewRef=subject['planReviewRef'],authorizingGrantRef=reference(PRIMARY,str((window/'GRANT.json').relative_to(PRIMARY))),originalOpeningRef=spec['wireContracts']['disposition']['originalOpeningRef'],authorizingFinancialHeadRef=financial_ref,classification='HISTORICAL_INELIGIBLE')\n    write_new(window/'DISPOSITION.json',disposition)\n    write_new(window/'SOURCE-BEFORE.json',subject['sourceBeforeRefs'])\n    write_new(window/'FROZEN-REPAIR-AUTHORITY.json',dict(grantRef=reference(PRIMARY,str((window/'GRANT.json').relative_to(PRIMARY))),dispositionRef=reference(PRIMARY,str((window/'DISPOSITION.json').relative_to(PRIMARY))),inputSubjectRef=reference(PRIMARY,str((window/'INPUT-SUBJECT.json').relative_to(PRIMARY))),sourceBeforeRef=reference(PRIMARY,str((window/'SOURCE-BEFORE.json').relative_to(PRIMARY))),issuanceClaimRef=reference(PRIMARY,str((window/'ISSUANCE-CLAIM.json').relative_to(PRIMARY)))))\n    print(json.dumps(dict(status='CONTROLLER_REPAIR_GRANT_ISSUED_NO_SOURCE_ASSURANCE',window=str(window),operation=operation,deadline=deadline,actualTokens=None)))\n\ndef issue(root,window):\n    require(os.name=='posix','unsupported controller platform')\n    import fcntl\n    fd=os.open(PRIMARY/'work/release-2-16/enforcement-decision',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)\n    try:\n        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)\n        issue_locked(root,window)\n    finally:\n        os.close(fd)\n\ndef active(root,window):\n    m,lock,cfg,spec=authority(root)\n    grant=read(window,'GRANT.json');ad=read(window,'admission.json')\n    claim=read(window,'ISSUANCE-CLAIM.json')\n    require(claim['planRef']==grant['planRef'] and claim['repairPackageId']==grant['repairPackageId'] and claim['inputSubjectDigest']==grant['inputSubjectDigest'] and claim['declaredAdmissionSha256']==reference(PRIMARY,str((window/'admission.json').relative_to(PRIMARY)))['sha256'],'issuance claim join')\n    for r in read(window,'FROZEN-REPAIR-AUTHORITY.json').values():checked(PRIMARY,r)\n    require(set(grant)==set(spec['bootstrap']['grantSchema']['closedKeys']),'grant fields')\n    require(NOW()<datetime.fromisoformat(grant['absoluteDeadlineUtc']) and grant['absoluteDeadlineUtc']==ad['absoluteDeadlineUtc'],'expired original grant')\n    require(grant['planRef']==reference(root,PACKAGE+'/plan.manifest.json') and grant['lockRef']==reference(root,PACKAGE+'/plan.lock.json') and grant['actorId']=='/root','grant lineage')\n    require(grant['admissionRef']==reference(PRIMARY,str((window/'admission.json').relative_to(PRIMARY))) and grant['inputSubjectDigest']==digest(read(window,'INPUT-SUBJECT.json')),'admission/subject altered')\n    require(grant['tokenCap']==ad['tokenCap']==CAP and grant['protectedCloseoutTokens']==ad['protectedCloseoutTokens']==RESERVE and 'sourceUsageBinding' not in ad,'finite source-only grant')\n    require(grant['repairOperationId']==ad['repairOperationId'] and grant['onlyWritePaths']==cfg['onlyWritePaths'] and grant['permittedWorkArtifacts']==cfg['permittedWorkArtifacts'] and grant['sourceAssurance']=='CONTROLLER_REPAIR_SOURCE_ONLY_UNAVAILABLE' and grant['taskAccepted'] is False and grant['releaseReady'] is False,'grant scope altered')\n    require(set(p.name for p in window.iterdir())<=set(grant['permittedWorkArtifacts']),'extra work artifact')\n    rd,_=finance(root);snapshot=rd(OLD,ancestor_head_sha256=spec['wireContracts']['disposition']['originalOpeningRef']['sha256']);checked(PRIMARY,grant['authorizingFinancialHeadRef'])\n    require(grant['authorizingFinancialHeadRef']['sha256'] in snapshot['ancestryHeadSha256s'],'admitted head absent')\n    current_interval=original_interval(snapshot,spec)\n    previous=read(window,'INPUT-SUBJECT.json')['verifiedOriginalInterval']\n    require(current_interval[:len(previous)]==previous,'original verified interval omitted or changed')\n    require(not (window/'cost.json').exists(),'already closed')\n    current=read(window,'SOURCE-AFTER.json') if (window/'SOURCE-AFTER.json').exists() else read(window,'SOURCE-BEFORE.json')\n    workspace(root,cfg,current)\n    return grant,cfg,spec,snapshot\n\ndef apply(root,window,replacements):\n    grant,cfg,spec,_=active(root,window)\n    require(replacements==window/'SOURCE-REPLACEMENTS.json' and not replacements.is_symlink(),'replacement artifact')\n    changes=json.loads(safe_read(window,'SOURCE-REPLACEMENTS.json',limit=8388608));require(set(changes)=={'sourceChanges'},'replacement fields')\n    rows=changes['sourceChanges'];require(isinstance(rows,list) and 0<len(rows)<=4,'replacement count')\n    require(len({r['path'] for r in rows})==len(rows) and set(r['path'] for r in rows)<=set(cfg['onlyWritePaths']),'replacement scope')\n    for r in rows:\n        require(set(r)=={'path','beforeSha256','afterText'} and reference(root,r['path'])['sha256']==r['beforeSha256'] and isinstance(r['afterText'],str) and len(r['afterText'].encode())<=1048576,'replacement before/size')\n    # Recheck all grant/deadline/frontier/ownership predicates immediately before effects.\n    active(root,window)\n    for r in rows:\n        require(NOW()<datetime.fromisoformat(grant['absoluteDeadlineUtc']),'expired before source write')\n        p=root/r['path'];require(not p.is_symlink(),'source symlink')\n        fd=os.open(p,os.O_WRONLY|os.O_NOFOLLOW|os.O_TRUNC)\n        with os.fdopen(fd,'wb') as f:f.write(r['afterText'].encode());f.flush();os.fsync(f.fileno())\n    current={p:reference(root,p) for p in cfg['onlyWritePaths']}\n    out=window/'SOURCE-AFTER.json';tmp=out.with_suffix('.pending.json');write_new(tmp,current);os.replace(tmp,out)\n    workspace(root,cfg,current)\n    print(json.dumps(dict(status='BOUNDED_SOURCE_PATCH_RECORDED_NOT_QUALIFIED',paths=[r['path'] for r in rows])))\n\ndef pre_effect(root,window,kind):\n    grant,cfg,spec,snapshot=active(root,window)\n    require(kind in ['TEST','REVIEW','CLOSEOUT'],'effect kind')\n    log=window/'GATE-CHECKS.jsonl';events=[]\n    if log.exists():events=[json.loads(b) for b in log.read_bytes().splitlines()]\n    limit={'TEST':3,'REVIEW':1,'CLOSEOUT':1}[kind]\n    require(sum(e['kind']==kind for e in events)<limit,'invocation limit')\n    event=dict(kind=kind,atUtc=NOW().isoformat(),originalDeadlineUtc=grant['absoluteDeadlineUtc'],headSha256=snapshot['headSha256'],sourceRefs={p:reference(root,p) for p in cfg['onlyWritePaths']},sourceAssurance='UNAVAILABLE')\n    with log.open('ab') as f:f.write(raw(event)+b'\\n');f.flush();os.fsync(f.fileno())\n    print(json.dumps(dict(status='PRE_EFFECT_ALLOWED_DECLARED_REPAIR_ONLY',kind=kind)))\n\nif __name__=='__main__':\n    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['issue','apply','pre-effect']);parser.add_argument('--root',required=True,type=Path);parser.add_argument('--window',required=True,type=Path);parser.add_argument('--replacements',type=Path);parser.add_argument('--kind',choices=['TEST','REVIEW','CLOSEOUT']);args=parser.parse_args()\n    try:\n        if args.action=='issue':issue(args.root.absolute(),args.window.absolute())\n        elif args.action=='apply':require(args.replacements is not None,'replacement required');apply(args.root.absolute(),args.window.absolute(),args.replacements)\n        else:pre_effect(args.root.absolute(),args.window.absolute(),args.kind)\n    except (ValueError,KeyError,OSError,json.JSONDecodeError) as exc:\n        print(str(exc),file=sys.stderr);sys.exit(2)\n"
RECOVERY_GATE_SHA256 = '88d83f0e7b809b043e168a3e8d9c8953dd545faee6a2717df89c0ef85ab02721'
RECOVERY_GATE_WRITE_PATHS = ['src/agent_lifecycle/contracts/scoped_usage_schemas.py', 'src/agent_lifecycle/workflow/limited_usage.py', 'tests/contracts/test_scoped_usage_schemas.py', 'tests/workflow/test_limited_usage.py']
RECOVERY_GATE_ARTIFACTS = ['admission.json', 'cost.json', 'INPUT-SUBJECT.json', 'FROZEN-REPAIR-AUTHORITY.json', 'controller_repair_gate.py', 'GRANT.json', 'DISPOSITION.json', 'GATE-CHECKS.jsonl', 'SOURCE-BEFORE.json', 'SOURCE-AFTER.json', 'AFFECTED-TEST-INVOCATIONS.json', 'AFFECTED-TEST-OBSERVATIONS.json', 'COMPLETE-FINANCIAL-SNAPSHOT.json', 'INDEPENDENT-REPAIR-REVIEW.json', 'SOURCE-REPLACEMENTS.json', 'ISSUANCE-CLAIM.json']
RECOVERY_GRANT_KEYS = ['absoluteDeadlineUtc', 'actorId', 'admissionRef', 'authorizingFinancialHeadRef', 'grantId', 'independentReviewerId', 'inputSubjectDigest', 'inventoryRef', 'lockRef', 'maxAffectedValidationCommands', 'maxIndependentSourceReviews', 'maxNativeInvocations', 'oldRunStateRef', 'onlyWritePaths', 'permittedWorkArtifacts', 'planRef', 'planReviewRef', 'protectedCloseoutTokens', 'releaseReady', 'repairOperationId', 'repairPackageId', 'requiresNonrunningWorkspace', 'schemaVersion', 'sourceAssurance', 'sourceBeforeRefs', 'sourceRevision', 'specificationRef', 'specificationReviewRef', 'taskAccepted', 'tokenCap', 'workArtifactRoot']


def multigroup_fixture(root, *, second_numbers=(401, 402)):
    """Two independent synthetic authorities; never live release evidence."""
    f = recovery_fixture(root)
    f.close_window()
    for number in second_numbers:
        f.append_window(number,bound=True,operation='second-historical-operation')
        f.close_window()
    windows=[]
    for number in second_numbers:
        window=BASE+'/r'+str(number)+'-fixture'
        refs=[{'path':window+'/'+name,'sha256':hashlib.sha256((root/window/name).read_bytes()).hexdigest(),
               'bytes':len((root/window/name).read_bytes())} for name in ('admission.json','cost.json')]
        windows.append({'windowId':window,'admissionRef':refs[0],'costRef':refs[1]})
    windows.sort(key=lambda row: row['windowId'])
    second_identity=deepcopy(f.recovery_disposition['identityTuple'])
    second_identity['semanticOperationId']='second-historical-operation'
    refusal=put(root,'work/second-recovery/refusal.json',{'code':'scoped-usage-window-conflict',
        'financialAdmissionPublished':True,'sourceExecutionAdmitted':False,
        'originalWindowIds':[r['windowId'] for r in windows],
        **{k:0 for k in ['newProductWrites','testInvocations','modelInvocations','nativeInvocations','holdReleased']}})
    stderr=put(root,'work/second-recovery/stderr.txt',b'original pre-effect refusal')
    spec={'schemaVersion':'alk-source-window-conflict-recovery-specification.v3',
          'exactConflict':{'identityTuple':second_identity,'originalWindowIds':[r['windowId'] for r in windows],
                           'originalRecords':[r[k] for r in windows for k in ('admissionRef','costRef')]},
          'wireContracts':{'disposition':{'basisRefusalRef':refusal,'actualGuardFailureRef':stderr}}}
    repair_dir='tasks/second-repair'
    spec_ref=put(root,repair_dir+'/spec.json',spec)
    spec_review=put(root,repair_dir+'/spec-review.json',{'authority':'EXACT_INDEPENDENT_PLAN_REPORT_REQUIRED'})
    inventory=put(root,repair_dir+'/before.json',{'assurance':'SYNTHETIC_ONLY'})
    plan={'schemaVersion':'agent-plan-manifest.v1','status':'FROZEN','planRevision':1,
          'package':{'id':'second-repair-fixture','planArtifactRoot':repair_dir},
          'packageIntegrity':{'required':True,'allowedUnlistedFiles':['plan.lock.json']},
          'planFiles':sorted([repair_dir+'/plan.manifest.json',spec_ref['path'],spec_review['path'],inventory['path'],repair_dir+'/review.json'])}
    plan_ref=put(root,repair_dir+'/plan.manifest.json',plan)
    report={'schemaVersion':'agent-plan-review.v1','verdict':'READY_TO_FREEZE','fullReview':True,'findings':[],
            'reviewedPlanHash':canonical_digest(plan),'packageId':'second-repair-fixture','planRevision':1,
            'reviewer':{'id':'second-independent-fixture','independent':True}}
    review_ref=put(root,repair_dir+'/review.json',report)
    lock_ref=put(root,repair_dir+'/plan.lock.json',build_plan_lock_v2(plan,repository_root=root))
    fields={'repairOperationId':'second-repair-operation','inputSubjectDigest':'b'*64}
    admission_ref=f.append_window(max(second_numbers)+1,repair_fields=fields)
    admitted=read_coordinator_cost_head(root)
    financial_ref=put(root,'work/second-recovery/admitted-head.json',admitted['headRaw'])
    ad=json.loads((root/admission_ref['path']).read_bytes())
    grant=deepcopy(json.loads((root/f.recovery_disposition['authorizingGrantRef']['path']).read_bytes()))
    grant.update(grantId='second-grant',independentReviewerId='second-independent-fixture',repairPackageId='second-repair-fixture',
                 repairOperationId=fields['repairOperationId'],inputSubjectDigest=fields['inputSubjectDigest'],specificationRef=spec_ref,
                 specificationReviewRef=spec_review,planRef=plan_ref,inventoryRef=inventory,lockRef=lock_ref,planReviewRef=review_ref,
                 admissionRef=admission_ref,authorizingFinancialHeadRef=financial_ref,absoluteDeadlineUtc=ad['absoluteDeadlineUtc'],
                 tokenCap=ad['tokenCap'],protectedCloseoutTokens=ad['protectedCloseoutTokens'])
    grant_ref=put(root,'work/second-recovery/grant.json',grant)
    disposition=deepcopy(f.recovery_disposition)
    disposition.update(schemaVersion='alk-source-window-conflict-disposition.v2',dispositionId='second-conflict',
                       identityTuple=second_identity,originalWindows=windows,basisReviewRef=review_ref,
                       authorizingReviewRef=review_ref,authorizingGrantRef=grant_ref,authorizingFinancialHeadRef=financial_ref)
    disp_ref=put(root,'tasks/strategy/second-disposition.json',disposition)
    put(root,'tasks/strategy/source-usage-conflict-recovery.json',{'schemaVersion':'alk-source-usage-conflict-recovery-policy.v2',
        'originalOpeningRef':f.policy['openingRef'],'dispositionRefs':[f.recovery_disposition_ref,disp_ref]})
    f.manifest['planFiles']=sorted(set(f.manifest['planFiles']+[disp_ref['path']]))
    f.freeze()
    f.task['modelRoute']['operationId']='final-current-operation'
    f.task['attemptModelRoute']['operationId']='final-current-operation'
    f.admission_ref=f.append_window(max(second_numbers)+2,bound=True,operation='final-current-operation')
    f.receipt=f.make_receipt()
    f.second_disposition=disposition
    f.second_disposition_ref=disp_ref
    return f


class SourceMultiConflictRecoveryTests(unittest.TestCase):
    def fixture(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        return multigroup_fixture(Path(directory.name).resolve())

    def select(self,f,second=None,refs=None):
        if second is not None:
            f.second_disposition=second
            f.second_disposition_ref=put(f.root,f.second_disposition_ref['path'],second)
        put(f.root,'tasks/strategy/source-usage-conflict-recovery.json',{
            'schemaVersion':'alk-source-usage-conflict-recovery-policy.v2','originalOpeningRef':f.policy['openingRef'],
            'dispositionRefs':refs or [f.recovery_disposition_ref,f.second_disposition_ref]})
        f.freeze()

    def reauthorize(self,f,mutate_spec=None,mutate_plan=None,mutate_report=None):
        d=deepcopy(f.second_disposition)
        grant=json.loads((f.root/d['authorizingGrantRef']['path']).read_bytes())
        plan=json.loads((f.root/grant['planRef']['path']).read_bytes())
        spec=json.loads((f.root/grant['specificationRef']['path']).read_bytes())
        report=json.loads((f.root/grant['planReviewRef']['path']).read_bytes())
        if mutate_spec:mutate_spec(spec)
        if mutate_plan:mutate_plan(plan)
        grant['specificationRef']=put(f.root,grant['specificationRef']['path'],spec)
        grant['planRef']=put(f.root,grant['planRef']['path'],plan)
        report['reviewedPlanHash']=canonical_digest(plan)
        if mutate_report:mutate_report(report)
        grant['planReviewRef']=put(f.root,grant['planReviewRef']['path'],report)
        grant['lockRef']=put(f.root,grant['lockRef']['path'],build_plan_lock_v2(plan,repository_root=f.root))
        d['basisReviewRef']=grant['planReviewRef'];d['authorizingReviewRef']=grant['planReviewRef']
        d['authorizingGrantRef']=put(f.root,d['authorizingGrantRef']['path'],grant)
        self.select(f,d)

    def denied(self,f,code=None):
        with self.assertRaises(LifecycleError) as caught:f.snapshot()
        if code:self.assertEqual(code,caught.exception.code)

    def test_two_groups_union_preserves_finance_original_bytes_and_denies_both_historical_receipts(self):
        f=self.fixture()
        all_refs=f.recovery_original_refs+[r[k] for r in f.second_disposition['originalWindows'] for k in ('admissionRef','costRef')]
        originals={r['path']:(f.root/r['path']).read_bytes() for r in all_refs}
        head=read_coordinator_cost_head(f.root)
        projection=f.snapshot()['projection']
        self.assertEqual(2,len(projection['conflictDispositions']))
        expected={r['windowId'] for d in (f.recovery_disposition,f.second_disposition) for r in d['originalWindows']}
        actual={r['windowId'] for r in projection['windowPools'] if r['eligibility']=='HISTORICAL_INELIGIBLE'}
        self.assertEqual(expected,actual)
        self.assertEqual(4,len(actual));self.assertEqual('PASS',f.validate()['status'])
        self.assertEqual(head['head']['unknownHolds'],projection['balances']['currentUnknownHolds'])
        self.assertEqual(head['head']['exposureLowerBound'],projection['balances']['currentExposureLowerBound'])
        self.assertIsNone(projection['balances']['actualTokens'])
        self.assertEqual('OPEN_UNAVAILABLE',f.validate()['usageAssurance']['financialClosure'])
        for d in (f.recovery_disposition,f.second_disposition):
            for row in d['originalWindows']:
                with self.subTest(historical=row['windowId']):
                    receipt=deepcopy(f.receipt);receipt['currentAdmissionRef']=row['admissionRef']
                    with self.assertRaises(LifecycleError):f.validate(receipt)
        self.assertEqual(head['headRaw'],read_coordinator_cost_head(f.root)['headRaw'])
        self.assertEqual(originals,{p:(f.root/p).read_bytes() for p in originals})

    def test_duplicate_or_overlapping_group_is_refused_before_eligibility_assignment(self):
        from agent_lifecycle.workflow.limited_usage import _classify_source_conflict
        f=self.fixture();selection=f.selection();snapshot=f.snapshot()
        pools=deepcopy(snapshot['projection']['windowPools'])
        for p in pools:p['eligibility']='UNTOUCHED'
        old=deepcopy(pools)
        selection['recovery']['groups'].append(deepcopy(selection['recovery']['groups'][0]))
        with self.assertRaises(LifecycleError) as caught:
            _classify_source_conflict(selection,snapshot['current'],snapshot['projection']['records'],pools)
        self.assertEqual('scoped-usage-recovery-invalid',caught.exception.code)
        self.assertEqual(old,pools)
        f=self.fixture();d=deepcopy(f.second_disposition)
        d['originalWindows']=deepcopy(f.recovery_disposition['originalWindows'])
        self.select(f,d)
        def authorize_overlap(spec):
            rows=d['originalWindows']
            spec['exactConflict']['originalWindowIds']=[r['windowId'] for r in rows]
            spec['exactConflict']['originalRecords']=[r[k] for r in rows for k in ('admissionRef','costRef')]
            ref=spec['wireContracts']['disposition']['basisRefusalRef']
            refusal=json.loads((f.root/ref['path']).read_bytes())
            refusal['originalWindowIds']=spec['exactConflict']['originalWindowIds']
            spec['wireContracts']['disposition']['basisRefusalRef']=put(f.root,ref['path'],refusal)
        self.reauthorize(f,mutate_spec=authorize_overlap)
        self.denied(f,'scoped-usage-recovery-invalid')

    def test_third_member_and_incomplete_or_edited_stage_refuse(self):
        for kind in ('third','missing','edited'):
            with self.subTest(kind=kind):
                f=self.fixture()
                if kind=='third':f.append_window(405,bound=True,operation=f.second_disposition['identityTuple']['semanticOperationId'])
                else:
                    p=f.root/f.second_disposition['originalWindows'][1]['costRef']['path']
                    if kind=='missing':p.unlink()
                    else:p.write_bytes(p.read_bytes()+b' ')
                if kind=='third':self.denied(f,'scoped-usage-window-conflict')
                else:
                    with self.assertRaises((LifecycleError,FileNotFoundError)):f.snapshot()

    def test_changed_unreviewed_or_unfrozen_second_authority_refuses(self):
        for kind in ('negative-review','unfrozen','wrong-package'):
            with self.subTest(kind=kind):
                f=self.fixture()
                if kind=='negative-review':self.reauthorize(f,mutate_report=lambda r:r.update(verdict='CHANGES_REQUIRED'))
                elif kind=='unfrozen':self.reauthorize(f,mutate_plan=lambda p:p.update(status='DRAFT'))
                else:self.reauthorize(f,mutate_report=lambda r:r.update(packageId='unreviewed-other-package'))
                self.denied(f,'scoped-usage-recovery-invalid')

    def test_nonancestral_second_authority_refuses(self):
        f=self.fixture();d=deepcopy(f.second_disposition)
        grant=json.loads((f.root/d['authorizingGrantRef']['path']).read_bytes())
        head=json.loads((f.root/d['authorizingFinancialHeadRef']['path']).read_bytes())
        head['unboundExtra']='not-original-ancestor'
        ref=put(f.root,'work/second-recovery/nonancestor.json',head)
        d['authorizingFinancialHeadRef']=ref;grant['authorizingFinancialHeadRef']=ref
        d['authorizingGrantRef']=put(f.root,d['authorizingGrantRef']['path'],grant)
        self.select(f,d);self.denied(f,'scoped-usage-recovery-invalid')

    def test_original_opening_change_and_unlisted_second_disposition_refuse(self):
        f=self.fixture()
        selector=json.loads((f.root/'tasks/strategy/source-usage-conflict-recovery.json').read_bytes())
        selector['originalOpeningRef']=f.second_disposition['authorizingFinancialHeadRef']
        put(f.root,'tasks/strategy/source-usage-conflict-recovery.json',selector);f.freeze()
        self.denied(f,'scoped-usage-recovery-invalid')
        f=self.fixture();f.manifest['planFiles'].remove(f.second_disposition_ref['path']);f.freeze()
        self.denied(f,'plan-file-undeclared')

    def test_second_v2_disposition_requires_exact_integrated_refusal_basis(self):
        for kind in ('wrong-review','wrong-refusal','wrong-schema'):
            with self.subTest(kind=kind):
                f=self.fixture()
                if kind=='wrong-review':
                    d=deepcopy(f.second_disposition);d['basisReviewRef']=f.recovery_disposition['basisReviewRef'];self.select(f,d)
                elif kind=='wrong-schema':self.reauthorize(f,mutate_spec=lambda s:s.update(schemaVersion='alk-source-window-conflict-recovery-specification.v2'))
                else:
                    def mutate(spec):
                        ref=spec['wireContracts']['disposition']['basisRefusalRef']
                        value=json.loads((f.root/ref['path']).read_bytes());value['originalWindowIds'].reverse()
                        spec['wireContracts']['disposition']['basisRefusalRef']=put(f.root,ref['path'],value)
                    self.reauthorize(f,mutate_spec=mutate)
                self.denied(f,'scoped-usage-recovery-invalid')

    def test_prepublication_operation_preflight_denies_reuse_and_preserves_all_bytes(self):
        from agent_lifecycle.workflow.limited_usage import require_source_operation_unused
        f=self.fixture();selection=f.selection()
        originals={str(p.relative_to(f.root)):p.read_bytes() for p in f.root.rglob('*') if p.is_file() and '.git' not in p.relative_to(f.root).parts}
        binding=deepcopy(json.loads((f.root/f.admission_ref['path']).read_bytes())['sourceUsageBinding'])
        binding['originalWindowId']=BASE+'/r405-fixture'
        new_binding=deepcopy(binding);new_binding['semanticOperationId']='genuinely-new-phase'
        result=require_source_operation_unused(selection,new_binding)
        self.assertEqual('UNUSED_DECLARED_SOURCE_OPERATION',result['status'])
        self.assertIs(result['executionAuthorized'],False)
        self.assertEqual('UNAVAILABLE',result['actualCapConformance'])
        for op in ('final-current-operation',f.recovery_disposition['identityTuple']['semanticOperationId'],f.second_disposition['identityTuple']['semanticOperationId']):
            existing=deepcopy(binding);existing['semanticOperationId']=op
            with self.subTest(operation=op):
                with self.assertRaises(LifecycleError) as caught:require_source_operation_unused(selection,existing)
                self.assertEqual('scoped-usage-window-conflict',caught.exception.code)
            for field,value in (('runId','different-run'),('packageId','different-package'),('taskId','different-task'),('attempt',2)):
                with self.subTest(operation=op,distinctIdentityField=field):
                    different=deepcopy(existing);different[field]=value
                    unused=require_source_operation_unused(selection,different)
                    self.assertEqual('UNUSED_DECLARED_SOURCE_OPERATION',unused['status'])
                    self.assertEqual(value,unused['identityTuple'][field])
                    self.assertIs(unused['executionAuthorized'],False)
                    self.assertEqual('UNAVAILABLE',unused['actualCapConformance'])
            for field in ('planDigest','sourceRevision','routeDecisionDigest','sourceUsagePolicyDigest','sourceInputSubjectDigest'):
                with self.subTest(operation=op,nonidentityField=field):
                    different=deepcopy(existing)
                    different[field]=('e' if existing[field] != 'e'*len(existing[field]) else 'd')*len(existing[field])
                    with self.assertRaises(LifecycleError) as caught:require_source_operation_unused(selection,different)
                    self.assertEqual('scoped-usage-window-conflict',caught.exception.code)
        invalid=deepcopy(binding);invalid['attempt']=True
        with self.assertRaises(LifecycleError):require_source_operation_unused(selection,invalid)
        self.assertEqual(originals,{str(p.relative_to(f.root)):p.read_bytes() for p in f.root.rglob('*') if p.is_file() and '.git' not in p.relative_to(f.root).parts})

    def test_legacy_policy_cannot_select_otherwise_valid_v2_disposition(self):
        f=self.fixture()
        self.assertEqual(2,len(f.snapshot()['projection']['conflictDispositions']))
        put(f.root,'tasks/strategy/source-usage-conflict-recovery.json',{
            'schemaVersion':'alk-source-usage-conflict-recovery-policy.v1',
            'originalOpeningRef':f.policy['openingRef'],'dispositionRef':f.second_disposition_ref})
        f.freeze();before=read_coordinator_cost_head(f.root)['headRaw']
        self.denied(f,'scoped-usage-recovery-invalid')
        self.assertEqual(before,read_coordinator_cost_head(f.root)['headRaw'])

    def test_authorized_group_across_revision_digit_boundary_preserves_all_stage_refs(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        f=multigroup_fixture(Path(directory.name).resolve(),second_numbers=(999,1000))
        refs=[r[k] for r in f.second_disposition['originalWindows'] for k in ('admissionRef','costRef')]
        original={r['path']:(f.root/r['path']).read_bytes() for r in refs}
        head=read_coordinator_cost_head(f.root)
        projection=f.snapshot()['projection']
        expected={BASE+'/r999-fixture',BASE+'/r1000-fixture'}
        self.assertEqual([BASE+'/r1000-fixture',BASE+'/r999-fixture'],[r['windowId'] for r in f.second_disposition['originalWindows']])
        actual={p['windowId'] for p in projection['windowPools'] if p['eligibility']=='HISTORICAL_INELIGIBLE'}
        self.assertTrue(expected<=actual);self.assertEqual(4,len(actual))
        self.assertEqual('PASS',f.validate()['status'])
        self.assertEqual(head['head']['unknownHolds'],projection['balances']['currentUnknownHolds'])
        self.assertEqual(head['head']['exposureLowerBound'],projection['balances']['currentExposureLowerBound'])
        for row in f.second_disposition['originalWindows']:
            with self.subTest(historical=row['windowId']):
                receipt=deepcopy(f.receipt);receipt['currentAdmissionRef']=row['admissionRef']
                with self.assertRaises(LifecycleError):f.validate(receipt)
        self.assertEqual(head['headRaw'],read_coordinator_cost_head(f.root)['headRaw'])
        self.assertEqual(original,{p:(f.root/p).read_bytes() for p in original})


def invalid_annotation_fixture(root, *, binding_mutator=None, financial_mutator=None, finish=True):
    """Local exact-pair authority; no host, live ledger or release assurance."""
    f = recovery_fixture(root)
    template = deepcopy(json.loads((root / f.admission_ref['path']).read_bytes())['sourceUsageBinding'])
    f.close_window()
    windows = []
    for number in (401, 402, 403):
        window = BASE + '/r' + str(number) + '-fixture'
        binding = {**template, 'originalWindowId': window,
                   'semanticOperationId': 'historical-' + str(number),
                   'originalCostScope': 'INVALID_HISTORICAL_SCOPE_' + str(number)}
        if binding_mutator is not None:
            binding_mutator(binding)
        fields = {'sourceUsageBinding': binding}
        if financial_mutator is not None:
            financial_mutator(fields)
        admission = f.append_window(number, bound=True, repair_fields=fields)
        f.close_window()
        path = window + '/cost.json'
        data = (root / path).read_bytes()
        windows.append({'windowId': window, 'admissionRef': admission,
                        'costRef': {'path': path, 'bytes': len(data),
                                    'sha256': hashlib.sha256(data).hexdigest()},
                        'originalBindingSha256': canonical_digest(binding)})
    f.append_window(404)
    authority = put(root, 'work/annotations/authorizing-head.json',
                    read_coordinator_cost_head(root)['headRaw'])
    parent_policy = json.loads((root / 'tasks/strategy/source-usage-conflict-recovery.json').read_bytes())
    decision = put(root, 'tasks/strategy/annotation-decision.json', {
        'status': 'USER_APPROVED_A_EXACT_HISTORICAL_ANNOTATION_RECOVERY',
        'answer': 'A — точечное восстановление учёта (рекомендуется)'})
    contract = put(root, 'tasks/strategy/annotation-contract.md', b'Synthetic fixture contract, not live approval.')
    procedure = put(root, 'tasks/strategy/annotation-procedure.py', b'# synthetic procedural provenance only\n')
    subject = {'schemaVersion': 'alk-source-invalid-annotation-specification-subject.v1',
        'contractRef': contract, 'scopeDecisionRef': decision,
        'originalOpeningRef': f.policy['openingRef'], 'originalWindows': windows,
        'sourceRevision': f.revision, 'prospectiveAdmissionProcedureRef': procedure,
        'historicalSourceRefs': [{'path': 'historical/' + str(i), 'bytes': 1,
                                 'sha256': 'a' * 64} for i in range(3)]}
    subject_ref = put(root, 'tasks/strategy/annotation-subject.json', subject)
    report_ref = put(root, 'tasks/strategy/annotation-review.json', {
        'schemaVersion': 'alk-source-recovery-contract-review.v1',
        'subjectDigest': canonical_digest(subject), 'reviewerId': 'independent-fixture',
        'independent': True, 'verdict': 'READY_TO_DRAFT', 'fullReview': True,
        'findings': [], 'coverage': ['local'], 'reviewText': 'Synthetic fixture only.',
        'unverifiedEvidence': ['no runtime or external approval'], 'toolCalls': 0,
        'productImplementationApproved': False, 'nativeApproved': False,
        'taskAccepted': False, 'releaseReady': False})
    disposition = {'schemaVersion': 'alk-source-invalid-annotation-disposition.v1',
        'dispositionId': 'synthetic-exact-three',
        'classification': 'FINANCIAL_HISTORY_ONLY_INVALID_SOURCE_ANNOTATION',
        'originalOpeningRef': f.policy['openingRef'], 'authorizingFinancialHeadRef': authority,
        'scopeDecisionRef': decision, 'specificationRef': contract,
        'specificationSubjectRef': subject_ref, 'specificationReviewRef': report_ref,
        'originalWindows': windows}
    disposition_ref = put(root, 'tasks/strategy/annotation-disposition.json', disposition)
    selector = put(root, 'tasks/strategy/source-invalid-annotation-recovery.json', {
        'schemaVersion': 'alk-source-usage-conflict-recovery-policy.v3',
        'originalOpeningRef': f.policy['openingRef'],
        'dispositionRefs': [parent_policy['dispositionRef']],
        'invalidAnnotationDispositionRef': disposition_ref})
    f.manifest['runtimePolicy']['sourceWindowConflictRecovery'] = {
        'invalidAnnotationScopeDecisionRef': decision}
    authorities = [decision, contract, procedure, subject_ref, report_ref, disposition_ref, selector]
    f.manifest['planFiles'] = sorted(f.manifest['planFiles'] + [r['path'] for r in authorities])
    f.freeze()
    f.task['modelRoute']['operationId'] = 'genuine-annotation-current'
    f.task['attemptModelRoute']['operationId'] = 'genuine-annotation-current'
    f.admission_ref = f.append_window(405, bound=True, operation='genuine-annotation-current')
    f.receipt = f.make_receipt() if finish else None
    f.annotation_windows = windows
    f.annotation_disposition = disposition
    f.annotation_selector = selector
    f.annotation_subject = deepcopy(subject)
    f.annotation_report = json.loads((root / report_ref['path']).read_bytes())
    return f


class InvalidAnnotationRecoveryTests(unittest.TestCase):
    def fixture(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return invalid_annotation_fixture(Path(directory.name).resolve())

    def test_exact_pairs_keep_all_costs_raw_records_and_unavailable_roles(self):
        f = self.fixture()
        before = {ref['path']: (f.root / ref['path']).read_bytes()
                  for row in f.annotation_windows for ref in (row['admissionRef'], row['costRef'])}
        snapshot = f.snapshot()
        value = snapshot['projection']
        self.assertEqual('alk-source-usage-current-registry.v3', value['schemaVersion'])
        self.assertEqual(1, len(value['conflictDispositions']))
        self.assertEqual(14, len(value))
        for row in f.annotation_windows:
            pool = next(p for p in value['windowPools'] if p['windowId'] == row['windowId'])
            self.assertIsNone(pool['binding'])
            self.assertEqual('HISTORICAL_INELIGIBLE', pool['eligibility'])
            self.assertEqual('UNAVAILABLE_LEGACY_DECLARED_WINDOW', pool['originalCostScope'])
            records = [r for r in value['records'] if r['windowId'] == row['windowId']]
            self.assertEqual(['ADMISSION', 'COST'], [r['stage'] for r in records])
            self.assertTrue(all(r['binding'] is None for r in records))
            self.assertTrue(all(row['windowId'] not in r['windowIds'] for r in value['roleDispositions']))
        self.assertEqual(snapshot['current']['head']['exposureLowerBound'],
                         value['balances']['currentExposureLowerBound'])
        self.assertEqual(snapshot['current']['head']['unknownHolds'],
                         value['balances']['currentUnknownHolds'])
        self.assertEqual(before, {path: (f.root / path).read_bytes() for path in before})
        self.assertEqual('PASS', f.validate(f.make_receipt())['status'])

    def test_default_without_selector_still_refuses_original_malformed_binding(self):
        f = self.fixture()
        path = f.annotation_selector['path']
        f.manifest['planFiles'].remove(path)
        (f.root / path).unlink()
        f.freeze()
        with self.assertRaises(LifecycleError) as caught:
            f.snapshot()
        self.assertEqual('scoped-usage-shape-invalid', caught.exception.code)

    def test_recovered_admissions_cannot_authorize_current_completion(self):
        f = self.fixture()
        for row in f.annotation_windows:
            receipt = f.make_receipt()
            receipt['currentAdmissionRef'] = row['admissionRef']
            with self.subTest(window=row['windowId']), self.assertRaises(LifecycleError) as caught:
                f.validate(receipt)
            self.assertEqual('scoped-usage-current-admission-unbound', caught.exception.code)

    def test_unlisted_new_malformed_binding_is_not_recovered(self):
        f = self.fixture()
        binding = deepcopy(json.loads((f.root / f.admission_ref['path']).read_bytes())['sourceUsageBinding'])
        binding.update(originalCostScope='UNLISTED_INVALID', originalWindowId=BASE + '/r406-fixture',
                       semanticOperationId='unlisted-operation')
        f.append_window(406, bound=True, repair_fields={'sourceUsageBinding': binding})
        with self.assertRaises(LifecycleError) as caught:
            f.snapshot()
        self.assertEqual('scoped-usage-shape-invalid', caught.exception.code)


def refreeze_annotation_fixture(f):
    """Repin only synthetic authority so refusal reaches the intended join."""
    disposition = f.annotation_disposition
    subject_ref = put(f.root, disposition['specificationSubjectRef']['path'], f.annotation_subject)
    review_ref = put(f.root, disposition['specificationReviewRef']['path'], f.annotation_report)
    disposition.update(specificationSubjectRef=subject_ref, specificationReviewRef=review_ref)
    disposition_ref = put(f.root, f.annotation_selector['path'].replace(
        'source-invalid-annotation-recovery.json', 'annotation-disposition.json'), disposition)
    selector = json.loads((f.root / f.annotation_selector['path']).read_bytes())
    selector['invalidAnnotationDispositionRef'] = disposition_ref
    f.annotation_selector = put(f.root, f.annotation_selector['path'], selector)
    f.freeze()


class InvalidAnnotationAuthorityRefusalTests(unittest.TestCase):
    def fixture(self, **kwargs):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return invalid_annotation_fixture(Path(directory.name).resolve(), **kwargs)

    def assert_read_only_refusal(self, f):
        paths = ['run.state.json', BASE + '/COORDINATOR-COST-HEAD.json']
        paths += [r['path'] for w in f.annotation_windows for r in (w['admissionRef'], w['costRef'])]
        before = {p: (f.root / p).read_bytes() for p in paths if (f.root / p).exists()}
        with self.assertRaises(LifecycleError):
            f.snapshot()
        self.assertEqual(before, {p: (f.root / p).read_bytes() for p in before})

    def test_changed_missing_and_swapped_original_source_refuse_without_writes(self):
        for mutation in ('changed', 'missing', 'swapped'):
            f = self.fixture()
            row = f.annotation_windows[0]
            with self.subTest(mutation=mutation):
                if mutation == 'changed':
                    (f.root / row['admissionRef']['path']).write_bytes(b'{}')
                elif mutation == 'missing':
                    (f.root / row['costRef']['path']).unlink()
                else:
                    f.annotation_disposition['originalWindows'][0]['costRef'] = (
                        f.annotation_windows[1]['costRef'])
                    refreeze_annotation_fixture(f)
                self.assert_read_only_refusal(f)

    def test_pinned_extra_binding_defects_and_canonical_scope_refuse(self):
        mutations = [lambda b: b.update(unapproved=True), lambda b: b.pop('actorId'),
                     lambda b: b.update(role='unlisted-role'), lambda b: b.update(attempt=False),
                     lambda b: b.update(originalWindowId=BASE + '/r999-other'),
                     lambda b: b.update(originalCostScope='COORDINATOR_FINITE_SOURCE_AUTHORING_WINDOW')]
        for number, mutate in enumerate(mutations):
            with self.subTest(mutation=number):
                f = self.fixture(binding_mutator=mutate, finish=False)
                self.assert_read_only_refusal(f)

    def test_selected_bad_original_clocks_and_reserve_refuse(self):
        for key, value in [('absoluteDeadlineUtc', '2000-01-01T00:00:00+00:00'),
                           ('protectedCloseoutTokens', 0), ('priorBudgetResumed', True)]:
            with self.subTest(key=key):
                if key == 'absoluteDeadlineUtc':
                    f = self.fixture(financial_mutator=lambda fields: fields.update({key: value}), finish=False)
                    self.assert_read_only_refusal(f)
                else:
                    # The original finance publisher rejects these before a
                    # historical projection can exist; never bypass that guard.
                    with self.assertRaises(LifecycleError):
                        self.fixture(financial_mutator=lambda fields: fields.update({key: value}), finish=False)

    def test_subject_review_and_copied_authority_lineage_refuse(self):
        for mutation in ('subject-digest', 'subject-windows', 'source-revision', 'contract',
                         'review-incomplete', 'review-not-independent', 'review-high-finding'):
            f = self.fixture()
            if mutation == 'subject-digest':
                f.annotation_report['subjectDigest'] = '0' * 64
            elif mutation == 'subject-windows':
                f.annotation_subject['originalWindows'][0]['originalBindingSha256'] = '0' * 64
                f.annotation_report['subjectDigest'] = canonical_digest(f.annotation_subject)
            elif mutation == 'source-revision':
                f.annotation_subject['sourceRevision'] = '0' * 40
                f.annotation_report['subjectDigest'] = canonical_digest(f.annotation_subject)
            elif mutation == 'contract':
                f.annotation_subject['contractRef'] = f.annotation_disposition['scopeDecisionRef']
                f.annotation_report['subjectDigest'] = canonical_digest(f.annotation_subject)
            elif mutation == 'review-incomplete':
                f.annotation_report['fullReview'] = False
            elif mutation == 'review-not-independent':
                f.annotation_report['reviewerId'] = '/root'
            else:
                f.annotation_report['findings'] = [{'id': 'fixture', 'severity': 'HIGH',
                    'target': 'fixture', 'impact': 'unresolved', 'requiredEdit': 'fix'}]
            refreeze_annotation_fixture(f)
            with self.subTest(mutation=mutation):
                self.assert_read_only_refusal(f)

    def test_decision_substitution_and_wrong_copied_authority_root_refuse(self):
        for mutation in ('decision', 'root'):
            f = self.fixture()
            if mutation == 'decision':
                decision = put(f.root, 'tasks/strategy/substituted-decision.json', {
                    'status': 'USER_APPROVED_A_EXACT_HISTORICAL_ANNOTATION_RECOVERY',
                    'answer': 'A — точечное восстановление учёта (рекомендуется)'})
                f.manifest['planFiles'].append(decision['path'])
                f.annotation_disposition['scopeDecisionRef'] = decision
                f.annotation_subject['scopeDecisionRef'] = decision
                f.annotation_report['subjectDigest'] = canonical_digest(f.annotation_subject)
                refreeze_annotation_fixture(f)
            else:
                path = f.root / f.annotation_disposition['specificationRef']['path']
                outside = f.root.parent / (f.root.name + '-outside-contract.md')
                outside.write_bytes(path.read_bytes())
                self.addCleanup(outside.unlink)
                path.unlink()
                path.symlink_to(outside)
            with self.subTest(mutation=mutation):
                self.assert_read_only_refusal(f)

    def test_unlisted_selector_and_original_conflict_overlap_refuse(self):
        for mutation in ('unlisted', 'overlap'):
            f = self.fixture()
            if mutation == 'unlisted':
                f.manifest['planFiles'].remove(f.annotation_selector['path'])
                f.freeze()
            else:
                old = f.selection()['recovery']['disposition']['originalWindows'][0]
                row = {**old, 'originalBindingSha256': '0' * 64}
                f.annotation_disposition['originalWindows'] = [row]
                f.annotation_subject['originalWindows'] = [row]
                f.annotation_report['subjectDigest'] = canonical_digest(f.annotation_subject)
                refreeze_annotation_fixture(f)
            with self.subTest(mutation=mutation):
                self.assert_read_only_refusal(f)

    def test_wrong_original_digest_and_authority_ancestry_order_refuse(self):
        for mutation in ('digest', 'authority-before-pairs', 'authority-not-ancestor'):
            f = self.fixture()
            if mutation == 'digest':
                f.annotation_disposition['originalWindows'][0]['originalBindingSha256'] = '0' * 64
                f.annotation_subject['originalWindows'] = deepcopy(f.annotation_disposition['originalWindows'])
                f.annotation_report['subjectDigest'] = canonical_digest(f.annotation_subject)
            elif mutation == 'authority-before-pairs':
                f.annotation_disposition['authorizingFinancialHeadRef'] = f.policy['openingRef']
            else:
                foreign = json.loads(read_coordinator_cost_head(f.root)['headRaw'])
                foreign['unselectedFixtureOnly'] = True
                f.annotation_disposition['authorizingFinancialHeadRef'] = put(
                    f.root, 'work/annotations/foreign-head.json', foreign)
            refreeze_annotation_fixture(f)
            with self.subTest(mutation=mutation):
                self.assert_read_only_refusal(f)

    def test_selected_repetition_and_late_appearance_refuse(self):
        from agent_lifecycle.workflow.limited_usage import _invalid_annotation_binding, _invalid_annotation_tracker
        f = self.fixture()
        selection = f.selection()
        current = f.snapshot()['current']
        chain = list(reversed(current['ancestryHeadSha256s']))
        row = f.annotation_windows[0]
        value = json.loads((f.root / row['admissionRef']['path']).read_bytes())
        tracker = _invalid_annotation_tracker(selection, chain)
        index = next(i for i, r in enumerate(f.snapshot()['projection']['records'])
                     if r['sourceRef'] == row['admissionRef'])
        self.assertIsNone(_invalid_annotation_binding(tracker, value, row['admissionRef'],
            row['windowId'], 'ADMISSION', index))
        for late in (index, tracker['authorityIndex'], len(chain)):
            with self.subTest(index=late), self.assertRaises(LifecycleError):
                _invalid_annotation_binding(tracker, value, row['admissionRef'],
                    row['windowId'], 'ADMISSION', late)


class ProspectiveAdmissionProcedureTests(unittest.TestCase):
    """Exact pinned executable in local synthetic data; no financial publisher."""
    def fixture(self):
        import importlib.util
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        f = DeclaredFixture(Path(directory.name).resolve())
        now = datetime.now(UTC)
        f.state.update(runStartedAt=(now - timedelta(minutes=2)).isoformat(),
                       runDeadlineAt=(now + timedelta(hours=2)).isoformat())
        f.task.update(attemptStartedAt=(now - timedelta(minutes=1)).isoformat(),
                      attemptDeadlineAt=(now + timedelta(hours=1)).isoformat())
        f.task['attemptModelRoute']['operationId'] = 'genuinely-prospective-procedure'
        f.manifest['orchestration'] = {'stateFile': 'run.state.json'}
        f.freeze()
        subject = {'schemaVersion': 'synthetic-prospective-input', 'currentRoot': str(f.root)}
        subject_ref = put(f.root, 'work/prospective-input.json', subject)
        admission = deepcopy(read_coordinator_cost_head(f.root)['source'])
        window_id = BASE + '/r480-prospective-fixture'
        admission.update(originalWindowId=window_id, actorId='/root', role='coordinator',
            originalCostScope='COORDINATOR_FINITE_SOURCE_AUTHORING_WINDOW',
            inputSubjectRef=subject_ref, inputSubjectDigest=canonical_digest(subject),
            admittedAtUtc=now.isoformat(), absoluteDeadlineUtc=(now + timedelta(minutes=10)).isoformat())
        admission['sourceUsageBinding'].update(originalWindowId=window_id,
            semanticOperationId=f.task['attemptModelRoute']['operationId'], planDigest=f.state['planDigest'],
            sourceInputSubjectDigest=canonical_digest(subject))
        procedure_path = Path(__file__).resolve().parents[2] / 'tasks/release-2-16/source-prospective-admission-procedure.py'
        spec = importlib.util.spec_from_file_location('synthetic_prospective_procedure', procedure_path)
        procedure = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(procedure)
        return f, procedure, admission, subject_ref

    def validate(self, f, procedure, admission, subject_ref):
        return procedure.validate_prospective_admission(f.root, f.state['manifestPath'], 'WS-01',
            admission, input_subject_ref=subject_ref)

    def test_live_prospective_validates_without_publishing_and_rechecks_caller(self):
        f, procedure, admission, subject_ref = self.fixture()
        before = read_coordinator_cost_head(f.root)['headRaw']
        state = (f.root / 'run.state.json').read_bytes()
        result = self.validate(f, procedure, admission, subject_ref)
        self.assertEqual('VALIDATED_BEFORE_PUBLICATION', result['status'])
        self.assertEqual(0, result['financialWrites'])
        self.assertFalse(result['wholeHistoricalProjectionQualified'])
        self.assertFalse(result['hostBudgetGuarantee'])
        procedure.require_live_admission_clocks(admission, f.state, f.task)
        self.assertEqual(before, read_coordinator_cost_head(f.root)['headRaw'])
        self.assertEqual(state, (f.root / 'run.state.json').read_bytes())
        self.assertFalse((f.root / (admission['originalWindowId'] + '/admission.json')).exists())

    def test_valid_shape_wrong_tuple_input_actor_and_duplicate_operation_refuse(self):
        f, procedure, admission, subject_ref = self.fixture()
        for key, value in [('runId', 'other-run'), ('semanticOperationId', 'wrong-operation'),
                           ('routeDecisionDigest', '0' * 64), ('actorId', 'other-actor'),
                           ('sourceInputSubjectDigest', '0' * 64), ('planDigest', '0' * 64)]:
            changed = deepcopy(admission)
            changed['sourceUsageBinding'][key] = value
            with self.subTest(key=key), self.assertRaises(LifecycleError):
                self.validate(f, procedure, changed, subject_ref)
        changed = {**deepcopy(admission), 'inputSubjectDigest': '0' * 64}
        with self.assertRaises(LifecycleError):
            self.validate(f, procedure, changed, subject_ref)
        # Use the original operation's actual identity and matching current plan:
        # uniqueness is independent of eligibility, scope or later source receipt.
        original = read_coordinator_cost_head(f.root)['source']['sourceUsageBinding']
        f.task['attemptModelRoute']['operationId'] = original['semanticOperationId']
        put(f.root, 'run.state.json', f.state)
        changed = deepcopy(admission)
        changed['sourceUsageBinding']['semanticOperationId'] = original['semanticOperationId']
        with self.assertRaises(LifecycleError) as caught:
            self.validate(f, procedure, changed, subject_ref)
        self.assertIn('already has an original binding', str(caught.exception))

    def test_expired_admission_live_run_task_and_exact_deadline_refuse(self):
        from unittest.mock import patch
        f, procedure, admission, subject_ref = self.fixture()
        deadline = datetime.fromisoformat(admission['absoluteDeadlineUtc'])
        for observed in (deadline, deadline + timedelta(seconds=1)):
            class FixedClock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return observed
            with self.subTest(observed=observed), patch.object(procedure, 'datetime', FixedClock):
                with self.assertRaises(LifecycleError):
                    self.validate(f, procedure, admission, subject_ref)
                with self.assertRaises(LifecycleError):
                    procedure.require_live_admission_clocks(admission, f.state, f.task)
        self.assertFalse((f.root / (admission['originalWindowId'] + '/admission.json')).exists())

    def test_clock_expiry_during_ancestry_walk_refuses_at_final_return(self):
        from unittest.mock import patch
        for expired in ('admission', 'run', 'attempt'):
            f, procedure, admission, subject_ref = self.fixture()
            live = datetime.fromisoformat(admission['admittedAtUtc'])
            deadline = live + timedelta(minutes=10)
            admission['absoluteDeadlineUtc'] = deadline.isoformat()
            if expired == 'run':
                f.state['runDeadlineAt'] = deadline.isoformat()
            elif expired == 'attempt':
                f.task['attemptDeadlineAt'] = deadline.isoformat()
            put(f.root, 'run.state.json', f.state)
            observations = iter([live, deadline])
            class AdvancingClock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return next(observations)
            before = read_coordinator_cost_head(f.root)['headRaw']
            with self.subTest(expired=expired), patch.object(procedure, 'datetime', AdvancingClock):
                with self.assertRaises(LifecycleError):
                    self.validate(f, procedure, admission, subject_ref)
            self.assertEqual(before, read_coordinator_cost_head(f.root)['headRaw'])

    def test_state_or_financial_frontier_changes_during_walk_refuse_without_writes(self):
        from unittest.mock import patch
        for changed in ('state', 'financial'):
            f, procedure, admission, subject_ref = self.fixture()
            before = read_coordinator_cost_head(f.root)['headRaw']
            original_state = (f.root / 'run.state.json').read_bytes()
            if changed == 'financial':
                original = procedure.read_coordinator_cost_head
                calls = []
                def read(*args, **kwargs):
                    value = original(*args, **kwargs)
                    calls.append(value)
                    return value if len(calls) == 1 else {**value, 'headRaw': value['headRaw'] + b' '}
                target, replacement = 'read_coordinator_cost_head', read
            else:
                original = procedure.read_authority_bytes
                calls = []
                def read(path, **kwargs):
                    value = original(path, **kwargs)
                    if path == f.root / 'run.state.json':
                        calls.append(value)
                        if len(calls) == 2:
                            return value + b' '
                    return value
                target, replacement = 'read_authority_bytes', read
            with self.subTest(changed=changed), patch.object(procedure, target, replacement):
                with self.assertRaises(LifecycleError) as caught:
                    self.validate(f, procedure, admission, subject_ref)
                self.assertIn('frontier changed', str(caught.exception))
            self.assertEqual(before, read_coordinator_cost_head(f.root)['headRaw'])
            self.assertEqual(original_state, (f.root / 'run.state.json').read_bytes())

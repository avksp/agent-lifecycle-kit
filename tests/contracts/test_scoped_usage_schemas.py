"""Closed scoped usage envelopes and unchanged strict legacy receipt behavior."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.scoped_usage_schemas import (
    SOURCE_USAGE_METRICS, SOURCE_USAGE_POLICY, SOURCE_USAGE_RECEIPT, SOURCE_RISK_PROFILE,
    SCOPED_USAGE_SCHEMAS, validate_source_usage_policy_shape, validate_source_usage_receipt_shape,
)
from agent_lifecycle.model_routing.receipts import validate_usage_receipt
from agent_lifecycle.workflow.model_usage import validate_task_model_usage_receipt
from tests.workflow.helpers import _model_route, _model_usage_receipt
from tests.workflow.test_limited_usage import DeclaredFixture


PINNED_LEGACY_SCHEMA_DIGESTS = {'agent-small-context-profile.v1': 'b4912070f7ddd24746ce92c61bdef801a19c795b34ac53308f1107e871cab763', 'agent-context-render-receipt.v1': '2b2cdbbd2ecaac196e952fb5bf80cfce397df3e4c81d85f0c939d815bc850364', 'agent-sdd-tier-resolution.v1': '12d001fee40326d2fff6bba16d476d6a31839daeb534a74a97b37a9aca16972f', 'agent-lifecycle-model-routing-profile.v1': 'b4b969d93d6c8ec91686c6669dcfb4233ee68e461b841936db5b95e7b957b5d1', 'agent-lifecycle-host-model-profile.v1': '09a5214408c6583e82a6fdd7d709823f4f931fe9a85f7e114923524bb1c1d6d8', 'agent-host-model-selection-profile.v1': 'c228500a0204199451a170acf2d9542286198d0bfac0906f164be428cecb658c', 'agent-host-model-selection-receipt.v1': 'e22ba581efc0ff17d95bbe2b0f049e913530f5b1d4e3f1bd9513b0d4cbbfd306', 'agent-lifecycle-budget-exceeded-policy.v1': 'f6c26eeb2bab7a5f711f6a309d156da1b7674c574aaf9e4fd851d31a0f986113', 'agent-lifecycle-budget-decision-receipt.v1': '86471ea04b75da8cad9ea45608a95d1e956c8ca79427f02524c299405fcc48e3', 'agent-cursor-compat-evidence.v1': 'f109cd30a12393816db7f82101f9ab210e386cbf1d1e9cf900af3cc34941e9cf', 'agent-lifecycle-model-route-request.v1': '36f52f2ab1bb0383886700ccbba53c460fc8e02a38c09ac206f8e25154cce2e5', 'agent-lifecycle-model-route-decision.v1': 'e3106ab1d70194cd0a495a46fa970c420f95c756737fd27f925022faf53f9229', 'agent-lifecycle-model-usage-receipt.v1': 'c83aa84095506b8db30b61b0f5f1ad741b533eb05daf0489f60b3bf57e8d3404', 'agent-risk-execution-policy.v1': 'cfaf3f102bfe3d85522ec7e285b10985fd83ce2b0b93bda951ac07a89cf47eff', 'agent-risk-execution-profile.v1': '9240728d5c135b0eebc3d97ae7c811fd38d303d72175046713de6a5591a1a91c'}


class ScopedUsageSchemaTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.f = DeclaredFixture(Path(self.directory.name).resolve())

    def denied(self, callback):
        with self.assertRaises(LifecycleError) as caught:
            callback()
        self.observedRefusalCode = caught.exception.code

    def test_legacy_v1_missing_null_declared_refuses(self):
        for kind in ('missing', 'null', 'declared'):
            with self.subTest(kind=kind):
                receipt = _model_usage_receipt(_model_route())
                receipt.update(planDigest=self.f.state['planDigest'], sourceRevision=self.f.revision)
                if kind == 'missing':
                    del receipt['usage']['billableTokens']
                elif kind == 'null':
                    receipt['usage']['billableTokens'] = None
                else:
                    receipt['attestation'] = {'source': 'alk-declared', 'status': 'UNAVAILABLE'}
                self.denied(lambda: validate_task_model_usage_receipt(self.f.state, self.f.task, receipt))

    def test_missing_unfrozen_or_receipt_selected_policy_refuses(self):
        self.denied(lambda: validate_task_model_usage_receipt(self.f.state, self.f.task, self.f.receipt))
        self.f.manifest['runtimePolicy'].pop('sourceUsageCompletion')
        self.f.freeze()
        self.denied(self.f.validate)

    def test_policy_task_adapter_host_scope_mismatch_refuses(self):
        for field, value in [('id', 'OTHER'), ('adapterId', 'other')]:
            with self.subTest(field=field):
                previous = self.f.task[field]
                self.f.task[field] = value
                self.denied(self.f.validate)
                self.f.task[field] = previous
        receipt = deepcopy(self.f.receipt)
        receipt['host'] = 'other'
        self.denied(lambda: self.f.validate(receipt))

    def test_unknown_metric_is_null_and_never_fake_zero(self):
        with self.subTest(case='all-seven-null-unavailable'):
            validate_source_usage_receipt_shape(self.f.receipt)
            self.assertEqual(set(SOURCE_USAGE_METRICS), set(self.f.receipt['usage']))
        for metric in SOURCE_USAGE_METRICS:
            for value in (0, 1, False):
                with self.subTest(case='manufactured-zero-or-numeric-as-actual', metric=metric, value=value):
                    receipt = deepcopy(self.f.receipt)
                    receipt['usage'][metric] = value
                    self.denied(lambda: validate_source_usage_receipt_shape(receipt))
            with self.subTest(case='missing-metric-or-state', metric=metric):
                receipt = deepcopy(self.f.receipt)
                del receipt['metricStates'][metric]
                self.denied(lambda: validate_source_usage_receipt_shape(receipt))

    def test_logical_source_author_cannot_be_no_model_or_native_executor(self):
        receipt = deepcopy(self.f.receipt)
        receipt['modelClass'] = 'no-model'
        self.denied(lambda: validate_source_usage_receipt_shape(receipt))
        receipt = deepcopy(self.f.receipt)
        receipt['attestation'] = {'source': 'host', 'status': 'ATTESTED'}
        self.denied(lambda: validate_source_usage_receipt_shape(receipt))

    def test_full_guard_request_on_limited_source_refuses(self):
        for key, value in [('actualCapConformance', 'PASS'), ('financialClosureAllowed', True)]:
            with self.subTest(field=key):
                policy = deepcopy(self.f.policy)
                policy[key] = value
                self.denied(lambda: validate_source_usage_policy_shape(policy))

    def test_v2_bounds_unknown_keys_bad_type_refs_and_hashes_refuse(self):
        mutations = [lambda r: r.update(extra='unknown'),
                     lambda r: r['lineage'].update(attempt=True),
                     lambda r: r['lineage'].update(planDigest='A' * 64),
                     lambda r: r['ledgerRef'].update(path='../outside'),
                     lambda r: r['ledgerRef'].update(bytes=False),
                     lambda r: r.update(operationId='x' * 257),
                     lambda r: r.update(sourceContextRefs=[r['ledgerRef']] * 129)]
        for mutate in mutations:
            with self.subTest(mutation=mutations.index(mutate)):
                receipt = deepcopy(self.f.receipt)
                mutate(receipt)
                self.denied(lambda: validate_source_usage_receipt_shape(receipt))
        with self.subTest(case='valid-exact-current-projection-serializer-and-emitter'):
            self.assertEqual('PASS', self.f.validate()['status'])
        for case, key, value in [
            ('wrong-current-registry-namespace-or-path', 'path', 'tasks/strategy/prefix.json'),
            ('frozen-prefix-hash-used-as-live-projection-hash', 'sha256', self.f.receipt['sourceAuthoringRegistryDigest']),
        ]:
            with self.subTest(case=case):
                receipt = deepcopy(self.f.receipt)
                receipt['currentRegistryRef'][key] = value
                self.denied(lambda: self.f.validate(receipt))

        with self.subTest(case='different-projection-record-order-or-terminal-identity'):
            from tests.workflow.test_limited_usage import raw
            path = self.f.root / self.f.receipt['currentRegistryRef']['path']
            original = path.read_bytes()
            value = __import__('json').loads(original)
            value['records'].reverse()
            path.write_bytes(raw(value))
            self.denied(self.f.validate)
            path.write_bytes(original)

    def test_public_v2_schemas_and_unchanged_legacy_schema_objects(self):
        from agent_lifecycle.contracts import schemas
        from agent_lifecycle.contracts.context_model_schemas import CONTEXT_MODEL_SCHEMAS
        from agent_lifecycle.contracts.schemas import RISK_EXECUTION_SCHEMAS
        with self.subTest(case='new-tags-available-through-existing-schema-api'):
            for name in (SOURCE_USAGE_POLICY, SOURCE_USAGE_RECEIPT, SOURCE_RISK_PROFILE):
                self.assertEqual(name, schemas.get_schema(name)['$id'])
        with self.subTest(case='legacy-v1-canonical-schema-digests-unchanged'):
            for name, expected_digest in PINNED_LEGACY_SCHEMA_DIGESTS.items():
                self.assertEqual(expected_digest, canonical_digest(schemas.get_schema(name)))
            for group in (CONTEXT_MODEL_SCHEMAS, RISK_EXECUTION_SCHEMAS):
                for name, original in group.items():
                    self.assertEqual(canonical_digest(original), canonical_digest(schemas.get_schema(name)))
        with self.subTest(case='duplicate-schema-ID-refused'):
            # Reload only in a child: callers may hold the canonical get_schema
            # binding, which must not be replaced by this negative import test.
            code = '''
import importlib
import unittest
from unittest.mock import patch
from agent_lifecycle.contracts import schemas
from agent_lifecycle.contracts.context_model_schemas import CONTEXT_MODEL_SCHEMAS
from agent_lifecycle.contracts.scoped_usage_schemas import SCOPED_USAGE_SCHEMAS
existing = next(iter(CONTEXT_MODEL_SCHEMAS))
with patch.dict(SCOPED_USAGE_SCHEMAS, {existing: CONTEXT_MODEL_SCHEMAS[existing]}):
    with unittest.TestCase().assertRaisesRegex(RuntimeError, 'duplicate schema ids'):
        importlib.reload(schemas)
'''
            completed = subprocess.run(
                [sys.executable, '-c', code], capture_output=True, text=True, timeout=30, check=False
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_r564_public_v2_schema_rejects_inherited_bad_types_model_classes_and_ref_bounds(self):
        from jsonschema import Draft202012Validator
        from agent_lifecycle.contracts.schemas import get_schema
        from tests.workflow.test_limited_usage import derive_fixture_risk
        profile = derive_fixture_risk(self.f, operation_id=self.f.task['modelRoute']['operationId'])
        validator = Draft202012Validator(get_schema(SOURCE_RISK_PROFILE))
        self.assertEqual([], list(validator.iter_errors(profile)))
        for key, value in [('status', None), ('operationId', 1), ('resourceCaps', []),
                           ('modelRoute', None), ('qualityFloorDecision', 'bad'),
                           ('hostLaunchStarted', True), ('planDigest', 'bad')]:
            with self.subTest(field=key):
                changed = deepcopy(profile);changed[key] = value
                self.assertTrue(list(validator.iter_errors(changed)))
        changed = deepcopy(profile);changed['resourceCaps']['maxInvocations'] = None
        self.assertTrue(list(validator.iter_errors(changed)))
        for tag, original, key in [(SOURCE_USAGE_POLICY, self.f.policy, 'openingRef'),
                                   (SOURCE_USAGE_POLICY, self.f.policy, 'sourceAuthoringRegistryRef'),
                                   (SOURCE_USAGE_RECEIPT, self.f.receipt, 'currentRegistryRef')]:
            with self.subTest(tag=tag, ref=key):
                from agent_lifecycle.contracts.scoped_usage_schemas import MAX_CURRENT_SOURCE_REGISTRY_BYTES
                limit = MAX_CURRENT_SOURCE_REGISTRY_BYTES if key == 'currentRegistryRef' else 65536
                changed = deepcopy(original);changed[key]['bytes'] = limit + 1
                self.assertTrue(list(Draft202012Validator(get_schema(tag)).iter_errors(changed)))
        for tag, original, key in [(SOURCE_USAGE_POLICY, self.f.policy, 'allowedModelClasses'),
                                   (SOURCE_USAGE_RECEIPT, self.f.receipt, 'modelClass')]:
            with self.subTest(tag=tag, class_field=key):
                changed = deepcopy(original);changed[key] = ['invented-class'] if key == 'allowedModelClasses' else 'invented-class'
                self.assertTrue(list(Draft202012Validator(get_schema(tag)).iter_errors(changed)))

    def test_current_registry_capacity_keeps_other_bounds_and_rejects_excess(self):
        from jsonschema import Draft202012Validator
        from agent_lifecycle.contracts.schemas import get_schema
        from agent_lifecycle.contracts.scoped_usage_schemas import MAX_CURRENT_SOURCE_REGISTRY_BYTES
        self.assertEqual(1048576, MAX_CURRENT_SOURCE_REGISTRY_BYTES)
        validator = Draft202012Validator(get_schema(SOURCE_USAGE_RECEIPT))
        for size in (65537, 1048576):
            with self.subTest(case='current-reference-within-capacity', bytes=size):
                receipt = deepcopy(self.f.receipt)
                receipt['currentRegistryRef']['bytes'] = size
                validate_source_usage_receipt_shape(receipt)
                self.assertEqual([], list(validator.iter_errors(receipt)))
        for size in (1048577, True, 65537.5):
            with self.subTest(case='current-reference-excess-or-invalid-type', bytes=size):
                receipt = deepcopy(self.f.receipt)
                receipt['currentRegistryRef']['bytes'] = size
                self.denied(lambda: validate_source_usage_receipt_shape(receipt))
                self.assertTrue(list(validator.iter_errors(receipt)))
        for key in ('openingRef', 'sourceAuthoringRegistryRef'):
            with self.subTest(case='frozen-reference-keeps-64k-bound', ref=key):
                policy = deepcopy(self.f.policy)
                policy[key]['bytes'] = 65537
                self.denied(lambda: validate_source_usage_policy_shape(policy))
                self.assertTrue(list(Draft202012Validator(get_schema(SOURCE_USAGE_POLICY)).iter_errors(policy)))



class SourceRecoveryClosedShapeTests(unittest.TestCase):
    def test_recovery_policy_is_closed_bounded_and_cannot_claim_new_opening(self):
        from agent_lifecycle.contracts.scoped_usage_schemas import validate_source_recovery_policy_shape
        reference = {'path': 'tasks/opening.json', 'sha256': 'a' * 64, 'bytes': 10}
        value = {'schemaVersion': 'alk-source-usage-conflict-recovery-policy.v1',
                 'originalOpeningRef': reference, 'dispositionRef': dict(reference, path='tasks/disposition.json')}
        self.assertEqual(value, validate_source_recovery_policy_shape(value))
        for mutate in (lambda v:v.update(ignoreConflicts=True),
                       lambda v:v['originalOpeningRef'].update(bytes=65537),
                       lambda v:v['dispositionRef'].update(path='../outside'),
                       lambda v:v.update(schemaVersion='alk-source-usage-conflict-recovery-policy.v2')):
            with self.subTest(mutation=mutate.__code__.co_firstlineno):
                changed = deepcopy(value); mutate(changed)
                with self.assertRaises(LifecycleError):validate_source_recovery_policy_shape(changed)


class SourceRecoveryV2ClosedShapeTests(unittest.TestCase):
    def test_policy_v2_closed_sorted_unique_and_bounded(self):
        from agent_lifecycle.contracts.scoped_usage_schemas import validate_source_recovery_policy_shape
        ref = {'path': 'tasks/opening.json', 'sha256': 'a'*64, 'bytes': 10}
        value = {'schemaVersion': 'alk-source-usage-conflict-recovery-policy.v2',
                 'originalOpeningRef': ref, 'dispositionRefs': [dict(ref, path='tasks/a.json'), dict(ref, path='tasks/b.json')]}
        self.assertEqual(value, validate_source_recovery_policy_shape(value))
        maximum = deepcopy(value)
        maximum['dispositionRefs'] = [dict(ref, path='tasks/%02d.json'%i) for i in range(16)]
        self.assertEqual(maximum, validate_source_recovery_policy_shape(maximum))
        for mutate in (lambda v:v.update(ignoreConflicts=True),
                       lambda v:v.update(dispositionRef=ref),
                       lambda v:v.update(dispositionRefs=[]),
                       lambda v:v['dispositionRefs'].reverse(),
                       lambda v:v['dispositionRefs'].append(v['dispositionRefs'][0]),
                       lambda v:v.update(dispositionRefs=[dict(ref, path='tasks/%02d.json'%i) for i in range(17)]),
                       lambda v:v['dispositionRefs'][0].update(bytes=65537),
                       lambda v:v['dispositionRefs'][0].update(path='../outside')):
            with self.subTest(mutation=mutate.__code__.co_firstlineno):
                changed = deepcopy(value);mutate(changed)
                with self.assertRaises(LifecycleError):validate_source_recovery_policy_shape(changed)

    def test_disposition_v2_closed_nonempty_id_and_legacy_unchanged(self):
        from agent_lifecycle.contracts.scoped_usage_schemas import validate_source_conflict_disposition_shape
        reference = {'path': 'tasks/ref.json', 'sha256': 'a'*64, 'bytes': 10}
        value = {'schemaVersion': 'alk-source-window-conflict-disposition.v2', 'dispositionId': 'second-group',
                 'classification': 'HISTORICAL_INELIGIBLE', 'identityTuple': {'runId':'r', 'packageId':'p', 'taskId':'t', 'attempt':1, 'semanticOperationId':'second'},
                 'originalWindows': [{'windowId':'work/a', 'admissionRef':dict(reference,path='work/a/admission.json'), 'costRef':dict(reference,path='work/a/cost.json')},
                                     {'windowId':'work/b', 'admissionRef':dict(reference,path='work/b/admission.json'), 'costRef':dict(reference,path='work/b/cost.json')}],
                 **{k:reference for k in ['basisReviewRef','authorizingReviewRef','authorizingGrantRef','originalOpeningRef','authorizingFinancialHeadRef']}}
        self.assertEqual(value,validate_source_conflict_disposition_shape(value))
        legacy = deepcopy(value);legacy.update(schemaVersion='alk-source-window-conflict-disposition.v1',dispositionId='r605-r606-source-window-conflict')
        self.assertEqual(legacy,validate_source_conflict_disposition_shape(legacy))
        for mutate in (lambda v:v.update(dispositionId=''),lambda v:v.update(extra=True),
                       lambda v:v.update(classification='CURRENT_ELIGIBLE'),
                       lambda v:v['originalWindows'].append(v['originalWindows'][0]),
                       lambda v:v['identityTuple'].update(attempt=True),
                       lambda v:v.update(schemaVersion='alk-source-window-conflict-disposition.v1')):
            with self.subTest(mutation=mutate.__code__.co_firstlineno):
                changed=deepcopy(value);mutate(changed)
                with self.assertRaises(LifecycleError):validate_source_conflict_disposition_shape(changed)


class InvalidAnnotationClosedShapeTests(unittest.TestCase):
    def reference(self, path):
        return {'path': path, 'bytes': 1, 'sha256': 'a' * 64}

    def disposition(self):
        window = 'work/release-2-16/enforcement-decision/r401-fixture'
        value = {'schemaVersion': 'alk-source-invalid-annotation-disposition.v1',
            'dispositionId': 'local-only',
            'classification': 'FINANCIAL_HISTORY_ONLY_INVALID_SOURCE_ANNOTATION',
            'originalWindows': [{'windowId': window,
                'admissionRef': self.reference(window + '/admission.json'),
                'costRef': self.reference(window + '/cost.json'), 'originalBindingSha256': 'b' * 64}]}
        for key in ('originalOpeningRef', 'authorizingFinancialHeadRef', 'scopeDecisionRef',
                    'specificationRef', 'specificationSubjectRef', 'specificationReviewRef'):
            value[key] = self.reference('tasks/' + key + '.json')
        return value

    def test_v3_requires_exact_new_ref_and_preserves_closed_legacy_shapes(self):
        from copy import deepcopy
        from agent_lifecycle.contracts.scoped_usage_schemas import validate_source_recovery_policy_shape
        v2 = {'schemaVersion': 'alk-source-usage-conflict-recovery-policy.v2',
              'originalOpeningRef': self.reference('tasks/opening.json'),
              'dispositionRefs': [self.reference('tasks/conflict.json')]}
        original = deepcopy(v2)
        self.assertEqual(v2, validate_source_recovery_policy_shape(v2))
        v3 = {**v2, 'schemaVersion': 'alk-source-usage-conflict-recovery-policy.v3',
              'invalidAnnotationDispositionRef': self.reference('tasks/annotation.json')}
        self.assertEqual(v3, validate_source_recovery_policy_shape(v3))
        self.assertEqual(original, v2)
        for value in ({**v3, 'ignoreMalformed': True}, {**v2, 'invalidAnnotationDispositionRef': v3['invalidAnnotationDispositionRef']}):
            with self.subTest(value=value), self.assertRaises(LifecycleError):
                validate_source_recovery_policy_shape(value)
        missing = deepcopy(v3)
        missing.pop('invalidAnnotationDispositionRef')
        with self.assertRaises(LifecycleError):
            validate_source_recovery_policy_shape(missing)

    def test_exact_pair_identity_duplicates_bounds_and_extra_authority_refuse(self):
        from copy import deepcopy
        from agent_lifecycle.contracts.scoped_usage_schemas import validate_source_invalid_annotation_disposition_shape
        base = self.disposition()
        self.assertEqual(base, validate_source_invalid_annotation_disposition_shape(base))
        changes = []
        for field, new in [('path', 'tasks/swapped.json'), ('bytes', 131073)]:
            value = deepcopy(base)
            value['originalWindows'][0]['costRef'][field] = new
            changes.append(value)
        for rows in ([], base['originalWindows'] * 2, base['originalWindows'] * 4):
            changes.append({**deepcopy(base), 'originalWindows': rows})
        changes.extend([{**deepcopy(base), 'classification': 'ELIGIBLE'},
                        {**deepcopy(base), 'allowUnknownWindows': True}])
        for value in changes:
            with self.subTest(value=value), self.assertRaises(LifecycleError):
                validate_source_invalid_annotation_disposition_shape(value)

    def test_review_cannot_grant_execution_or_hide_applicable_findings(self):
        from copy import deepcopy
        from agent_lifecycle.contracts.scoped_usage_schemas import validate_source_invalid_annotation_review_shape
        base = {'schemaVersion': 'alk-source-recovery-contract-review.v1',
            'subjectDigest': 'a' * 64, 'reviewerId': 'independent-local', 'independent': True,
            'verdict': 'READY_TO_DRAFT', 'fullReview': True, 'findings': [], 'coverage': [],
            'reviewText': 'Synthetic fixture.', 'unverifiedEvidence': [], 'toolCalls': 0,
            'productImplementationApproved': False, 'nativeApproved': False,
            'taskAccepted': False, 'releaseReady': False}
        self.assertEqual(base, validate_source_invalid_annotation_review_shape(base))
        for key, value in [('reviewerId', '/root'), ('independent', False), ('fullReview', False),
                           ('toolCalls', False), ('toolCalls', 1), ('releaseReady', True),
                           ('productImplementationApproved', True), ('nativeApproved', True),
                           ('verdict', 'CHANGES_REQUIRED')]:
            with self.subTest(key=key, value=value), self.assertRaises(LifecycleError):
                validate_source_invalid_annotation_review_shape({**deepcopy(base), key: value})
        for severity in ('MEDIUM', 'HIGH'):
            value = {**deepcopy(base), 'findings': [{'id': 'local', 'severity': severity,
                'target': 'source', 'impact': 'unresolved', 'requiredEdit': 'fix'}]}
            with self.subTest(severity=severity), self.assertRaises(LifecycleError):
                validate_source_invalid_annotation_review_shape(value)

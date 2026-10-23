"""Source selection and pure risk decisions against frozen authority fixtures."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_lifecycle.accounting.source_usage_context import (
    load_source_usage_context, validate_source_usage_context,
)
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.policy.risk_execution import derive_risk_execution_profile
from tests.workflow.test_limited_usage import DeclaredFixture, put
from tests.workflow.test_task_transitions import _load_repo_json


class SourceUsageContextTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.fixture = DeclaredFixture(Path(tmp.name), with_full_task=True)
        self.context = self.load()

    def load(self, **overrides):
        f = self.fixture
        values = dict(repository_root=f.root, manifest=f.manifest, state=f.state,
                      task=f.task, adapter_id='codex', adapter_host='codex')
        values.update(overrides)
        return load_source_usage_context(**values)

    def risk(self, context):
        f = self.fixture
        return derive_risk_execution_profile(
            manifest=f.manifest, state=f.state, task_id='WS-01', adapter_id='codex',
            adapter_host='codex', operation_id='context-fixture', source_revision=f.revision,
            requested_risk='auto', source_usage_context=context,
            risk_policy=_load_repo_json('profiles/risk-execution-policy.v1.json'),
            routing_profile=_load_repo_json('profiles/model-routing-profile.v1.json'),
            baseline_profile=_load_repo_json('profiles/lifecycle-baselines.v1.json'),
            host_profile=_load_repo_json('profiles/hosts/codex-live-profile.v1.json'),
        )

    def validate(self, context, **overrides):
        f = self.fixture
        values = dict(manifest=f.manifest, state=f.state, task_id='WS-01',
                      adapter_id='codex', adapter_host='codex')
        values.update(overrides)
        return validate_source_usage_context(context, **values)

    def test_checked_context_is_immutable_and_risk_performs_no_source_reads(self):
        with self.assertRaises(FrozenInstanceError):
            self.context.runId = 'changed'
        with patch('agent_lifecycle.accounting.source_usage_context.read_authority_bytes',
                   side_effect=AssertionError('pure risk attempted a Source read')):
            result = self.risk(self.context)
        self.assertEqual(result['usageMode'], self.context.usageMode)
        self.assertEqual(result['sourceUsagePolicyDigest'], self.context.policyDigest)
        self.assertFalse(result['modelCallsStarted'])

    def test_missing_and_each_rebound_context_field_refuse(self):
        with self.assertRaises(LifecycleError):
            self.risk(None)
        changes = dict(manifestDigest='0'*64, stateDigest='0'*64, runId='other-run',
                       taskId='WS-02', adapterId='claude', adapterHost='claude-code',
                       policyDigest='0'*64, appliesToTask=False,
                       allowedModelClasses=('local-small',), usageMode='FULL')
        for field, value in changes.items():
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                self.validate(replace(self.context, **{field: value}))
        state = deepcopy(self.fixture.state)
        state['stateRevision'] += 1
        with self.assertRaises(LifecycleError):
            self.validate(self.context, state=state)

    def test_factory_refuses_manifest_task_adapter_and_unlisted_recovery(self):
        f = self.fixture
        manifest = deepcopy(f.manifest)
        manifest['planRevision'] += 1
        with self.assertRaises(LifecycleError):
            self.load(manifest=manifest)
        task = deepcopy(f.task)
        task['attempt'] += 1
        with self.assertRaises(LifecycleError):
            self.load(task=task)
        with self.assertRaises(LifecycleError):
            self.load(adapter_host='other-host')
        put(f.root, 'tasks/strategy/source-usage-conflict-recovery.json', {})
        with self.assertRaises(LifecycleError) as caught:
            self.load()
        self.assertEqual(caught.exception.code, 'plan-file-undeclared')

    def test_other_task_keeps_full_mode_without_claiming_limited_scope(self):
        f = self.fixture
        context = self.load(task=f.state['tasks'][1], adapter_id='claude', adapter_host='claude-code')
        self.assertFalse(context.appliesToTask)
        self.assertIs(self.validate(context, task_id='WS-02', adapter_id='claude',
                                    adapter_host='claude-code'), context)

    def test_exact_frozen_lock_and_opening_bytes_are_required(self):
        f = self.fixture
        opening = f.root / f.policy['openingRef']['path']
        opening.write_bytes(opening.read_bytes() + b' ')
        with self.assertRaises(LifecycleError):
            self.load()


if __name__ == '__main__':
    unittest.main()


class WorkflowUsageContextTests(unittest.TestCase):
    def test_public_factory_selects_typed_legacy_reader_and_mapping_compatibility(self):
        from agent_lifecycle.accounting.source_usage_context import load_frozen_usage_context
        from agent_lifecycle.accounting.usage_types import UsageContext

        with TemporaryDirectory() as directory:
            f = DeclaredFixture(Path(directory).resolve())
            context = load_frozen_usage_context(f.root, f.state)
            self.assertIsInstance(context, UsageContext)
            self.assertEqual(context.policy, context['policy'])
            self.assertEqual(context.policy_digest, context['policyDigest'])
            self.assertEqual(dict(context), context.inputs)
            with self.assertRaises(FrozenInstanceError):
                context.root = Path('another-root')
            # A same-process value never replaces the factory's actual frozen reads.
            f.manifest['planRevision'] += 1
            with self.assertRaises(LifecycleError):
                load_source_usage_context(f.root, f.manifest, f.state, f.task, 'codex', 'codex')

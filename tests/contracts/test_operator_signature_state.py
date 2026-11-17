"""Required-only version and native storage composition, independent of host keys."""

from __future__ import annotations

import unittest
from copy import deepcopy

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.operator_signature import require_operator_adoption
from agent_lifecycle.contracts.review_remedy_schemas import require_remedy_authority
from agent_lifecycle.contracts.workflow_state_schemas import (
    WORKFLOW_STATE_SCHEMAS,
    has_current_workflow_semantics,
    validate_workflow_state,
)
from agent_lifecycle.contracts.workflow_storage import prepare_storage
from agent_lifecycle.contracts.workflow_storage_schemas import uses_reference_storage
from agent_lifecycle.review_mesh.remediation import _require_artifact_kind
from tests.contracts.test_operator_signature import manifest, state
from tests.review_mesh.test_remediation import config


class OperatorSignatureStateTests(unittest.TestCase):
    def test_both_required_profiles_keep_distinct_authority_markers(self):
        value = state()
        value["reviewMesh"] = config()
        value["reviewRemedyAuthority"] = {
            "schemaVersion": "agent-review-remedy-authority.v1",
            "requiredPolicyDigest": value["reviewMesh"]["remedyProfile"]["policyDigest"],
            "stateSchemaVersion": "agent-workflow-state.v6",
        }
        self.assertIs(validate_workflow_state(value), value)
        require_remedy_authority(value, state=True)
        _require_artifact_kind("state", value, canonical_digest(value))
        compact = prepare_storage(value).state
        self.assertEqual(compact["reviewRemedyAuthority"], value["reviewRemedyAuthority"])
        self.assertEqual(compact["operatorSignatureAuthority"], value["operatorSignatureAuthority"])
        operator_only = state()
        with self.assertRaises(LifecycleError):
            _require_artifact_kind("state", operator_only, canonical_digest(operator_only))
        for field in ("reviewRemedyAuthority", "operatorSignatureAuthority"):
            invalid = deepcopy(value)
            invalid.pop(field)
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                validate_workflow_state(invalid)

    def test_required_v7_is_current_reference_storage_with_unchanged_policy(self):
        value = state()
        self.assertIs(validate_workflow_state(value), value)
        self.assertTrue(has_current_workflow_semantics(value))
        self.assertTrue(uses_reference_storage(value))
        compact = prepare_storage(value).state
        self.assertEqual(compact["schemaVersion"], "agent-workflow-state.v7")
        self.assertEqual(compact["operatorSignatureAuthority"], value["operatorSignatureAuthority"])
        self.assertEqual(compact["operatorSignaturePolicy"], value["operatorSignaturePolicy"])
        self.assertIn("agent-workflow-state.v7", WORKFLOW_STATE_SCHEMAS)

    def test_missing_marker_or_policy_refuses_at_actual_central_validator(self):
        for key in ("operatorSignatureAuthority", "operatorSignaturePolicy"):
            value = state()
            value.pop(key)
            with self.subTest(key=key), self.assertRaises(LifecycleError):
                validate_workflow_state(value)
        value = state()
        value["schemaVersion"] = "agent-workflow-state.v4"
        with self.assertRaises(LifecycleError):
            validate_workflow_state(value)

    def test_adoption_cannot_downgrade_replace_root_or_auto_authorize(self):
        current = state()
        require_operator_adoption(current, manifest(), start_mode="approval-required")
        for target in ({}, manifest("advisory")):
            with self.assertRaises(LifecycleError):
                require_operator_adoption(current, target, start_mode="approval-required")
        changed = manifest()
        changed["operatorSignaturePolicy"]["trustRoot"]["rootId"] = "changed"
        with self.assertRaises(LifecycleError):
            require_operator_adoption(current, changed, start_mode="approval-required")
        for mode in ("auto-after-freeze", "plan-only"):
            with self.subTest(mode=mode), self.assertRaises(LifecycleError):
                require_operator_adoption({}, manifest(), start_mode=mode)

    def test_ordinary_v4_record_is_unchanged_and_not_promoted(self):
        value = state("advisory")
        value.pop("operatorSignaturePolicy")
        value.pop("storage")
        before = deepcopy(value)
        validate_workflow_state(value)
        self.assertEqual(value, before)
        self.assertFalse(uses_reference_storage(value))


if __name__ == "__main__":
    unittest.main()

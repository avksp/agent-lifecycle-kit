"""Required authority envelopes and preserved legacy schema definitions."""

from __future__ import annotations

import unittest
from copy import deepcopy

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.plan_manifest_schemas import PLAN_MANIFEST_SCHEMAS
from agent_lifecycle.contracts.review_remedy_schemas import remedy_policy, require_remedy_authority
from agent_lifecycle.contracts.schemas import get_schema
from agent_lifecycle.contracts.workflow_state_schemas import has_current_workflow_semantics, validate_workflow_state
from agent_lifecycle.contracts.workflow_storage_schemas import uses_reference_storage
from tests.contracts.test_workflow_state_schemas import _state
from tests.review_mesh.test_remediation import config, policy


def authority(selected=None):
    selected = selected or policy()
    return {
        "schemaVersion": "agent-review-remedy-authority.v1",
        "requiredPolicyDigest": selected["policyDigest"],
        "stateSchemaVersion": "agent-workflow-state.v6",
    }


def required_state():
    state = _state()
    state.update(
        schemaVersion="agent-workflow-state.v6",
        reviewMesh=config(),
        reviewRemedyAuthority=authority(),
        storage={"schemaVersion": "agent-workflow-storage.v1", "root": "state.storage"},
    )
    for task in state["tasks"]:
        task["reviewMesh"] = deepcopy(state["reviewMesh"])
    return state


class ReviewRemedyAuthorityTests(unittest.TestCase):
    def test_task_cannot_erase_or_shadow_fallback_roles(self):
        state = required_state()
        run_config = state["reviewMesh"]
        run_config.pop("quorumPolicy")
        run_config["requiredRoles"] = ["quality", "reviewer"]
        for task in state["tasks"]:
            task["reviewMesh"] = deepcopy(run_config)
        self.assertIsNotNone(require_remedy_authority(state, state=True))
        for override in [
            {"requiredRoles": ["reviewer"]},
            {"quorumPolicy": {"requiredRoles": ["reviewer"], "minReviewers": 1}},
        ]:
            changed = deepcopy(state)
            changed["tasks"][0]["reviewMesh"].update(override)
            with self.assertRaises(LifecycleError):
                require_remedy_authority(changed, state=True)

    def test_task_cannot_lower_inherited_default_minimum(self):
        selected = policy(
            roles=[
                {"role": role, "modules": [], "paths": ["src/a.py"], "checkIds": ["AC-1"]}
                for role in ["quality", "reviewer"]
            ]
        )
        state = required_state()
        state["reviewMesh"] = config(selected)
        state["reviewRemedyAuthority"] = authority(selected)
        state["reviewMesh"].pop("quorumPolicy")
        state["reviewMesh"]["requiredRoles"] = ["quality", "reviewer"]
        for task in state["tasks"]:
            task["reviewMesh"] = deepcopy(state["reviewMesh"])
        self.assertIsNotNone(require_remedy_authority(state, state=True))
        changed = deepcopy(state)
        changed["tasks"][0]["reviewMesh"]["quorumPolicy"] = {
            "requiredRoles": ["quality", "reviewer"],
            "minReviewers": 1,
        }
        with self.assertRaises(LifecycleError):
            require_remedy_authority(changed, state=True)
        changed["tasks"][0]["reviewMesh"]["quorumPolicy"]["minReviewers"] = 2
        self.assertIsNotNone(require_remedy_authority(changed, state=True))

    def test_required_marker_has_exact_policy_binding(self):
        self.assertEqual(
            require_remedy_authority({"reviewMesh": config(), "reviewRemedyAuthority": authority()}), policy()
        )
        for marker in [
            None,
            {**authority(), "requiredPolicyDigest": "0" * 64},
            {**authority(), "extra": True},
            {**authority(), "stateSchemaVersion": "agent-workflow-state.v5"},
        ]:
            with self.assertRaises(LifecycleError):
                require_remedy_authority({"reviewMesh": config(), "reviewRemedyAuthority": marker})

    def test_off_and_advisory_omit_marker(self):
        self.assertIsNone(require_remedy_authority({}))
        self.assertIsNone(require_remedy_authority({"reviewMesh": config(policy(mode="advisory"))}))
        with self.assertRaises(LifecycleError):
            require_remedy_authority({"reviewRemedyAuthority": authority()})
        with self.assertRaises(LifecycleError):
            require_remedy_authority(
                {"reviewMesh": config(policy(mode="advisory")), "reviewRemedyAuthority": authority()}
            )

    def test_required_v6_uses_current_full_storage_semantics(self):
        state = required_state()
        self.assertTrue(uses_reference_storage(state))
        self.assertTrue(has_current_workflow_semantics(state))
        self.assertIs(validate_workflow_state(state), state)
        for version in ["agent-workflow-state.v3", "agent-workflow-state.v4", "agent-workflow-state.v5"]:
            old = deepcopy(state)
            old["schemaVersion"] = version
            with self.assertRaises(LifecycleError):
                validate_workflow_state(old)

    def test_v6_missing_policy_and_task_erasure_refuse(self):
        for mutate in [
            lambda x: x.pop("reviewMesh"),
            lambda x: x.pop("reviewRemedyAuthority"),
            lambda x: x["tasks"][0].update(reviewMesh={"required": False}),
            lambda x: x["tasks"][0]["reviewMesh"]["remedyProfile"].update(mode="advisory"),
        ]:
            state = required_state()
            mutate(state)
            with self.assertRaises(LifecycleError):
                validate_workflow_state(state)

    def test_required_phase_and_roles_cannot_escape_containing_gate(self):
        for value in [
            {**config(), "required": False},
            {**config(), "phases": ["freeze"]},
            {**config(), "quorumPolicy": {"requiredRoles": []}},
        ]:
            with self.assertRaises(LifecycleError):
                remedy_policy(value)

    def test_registry_exports_v6_and_marker_without_changing_legacy_ids(self):
        schema = get_schema("agent-workflow-state.v6")
        self.assertIn("reviewRemedyAuthority", schema["required"])
        self.assertFalse(get_schema("agent-review-remedy-authority.v1")["additionalProperties"])
        self.assertIn("reviewRemedyAuthority", PLAN_MANIFEST_SCHEMAS["agent-plan-manifest.v1"]["properties"])
        for version in ("v4", "v5"):
            old = get_schema("agent-workflow-state." + version)
            self.assertNotIn("reviewRemedyAuthority", old["properties"])
            self.assertEqual(old["properties"]["schemaVersion"]["const"], "agent-workflow-state." + version)
            self.assertEqual(len(canonical_digest(old)), 64)

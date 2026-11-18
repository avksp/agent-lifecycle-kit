"""Native reviewer state version gating and explicitly preserved default state."""

from __future__ import annotations

from copy import deepcopy
from unittest import TestCase

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.reviewer_identity_schemas import (
    REVIEWER_REQUIRED_STATE,
    reviewer_attestation_authority,
)
from agent_lifecycle.contracts.workflow_state_schemas import validate_workflow_state
from tests.contracts.test_operator_signature import state
from tests.review.test_reviewer_attestation_strict import policy_for


class ReviewerStateCompatibilityTests(TestCase):
    def test_operator_only_state_keeps_v7_and_default_keeps_v4(self) -> None:
        original = state()
        self.assertIs(validate_workflow_state(original), original)
        self.assertEqual(original["schemaVersion"], "agent-workflow-state.v7")
        default = state("advisory")
        default.pop("operatorSignaturePolicy")
        default.pop("storage")
        self.assertIs(validate_workflow_state(default), default)
        self.assertEqual(default["schemaVersion"], "agent-workflow-state.v4")
        self.assertNotIn("reviewerAttestationAuthority", default)

    def test_required_reviewer_state_requires_marker_and_refuses_legacy_tag(self) -> None:
        policy = policy_for("freeze")
        combined = state()
        combined.update(
            schemaVersion=REVIEWER_REQUIRED_STATE,
            reviewerAttestationPolicy=policy,
            reviewerAttestationAuthority=reviewer_attestation_authority(policy),
        )
        self.assertIs(validate_workflow_state(combined), combined)
        downgrade = {**combined, "schemaVersion": "agent-workflow-state.v7"}
        with self.assertRaisesRegex(LifecycleError, "native v8 must occur together"):
            validate_workflow_state(downgrade)
        for missing in ("reviewerAttestationAuthority", "reviewerAttestationPolicy"):
            broken = deepcopy(combined)
            broken.pop(missing)
            with self.assertRaises(LifecycleError):
                validate_workflow_state(broken)

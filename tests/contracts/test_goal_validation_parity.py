"""Keep the public goal routes on one validation contract."""

from __future__ import annotations

import copy
import unittest

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.goal_validation import validate_goal_record
from agent_lifecycle.goal import validate_goal_record as public_validate
from agent_lifecycle.goal.records import validate_goal_record as legacy_validate


class GoalValidationParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = {
            "runId": "run", "packageId": "package", "planRevision": 1,
            "planDigest": "a" * 64, "sourceRevision": "source", "stateRevision": 3,
        }
        self.record = {
            "schemaVersion": "agent-goal-record.v1", "goalId": "goal",
            "userIntent": "Keep compatibility", "ownerOutcome": "Stable results",
            "status": "ACTIVE", "constraints": ["Keep history"],
            "evidenceIds": [], "lineage": dict(self.state),
        }

    def test_public_and_legacy_routes_share_authoritative_validator(self) -> None:
        self.assertIs(public_validate, validate_goal_record)
        self.assertIs(legacy_validate, validate_goal_record)
        expected = {
            "schemaVersion": "agent-goal-record-validation.v1", "status": "PASS",
            "goalId": "goal", "goalStatus": "ACTIVE", "lineage": self.state,
            "stateRevision": 3, "constraintCount": 1, "evidenceIds": [],
            "completionCheck": None, "goalDigest": canonical_digest(self.record),
        }
        original = copy.deepcopy(self.record)
        for validate in (validate_goal_record, public_validate, legacy_validate):
            self.assertEqual(validate(self.record, state=self.state, require_current=True), expected)
        self.assertEqual(self.record, original)

    def test_errors_and_stale_details_are_compatible(self) -> None:
        cases = [
            ({**self.record, "constraints": []}, "invalid-goal-record", {}),
            ({**self.record, "status": "DONE"}, "invalid-goal-record", {}),
            ({**self.record, "lineage": {**self.state, "runId": "other"}}, "goal-lineage-mismatch", {}),
            (
                {**self.record, "lineage": {**self.state, "stateRevision": 2}},
                "goal-state-stale", {"goalStateRevision": 2, "stateRevision": 3},
            ),
        ]
        for record, code, details in cases:
            for validate in (validate_goal_record, public_validate, legacy_validate):
                with self.subTest(code=code, validator=validate.__module__):
                    with self.assertRaises(LifecycleError) as raised:
                        validate(record, state=self.state, require_current=True)
                    self.assertEqual(raised.exception.code, code)
                    self.assertEqual(raised.exception.details, details)


if __name__ == "__main__":
    unittest.main()

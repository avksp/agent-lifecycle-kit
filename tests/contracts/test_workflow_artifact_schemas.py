from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema


class WorkflowArtifactSchemaTests(unittest.TestCase):
    def test_freshness_and_attempt_history_schemas_are_registered(self) -> None:
        change_set = get_schema("agent-task-change-set-evidence.v1")
        claim = get_schema("agent-task-change-set-claim.v1")
        history = get_schema("agent-task-attempt-history-entry.v1")

        self.assertEqual(change_set["properties"]["provider"]["const"], "git-worktree-v2")
        self.assertEqual(claim["properties"]["provider"]["const"], "git-worktree-v2")
        self.assertEqual(history["properties"]["attempt"]["minimum"], 1)


if __name__ == "__main__":
    unittest.main()

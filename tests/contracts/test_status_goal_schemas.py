from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class StatusGoalSchemaTests(unittest.TestCase):
    def test_progress_watch_and_change_summary_schemas_are_registered(self) -> None:
        schema_ids = {item["id"] for item in list_schemas()["schemas"]}

        self.assertIn("agent-lifecycle-progress-watch.v1", schema_ids)
        self.assertIn("agent-change-summary-receipt.v1", schema_ids)

    def test_progress_and_change_summary_outputs_are_read_only(self) -> None:
        progress_watch = get_schema("agent-lifecycle-progress-watch.v1")
        change_summary = get_schema("agent-change-summary-receipt.v1")

        self.assertEqual(progress_watch["properties"]["readOnly"], {"const": True})
        self.assertEqual(progress_watch["properties"]["modelCallsStarted"], {"const": False})
        self.assertEqual(progress_watch["properties"]["tokenSpendForProgress"], {"const": False})
        self.assertEqual(change_summary["properties"]["readOnly"], {"const": True})
        self.assertEqual(change_summary["properties"]["modelCallsStarted"], {"const": False})


if __name__ == "__main__":
    unittest.main()

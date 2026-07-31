from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.reporting import render_usage_export_json, render_usage_export_table  # noqa: E402


class UsageExportReportingTests(unittest.TestCase):
    def test_json_renderer_is_deterministic(self) -> None:
        export = _export()

        first = render_usage_export_json(export)
        second = render_usage_export_json(export)

        self.assertEqual(first, second)
        self.assertEqual(json.loads(first)["schemaVersion"], "agent-usage-export.v1")

    def test_table_renderer_contains_usage_columns(self) -> None:
        table = render_usage_export_table(_export())

        self.assertIn("entry", table)
        self.assertIn("total", table)
        self.assertIn("host-reported:null", table)
        self.assertNotIn("{", table)


def _export() -> dict:
    return {
        "schemaVersion": "agent-usage-export.v1",
        "entries": [
            {
                "entryId": "usage-1",
                "adapterId": "metered-host",
                "taskId": "WS-01",
                "operationId": "op",
                "tokens": {"input": 10, "output": 5, "total": 15},
                "steps": 1,
                "durationMs": 50,
                "budgetDecision": {"action": "continue"},
                "monetary": {"hostReported": True, "currency": "USD", "cost_usd": None, "canonical": False},
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()

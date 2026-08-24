from __future__ import annotations

import unittest
from datetime import UTC, datetime

from agent_lifecycle.reporting.attention import build_attention_projection, build_multi_run_overlap


class AttentionProjectionTests(unittest.TestCase):
    def test_unavailable_source_is_high_attention_and_overlap_is_advisory(self) -> None:
        sources = [
            {
                "sourceId": "run-a",
                "runId": "run-a",
                "status": "FAIL",
                "rootPath": "work/run-a",
                "summary": {},
                "blockers": [{"code": "invalid-json", "message": "source is invalid"}],
            },
            {
                "sourceId": "run-b",
                "runId": "run-b",
                "status": "PASS",
                "rootPath": "work/run-b",
                "summary": {
                    "packageId": "p-b",
                    "planRevision": 2,
                    "planDigest": "2" * 64,
                    "sourceRevision": "source-b",
                    "stateRevision": 4,
                    "phase": "COMPLETE",
                    "tasks": [],
                },
                "ownershipPaths": ["src/shared.py"],
                "blockers": [],
            },
            {
                "sourceId": "run-c",
                "runId": "run-c",
                "status": "PASS",
                "rootPath": "work/run-c",
                "summary": {
                    "packageId": "p-c",
                    "planRevision": 3,
                    "planDigest": "3" * 64,
                    "sourceRevision": "source-c",
                    "stateRevision": 5,
                    "phase": "RUNNING",
                    "tasks": [],
                },
                "ownershipPaths": ["src/shared.py"],
                "blockers": [],
            },
        ]
        items = build_attention_projection(sources, now=datetime(2026, 8, 25, tzinfo=UTC))
        overlaps = build_multi_run_overlap(sources)

        self.assertEqual(items[0]["reasonCode"], "SOURCE_UNAVAILABLE")
        self.assertEqual(items[0]["severity"], "HIGH")
        self.assertEqual(overlaps[0]["runIds"], ["run-b", "run-c"])
        self.assertTrue(overlaps[0]["authorityRetained"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.adapter_sessions.planning_launch import (  # noqa: E402
    build_planning_envelope,
    parse_planning_result,
    run_planning_launch,
)
from agent_lifecycle.contracts.schemas import get_schema  # noqa: E402


class PlanningLaunchContractTests(unittest.TestCase):
    def test_public_contracts_are_registered(self) -> None:
        for schema_id in (
            "agent-planning-launch-envelope.v1",
            "agent-planning-result.v1",
            "agent-planning-launch-receipt.v1",
            "agent-planning-session-state.v1",
        ):
            self.assertEqual(get_schema(schema_id)["$id"], schema_id)

    def test_envelope_labels_raw_task_as_untrusted_and_planning_only(self) -> None:
        envelope = build_planning_envelope(
            adapter_id="codex",
            session_id="session-1",
            requested_mode="plan",
            task_text="inspect the repository",
            input_source="text",
        )

        self.assertEqual(envelope["task"]["untrustedText"], "inspect the repository")
        self.assertTrue(envelope["authority"]["planningOnly"])
        self.assertFalse(envelope["authority"]["implementationAuthorized"])

    def test_successful_launch_returns_review_required_without_raw_task(self) -> None:
        raw_task = "private customer task"
        result = {
            "schemaVersion": "agent-planning-result.v1",
            "status": "REVIEW_REQUIRED",
            "summary": "A bounded plan candidate",
            "requirements": [{"id": "R1", "statement": "Inspect inputs"}],
            "workstreams": [{"id": "WS1", "goal": "Research"}],
            "evidenceRoutes": [{"id": "EV1", "route": "tests"}],
            "implementationAuthorized": False,
            "productionPromotionClaimed": False,
        }
        command = [sys.executable, "-c", f"print({json.dumps(json.dumps(result))})"]

        receipt = run_planning_launch(
            adapter_id="codex",
            session_id="session-1",
            requested_mode="plan",
            task_text=raw_task,
            input_source="text",
            argv=command,
            env=dict(os.environ),
        )

        self.assertEqual(receipt["status"], "REVIEW_REQUIRED")
        self.assertFalse(receipt["implementationAuthorized"])
        self.assertTrue(receipt["requiresReview"])
        self.assertNotIn(raw_task, json.dumps(receipt))
        self.assertEqual(receipt["usageEvidence"]["confidence"], "MISSING")

    def test_authority_claim_is_rejected(self) -> None:
        payload = {
            "schemaVersion": "agent-planning-result.v1",
            "status": "REVIEW_REQUIRED",
            "summary": "bad",
            "requirements": ["R"],
            "workstreams": [{"id": "WS"}],
            "evidenceRoutes": [{"id": "EV"}],
            "implementationAuthorized": True,
            "productionPromotionClaimed": False,
        }

        result, blockers = parse_planning_result(json.dumps(payload))

        self.assertIsNone(result)
        self.assertIn("planning-result-authority-claim", {item["code"] for item in blockers})


if __name__ == "__main__":
    unittest.main()

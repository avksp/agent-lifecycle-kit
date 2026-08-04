from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.reporting import (
    build_progress_bridge_config,
    build_progress_bridge_receipt,
    render_progress_bridge_terminal,
)


class ProgressBridgeTests(unittest.TestCase):
    def test_bridge_receipt_is_read_only_and_renders_terminal_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = _write_state(root)
            before = state.read_bytes()

            receipt = build_progress_bridge_receipt(
                adapter_id="codex",
                support_level="WATCH",
                hook_point="side-terminal-watch",
                state_path=state,
            )
            rendered = render_progress_bridge_terminal(receipt)
            after = state.read_bytes()

        self.assertEqual(receipt["schemaVersion"], "agent-progress-bridge-receipt.v1")
        self.assertTrue(receipt["readOnly"])
        self.assertFalse(receipt["modelCallsStarted"])
        self.assertFalse(receipt["stateWritten"])
        self.assertFalse(receipt["tokenSpendForProgress"])
        self.assertFalse(receipt["hostTelemetryParsedInCore"])
        self.assertIn("RUNNING", rendered)
        self.assertIn("↑?/↓? tok", rendered)
        self.assertEqual(before, after)

    def test_bridge_config_declares_adapter_support_without_maturity_claim(self) -> None:
        config = build_progress_bridge_config(
            adapter_id="goose",
            support_level="MANUAL",
            hook_points=["manual"],
        )

        self.assertEqual(config["schemaVersion"], "agent-progress-bridge-config.v1")
        self.assertEqual(config["supportLevel"], "MANUAL")
        self.assertFalse(config["productionPromotionClaimed"])
        self.assertFalse(config["hostTelemetryParsedInCore"])


def _write_state(root: Path) -> Path:
    state = root / "state.json"
    state.write_text(
        json.dumps(
            {
                "schemaVersion": "agent-workflow-state.v3",
                "runId": "run-1",
                "packageId": "package",
                "planRevision": 1,
                "planDigest": "0" * 64,
                "sourceRevision": "main",
                "stateRevision": 1,
                "phase": "RUNNING",
                "authorization": {"mode": "approval-required"},
                "budgets": {},
                "tasks": [],
            }
        ),
        encoding="utf-8",
    )
    return state


if __name__ == "__main__":
    unittest.main()

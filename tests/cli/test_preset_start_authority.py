from __future__ import annotations

import contextlib
import io
import json
import unittest

from agent_lifecycle.cli import main


class PresetStartAuthorityTests(unittest.TestCase):
    def test_start_preset_is_draft_only_without_launch(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(
                [
                    "start",
                    "--adapter",
                    "codex",
                    "--preset",
                    "research-review",
                    "--text",
                    "Review this research question",
                ]
            )
        receipt = json.loads(output.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(receipt["schemaVersion"], "agent-guided-action-receipt.v1")
        self.assertEqual(receipt["effectiveProfile"]["defaultMode"], "research")
        self.assertEqual(receipt["effectiveProfile"]["defaultRisk"], "S1")
        self.assertFalse(receipt["modelCallsStarted"])
        self.assertFalse(receipt["startReceipt"]["hostLaunchStarted"])


if __name__ == "__main__":
    unittest.main()

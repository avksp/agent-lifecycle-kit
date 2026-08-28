from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.release.validate_workflow_transition_contract import validate_transition_contract

ROOT = Path(__file__).resolve().parents[2]


class WorkflowTransitionValidatorTests(unittest.TestCase):
    def test_live_catalog_and_consumers_pass(self) -> None:
        result = validate_transition_contract(ROOT / "src" / "agent_lifecycle")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["blockers"], [])
        self.assertGreater(result["removedRunnerCommandCount"], 0)
        self.assertIn(
            "src/agent_lifecycle/workflow/continuation.py",
            {item["path"] for item in result["sourceChecks"]},
        )

    def test_missing_consumer_is_blocking(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "tools.release.validate_workflow_transition_contract.CONSUMERS",
                {"src/agent_lifecycle/missing.py": "transition_contract"},
            ),
        ):
            result = validate_transition_contract(Path(tmp))
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("transition-consumer-missing", {item["code"] for item in result["blockers"]})


if __name__ == "__main__":
    unittest.main()

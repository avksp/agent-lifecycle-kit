from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.cli.main import main


class WorkflowStateCommandTests(unittest.TestCase):
    def test_workflow_init_cli_creates_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "run.state.json"
            result = main(
                [
                    "workflow",
                    "init",
                    "--state",
                    str(state),
                    "--run-id",
                    "run",
                    "--package-id",
                    "package",
                ]
            )
            self.assertEqual(result, 0)
            self.assertTrue(state.exists())


if __name__ == "__main__":
    unittest.main()

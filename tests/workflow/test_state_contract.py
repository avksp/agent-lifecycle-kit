from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.workflow import initialize_workflow_state, status


class WorkflowStateContractTests(unittest.TestCase):
    def test_init_creates_unbound_private_v4_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "run.state.json"
            payload = initialize_workflow_state(state_path, run_id="run", package_id="package")
            self.assertEqual(payload["phase"], "AWAITING_AUTHORIZATION")
            self.assertEqual(status(state_path)["schemaVersion"], "agent-workflow-status.v1")
            with self.assertRaises(FileExistsError):
                initialize_workflow_state(state_path, run_id="run", package_id="package")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.cli.main import main
from agent_lifecycle.workflow import initialize_workflow_state


class WorkflowStateCommandTests(unittest.TestCase):
    def test_explicit_v5_target_uses_native_migration_and_default_init_stays_v4(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            initialize_workflow_state(state, run_id="run", package_id="package")
            value = json.loads(state.read_bytes())
            self.assertEqual(value["schemaVersion"], "agent-workflow-state.v4")
            value["sourceRevision"] = "source"
            state.write_text(json.dumps(value), encoding="utf-8")
            result = main(
                [
                    "workflow",
                    "state-migrate",
                    "--state",
                    str(state),
                    "--operation-id",
                    "migrate",
                    "--expected-revision",
                    "1",
                    "--source-revision",
                    "source",
                    "--target-schema",
                    "agent-workflow-state.v5",
                ]
            )
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(state.read_bytes())["schemaVersion"], "agent-workflow-state.v5")

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

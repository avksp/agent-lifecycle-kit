from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.workflow import start_task

from .helpers import _write_state


class TaskTransitionAuthorityTests(unittest.TestCase):
    def test_start_task_rejects_pseudo_glob_before_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["writes"] = ["src/**"]
            state_path.write_text(json.dumps(state), encoding="utf-8")
            before = state_path.read_bytes()

            with self.assertRaises(LifecycleError) as raised:
                start_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="start-invalid-authority",
                    expected_revision=1,
                    source_revision="source",
                    reason="test",
                )

            self.assertEqual(raised.exception.code, "invalid-authority-path")
            self.assertEqual(state_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

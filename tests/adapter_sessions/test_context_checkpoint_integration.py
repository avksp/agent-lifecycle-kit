from __future__ import annotations

import unittest

from agent_lifecycle.adapter_sessions.session_store import create_session, load_session


class AdapterContextCheckpointIntegrationTests(unittest.TestCase):
    def test_session_state_can_carry_checkpoint_policy_without_native_reattach(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = create_session(
                adapter_id="adapter-1",
                mode="MANAGED_TASK",
                status="READY",
                launch_profile={"status": "WRAPPER_ONLY"},
                session_root=root,
                context_checkpoint_policy={
                    "enabled": True,
                    "required": False,
                    "milestoneEvents": ["task-completed"],
                },
            )
            restored = load_session(session["sessionId"], session_root=root)
            self.assertEqual(restored["contextCheckpointPolicy"]["milestoneEvents"], ["task-completed"])
            self.assertFalse(restored.get("nativeConfigWritten"))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.context.checkpoint_store import (
    list_context_checkpoints,
    restore_context_checkpoint,
    write_context_checkpoint,
)
from agent_lifecycle.context.checkpoints import build_context_checkpoint
from agent_lifecycle.contracts import LifecycleError


def _checkpoint(revision: int, *, created_at: str | None = None):
    return build_context_checkpoint(
        session_id="session-1",
        run_id="run-1",
        adapter_id="adapter-1",
        package_id="package-1",
        plan_revision=1,
        plan_digest="a" * 64,
        state_revision=revision,
        source_revision="main@abc",
        capture_mode="MILESTONE",
        reason="milestone",
        summary={"nextRequiredAction": f"step-{revision}"},
        created_at=created_at or f"2026-08-13T12:00:{revision:02d}Z",
    )


class ContextCheckpointStoreTests(unittest.TestCase):
    def test_store_is_idempotent_and_retains_latest_bounded_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = _checkpoint(1)
            self.assertTrue(write_context_checkpoint(first, root=root, max_checkpoints_per_run=2)["created"])
            self.assertFalse(write_context_checkpoint(first, root=root, max_checkpoints_per_run=2)["created"])
            write_context_checkpoint(_checkpoint(2), root=root, max_checkpoints_per_run=2)
            write_context_checkpoint(_checkpoint(3), root=root, max_checkpoints_per_run=2)
            stored = list_context_checkpoints(root=root, run_id="run-1")
            self.assertEqual([item["stateRevision"] for item in stored], [2, 3])

    @unittest.skipUnless(os.name != "nt", "POSIX mode contract only")
    def test_checkpoint_directory_and_file_are_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkpoints"
            old_umask = os.umask(0)
            try:
                result = write_context_checkpoint(_checkpoint(1), root=root)
            finally:
                os.umask(old_umask)
            path = Path(result["path"])
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_store_rejects_conflicting_reuse_and_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint = _checkpoint(1)
            write_context_checkpoint(checkpoint, root=root)
            altered = dict(checkpoint)
            altered["summary"] = {"nextRequiredAction": "different"}
            with self.assertRaises(LifecycleError):
                write_context_checkpoint(altered, root=root)

    def test_restore_requires_current_lineage_and_keeps_authority_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint = _checkpoint(1)
            result = write_context_checkpoint(checkpoint, root=root)
            continuation = restore_context_checkpoint(
                Path(result["path"]),
                state={
                    "runId": "run-1",
                    "packageId": "package-1",
                    "planRevision": 1,
                    "planDigest": "a" * 64,
                    "stateRevision": 1,
                    "sourceRevision": "main@abc",
                },
                session_id="session-1",
            )
            self.assertEqual(continuation["status"], "PASS")
            self.assertFalse(continuation["implementationAuthorized"])
            self.assertEqual(continuation["proofAuthority"], "none")

            stale = restore_context_checkpoint(
                Path(result["path"]),
                state={
                    "runId": "run-1",
                    "packageId": "package-1",
                    "planRevision": 1,
                    "planDigest": "a" * 64,
                    "stateRevision": 2,
                    "sourceRevision": "main@abc",
                },
                session_id="session-1",
            )
            self.assertEqual(stale["status"], "BLOCKED")

    def test_store_retains_normalized_public_locator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint = _checkpoint(1)
            checkpoint["summary"]["citation"] = "HTTPS://EXAMPLE.COM:443/store#Context"
            checkpoint = build_context_checkpoint(
                session_id=checkpoint["sessionId"],
                run_id=checkpoint["runId"],
                adapter_id=checkpoint["adapterId"],
                package_id=checkpoint["packageId"],
                plan_revision=checkpoint["planRevision"],
                plan_digest=checkpoint["planDigest"],
                state_revision=checkpoint["stateRevision"],
                source_revision=checkpoint["sourceRevision"],
                capture_mode=checkpoint["captureMode"],
                reason=checkpoint["reason"],
                summary=checkpoint["summary"],
                created_at=checkpoint["createdAt"],
            )

            write_context_checkpoint(checkpoint, root=root)
            stored = list_context_checkpoints(root=root, run_id="run-1")

            self.assertEqual(stored[0]["summary"]["citation"], "https://example.com/store#Context")


if __name__ == "__main__":
    unittest.main()

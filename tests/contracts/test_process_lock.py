"""Observable local-process exclusion and crash/exception recovery."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.process_lock import exclusive_process_lock


class ProcessLockTests(unittest.TestCase):
    def test_live_holder_cannot_be_stolen_by_age_and_crash_releases_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "operation.lock"
            ready = Path(tmp) / "ready"
            script = (
                "import sys,time; from pathlib import Path; "
                "from agent_lifecycle.contracts.process_lock import exclusive_process_lock; "
                "lock=exclusive_process_lock(Path(sys.argv[1])); lock.__enter__(); "
                "Path(sys.argv[2]).touch(); time.sleep(30)"
            )
            child = subprocess.Popen([sys.executable, "-B", "-c", script, str(path), str(ready)])
            try:
                deadline = time.monotonic() + 10
                while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists(), "child did not acquire its lock")
                os.utime(path, (1, 1))
                with self.assertRaises(LifecycleError) as caught, exclusive_process_lock(path, timeout_seconds=0.05):
                    self.fail("a live lock was stolen")
                self.assertEqual(caught.exception.code, "process-lock-timeout")
            finally:
                child.terminate()
                child.wait(timeout=10)
            with exclusive_process_lock(path, timeout_seconds=1):
                self.assertTrue(path.is_file())
                self.assertEqual(path.read_bytes(), b"")

    def test_exception_releases_lock_without_replacing_its_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "operation.lock"
            with self.assertRaisesRegex(RuntimeError, "business failure"), exclusive_process_lock(path):
                identity = path.stat().st_dev, path.stat().st_ino
                raise RuntimeError("business failure")
            with exclusive_process_lock(path, timeout_seconds=0):
                self.assertEqual((path.stat().st_dev, path.stat().st_ino), identity)

    def test_invalid_timeout_does_not_create_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "absent" / "operation.lock"
            for timeout in (-1, True, float("inf"), float("nan")):
                with self.subTest(timeout=timeout), self.assertRaises(LifecycleError) as caught:
                    with exclusive_process_lock(path, timeout_seconds=timeout):
                        self.fail("invalid timeout acquired a lock")
                self.assertEqual(caught.exception.code, "process-lock-timeout-invalid")
                self.assertFalse(path.parent.exists())

    def test_hardlinked_lock_is_not_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / "original"
            original.touch(mode=0o600)
            path = Path(tmp) / "operation.lock"
            os.link(original, path)
            with self.assertRaises(LifecycleError) as caught, exclusive_process_lock(path):
                self.fail("hardlinked lock was accepted")
            self.assertEqual(caught.exception.code, "process-lock-unsafe")
            self.assertEqual(original.read_bytes(), b"")

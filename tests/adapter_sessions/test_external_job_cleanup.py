from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.external_jobs import (
    load_external_job_attempt,
    request_external_job_cancel,
    run_external_job,
)
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.external_job_schemas import build_external_job_request


def _request(
    job_id: str,
    *,
    parent: dict[str, Any] | None = None,
    max_wall_seconds: int = 10,
    cancel_grace_seconds: int = 1,
) -> dict[str, Any]:
    return build_external_job_request(
        job_id=job_id,
        attempt=1,
        adapter_id="synthetic-adapter",
        operation="incident-reproduction",
        execution_kind="PROCESS",
        descriptor_digest="5" * 64,
        plan_digest="6" * 64,
        plan_lock_digest="7" * 64,
        source_revision="source-revision",
        source_snapshot_digest="8" * 64,
        limits={
            "maxWallSeconds": max_wall_seconds,
            "maxAttempts": 2,
            "maxOutputBytes": 8192,
            "maxArtifactBytes": 8192,
            "maxArtifacts": 4,
            "maxCostMicros": 1000,
            "maxReportedTokens": 1000,
            "cancelGraceSeconds": cancel_grace_seconds,
        },
        parent_job_id=parent["jobId"] if parent else None,
        parent_attempt=parent["attempt"] if parent else None,
        parent_request_digest=parent["requestDigest"] if parent else None,
    )


def _wait_for_state(request: dict[str, Any], root: Path, state: str) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            if load_external_job_attempt(request, job_root=root)["jobStatus"]["state"] == state:
                return
        except LifecycleError:
            pass
        time.sleep(0.02)
    raise AssertionError(f"job did not reach {state}")


class ExternalJobCleanupTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "process-group incident fixture uses POSIX sessions")
    def test_addressed_cancel_terminates_descendants_without_mixed_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "jobs"
            request = _request("cancelled-wrapper")
            script = (
                "import os,pathlib,subprocess,sys,time; "
                "p=pathlib.Path(os.environ['ALK_EXTERNAL_JOB_ARTIFACT_DIR'])/'child.txt'; "
                "code=\"import pathlib,time; p=pathlib.Path(%r); time.sleep(.4); p.write_text('late',encoding='utf-8'); time.sleep(30)\" % str(p); "
                "subprocess.Popen([sys.executable,'-c',code]); time.sleep(30)"
            )
            holder: dict[str, Any] = {}
            worker = threading.Thread(
                target=lambda: holder.setdefault(
                    "view",
                    run_external_job(request, [sys.executable, "-c", script], env=dict(os.environ), job_root=root),
                )
            )
            worker.start()
            _wait_for_state(request, root, "RUNNING")
            first = request_external_job_cancel(request, job_root=root)
            second = request_external_job_cancel(request, job_root=root)
            worker.join(timeout=8)

            self.assertFalse(worker.is_alive())
            self.assertEqual(first["status"], "PASS")
            self.assertTrue(second["idempotent"])
            view = holder["view"]
            self.assertEqual(view["result"]["state"], "CANCELLED")
            self.assertEqual(view["jobStatus"]["processCleanupStatus"], "PASS")
            self.assertFalse(view["jobStatus"]["postTerminalWriteDetected"])
            self.assertFalse((root / "cancelled-wrapper/attempt-1/artifacts/child.txt").exists())

    def test_late_cancel_persists_terminal_state_within_wall_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "jobs"
            request = _request("late-cancel", max_wall_seconds=1, cancel_grace_seconds=0)
            holder: dict[str, Any] = {}
            worker = threading.Thread(
                target=lambda: holder.setdefault(
                    "view",
                    run_external_job(
                        request,
                        [sys.executable, "-c", "import time; time.sleep(10)"],
                        env=dict(os.environ),
                        job_root=root,
                    ),
                )
            )
            worker.start()
            _wait_for_state(request, root, "RUNNING")
            time.sleep(0.7)
            cancel = request_external_job_cancel(request, job_root=root)
            worker.join(timeout=5)

            self.assertFalse(worker.is_alive())
            self.assertEqual(cancel["status"], "PASS")
            self.assertEqual(holder["view"]["result"]["state"], "CANCELLED")
            self.assertLessEqual(holder["view"]["result"]["usage"]["wallMilliseconds"], 1000)
            loaded = load_external_job_attempt(request, job_root=root)
            self.assertEqual(loaded["result"]["state"], "CANCELLED")

    def test_terminal_parent_cancels_declared_live_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "jobs"
            parent = _request("parent-job")
            child = _request("child-job", parent=parent)
            holder: dict[str, Any] = {}
            child_worker = threading.Thread(
                target=lambda: holder.setdefault(
                    "child",
                    run_external_job(
                        child,
                        [sys.executable, "-c", "import time; time.sleep(30)"],
                        env=dict(os.environ),
                        job_root=root,
                    ),
                )
            )
            child_worker.start()
            _wait_for_state(child, root, "RUNNING")
            parent_view = run_external_job(
                parent,
                [sys.executable, "-c", "pass"],
                env=dict(os.environ),
                job_root=root,
                child_requests=[child],
            )
            child_worker.join(timeout=8)

            self.assertFalse(child_worker.is_alive())
            self.assertEqual(holder["child"]["result"]["state"], "CANCELLED")
            self.assertEqual(parent_view["result"]["state"], "SUCCEEDED")
            self.assertEqual(parent_view["transitionValidation"]["status"], "PASS")

    def test_post_terminal_artifact_write_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "jobs"
            request = _request("late-write-job")

            def fake_runner(_argv: list[str], **kwargs: Any) -> dict[str, Any]:
                artifact_root = Path(kwargs["env"]["ALK_EXTERNAL_JOB_ARTIFACT_DIR"])
                late_path = artifact_root / "late.txt"
                late_path.write_text("same bytes", encoding="utf-8")
                threading.Thread(
                    target=lambda: (time.sleep(0.03), late_path.write_text("same bytes", encoding="utf-8")),
                    daemon=True,
                ).start()
                return {
                    "status": "PASS",
                    "timedOut": False,
                    "cancelled": False,
                    "outputBytes": 0,
                    "stdout": "",
                    "stderr": "",
                    "cleanup": {"status": "PASS"},
                    "blockers": [],
                    "processReceipt": {"schemaVersion": "fixture", "elapsedMs": 1},
                }

            view = run_external_job(
                request,
                ["fixture"],
                env={},
                job_root=root,
                process_runner=fake_runner,
                post_terminal_quiet_seconds=0.1,
            )

        self.assertEqual(view["result"]["state"], "FAILED")
        self.assertTrue(view["jobStatus"]["postTerminalWriteDetected"])
        self.assertFalse(view["result"]["blockingEligible"])

    def test_cancel_after_completion_observation_does_not_claim_effect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "jobs"
            request = _request("completion-race")
            holder: dict[str, Any] = {}

            def fake_runner(_argv: list[str], **_kwargs: Any) -> dict[str, Any]:
                return {
                    "status": "PASS",
                    "timedOut": False,
                    "cancelled": False,
                    "outputBytes": 0,
                    "stdout": "",
                    "stderr": "",
                    "cleanup": {"status": "PASS"},
                    "blockers": [],
                    "processReceipt": {"schemaVersion": "fixture", "timing": {"elapsedMs": 1}},
                }

            worker = threading.Thread(
                target=lambda: holder.setdefault(
                    "view",
                    run_external_job(
                        request,
                        ["fixture"],
                        env={},
                        job_root=root,
                        process_runner=fake_runner,
                        post_terminal_quiet_seconds=0.3,
                    ),
                )
            )
            worker.start()
            completion = root / "completion-race/attempt-1/completion-observed.json"
            deadline = time.monotonic() + 3
            while not completion.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            cancel = request_external_job_cancel(request, job_root=root)
            worker.join(timeout=3)

        self.assertEqual(cancel["status"], "NOT_REQUIRED")
        self.assertTrue(cancel["idempotent"])
        self.assertEqual(holder["view"]["result"]["state"], "SUCCEEDED")


if __name__ == "__main__":
    unittest.main()

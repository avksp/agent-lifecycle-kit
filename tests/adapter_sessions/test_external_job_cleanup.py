from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

from agent_lifecycle.adapter_sessions import external_jobs as external_job_runtime
from agent_lifecycle.adapter_sessions.external_jobs import (
    load_external_job_attempt,
    request_external_job_cancel,
    run_external_job,
)
from agent_lifecycle.contracts import LifecycleError, canonical_digest
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


@contextmanager
def _cancel_attempt() -> Iterator[tuple[Path, dict[str, Any], Path]]:
    """Isolate acknowledgement schedules; native cleanup is tested separately."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "jobs"
        request = _request("acknowledgement")
        attempt = external_job_runtime.external_job_attempt_path(request, job_root=root)
        external_job_runtime.create_private_json(attempt / "request.json", request)
        with mock.patch.object(external_job_runtime, "_latest_status", return_value={"state": "RUNNING"}):
            yield root, request, attempt


class ExternalJobCleanupTests(unittest.TestCase):
    def test_publication_acknowledgement_survives_native_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "jobs"
            request = _request("ordered-native-cancel", max_wall_seconds=3, cancel_grace_seconds=0)
            completion_written = threading.Event()
            holder: dict[str, Any] = {}
            original = external_job_runtime.create_private_json

            def publish_then_wait(path: Path, value: dict[str, Any]) -> None:
                if path.name == "cancel-request.json":
                    self.assertFalse((path.parent / "completion-observed.json").exists())
                original(path, value)
                if path.name == "completion-observed.json":
                    completion_written.set()
                if path.name == "cancel-request.json":
                    holder["cancelBytes"] = path.read_bytes()
                    self.assertTrue(completion_written.wait(timeout=2))

            with (
                mock.patch.object(external_job_runtime, "create_private_json", side_effect=publish_then_wait),
                ThreadPoolExecutor(max_workers=1) as pool,
            ):
                worker = pool.submit(
                    run_external_job,
                    request,
                    [sys.executable, "-c", "import time; time.sleep(10)"],
                    env=dict(os.environ),
                    job_root=root,
                )
                try:
                    _wait_for_state(request, root, "RUNNING")
                    receipt = request_external_job_cancel(request, job_root=root)
                finally:
                    view = worker.result(timeout=5)
            self.assertEqual(receipt["status"], "PASS")
            self.assertFalse(receipt["idempotent"])
            self.assertEqual(view["result"]["state"], "CANCELLED")
            self.assertEqual(view["jobStatus"]["processCleanupStatus"], "PASS")
            self.assertLessEqual(view["result"]["usage"]["wallMilliseconds"], 3000)
            attempt = root / "ordered-native-cancel/attempt-1"
            self.assertEqual((attempt / "cancel-request.json").read_bytes(), holder["cancelBytes"])

    def test_completion_between_initial_check_and_publication_is_not_cancellation_proof(self) -> None:
        with _cancel_attempt() as (root, request, attempt):
            original = external_job_runtime.create_private_json
            terminal = attempt / "terminal-fixture.json"

            def complete_then_publish(path: Path, value: dict[str, Any]) -> None:
                original(attempt / "completion-observed.json", {"observedAt": "fixture"})
                original(terminal, {"state": "SUCCEEDED"})
                original(path, value)

            with mock.patch.object(external_job_runtime, "create_private_json", side_effect=complete_then_publish):
                receipt = request_external_job_cancel(request, job_root=root)
            before = {path.name: path.read_bytes() for path in attempt.iterdir()}
            repeated = request_external_job_cancel(request, job_root=root)
            self.assertEqual(receipt["status"], "PASS")
            self.assertFalse(receipt["idempotent"])
            self.assertFalse(receipt["authorityClaimed"])
            self.assertEqual(receipt["observedState"], "RUNNING")
            self.assertEqual(json.loads(terminal.read_bytes())["state"], "SUCCEEDED")
            self.assertEqual(repeated["status"], "NOT_REQUIRED")
            self.assertTrue(repeated["idempotent"])
            self.assertEqual(before, {path.name: path.read_bytes() for path in attempt.iterdir()})

    def test_initial_terminal_or_completion_is_a_read_only_noop(self) -> None:
        for state in ("SUCCEEDED", "CANCELLED", "COMPLETION_OBSERVED"):
            with self.subTest(state=state), _cancel_attempt() as (root, request, attempt):
                if state == "COMPLETION_OBSERVED":
                    external_job_runtime.create_private_json(
                        attempt / "completion-observed.json", {"observedAt": "fixture"}
                    )
                before = {path.name: path.read_bytes() for path in attempt.iterdir()}
                latest = {"state": "RUNNING" if state == "COMPLETION_OBSERVED" else state}
                with mock.patch.object(external_job_runtime, "_latest_status", return_value=latest):
                    receipt = request_external_job_cancel(request, job_root=root)
                self.assertEqual(receipt["status"], "NOT_REQUIRED")
                self.assertTrue(receipt["idempotent"])
                self.assertFalse((attempt / "cancel-request.json").exists())
                self.assertEqual(before, {path.name: path.read_bytes() for path in attempt.iterdir()})

    def test_nonterminal_retry_reuses_immutable_request(self) -> None:
        with _cancel_attempt() as (root, request, attempt):
            first = request_external_job_cancel(request, job_root=root, now=lambda: "2026-09-06T00:00:00Z")
            before = (attempt / "cancel-request.json").read_bytes()
            second = request_external_job_cancel(request, job_root=root, now=lambda: "2026-09-06T00:00:01Z")
            self.assertEqual((first["status"], first["idempotent"]), ("PASS", False))
            self.assertEqual((second["status"], second["idempotent"]), ("PASS", True))
            self.assertEqual(first["requestedAt"], second["requestedAt"])
            self.assertEqual(before, (attempt / "cancel-request.json").read_bytes())
            stored = json.loads(before)
            self.assertEqual(
                stored["cancelDigest"], canonical_digest({k: v for k, v in stored.items() if k != "cancelDigest"})
            )

    def test_competing_creators_acknowledge_one_immutable_publication(self) -> None:
        with _cancel_attempt() as (root, request, attempt):
            barrier = threading.Barrier(2, timeout=3)
            publication = threading.Lock()
            original = external_job_runtime.create_private_json

            def contend(path: Path, value: dict[str, Any]) -> None:
                barrier.wait()
                # Both callers passed exists(); the loser observes a complete publication.
                with publication:
                    original(path, value)

            with (
                mock.patch.object(external_job_runtime, "create_private_json", side_effect=contend),
                ThreadPoolExecutor(max_workers=2) as pool,
            ):
                workers = [pool.submit(request_external_job_cancel, request, job_root=root) for _ in range(2)]
                receipts = [worker.result(timeout=5) for worker in workers]
            self.assertEqual(len(receipts), 2)
            self.assertEqual(sorted(r["idempotent"] for r in receipts), [False, True])
            self.assertTrue(all(r["status"] == "PASS" for r in receipts))
            self.assertEqual(receipts[0]["requestedAt"], receipts[1]["requestedAt"])
            before = (attempt / "cancel-request.json").read_bytes()
            request_external_job_cancel(request, job_root=root)
            self.assertEqual(before, (attempt / "cancel-request.json").read_bytes())

    def test_wrong_lineage_and_failed_publication_do_not_acknowledge(self) -> None:
        with _cancel_attempt() as (root, request, attempt):
            before = {path.name: path.read_bytes() for path in attempt.iterdir()}
            changed = {**request, "sourceRevision": "different-source"}
            changed["requestDigest"] = canonical_digest({k: v for k, v in changed.items() if k != "requestDigest"})
            with self.assertRaises(LifecycleError) as caught:
                request_external_job_cancel(changed, job_root=root)
            self.assertEqual(caught.exception.code, "external-job-cancel-lineage-mismatch")
            with (
                mock.patch.object(
                    external_job_runtime, "create_private_json", side_effect=OSError("fixture write failure")
                ),
                self.assertRaises(OSError),
            ):
                request_external_job_cancel(request, job_root=root)
            self.assertEqual(before, {path.name: path.read_bytes() for path in attempt.iterdir()})

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

    def test_cancel_before_timeout_persists_terminal_state_within_wall_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "jobs"
            request = _request("late-cancel", max_wall_seconds=3, cancel_grace_seconds=0)
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
            cancel = request_external_job_cancel(request, job_root=root)
            worker.join(timeout=5)

            self.assertFalse(worker.is_alive())
            self.assertEqual(cancel["status"], "PASS")
            self.assertFalse(cancel["idempotent"])
            self.assertEqual(holder["view"]["result"]["state"], "CANCELLED")
            self.assertLessEqual(holder["view"]["result"]["usage"]["wallMilliseconds"], 3000)
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
            late_path = root / "late-write-job/attempt-1/artifacts/late.txt"

            def fake_runner(_argv: list[str], **kwargs: Any) -> dict[str, Any]:
                artifact_root = Path(kwargs["env"]["ALK_EXTERNAL_JOB_ARTIFACT_DIR"])
                self.assertEqual(artifact_root.resolve(), late_path.parent.resolve())
                late_path.write_text("same bytes", encoding="utf-8")
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

            collect_artifacts = external_job_runtime._collect_artifacts
            collection_count = 0

            def collect_with_same_byte_replacement(
                collect_request: dict[str, Any], artifact_root: Path
            ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
                nonlocal collection_count
                collection_count += 1
                if collection_count == 2:
                    before = late_path.stat()
                    replacement = late_path.with_suffix(".replacement")
                    replacement.write_text("same bytes", encoding="utf-8")
                    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))
                    replacement.replace(late_path)
                return collect_artifacts(collect_request, artifact_root)

            with mock.patch.object(
                external_job_runtime,
                "_collect_artifacts",
                side_effect=collect_with_same_byte_replacement,
            ):
                view = run_external_job(
                    request,
                    ["fixture"],
                    env={},
                    job_root=root,
                    process_runner=fake_runner,
                    post_terminal_quiet_seconds=0.1,
                )

        self.assertEqual(collection_count, 2)
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

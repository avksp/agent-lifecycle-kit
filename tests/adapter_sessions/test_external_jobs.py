from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.adapter_sessions.external_jobs import (
    external_job_attempt_path,
    load_external_job_attempt,
    run_external_job,
)
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.external_job_schemas import build_external_job_request


def _request(
    job_id: str,
    *,
    attempt: int = 1,
    parent: dict[str, object] | None = None,
    operation: str = "bounded-audit",
) -> dict[str, object]:
    return build_external_job_request(
        job_id=job_id,
        attempt=attempt,
        adapter_id="synthetic-adapter",
        operation=operation,
        execution_kind="PROCESS",
        descriptor_digest="1" * 64,
        plan_digest="2" * 64,
        plan_lock_digest="3" * 64,
        source_revision="source-revision",
        source_snapshot_digest="4" * 64,
        limits={
            "maxWallSeconds": 5,
            "maxAttempts": 3,
            "maxOutputBytes": 4096,
            "maxArtifactBytes": 4096,
            "maxArtifacts": 4,
            "maxCostMicros": 1000,
            "maxReportedTokens": 1000,
            "cancelGraceSeconds": 1,
        },
        parent_job_id=str(parent["jobId"]) if parent else None,
        parent_attempt=int(parent["attempt"]) if parent else None,
        parent_request_digest=str(parent["requestDigest"]) if parent else None,
    )


class ExternalJobRuntimeTests(unittest.TestCase):
    def test_success_persists_private_bounded_artifact_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "jobs"
            request = _request("artifact-job")
            script = (
                "import os,pathlib; "
                "p=pathlib.Path(os.environ['ALK_EXTERNAL_JOB_ARTIFACT_DIR'])/'report.txt'; "
                "p.write_text('bounded result', encoding='utf-8'); print('raw output')"
            )
            view = run_external_job(request, [sys.executable, "-c", script], env=dict(os.environ), job_root=root)

            self.assertEqual(view["result"]["state"], "SUCCEEDED")
            self.assertTrue(view["result"]["blockingEligible"])
            self.assertEqual(view["result"]["artifacts"][0]["locator"], "artifacts/report.txt")
            self.assertNotIn("stdout", view)
            self.assertNotIn(str(root.resolve()), str(view))
            loaded = load_external_job_attempt(request, job_root=root)
            self.assertEqual(loaded["viewDigest"], view["viewDigest"])
            attempt_root = external_job_attempt_path(request, job_root=root)
            if os.name != "nt":
                self.assertEqual(attempt_root.stat().st_mode & 0o777, 0o700)
                self.assertEqual((attempt_root / "request.json").stat().st_mode & 0o777, 0o600)
                self.assertEqual((attempt_root / "artifacts/report.txt").stat().st_mode & 0o777, 0o600)

    def test_attempt_namespace_is_create_only_and_recovery_uses_new_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "jobs"
            first = _request("retry-job")
            run_external_job(first, [sys.executable, "-c", "pass"], env=dict(os.environ), job_root=root)
            first_root = external_job_attempt_path(first, job_root=root)
            before = canonical_digest(
                {path.name: path.read_bytes().hex() for path in sorted(first_root.glob("*.json"))}
            )
            with self.assertRaises(LifecycleError) as raised:
                run_external_job(first, [sys.executable, "-c", "pass"], env=dict(os.environ), job_root=root)
            self.assertEqual(raised.exception.code, "external-job-attempt-exists")

            second = _request("retry-job", attempt=2)
            run_external_job(second, [sys.executable, "-c", "pass"], env=dict(os.environ), job_root=root)
            after = canonical_digest({path.name: path.read_bytes().hex() for path in sorted(first_root.glob("*.json"))})
            self.assertEqual(after, before)
            self.assertTrue(external_job_attempt_path(second, job_root=root).is_dir())

    def test_no_final_verdict_is_terminal_and_has_no_acceptance_effect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request = _request("no-verdict-job")
            view = run_external_job(
                request,
                [sys.executable, "-c", "print('partial evidence')"],
                env=dict(os.environ),
                job_root=Path(directory) / "jobs",
                verdict="NO_FINAL_VERDICT",
                reported_tokens=37,
            )

        self.assertEqual(view["result"]["state"], "FAILED")
        self.assertEqual(view["result"]["verdict"], "NO_FINAL_VERDICT")
        self.assertFalse(view["result"]["blockingEligible"])
        self.assertEqual(view["result"]["usage"]["reportedTokens"], 37)

    def test_oversized_artifact_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request = _request("oversized-artifact")
            script = (
                "import os,pathlib; "
                "(pathlib.Path(os.environ['ALK_EXTERNAL_JOB_ARTIFACT_DIR'])/'large.bin').write_bytes(b'x'*5000)"
            )
            view = run_external_job(
                request,
                [sys.executable, "-c", script],
                env=dict(os.environ),
                job_root=Path(directory) / "jobs",
            )

        self.assertEqual(view["result"]["state"], "FAILED")
        self.assertIn("external-job-artifact-byte-limit", {item["code"] for item in view["result"]["blockers"]})
        self.assertFalse(view["result"]["blockingEligible"])

    def test_sensitive_request_metadata_is_rejected_before_state_allocation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "jobs"
            private_path = "/" + "Users/operator/private.txt"
            request = _request("private-metadata", operation=f"audit {private_path}")
            with self.assertRaises(LifecycleError) as raised:
                run_external_job(request, [sys.executable, "-c", "pass"], env=dict(os.environ), job_root=root)

        self.assertEqual(raised.exception.code, "external-job-request-sensitive-metadata")
        self.assertFalse(root.exists())

    def test_ordinary_code_path_allocates_no_external_job_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".alk" / "external-jobs"
            _ = canonical_digest({"ordinaryWorkflow": True})
            self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()

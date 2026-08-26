from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts.external_job_schemas import build_external_job_request

try:
    from .helpers import _run_cli
except ImportError:
    from helpers import _run_cli


class ExternalJobCliTests(unittest.TestCase):
    def test_run_status_and_terminal_cancel_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_root = root / "jobs"
            request = build_external_job_request(
                job_id="cli-job",
                attempt=1,
                adapter_id="fixture",
                operation="cli-fixture",
                execution_kind="PROCESS",
                descriptor_digest="1" * 64,
                plan_digest="2" * 64,
                plan_lock_digest="3" * 64,
                source_revision="source",
                source_snapshot_digest="4" * 64,
                limits={
                    "maxWallSeconds": 5,
                    "maxAttempts": 1,
                    "maxOutputBytes": 1024,
                    "maxArtifactBytes": 1024,
                    "maxArtifacts": 1,
                    "maxCostMicros": 0,
                    "maxReportedTokens": 0,
                    "cancelGraceSeconds": 1,
                },
            )
            request_path = root / "request.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            code, run_payload = _run_cli(
                [
                    "adapter",
                    "external-job",
                    "run",
                    "--request",
                    str(request_path),
                    "--job-root",
                    str(job_root),
                    "--",
                    sys.executable,
                    "-c",
                    "print('bounded')",
                ]
            )
            status_code, status_payload = _run_cli(
                ["adapter", "external-job", "status", "--request", str(request_path), "--job-root", str(job_root)]
            )
            cancel_code, cancel_payload = _run_cli(
                ["adapter", "external-job", "cancel", "--request", str(request_path), "--job-root", str(job_root)]
            )

        self.assertEqual(code, 0, run_payload)
        self.assertEqual(status_code, 0, status_payload)
        self.assertEqual(cancel_code, 0, cancel_payload)
        self.assertEqual(run_payload["result"]["state"], "SUCCEEDED")
        self.assertEqual(status_payload["viewDigest"], run_payload["viewDigest"])
        self.assertEqual(cancel_payload["status"], "NOT_REQUIRED")
        self.assertNotIn(str(job_root), str(run_payload))
        self.assertNotIn("bounded", str(run_payload))

    def test_run_requires_explicit_argv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = build_external_job_request(
                job_id="no-argv",
                attempt=1,
                adapter_id="fixture",
                operation="cli-fixture",
                execution_kind="PROCESS",
                descriptor_digest="1" * 64,
                plan_digest="2" * 64,
                plan_lock_digest="3" * 64,
                source_revision="source",
                source_snapshot_digest="4" * 64,
                limits={
                    "maxWallSeconds": 5,
                    "maxAttempts": 1,
                    "maxOutputBytes": 1024,
                    "maxArtifactBytes": 1024,
                    "maxArtifacts": 0,
                    "maxCostMicros": 0,
                    "maxReportedTokens": 0,
                    "cancelGraceSeconds": 1,
                },
            )
            path = root / "request.json"
            path.write_text(json.dumps(request), encoding="utf-8")
            code, payload = _run_cli(
                ["adapter", "external-job", "run", "--request", str(path), "--job-root", str(root / "jobs")]
            )

        self.assertEqual(code, 2)
        self.assertEqual(payload["code"], "external-job-argv-invalid")


if __name__ == "__main__":
    unittest.main()

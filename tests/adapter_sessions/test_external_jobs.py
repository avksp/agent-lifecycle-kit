from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.adapter_sessions.external_jobs import (
    external_job_attempt_path,
    load_external_job_attempt,
    load_external_job_response,
    recover_external_job_attempt,
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
    max_wall_seconds: int = 5,
    cancel_grace_seconds: int = 1,
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
            "maxWallSeconds": max_wall_seconds,
            "maxAttempts": 3,
            "maxOutputBytes": 4096,
            "maxArtifactBytes": 4096,
            "maxArtifacts": 4,
            "maxCostMicros": 1000,
            "maxReportedTokens": 1000,
            "cancelGraceSeconds": cancel_grace_seconds,
        },
        parent_job_id=str(parent["jobId"]) if parent else None,
        parent_attempt=int(parent["attempt"]) if parent else None,
        parent_request_digest=str(parent["requestDigest"]) if parent else None,
    )


class ExternalJobRuntimeTests(unittest.TestCase):
    def test_selected_transient_retry_requires_finite_bound_grant(self):
        from dataclasses import replace

        from agent_lifecycle.accounting.journal import Journal
        from agent_lifecycle.adapter_sessions.process_admission import JournalPreparationAdmission
        from tests.accounting.test_journal import PROOF, open_scope
        from tests.adapter_sessions.test_process_admission import (
            preparation_operation,
            qualified_context,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with Journal(root / "usage.db", PROOF) as journal:
                open_scope(journal)
                first_request = _request("transient")
                def first_context(prefix):
                    context = qualified_context(prefix)
                    context["inputDigest"] = first_request["requestDigest"]
                    return context
                first_admission = JournalPreparationAdmission(
                    journal, replace(preparation_operation(), input_digest=first_request["requestDigest"]),
                    first_context, clock=lambda: 100,
                )
                failed = run_external_job(
                    first_request, [sys.executable, "-c", "raise SystemExit(75)"],
                    env=dict(os.environ), cwd=root, job_root=root / "jobs",
                    preparation=first_admission,
                )
                self.assertEqual(failed["result"]["state"], "FAILED")
                second_request = _request("transient", attempt=2)
                op = replace(preparation_operation("retry"), retry_ordinal=1,
                             input_digest=second_request["requestDigest"])
                def second_context(prefix):
                    context = qualified_context(prefix)
                    context["inputDigest"] = second_request["requestDigest"]
                    context["repeat"] = {
                        "required": True, "qualified": True,
                        "disposition": "INVALIDATED", "inputDigests": ["e" * 64],
                        "benefitDigest": "f" * 64,
                    }
                    return context
                no_grant = JournalPreparationAdmission(journal, op, second_context, clock=lambda: 100)
                with self.assertRaises(LifecycleError) as caught:
                    run_external_job(second_request, ["never"], env={}, cwd=root,
                                     job_root=root / "jobs", preparation=no_grant)
                self.assertEqual(caught.exception.code, "REVIEW_ROUTE_SUSPENDED")
                self.assertFalse(external_job_attempt_path(second_request, job_root=root / "jobs").exists())
                def retry_context(prefix):
                    context = second_context(prefix)
                    context["retry"] = {
                        "qualified": True, "authorizationDigest": "a" * 64,
                        "priorRequestDigest": first_request["requestDigest"],
                        "priorResultDigest": failed["result"]["resultDigest"],
                        "disposition": "TRANSIENT_SETTLED", "maxGenerationRetries": 1,
                    }
                    return context
                allowed = JournalPreparationAdmission(journal, op, retry_context, clock=lambda: 100)
                complete = run_external_job(
                    second_request, [sys.executable, "-c", "print('recovered')"],
                    env=dict(os.environ), cwd=root, job_root=root / "jobs", preparation=allowed,
                )
                self.assertEqual(complete["result"]["state"], "SUCCEEDED")
                self.assertEqual(journal.snapshot("run").active_reservations, 200)

    def test_transport_recovery_keeps_one_original_result_and_charge(self):
        from unittest.mock import Mock

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "jobs"
            request = _request("recover-complete")
            first = run_external_job(
                request, [sys.executable, "-c", "print('complete')"],
                env=dict(os.environ), job_root=root, reported_tokens=37,
            )
            runner = Mock(side_effect=AssertionError("second generation"))
            recovered = run_external_job(
                request, ["invalid-new-argv"], env={}, job_root=root,
                recover_existing=True, process_runner=runner,
            )
            self.assertEqual(recovered["result"], first["result"])
            self.assertEqual(recovered["jobStatus"], first["jobStatus"])
            self.assertEqual(recovered["result"]["usage"]["reportedTokens"], 37)
            self.assertIsNone(recovered["processReceipt"])
            self.assertEqual(recover_external_job_attempt(request, job_root=root), recovered)
            runner.assert_not_called()

    def test_private_response_roundtrip_and_missing_or_changed_body_refuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "jobs"
            request = _request("durable-response")
            first = run_external_job(
                request, [sys.executable, "-c", "print('complete private body')"],
                env=dict(os.environ), job_root=root, reported_tokens=37,
            )
            attempt = external_job_attempt_path(request, job_root=root)
            original = (attempt / "result.json").read_bytes()
            self.assertEqual(load_external_job_response(request, job_root=root),
                             {"stdout": "complete private body\n", "stderr": ""})
            self.assertEqual(recover_external_job_attempt(request, job_root=root)["result"],
                             first["result"])
            if os.name != "nt":
                for stream in ("stdout", "stderr"):
                    self.assertEqual((attempt / ("response." + stream)).stat().st_mode
                                     & 0o777, 0o600)
            (attempt / "response.stdout").write_text("changed body", encoding="utf-8")
            with self.assertRaises(LifecycleError) as changed:
                recover_external_job_attempt(request, job_root=root)
            self.assertEqual(changed.exception.code, "REVIEW_RECOVERY_INVALID")
            (attempt / "response.stdout").unlink()
            with self.assertRaises(LifecycleError) as missing:
                recover_external_job_attempt(request, job_root=root)
            self.assertEqual(missing.exception.code, "REVIEW_RESPONSE_UNAVAILABLE")
            # Historical metadata remains readable, but cannot qualify as a response.
            self.assertEqual(load_external_job_attempt(request, job_root=root)["result"],
                             first["result"])
            self.assertEqual((attempt / "result.json").read_bytes(), original)

    def test_recovery_refuses_open_schema_private_extras_without_rewriting(self):
        from agent_lifecycle.contracts.external_job_schemas import (
            validate_external_job_result,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "jobs"
            request = _request("recovery-private-extras")
            first = run_external_job(
                request, [sys.executable, "-c", "print('complete')"],
                env=dict(os.environ), job_root=root,
            )
            attempt = external_job_attempt_path(request, job_root=root)
            result = dict(first["result"], diagnostic={
                "api_key": "private-key-should-never-leave",
                "prompt": "private prompt", "path": str(attempt),
                "large": "x" * 200000,
            })
            result["resultDigest"] = canonical_digest({
                k: v for k, v in result.items() if k != "resultDigest"
            })
            self.assertEqual(validate_external_job_result(
                result, request=request, status=first["jobStatus"],
            )["status"], "PASS")
            path = attempt / "result.json"
            path.write_text(json.dumps(result), encoding="utf-8")
            original = path.read_bytes()
            with self.assertRaises(LifecycleError) as caught:
                recover_external_job_attempt(request, job_root=root)
            self.assertEqual(caught.exception.code, "REVIEW_RECOVERY_INVALID")
            self.assertLess(len(str(caught.exception)), 200)
            self.assertNotIn("private-key", str(caught.exception))
            self.assertNotIn(str(attempt), str(caught.exception))
            self.assertEqual(path.read_bytes(), original)

    def test_recovery_refuses_partial_wrong_subject_and_modified_artifacts(self):

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "jobs"
            request = _request("recover-artifact")
            script = (
                "import os,pathlib; "
                "(pathlib.Path(os.environ['ALK_EXTERNAL_JOB_ARTIFACT_DIR'])"
                "/'result.txt').write_text('complete')"
            )
            run_external_job(request, [sys.executable, "-c", script],
                             env=dict(os.environ), job_root=root)
            attempt = external_job_attempt_path(request, job_root=root)
            (attempt / "artifacts/result.txt").write_text("changed", encoding="utf-8")
            with self.assertRaises(LifecycleError) as caught:
                recover_external_job_attempt(request, job_root=root)
            self.assertEqual(caught.exception.code, "REVIEW_RECOVERY_INVALID")
            partial = _request("recover-partial")
            run_external_job(partial, [sys.executable, "-c", "pass"],
                             env=dict(os.environ), job_root=root, complete=False)
            with self.assertRaises(LifecycleError) as caught:
                recover_external_job_attempt(partial, job_root=root)
            self.assertEqual(caught.exception.code, "REVIEW_ROUTE_SUSPENDED")
            wrong = dict(request, sourceRevision="wrong-source")
            with self.assertRaises(LifecycleError):
                recover_external_job_attempt(wrong, job_root=root)

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

    def test_real_timeout_persists_expired_terminal_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "jobs"
            request = _request("timeout-job", max_wall_seconds=1, cancel_grace_seconds=0)
            view = run_external_job(
                request,
                [sys.executable, "-c", "import time; time.sleep(10)"],
                env=dict(os.environ),
                job_root=root,
            )

            self.assertEqual(view["result"]["state"], "EXPIRED")
            self.assertFalse(view["result"]["blockingEligible"])
            self.assertLessEqual(view["result"]["usage"]["wallMilliseconds"], 1000)
            self.assertGreaterEqual(view["processReceipt"]["timing"]["elapsedMs"], 1000)
            self.assertEqual(load_external_job_attempt(request, job_root=root)["result"]["state"], "EXPIRED")
            attempt_root = external_job_attempt_path(request, job_root=root)
            self.assertTrue((attempt_root / "status-000002.json").is_file())
            self.assertTrue((attempt_root / "process-receipt.json").is_file())
            self.assertTrue((attempt_root / "result.json").is_file())

    def test_nested_artifact_directories_are_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "jobs"
            request = _request("nested-artifact-job")
            script = (
                "import os,pathlib; "
                "p=pathlib.Path(os.environ['ALK_EXTERNAL_JOB_ARTIFACT_DIR'])/'private'/'nested'/'report.txt'; "
                "p.parent.mkdir(parents=True); p.write_text('result', encoding='utf-8')"
            )
            view = run_external_job(request, [sys.executable, "-c", script], env=dict(os.environ), job_root=root)

            self.assertEqual(view["result"]["state"], "SUCCEEDED")
            if os.name != "nt":
                artifact_root = external_job_attempt_path(request, job_root=root) / "artifacts"
                self.assertEqual((artifact_root / "private").stat().st_mode & 0o777, 0o700)
                self.assertEqual((artifact_root / "private/nested").stat().st_mode & 0o777, 0o700)

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
            root = Path(directory)
            repository_root = Path(__file__).resolve().parents[2]
            env = dict(os.environ)
            env["PYTHONPATH"] = str(repository_root / "src")
            completed = subprocess.run(
                [sys.executable, "-m", "agent_lifecycle", "workflow", "status", "--state", "missing-state.json"],
                cwd=root,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=False,
                timeout=10,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertFalse((root / ".alk" / "external-jobs").exists())


if __name__ == "__main__":
    unittest.main()

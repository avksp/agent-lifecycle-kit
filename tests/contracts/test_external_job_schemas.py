from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.external_job_schemas import (
    EXTERNAL_JOB_ARTIFACT_SCHEMA,
    EXTERNAL_JOB_REQUEST_SCHEMA,
    EXTERNAL_JOB_RESULT_SCHEMA,
    EXTERNAL_JOB_STATUS_SCHEMA,
    EXTERNAL_JOB_TRANSITION_VALIDATION_SCHEMA,
    EXTERNAL_JOB_VALIDATION_SCHEMA,
    build_external_job_artifact,
    build_external_job_request,
    build_external_job_result,
    build_external_job_status,
    validate_external_job_artifact,
    validate_external_job_request,
    validate_external_job_result,
    validate_external_job_status,
)
from agent_lifecycle.contracts.schemas import get_schema


class ExternalJobContractTests(unittest.TestCase):
    def test_external_job_contracts_are_registered(self) -> None:
        for schema_id in (
            EXTERNAL_JOB_REQUEST_SCHEMA,
            EXTERNAL_JOB_STATUS_SCHEMA,
            EXTERNAL_JOB_ARTIFACT_SCHEMA,
            EXTERNAL_JOB_RESULT_SCHEMA,
            EXTERNAL_JOB_VALIDATION_SCHEMA,
            EXTERNAL_JOB_TRANSITION_VALIDATION_SCHEMA,
        ):
            self.assertEqual(get_schema(schema_id)["$id"], schema_id)

    def test_complete_result_is_source_bound_and_blocking_eligible(self) -> None:
        request = self._request()
        status = self._status(request)
        artifact = build_external_job_artifact(
            artifact_id="summary",
            media_type="application/json",
            bytes_count=42,
            sha256="6" * 64,
            locator="artifacts/summary.json",
        )
        result = build_external_job_result(
            result_id="result-1",
            request=request,
            status=status,
            verdict="PASS",
            complete=True,
            artifacts=[artifact],
            output_digest="7" * 64,
            output_bytes=42,
        )

        self.assertEqual(validate_external_job_request(request)["status"], "PASS")
        self.assertEqual(validate_external_job_status(status, request=request)["status"], "PASS")
        validation = validate_external_job_result(result, request=request, status=status)
        self.assertEqual(validation["status"], "PASS")
        self.assertTrue(validation["blockingEligible"])

    def test_parent_lineage_and_contract_digest_fail_closed(self) -> None:
        request = self._request()
        request["parentJobId"] = "parent-1"
        request["requestDigest"] = canonical_digest({k: v for k, v in request.items() if k != "requestDigest"})

        validation = validate_external_job_request(request)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("external-job-parent-lineage-invalid", self._codes(validation))
        request["jobId"] = "../job"
        self.assertIn("external-job-job-id-invalid", self._codes(validate_external_job_request(request)))

    def test_artifact_locator_is_relative_and_attempt_scoped_by_caller(self) -> None:
        artifact = build_external_job_artifact(
            artifact_id="summary",
            media_type="text/plain",
            bytes_count=4,
            sha256="6" * 64,
            locator="artifacts/attempt-1/summary.txt",
        )
        self.assertEqual(validate_external_job_artifact(artifact)["status"], "PASS")

        for locator in ("../summary.txt", "/tmp/summary.txt", "outputs/summary.txt"):
            with self.subTest(locator=locator), self.assertRaises(LifecycleError):
                build_external_job_artifact(
                    artifact_id="summary",
                    media_type="text/plain",
                    bytes_count=4,
                    sha256="6" * 64,
                    locator=locator,
                )

    def test_no_final_verdict_and_partial_output_have_no_acceptance_effect(self) -> None:
        request = self._request()
        status = self._status(request, state="EXPIRED", cleanup="PASS")
        result = build_external_job_result(
            result_id="result-expired",
            request=request,
            status=status,
            verdict="NO_FINAL_VERDICT",
            complete=False,
            artifacts=[],
            output_digest=None,
            output_bytes=0,
            blockers=[{"code": "external-job-timeout"}],
        )

        validation = validate_external_job_result(result, request=request, status=status)

        self.assertEqual(validation["status"], "PASS")
        self.assertFalse(validation["blockingEligible"])
        self.assertFalse(result["blockingEligible"])

    def test_usage_and_artifact_limits_are_enforced_after_digest_rebinding(self) -> None:
        request = self._request()
        status = self._status(request)
        status["usage"]["reportedTokens"] = request["limits"]["maxReportedTokens"] + 1
        self._redigest(status, "statusDigest")
        validation = validate_external_job_status(status, request=request)
        self.assertIn("external-job-token-limit-exceeded", self._codes(validation))

        clean_status = self._status(request)
        artifact = build_external_job_artifact(
            artifact_id="large",
            media_type="application/octet-stream",
            bytes_count=request["limits"]["maxArtifactBytes"] + 1,
            sha256="6" * 64,
            locator="artifacts/large.bin",
        )
        with self.assertRaises(LifecycleError):
            build_external_job_result(
                result_id="result-large",
                request=request,
                status=clean_status,
                verdict="PASS",
                complete=True,
                artifacts=[artifact],
                output_digest=None,
                output_bytes=0,
            )

    def test_status_and_result_replay_are_rejected(self) -> None:
        request = self._request()
        status = self._status(request)
        stale_request = {**request, "sourceSnapshotDigest": "9" * 64}
        self._redigest(stale_request, "requestDigest")
        self.assertIn(
            "external-job-status-lineage-mismatch",
            self._codes(validate_external_job_status(status, request=stale_request)),
        )

        result = build_external_job_result(
            result_id="result-1",
            request=request,
            status=status,
            verdict="PASS",
            complete=True,
            artifacts=[],
            output_digest=None,
            output_bytes=0,
        )
        result["statusDigest"] = "8" * 64
        self._redigest(result, "resultDigest")
        self.assertIn(
            "external-job-result-status-mismatch",
            self._codes(validate_external_job_result(result, request=request, status=status)),
        )

    @staticmethod
    def _request(*, job_id: str = "job-1", parent: tuple[str, int] | None = None) -> dict:
        return build_external_job_request(
            job_id=job_id,
            attempt=1,
            parent_job_id=parent[0] if parent else None,
            parent_attempt=parent[1] if parent else None,
            adapter_id="synthetic",
            operation="review",
            execution_kind="PROCESS",
            descriptor_digest="1" * 64,
            plan_digest="2" * 64,
            plan_lock_digest="3" * 64,
            source_revision="0123456789abcdef",
            source_snapshot_digest="4" * 64,
            limits={
                "maxWallSeconds": 60,
                "maxOutputBytes": 1024,
                "maxArtifactBytes": 1024,
                "maxArtifacts": 4,
                "maxCostMicros": 1_000_000,
                "maxReportedTokens": 10_000,
                "cancelGraceSeconds": 2,
            },
        )

    @staticmethod
    def _status(request: dict, *, state: str = "SUCCEEDED", cleanup: str = "PASS") -> dict:
        return build_external_job_status(
            request=request,
            state=state,
            sequence=2,
            observed_at="2026-08-26T03:30:02Z",
            started_at="2026-08-26T03:30:00Z",
            ended_at="2026-08-26T03:30:02Z",
            process_cleanup_status=cleanup,
            usage={"wallMilliseconds": 2000, "outputBytes": 42, "artifactBytes": 42},
        )

    @staticmethod
    def _redigest(value: dict, field: str) -> None:
        value[field] = canonical_digest({key: item for key, item in value.items() if key != field})

    @staticmethod
    def _codes(validation: dict) -> set[str]:
        return {item["code"] for item in validation["blockers"]}


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from agent_lifecycle.audit.external_checks import audit_external_check_result, require_external_check_audit_pass
from agent_lifecycle.contracts.external_check_schemas import (
    build_external_check_descriptor,
    build_external_check_invocation,
    build_external_check_result,
)


class ExternalCheckAuditTests(unittest.TestCase):
    def test_clean_result_can_be_audited_without_claiming_authority(self) -> None:
        descriptor = _descriptor()
        invocation = build_external_check_invocation(
            invocation_id="audit-invocation",
            operation_id="audit-operation",
            descriptor=descriptor,
            started_at="2026-08-24T14:30:00Z",
        )
        result = build_external_check_result(
            result_id="audit-result",
            descriptor=descriptor,
            invocation=invocation,
            status="PASS",
            findings=[],
            output_digest=None,
            output_bytes=0,
            complete=True,
            timed_out=False,
            output_truncated=False,
            process_cleanup_status="PASS",
            exit_code=0,
        )

        audit = audit_external_check_result(
            result,
            descriptor=descriptor,
            invocation=invocation,
            blocking_required=True,
        )

        self.assertEqual(audit["status"], "PASS")
        self.assertTrue(audit["blockingEligible"])
        self.assertFalse(audit["authorityClaimed"])
        self.assertEqual(require_external_check_audit_pass(audit), audit)

    def test_stale_result_cannot_be_promoted(self) -> None:
        descriptor = _descriptor()
        invocation = build_external_check_invocation(
            invocation_id="audit-invocation-2",
            operation_id="audit-operation-2",
            descriptor=descriptor,
            started_at="2026-08-24T14:30:00Z",
        )
        result = build_external_check_result(
            result_id="audit-result-2",
            descriptor=descriptor,
            invocation=invocation,
            status="PASS",
            findings=[],
            output_digest=None,
            output_bytes=0,
            complete=True,
            timed_out=False,
            output_truncated=False,
            process_cleanup_status="PASS",
            exit_code=0,
        )
        result["planDigest"] = "f" * 64

        audit = audit_external_check_result(
            result,
            descriptor=descriptor,
            invocation=invocation,
            blocking_required=True,
        )

        self.assertEqual(audit["status"], "FAIL")
        self.assertFalse(audit["blockingEligible"])
        self.assertIn({"code": "external-check-result-digest-mismatch"}, audit["blockers"])


def _descriptor() -> dict:
    return build_external_check_descriptor(
        descriptor_id="audit-descriptor",
        check_id="import-boundaries",
        tool_id="import-linter",
        tool_version="2.5.0",
        executable="import-linter",
        argv=["import-linter", "--config", "pyproject.toml"],
        config_digest="1" * 64,
        source_snapshot={"revision": "9d26b848c77c2bb79971651ab08cb5b924656130", "fileSetDigest": "2" * 64},
        plan_digest="3" * 64,
        plan_lock_digest="4" * 64,
    )


if __name__ == "__main__":
    unittest.main()

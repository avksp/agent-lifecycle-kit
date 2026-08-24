from __future__ import annotations

import unittest

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.external_check_schemas import (
    EXTERNAL_CHECK_DESCRIPTOR_SCHEMA,
    EXTERNAL_CHECK_FINDING_SCHEMA,
    EXTERNAL_CHECK_INVOCATION_SCHEMA,
    EXTERNAL_CHECK_RESULT_SCHEMA,
    build_external_check_descriptor,
    build_external_check_finding,
    build_external_check_invocation,
    build_external_check_result,
    validate_external_check_descriptor,
    validate_external_check_finding,
    validate_external_check_invocation,
    validate_external_check_result,
)
from agent_lifecycle.contracts.schemas import get_schema


class ExternalCheckContractTests(unittest.TestCase):
    def test_external_check_contracts_are_registered(self) -> None:
        for schema_id in (
            EXTERNAL_CHECK_DESCRIPTOR_SCHEMA,
            EXTERNAL_CHECK_INVOCATION_SCHEMA,
            EXTERNAL_CHECK_FINDING_SCHEMA,
            EXTERNAL_CHECK_RESULT_SCHEMA,
        ):
            self.assertEqual(get_schema(schema_id)["$id"], schema_id)

    def test_clean_result_is_bound_to_descriptor_invocation_and_snapshot(self) -> None:
        descriptor = self._descriptor()
        invocation = build_external_check_invocation(
            invocation_id="invocation-1",
            operation_id="operation-1",
            descriptor=descriptor,
            started_at="2026-08-24T14:30:00Z",
            status="COMPLETED",
            ended_at="2026-08-24T14:30:01Z",
        )
        result = build_external_check_result(
            result_id="result-1",
            descriptor=descriptor,
            invocation=invocation,
            status="PASS",
            findings=[],
            output_digest=canonical_digest({"stdout": "clean"}),
            output_bytes=7,
            complete=True,
            timed_out=False,
            output_truncated=False,
            process_cleanup_status="PASS",
            exit_code=0,
        )

        self.assertEqual(validate_external_check_descriptor(descriptor)["status"], "PASS")
        self.assertEqual(validate_external_check_invocation(invocation, descriptor=descriptor)["status"], "PASS")
        validation = validate_external_check_result(result, descriptor=descriptor, invocation=invocation)

        self.assertEqual(validation["status"], "PASS")
        self.assertTrue(validation["blockingEligible"])

    def test_descriptor_rejects_shell_and_environment_patterns(self) -> None:
        descriptor = self._descriptor()
        descriptor["shell"] = True
        descriptor["environment"]["allowPatterns"] = ["*"]

        validation = validate_external_check_descriptor(descriptor)

        self.assertEqual(validation["status"], "FAIL")
        codes = {item["code"] for item in validation["blockers"]}
        self.assertIn("external-check-descriptor-shell-enabled", codes)
        self.assertIn("external-check-environment-invalid", codes)

    def test_result_rejects_stale_source_and_incomplete_execution(self) -> None:
        descriptor = self._descriptor()
        invocation = build_external_check_invocation(
            invocation_id="invocation-2",
            operation_id="operation-2",
            descriptor=descriptor,
            started_at="2026-08-24T14:30:00Z",
        )
        result = build_external_check_result(
            result_id="result-2",
            descriptor=descriptor,
            invocation=invocation,
            status="UNAVAILABLE",
            findings=[],
            output_digest=None,
            output_bytes=0,
            complete=False,
            timed_out=True,
            output_truncated=False,
            process_cleanup_status="UNAVAILABLE",
            exit_code=None,
            blockers=[{"code": "tool-not-installed"}],
        )
        result["sourceSnapshot"] = {**result["sourceSnapshot"], "revision": "stale"}

        validation = validate_external_check_result(result, descriptor=descriptor, invocation=invocation)

        self.assertEqual(validation["status"], "FAIL")
        codes = {item["code"] for item in validation["blockers"]}
        self.assertIn("external-check-result-digest-mismatch", codes)
        self.assertIn("external-check-result-lineage-mismatch", codes)

    def test_finding_location_is_repository_relative_and_digest_bound(self) -> None:
        finding = build_external_check_finding(
            rule_id="layer.forbidden-import",
            severity="HIGH",
            message="module imports a protected layer",
            location={"path": "src/app.py", "line": 12, "column": 1},
        )

        validation = validate_external_check_finding(finding)

        self.assertEqual(validation["status"], "PASS")
        finding["location"]["path"] = "../outside.py"
        self.assertEqual(validate_external_check_finding(finding)["status"], "FAIL")

    @staticmethod
    def _descriptor() -> dict:
        return build_external_check_descriptor(
            descriptor_id="descriptor-1",
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

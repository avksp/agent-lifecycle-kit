from __future__ import annotations

import unittest

from agent_lifecycle.contracts.external_check_schemas import (
    build_external_check_descriptor,
    build_external_check_invocation,
)
from agent_lifecycle.quality.external_checks import (
    normalize_external_check_result,
    validate_normalized_external_check_result,
)


class ExternalCheckQualityTests(unittest.TestCase):
    def test_normalization_redacts_output_and_finding_text(self) -> None:
        descriptor = _descriptor()
        invocation = build_external_check_invocation(
            invocation_id="quality-invocation",
            operation_id="quality-operation",
            descriptor=descriptor,
            started_at="2026-08-24T14:30:00Z",
        )
        private_path = "/" + "Users/private/project/src/app.py"
        result = normalize_external_check_result(
            {
                "status": "FAIL",
                "complete": True,
                "timedOut": False,
                "processCleanupStatus": "PASS",
                "exitCode": 1,
                "stdout": "https://github.com/example/project and sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
                "findings": [
                    {
                        "ruleId": "layer.forbidden-import",
                        "severity": "HIGH",
                        "message": f"see {private_path}",
                        "location": {"path": "src/app.py", "line": 4},
                    }
                ],
            },
            descriptor=descriptor,
            invocation=invocation,
            result_id="quality-result",
        )

        validation = validate_normalized_external_check_result(
            result,
            descriptor=descriptor,
            invocation=invocation,
        )

        self.assertEqual(validation["status"], "PASS")
        self.assertNotIn("sk-proj-", str(result))
        self.assertNotIn("/" + "Users/private", str(result))
        self.assertNotIn("stdout", str(result))
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["blockingEligible"])

    def test_missing_or_truncated_output_is_not_eligible(self) -> None:
        descriptor = _descriptor()
        invocation = build_external_check_invocation(
            invocation_id="quality-invocation-2",
            operation_id="quality-operation-2",
            descriptor=descriptor,
            started_at="2026-08-24T14:30:00Z",
        )
        result = normalize_external_check_result(
            {
                "status": "PASS",
                "complete": False,
                "timedOut": False,
                "outputTruncated": True,
                "processCleanupStatus": "PASS",
                "exitCode": 0,
                "stdout": "partial",
                "findings": [],
            },
            descriptor=descriptor,
            invocation=invocation,
            result_id="quality-result-2",
        )

        self.assertFalse(result["blockingEligible"])
        self.assertIn({"code": "external-check-output-incomplete"}, result["blockers"])
        self.assertIn({"code": "external-check-output-truncated"}, result["blockers"])


def _descriptor() -> dict:
    return build_external_check_descriptor(
        descriptor_id="quality-descriptor",
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

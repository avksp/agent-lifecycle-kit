from __future__ import annotations

import unittest

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.structured_result_schemas import (
    STRUCTURED_RESULT_OUTPUT_CONTRACT_SCHEMA,
    build_structured_result_capability,
    select_structured_result_mode,
)
from agent_lifecycle.host_protocol.structured_results import validate_structured_result_output


class StructuredResultHostProtocolTests(unittest.TestCase):
    def test_valid_output_is_accepted_without_promotion(self) -> None:
        selection = _selection()
        contract_body = {
            "schemaVersion": STRUCTURED_RESULT_OUTPUT_CONTRACT_SCHEMA,
            "operationId": "task-result",
            "requiredMode": "JSON_ENFORCED",
            "resultSchemaVersion": "agent-task-result.v2",
            "requiredFields": ["status", "summary"],
            "selectionDigest": selection["selectionDigest"],
            "schemaDigest": "c" * 64,
            "maxRepairAttempts": 2,
            "forbiddenFields": ["reasoningTrace"],
            "productionPromotionClaimed": False,
        }
        contract = {**contract_body, "contractDigest": canonical_digest(contract_body)}
        output = {
            "schemaVersion": "agent-task-result.v2",
            "operationId": "task-result",
            "selectionDigest": selection["selectionDigest"],
            "status": "PASS",
            "summary": "valid",
            "productionPromotionClaimed": False,
        }
        result = validate_structured_result_output(output, contract, selection, attempt=1, repair_attempts=1)
        self.assertEqual(result["status"], "PASS")

    def test_repair_budget_and_forbidden_reasoning_fail_closed(self) -> None:
        selection = _selection()
        contract = {
            "schemaVersion": STRUCTURED_RESULT_OUTPUT_CONTRACT_SCHEMA,
            "operationId": "task-result",
            "resultSchemaVersion": "agent-task-result.v2",
            "requiredFields": ["status"],
            "selectionDigest": selection["selectionDigest"],
            "maxRepairAttempts": 2,
            "forbiddenFields": ["reasoningTrace"],
        }
        output = {
            "schemaVersion": "agent-task-result.v2",
            "operationId": "task-result",
            "selectionDigest": selection["selectionDigest"],
            "status": "PASS",
            "reasoningTrace": "must not be portable",
        }
        result = validate_structured_result_output(output, contract, selection, attempt=1, repair_attempts=3)
        codes = {item["code"] for item in result["errors"]}
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("structured-result-repair-budget-exceeded", codes)
        self.assertIn("structured-result-output-forbidden-field", codes)


def _selection() -> dict[str, object]:
    capability = build_structured_result_capability(
        operation_id="task-result",
        adapter_id="adapter",
        descriptor_digest="a" * 64,
        host_version="1.0.0",
        model_class="standard",
        capability_level="SCHEMA_ENFORCED",
        qualification_status="QUALIFIED",
        capability_manifest_digest="b" * 64,
        evidence_digest="e" * 64,
        measured_run_count=2,
    )
    return select_structured_result_mode(
        [capability],
        operation_id="task-result",
        required_mode="JSON_ENFORCED",
        adapter_id="adapter",
        descriptor_digest="a" * 64,
        host_version="1.0.0",
        model_class="standard",
        capability_manifest_digest="b" * 64,
        required_schema_digest="c" * 64,
    )


if __name__ == "__main__":
    unittest.main()

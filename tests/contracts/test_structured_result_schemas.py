from __future__ import annotations

import unittest

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.schemas import get_schema
from agent_lifecycle.contracts.structured_result_schemas import (
    STRUCTURED_RESULT_CAPABILITY_SCHEMA,
    STRUCTURED_RESULT_MODES,
    build_structured_result_capability,
    select_structured_result_mode,
    validate_structured_result_capability,
    validate_structured_result_selection,
)


class StructuredResultSchemaTests(unittest.TestCase):
    def test_structured_result_schemas_are_registered(self) -> None:
        for schema_id in (
            STRUCTURED_RESULT_CAPABILITY_SCHEMA,
            "agent-structured-result-selection.v1",
            "agent-structured-result-output-contract.v1",
            "agent-structured-result-validation.v1",
        ):
            self.assertEqual(get_schema(schema_id)["$id"], schema_id)

    def test_capability_is_bound_to_one_operation(self) -> None:
        capability = _capability(operation="task-result", mode="SCHEMA_ENFORCED")
        self.assertEqual(validate_structured_result_capability(capability)["status"], "PASS")
        changed = {**capability, "operationId": "other-operation"}
        changed["capabilityDigest"] = canonical_digest({key: value for key, value in changed.items() if key != "capabilityDigest"})
        result = validate_structured_result_capability(changed, expected={"operationId": "task-result"})
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("structured-result-capability-lineage-mismatch", {item["code"] for item in result["blockers"]})

    def test_selection_chooses_strongest_qualified_mode(self) -> None:
        capabilities = [
            _capability(operation="task-result", mode="JSON_ENFORCED"),
            _capability(operation="task-result", mode="SCHEMA_ENFORCED"),
        ]
        result = select_structured_result_mode(
            capabilities,
            operation_id="task-result",
            required_mode="JSON_ENFORCED",
            adapter_id="adapter",
            descriptor_digest="a" * 64,
            host_version="1.0.0",
            model_class="standard",
            capability_manifest_digest="b" * 64,
            required_schema_digest="c" * 64,
            lineage={"planDigest": "d" * 64, "planRevision": 4},
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["selectedMode"], "SCHEMA_ENFORCED")
        self.assertEqual(validate_structured_result_selection(result)["status"], "PASS")

    def test_required_schema_does_not_fall_back(self) -> None:
        result = select_structured_result_mode(
            [_capability(operation="task-result", mode="JSON_ENFORCED")],
            operation_id="task-result",
            required_mode="SCHEMA_ENFORCED",
            adapter_id="adapter",
            descriptor_digest="a" * 64,
            host_version="1.0.0",
            model_class="standard",
            capability_manifest_digest="b" * 64,
            required_schema_digest="c" * 64,
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["selectedMode"], "UNAVAILABLE")
        self.assertIn("structured-result-required-capability-unavailable", {item["code"] for item in result["blockers"]})
        self.assertEqual(set(STRUCTURED_RESULT_MODES), {"SCHEMA_ENFORCED", "JSON_ENFORCED", "VALIDATED_TEXT", "UNAVAILABLE"})


def _capability(*, operation: str, mode: str) -> dict[str, object]:
    return build_structured_result_capability(
        operation_id=operation,
        adapter_id="adapter",
        descriptor_digest="a" * 64,
        host_version="1.0.0",
        model_class="standard",
        capability_level=mode,
        qualification_status="QUALIFIED",
        capability_manifest_digest="b" * 64,
        evidence_digest="e" * 64,
        measured_run_count=2,
    )


if __name__ == "__main__":
    unittest.main()

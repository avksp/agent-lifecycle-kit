from __future__ import annotations

import json
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.schemas import get_schema
from agent_lifecycle.contracts.workflow_economics_schemas import (
    build_comparable_workload_identity,
    build_workflow_economics_comparison_pair,
    validate_workflow_economics_comparison,
)


class WorkflowEconomicsSchemaTests(unittest.TestCase):
    def test_release_2_11_tracked_pair_uses_exact_schema_and_unavailable_tokens(self) -> None:
        root = Path(__file__).parents[1] / "metrics/fixtures"
        declaration = json.loads((root / "release-2-11-phase-packet-comparison-pair.json").read_text(encoding="utf-8"))
        before = json.loads((root / "release-2-11-phase-packet-before.json").read_text(encoding="utf-8"))
        after = json.loads((root / "release-2-11-phase-packet-after.json").read_text(encoding="utf-8"))

        validation = validate_workflow_economics_comparison(declaration, before, after)

        self.assertEqual(validation["status"], "PASS", validation["blockers"])
        self.assertEqual(before["tokenUsage"], "UNAVAILABLE")
        self.assertEqual(after["tokenUsage"], "UNAVAILABLE")
        self.assertEqual(after["selectedLevel"], "TASK_FAST")

    def test_exact_pair_validates_and_missing_tokens_remain_unavailable(self) -> None:
        identity = _identity()
        before = _implementation("before", "a" * 40, "2.8.0")
        after = _implementation("after", "b" * 40, "2.10.0")
        declaration = build_workflow_economics_comparison_pair(
            workload_identity=identity,
            before={key: value for key, value in before.items() if key != "role"},
            after={key: value for key, value in after.items() if key != "role"},
        )
        before_measurement = _measurement(declaration, identity, before)
        after_measurement = _measurement(declaration, identity, after)

        validation = validate_workflow_economics_comparison(
            declaration,
            before_measurement,
            after_measurement,
        )

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(before_measurement["tokenUsage"], "UNAVAILABLE")
        self.assertTrue(set(get_schema(validation["schemaVersion"])["required"]).issubset(validation))

    def test_undeclared_implementation_returns_no_comparable_baseline(self) -> None:
        identity = _identity()
        before = _implementation("before", "a" * 40, "2.8.0")
        after = _implementation("after", "b" * 40, "2.10.0")
        declaration = build_workflow_economics_comparison_pair(
            workload_identity=identity,
            before={key: value for key, value in before.items() if key != "role"},
            after={key: value for key, value in after.items() if key != "role"},
        )
        changed = _measurement(declaration, identity, {**after, "sourceRevision": "c" * 40})

        validation = validate_workflow_economics_comparison(
            declaration,
            _measurement(declaration, identity, before),
            changed,
        )

        self.assertEqual(validation["status"], "NO_COMPARABLE_BASELINE")
        self.assertIn("comparison-implementation-mismatch", {item["code"] for item in validation["blockers"]})

    def test_token_usage_accepts_only_non_negative_integer_or_unavailable(self) -> None:
        declaration, before, after = _comparison_fixture()
        before["tokenUsage"] = "estimated-1200"

        validation = validate_workflow_economics_comparison(declaration, before, after)

        self.assertEqual(validation["status"], "NO_COMPARABLE_BASELINE")
        self.assertIn("comparison-token-usage-invalid", {item["code"] for item in validation["blockers"]})
        schema = get_schema("agent-workflow-economics-measurement.v1")
        self.assertEqual(
            schema["properties"]["tokenUsage"],
            {"oneOf": [{"type": "integer", "minimum": 0}, {"const": "UNAVAILABLE"}]},
        )

    def test_identity_declaration_and_measurement_digests_are_recomputed(self) -> None:
        mutations = (
            (
                "identity",
                lambda declaration, _before, _after: declaration["workloadIdentity"].__setitem__(
                    "name", "substituted-workload"
                ),
                "comparison-workload-identity-digest-invalid",
            ),
            (
                "declaration",
                lambda declaration, _before, _after: declaration["after"].__setitem__("sourceRevision", "c" * 40),
                "comparison-pair-digest-invalid",
            ),
            (
                "measurement",
                lambda _declaration, _before, after: after.__setitem__("outputBytes", 101),
                "comparison-measurement-digest-invalid",
            ),
        )
        for label, mutate, expected_code in mutations:
            with self.subTest(label=label):
                declaration, before, after = _comparison_fixture()
                mutate(declaration, before, after)

                validation = validate_workflow_economics_comparison(declaration, before, after)

                self.assertEqual(validation["status"], "NO_COMPARABLE_BASELINE")
                self.assertIn(expected_code, {item["code"] for item in validation["blockers"]})


def _identity() -> dict[str, object]:
    return build_comparable_workload_identity(
        name="two-transition-continuation",
        fixture_shape_digest="1" * 64,
        workload_input_digest="2" * 64,
        environment_digest="3" * 64,
        required_gate_floor_digest="4" * 64,
    )


def _implementation(role: str, source: str, version: str) -> dict[str, object]:
    return {
        "role": role,
        "sourceRevision": source,
        "coreVersion": version,
        "publicationVersions": {"root": version, "adapter": version},
    }


def _measurement(
    declaration: dict[str, object],
    identity: dict[str, object],
    implementation: dict[str, object],
) -> dict[str, object]:
    body = {
        "schemaVersion": "agent-workflow-economics-measurement.v1",
        "role": implementation["role"],
        "comparisonPairId": declaration["comparisonPairId"],
        "workloadIdentityDigest": identity["workloadIdentityDigest"],
        "implementation": implementation,
        "commandCount": 2,
        "outputBytes": 100,
        "wallSeconds": 0.1,
        "tokenUsage": "UNAVAILABLE",
    }
    return {**body, "measurementDigest": canonical_digest(body)}


def _comparison_fixture() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    identity = _identity()
    before = _implementation("before", "a" * 40, "2.8.0")
    after = _implementation("after", "b" * 40, "2.10.0")
    declaration = build_workflow_economics_comparison_pair(
        workload_identity=identity,
        before={key: value for key, value in before.items() if key != "role"},
        after={key: value for key, value in after.items() if key != "role"},
    )
    return declaration, _measurement(declaration, identity, before), _measurement(declaration, identity, after)


if __name__ == "__main__":
    unittest.main()

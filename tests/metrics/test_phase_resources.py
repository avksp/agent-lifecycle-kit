from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.metrics import (
    MAX_PHASE_RESOURCE_ENTRIES,
    build_phase_resource_measurement,
    validate_phase_resource_measurement,
)


class PhaseResourceTests(unittest.TestCase):
    def test_phase_measurement_reuses_usage_export_without_money(self) -> None:
        measurement = build_phase_resource_measurement(
            [
                {
                    "phaseId": "implementation",
                    "phaseKind": "code",
                    "taskId": "WS22-04",
                    "tokens": {"input": 100, "output": 25},
                    "steps": 2,
                    "resources": {"toolCalls": 3, "contextBytes": 4096},
                    "durationMs": 1200,
                    "receiptDigests": ["a" * 64],
                },
                {
                    "phaseId": "validation",
                    "phaseKind": "test",
                    "tokens": {"input": 20, "output": 5, "total": 25},
                    "steps": 1,
                    "resources": {"validationRuns": 1},
                    "durationMs": 800,
                    "receiptDigests": [],
                },
            ],
            lineage={"runId": "run-22"},
        )

        validation = validate_phase_resource_measurement(measurement)

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(measurement["phaseCount"], 2)
        self.assertEqual(measurement["usageExport"]["schemaVersion"], "agent-usage-export.v1")
        self.assertEqual(measurement["totals"]["tokens"]["total"], 150)
        self.assertEqual(measurement["totals"]["hostReportedCost"]["entryCount"], 0)
        self.assertNotIn("monetary", measurement["phases"][0])
        self.assertFalse(measurement["productionPromotionClaimed"])

    def test_monetary_phase_fields_are_rejected(self) -> None:
        with self.assertRaises(LifecycleError):
            build_phase_resource_measurement(
                [
                    {
                        "phaseId": "implementation",
                        "phaseKind": "code",
                        "tokens": {"input": 1, "output": 1},
                        "steps": 1,
                        "resources": {},
                        "durationMs": 1,
                        "receiptDigests": [],
                        "cost_usd": 1.0,
                    }
                ]
            )

    def test_phase_count_is_bounded_in_build_and_validation(self) -> None:
        phases = [_phase(f"phase-{index}") for index in range(MAX_PHASE_RESOURCE_ENTRIES)]
        self.assertEqual(build_phase_resource_measurement(phases)["phaseCount"], MAX_PHASE_RESOURCE_ENTRIES)
        with self.assertRaises(LifecycleError) as raised:
            build_phase_resource_measurement([*phases, _phase("overflow")])
        self.assertEqual(raised.exception.code, "phase-resource-entry-limit")

        measurement = build_phase_resource_measurement(phases)
        measurement["phases"].append(dict(measurement["phases"][-1], entryId="phase-257"))
        measurement["phaseCount"] = len(measurement["phases"])
        measurement["measurementDigest"] = canonical_digest(
            {key: value for key, value in measurement.items() if key != "measurementDigest"}
        )
        validation = validate_phase_resource_measurement(measurement)
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("phase-resource-entry-limit", {item["code"] for item in validation["blockers"]})

    def test_source_artifact_digest_is_validated(self) -> None:
        with self.assertRaises(LifecycleError):
            build_phase_resource_measurement(
                [_phase("planning")],
                source_artifacts=[
                    {
                        "path": "evidence/source.json",
                        "sha256": "invalid",
                        "bytes": 10,
                        "schemaVersion": "example.v1",
                        "payloadDigest": "0" * 64,
                    }
                ],
            )

    def test_invalid_token_duration_and_resource_fields_fail_closed(self) -> None:
        mutations = [
            ("tokens", {"input": "1", "output": 1, "total": 2}),
            ("durationMs", -1),
            ("resources", {"unsupported": 1}),
        ]
        for field, value in mutations:
            with self.subTest(field=field):
                phase = _phase("invalid")
                phase[field] = value
                with self.assertRaises(LifecycleError):
                    build_phase_resource_measurement([phase])


def _phase(phase_id: str) -> dict[str, object]:
    return {
        "phaseId": phase_id,
        "phaseKind": "IMPLEMENTATION",
        "tokens": {"input": 1, "output": 1, "total": 2},
        "steps": 1,
        "resources": {},
        "durationMs": 1,
        "receiptDigests": [],
    }


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.workflow_economics_schemas import (
    validate_workflow_economics_comparison,
)
from agent_lifecycle.metrics import (
    MAX_PHASE_RESOURCE_ENTRIES,
    build_phase_resource_measurement,
    validate_phase_resource_measurement,
)


class PhaseResourceTests(unittest.TestCase):
    def test_release_2_10_economics_pair_is_predeclared_exact_and_more_compact(self) -> None:
        root = Path(__file__).parent / "fixtures"
        declaration = _load(root / "release-2-10-continuation-comparison-pair.json")
        before = _load(root / "release-2-8-continuation-baseline.json")
        after = _load(root / "release-2-10-continuation-baseline.json")

        validation = validate_workflow_economics_comparison(declaration, before, after)

        self.assertEqual(validation["status"], "PASS", validation["blockers"])
        self.assertLess(declaration["declaredAt"], before["measuredAt"])
        self.assertLess(declaration["declaredAt"], after["measuredAt"])
        self.assertEqual(
            declaration["before"]["sourceRevision"],
            "0ac782e765e4e6c2d528c095783c5bd0eb7b32b3",
        )
        self.assertEqual(
            declaration["after"]["sourceRevision"],
            "9d84051344a9c0a066eb09d964e19457b5c12bea",
        )
        for role, version in (("before", "2.8.0"), ("after", "2.10.0")):
            implementation = declaration[role]
            self.assertEqual(implementation["coreVersion"], version)
            self.assertEqual(set(implementation["publicationVersions"].values()), {version})
        self.assertEqual(before["commandCount"], 4)
        self.assertEqual(after["commandCount"], 1)
        self.assertEqual(before["transitionCount"], after["transitionCount"])
        self.assertEqual(before["eventTypes"], after["eventTypes"])
        self.assertEqual(before["finalStateRevision"], after["finalStateRevision"])
        self.assertEqual(before["modelTurns"], after["modelTurns"])
        self.assertEqual(before["tokenUsage"], "UNAVAILABLE")
        self.assertEqual(after["tokenUsage"], "UNAVAILABLE")
        self.assertNotIn("reductionPercent", before)
        self.assertNotIn("reductionPercent", after)
        self.assertEqual(after["routeObservations"]["direct"]["commandCount"], 2)
        self.assertEqual(after["routeObservations"]["one-step"]["commandCount"], 4)
        self.assertEqual(after["routeObservations"]["bounded"]["commandCount"], 1)

    def test_release_2_10_economics_mutations_have_no_comparable_baseline(self) -> None:
        root = Path(__file__).parent / "fixtures"
        original_declaration = _load(root / "release-2-10-continuation-comparison-pair.json")
        original_before = _load(root / "release-2-8-continuation-baseline.json")
        original_after = _load(root / "release-2-10-continuation-baseline.json")
        mutations = (
            ("role", _mutate_role),
            ("source", _mutate_source),
            ("version", _mutate_version),
            ("gate-floor", _mutate_gate_floor),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                declaration = deepcopy(original_declaration)
                before = deepcopy(original_before)
                after = deepcopy(original_after)
                mutate(declaration, before, after)

                validation = validate_workflow_economics_comparison(declaration, before, after)

                self.assertEqual(validation["status"], "NO_COMPARABLE_BASELINE")
                self.assertTrue(validation["blockers"])

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


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _refresh_digest(payload: dict[str, object], field: str) -> None:
    payload[field] = canonical_digest({key: value for key, value in payload.items() if key != field})


def _mutate_role(
    _declaration: dict[str, object], _before: dict[str, object], after: dict[str, object]
) -> None:
    after["role"] = "before"
    _refresh_digest(after, "measurementDigest")


def _mutate_source(
    _declaration: dict[str, object], _before: dict[str, object], after: dict[str, object]
) -> None:
    implementation = after["implementation"]
    assert isinstance(implementation, dict)
    implementation["sourceRevision"] = "f" * 40
    _refresh_digest(after, "measurementDigest")


def _mutate_version(
    _declaration: dict[str, object], _before: dict[str, object], after: dict[str, object]
) -> None:
    implementation = after["implementation"]
    assert isinstance(implementation, dict)
    implementation["coreVersion"] = "2.10.1"
    _refresh_digest(after, "measurementDigest")


def _mutate_gate_floor(
    declaration: dict[str, object], _before: dict[str, object], _after: dict[str, object]
) -> None:
    identity = declaration["workloadIdentity"]
    assert isinstance(identity, dict)
    identity["requiredGateFloorDigest"] = "f" * 64
    _refresh_digest(identity, "workloadIdentityDigest")
    _refresh_digest(declaration, "comparisonPairId")


if __name__ == "__main__":
    unittest.main()

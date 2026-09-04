from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, canonical_digest, write_json_create
from agent_lifecycle.metrics import (
    build_phase_resource_measurement,
    build_release_accounting,
    build_release_accounting_source,
    validate_release_accounting,
    validate_release_accounting_source,
)


class ReleaseAccountingTests(unittest.TestCase):
    def test_release_2_13_strategy_fixture_is_comparable_and_non_authoritative(self) -> None:
        fixture_root = Path(__file__).parent / "fixtures"
        baseline = json.loads((fixture_root / "release-2-13-strategy-baseline.json").read_text(encoding="utf-8"))
        comparison_pair = json.loads(
            (fixture_root / "release-2-10-continuation-comparison-pair.json").read_text(encoding="utf-8")
        )

        self.assertEqual(baseline["schemaVersion"], "agent-execution-strategy-economics-baseline.v1")
        self.assertEqual(baseline["releaseId"], "2.13.0")
        self.assertEqual(baseline["workloadIdentity"], comparison_pair["workloadIdentity"])
        self.assertEqual({item["riskTier"] for item in baseline["cases"]}, {"S0", "S1", "S2"})
        for case in baseline["cases"]:
            with self.subTest(case=case["caseId"]):
                automatic = case["automaticAdoption"]
                manual = case["explicitManualRouting"]
                self.assertEqual(automatic["status"], "MEASURED")
                self.assertEqual(manual["status"], "MEASURED")
                self.assertEqual(automatic["commandCount"], 1)
                self.assertEqual(manual["commandCount"], 2)
                self.assertEqual(automatic["modelTurns"], 0)
                self.assertEqual(manual["modelTurns"], 0)
                self.assertGreater(automatic["packetBytes"], 0)
                self.assertGreater(manual["packetBytes"], 0)
                self.assertEqual(manual["wallSeconds"], {"status": "UNAVAILABLE", "value": None})
                self.assertTrue(case["comparison"]["qualityFloorPreserved"])
                self.assertFalse(case["comparison"]["ratioAuthority"])
        self.assertEqual(
            baseline["modelTelemetry"],
            {
                "status": "UNAVAILABLE",
                "inputTokens": None,
                "cachedInputTokens": None,
                "outputTokens": None,
                "reason": "NO_MODEL_OR_HOST_WAS_CALLED_BY_THE_DETERMINISTIC_POLICY_MEASUREMENT",
            },
        )
        self.assertEqual(set(baseline["gateOutcomes"].values()), {"PASS"})
        self.assertTrue(baseline["qualityFloorPreserved"])
        self.assertTrue(baseline["releaseFullRequired"])
        self.assertFalse(baseline["automaticPolicyMutation"])
        self.assertFalse(baseline["productionPromotionClaimed"])
        body = {key: value for key, value in baseline.items() if key != "fixtureDigest"}
        self.assertEqual(baseline["fixtureDigest"], canonical_digest(body))
        serialized = json.dumps(baseline, sort_keys=True)
        for private_marker in ("/" + "Volumes/", "/" + "Users/", "file" + "://", "C:" + "\\\\"):
            self.assertNotIn(private_marker, serialized)

    def test_release_2_11_fixture_separates_workflow_implementation_audit_and_remediation(self) -> None:
        fixture_path = Path(__file__).parent / "fixtures/release-2-11-accounting.json"
        accounting = json.loads(fixture_path.read_text(encoding="utf-8"))

        self.assertEqual(validate_release_accounting(accounting)["status"], "PASS")
        self.assertEqual(accounting["releaseId"], "2.11.0")
        expected_wall = {
            "alkProcess": ("PARTIAL", 128_000),
            "implementation": ("TIME_WINDOW_ONLY", 7_402_000),
            "audit": ("TIME_WINDOW_ONLY", 7_556_000),
            "postAuditRemediation": ("TIME_WINDOW_ONLY", 974_000),
        }
        for view, (status, value) in expected_wall.items():
            with self.subTest(view=view):
                self.assertEqual(
                    accounting["views"][view]["metrics"]["elapsedWallMs"],
                    {"status": status, "value": value},
                )
                self.assertEqual(
                    accounting["views"][view]["metrics"]["tokens"],
                    {"status": "UNAVAILABLE", "value": None},
                )
        self.assertEqual(accounting["views"]["alkProcess"]["metrics"]["steps"]["value"], 19)
        self.assertEqual(
            accounting["exclusions"],
            [
                {
                    "entryId": "post-cutoff-work-after-20260831t200842z",
                    "reason": "NON_ADDITIVE_SCOPE",
                }
            ],
        )
        self.assertEqual(
            accounting["provenance"]["identities"]["sourceRevision"]["declared"],
            "a611ef87abffed6fee9a24301d12e69f3a5af38f",
        )
        self.assertEqual(accounting["provenance"]["identities"]["controllerVersion"]["declared"], "2.8.0")
        self.assertEqual(accounting["provenance"]["identities"]["coreVersion"]["declared"], "2.11.0")
        phase_packet_after = json.loads(
            (fixture_path.parent / "release-2-11-phase-packet-after.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            accounting["provenance"]["identities"]["measurementDigest"]["declared"],
            phase_packet_after["measurementDigest"],
        )
        self.assertTrue(
            all(identity["status"] == "MATCHED" for identity in accounting["provenance"]["identities"].values())
        )
        self.assertEqual(
            accounting["accountingDigest"],
            "a005d07491d27d55a502cf210ef778b1797299fa3e9c510d6714b9bf5195bb72",
        )
        self.assertFalse(accounting["productionPromotionClaimed"])

    def test_release_2_10_fixture_separates_windows_and_preserves_unavailable_tokens(self) -> None:
        fixture_path = Path(__file__).parent / "fixtures/release-2-10-accounting.json"
        accounting = json.loads(fixture_path.read_text(encoding="utf-8"))

        self.assertEqual(validate_release_accounting(accounting)["status"], "PASS")
        self.assertEqual(accounting["releaseId"], "2.10.0")
        expected_wall = {
            "alkProcess": ("PARTIAL", 77_000),
            "implementation": ("TIME_WINDOW_ONLY", 3_834_000),
            "audit": ("TIME_WINDOW_ONLY", 7_806_000),
            "postAuditRemediation": ("TIME_WINDOW_ONLY", 1_191_000),
        }
        for view, (status, value) in expected_wall.items():
            with self.subTest(view=view):
                self.assertEqual(
                    accounting["views"][view]["metrics"]["elapsedWallMs"],
                    {"status": status, "value": value},
                )
                self.assertEqual(
                    accounting["views"][view]["metrics"]["tokens"],
                    {"status": "UNAVAILABLE", "value": None},
                )
        self.assertEqual(accounting["views"]["alkProcess"]["metrics"]["steps"]["value"], 16)
        self.assertEqual(
            accounting["exclusions"],
            [
                {
                    "entryId": "post-cutoff-work-after-20260831t081722z",
                    "reason": "NON_ADDITIVE_SCOPE",
                }
            ],
        )
        self.assertEqual(
            accounting["provenance"]["identities"]["sourceRevision"]["declared"],
            "90cb0c921fe04cbdcaba2fecb590fe6f51f194b9",
        )
        self.assertEqual(
            accounting["provenance"]["identities"]["measurementDigest"]["declared"],
            "dd001f89e122c2a9da56662b2aff1fe1549d291906d60231eeeb648b0b3c7a04",
        )
        self.assertTrue(
            all(identity["status"] == "MATCHED" for identity in accounting["provenance"]["identities"].values())
        )
        self.assertEqual(
            accounting["accountingDigest"],
            "2e7ad9618391e7844c3b28be65c366a12f73951ba1924ca901a328f4e646c925",
        )
        self.assertFalse(accounting["productionPromotionClaimed"])

    def test_release_2_9_fixture_preserves_bounded_partial_measurements(self) -> None:
        fixture_path = Path(__file__).parent / "fixtures/release-2-9-accounting.json"
        accounting = json.loads(fixture_path.read_text(encoding="utf-8"))

        self.assertEqual(validate_release_accounting(accounting)["status"], "PASS")
        self.assertEqual(accounting["releaseId"], "2.9.0")
        self.assertEqual(
            set(accounting["views"]),
            {
                "alkProcess",
                "implementation",
                "audit",
                "postAuditRemediation",
            },
        )
        self.assertEqual(
            accounting["views"]["audit"]["metrics"]["tokens"],
            {
                "status": "PARTIAL",
                "value": 467_541,
            },
        )
        self.assertEqual(
            accounting["views"]["implementation"]["metrics"]["tokens"],
            {
                "status": "UNAVAILABLE",
                "value": None,
            },
        )
        self.assertEqual(
            accounting["views"]["postAuditRemediation"]["metrics"]["tokens"],
            {
                "status": "UNAVAILABLE",
                "value": None,
            },
        )
        self.assertEqual(
            accounting["views"]["alkProcess"]["metrics"]["elapsedWallMs"],
            {
                "status": "PARTIAL",
                "value": 1_240_263,
            },
        )
        self.assertEqual(
            accounting["views"]["implementation"]["metrics"]["elapsedWallMs"],
            {
                "status": "TIME_WINDOW_ONLY",
                "value": 1_783_013,
            },
        )
        self.assertEqual(
            accounting["views"]["audit"]["metrics"]["elapsedWallMs"],
            {
                "status": "PARTIAL",
                "value": 2_158_737,
            },
        )
        self.assertEqual(
            accounting["views"]["postAuditRemediation"]["metrics"]["elapsedWallMs"],
            {
                "status": "TIME_WINDOW_ONLY",
                "value": 831_000,
            },
        )
        for field in (
            "controllerVersion",
            "coreVersion",
            "hostPluginVersion",
            "skillPackageVersion",
            "runAlkVersion",
        ):
            self.assertEqual(accounting["provenance"]["identities"][field]["declared"], "2.8.0")
            self.assertEqual(accounting["provenance"]["identities"][field]["status"], "MATCHED")
        self.assertEqual(
            accounting["provenance"]["identities"]["sourceRevision"]["declared"],
            "0ac782e765e4e6c2d528c095783c5bd0eb7b32b3",
        )
        self.assertEqual(
            accounting["accountingDigest"],
            "7f9e594321aa31c1f12f00a25dd7338f28515ab9f50282304a1fc26f8fa1dcc6",
        )
        serialized = json.dumps(accounting, sort_keys=True)
        private_markers = (
            "/" + "Volumes/",
            "/" + "Users/",
            "file" + "://",
            "C:" + "\\\\",
        )
        for private_marker in private_markers:
            self.assertNotIn(private_marker, serialized)
        self.assertFalse(accounting["productionPromotionClaimed"])

    def test_accounting_preserves_wall_compute_availability_and_additivity(self) -> None:
        source = build_release_accounting_source(
            "2.6.0",
            [
                _entry(
                    "audit-panel",
                    "audit",
                    "productValidation",
                    tokens=9_654_447,
                    wall=3_649_237,
                    compute=4_061_376,
                ),
                _unavailable_entry("implementation", "implementation", "implementation"),
                _entry(
                    "multi-release-goal",
                    "alkProcess",
                    "coordination",
                    tokens=1_970_471,
                    wall=8_611_000,
                    compute=8_611_000,
                    scope_additive=False,
                ),
            ],
            provenance={
                "controllerVersion": "2.6.0",
                "coreVersion": "2.6.0",
                "hostPluginVersion": "2.4.0",
                "skillPackageVersion": "2.4.0",
                "runAlkVersion": "1.80.0",
                "runId": "R04",
                "sourceRevision": "abc123",
                "measurementDigest": "1" * 64,
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json_create(root / "accounting-source.json", source)
            accounting = build_release_accounting(
                "2.6.0",
                [Path("accounting-source.json")],
                project_root=root,
                declared_provenance={
                    "controllerVersion": "2.6.0",
                    "coreVersion": "2.6.0",
                    "hostPluginVersion": "2.5.0",
                },
            )

        self.assertEqual(validate_release_accounting(accounting)["status"], "PASS")
        self.assertEqual(accounting["views"]["audit"]["metrics"]["elapsedWallMs"]["value"], 3_649_237)
        self.assertEqual(accounting["views"]["audit"]["metrics"]["computeMs"]["value"], 4_061_376)
        self.assertEqual(accounting["views"]["implementation"]["metrics"]["tokens"]["status"], "UNAVAILABLE")
        self.assertIsNone(accounting["views"]["implementation"]["metrics"]["tokens"]["value"])
        self.assertEqual(accounting["totals"]["metrics"]["tokens"]["value"], 9_654_447)
        self.assertEqual(accounting["exclusions"], [{"entryId": "multi-release-goal", "reason": "NON_ADDITIVE_SCOPE"}])
        self.assertEqual(accounting["provenance"]["identities"]["coreVersion"]["status"], "MATCHED")
        self.assertEqual(accounting["provenance"]["identities"]["hostPluginVersion"]["status"], "MISMATCH")
        self.assertFalse(accounting["provenance"]["confidencePromotionClaimed"])

    def test_provenance_mutation_invalidates_digest(self) -> None:
        source = build_release_accounting_source("2.6.0", [_entry("audit", "audit", "productValidation")])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json_create(root / "source.json", source)
            accounting = build_release_accounting("2.6.0", [Path("source.json")], project_root=root)

        accounting["provenance"]["identities"]["coreVersion"]["declared"] = "2.6.1"
        validation = validate_release_accounting(accounting)
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("release-accounting-digest-mismatch", {item["code"] for item in validation["blockers"]})

    def test_every_provenance_identity_reports_mismatch_independently(self) -> None:
        observed = {
            "controllerVersion": "observed-controller",
            "coreVersion": "observed-core",
            "hostPluginVersion": "observed-plugin",
            "skillPackageVersion": "observed-skill",
            "runAlkVersion": "observed-run-version",
            "runId": "observed-run",
            "sourceRevision": "observed-source",
            "measurementDigest": "1" * 64,
        }
        declared = {
            "controllerVersion": "declared-controller",
            "coreVersion": "declared-core",
            "hostPluginVersion": "declared-plugin",
            "skillPackageVersion": "declared-skill",
            "runAlkVersion": "declared-run-version",
            "runId": "declared-run",
            "sourceRevision": "declared-source",
            "measurementDigest": "2" * 64,
        }
        source = build_release_accounting_source(
            "2.6.0",
            [_entry("audit", "audit", "productValidation")],
            provenance=observed,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json_create(root / "source.json", source)
            accounting = build_release_accounting(
                "2.6.0",
                [Path("source.json")],
                project_root=root,
                declared_provenance=declared,
            )

        for field in declared:
            self.assertEqual(accounting["provenance"]["identities"][field]["status"], "MISMATCH")
        self.assertNotIn("ATTESTED", repr(accounting["provenance"]))

    def test_recomputed_digest_cannot_hide_false_provenance_status(self) -> None:
        source = build_release_accounting_source(
            "2.6.0",
            [_entry("audit", "audit", "productValidation")],
            provenance={"coreVersion": "2.6.0"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json_create(root / "source.json", source)
            accounting = build_release_accounting(
                "2.6.0",
                [Path("source.json")],
                project_root=root,
                declared_provenance={"coreVersion": "2.5.0"},
            )

        accounting["provenance"]["identities"]["coreVersion"]["status"] = "MATCHED"
        accounting["provenance"]["status"] = "REPORTED"
        accounting["accountingDigest"] = canonical_digest(
            {key: value for key, value in accounting.items() if key != "accountingDigest"}
        )
        validation = validate_release_accounting(accounting)
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn(
            "release-accounting-provenance-status-mismatch",
            {item["code"] for item in validation["blockers"]},
        )

    def test_source_rejects_attested_metrics_and_duplicate_ids(self) -> None:
        invalid = _entry("audit", "audit", "productValidation")
        invalid["metrics"]["tokens"]["status"] = "ATTESTED"
        with self.assertRaisesRegex(LifecycleError, "status is invalid"):
            build_release_accounting_source("2.6.0", [invalid])
        with self.assertRaisesRegex(LifecycleError, "unique"):
            build_release_accounting_source(
                "2.6.0",
                [_entry("same", "audit", "productValidation"), _entry("same", "audit", "productValidation")],
            )

    def test_source_digest_and_metric_mutations_fail_validation(self) -> None:
        source = build_release_accounting_source("2.6.0", [_entry("audit", "audit", "productValidation")])
        source["entries"][0]["metrics"]["elapsedWallMs"]["value"] = -1
        source["sourceDigest"] = canonical_digest(
            {key: value for key, value in source.items() if key != "sourceDigest"}
        )
        validation = validate_release_accounting_source(source)
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("release-accounting-metric-invalid", {item["code"] for item in validation["blockers"]})

    def test_phase_measurement_maps_to_release_views_and_declared_totals(self) -> None:
        measurement = build_phase_resource_measurement(
            [
                _phase("planning", "PLANNING", 10),
                _phase("implementation", "IMPLEMENTATION", 20),
                _phase("audit", "AUDIT", 30),
                _phase("remediation", "REMEDIATION", 40),
            ],
            lineage={"coreVersion": "2.6.0", "sourceRevision": "abc123"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json_create(root / "phases.json", measurement)
            accounting = build_release_accounting("2.6.0", [Path("phases.json")], project_root=root)

        self.assertEqual(accounting["totals"]["metrics"]["tokens"]["value"], 100)
        self.assertEqual(accounting["views"]["alkProcess"]["metrics"]["tokens"]["value"], 10)
        self.assertEqual(accounting["views"]["implementation"]["metrics"]["tokens"]["value"], 20)
        self.assertEqual(accounting["views"]["audit"]["metrics"]["tokens"]["value"], 30)
        self.assertEqual(accounting["views"]["postAuditRemediation"]["metrics"]["tokens"]["value"], 40)
        self.assertEqual(
            accounting["provenance"]["identities"]["measurementDigest"]["observed"],
            [measurement["measurementDigest"]],
        )

    def test_duplicate_source_artifact_cannot_double_account_totals(self) -> None:
        measurement = build_phase_resource_measurement([_phase("audit", "AUDIT", 30)])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json_create(root / "phases.json", measurement)
            with self.assertRaisesRegex(LifecycleError, "unique content"):
                build_release_accounting(
                    "2.6.0",
                    [Path("phases.json"), Path("phases.json")],
                    project_root=root,
                )

    def test_recomputed_digest_cannot_hide_duplicate_source_artifact(self) -> None:
        source = build_release_accounting_source("2.6.0", [_entry("audit", "audit", "productValidation")])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json_create(root / "source.json", source)
            accounting = build_release_accounting("2.6.0", [Path("source.json")], project_root=root)

        accounting["sourceArtifacts"].append(dict(accounting["sourceArtifacts"][0]))
        accounting["provenance"]["sourceArtifactDigests"].append(accounting["sourceArtifacts"][0]["sha256"])
        accounting["accountingDigest"] = canonical_digest(
            {key: value for key, value in accounting.items() if key != "accountingDigest"}
        )
        validation = validate_release_accounting(accounting)
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn(
            "release-accounting-source-artifact-duplicate",
            {item["code"] for item in validation["blockers"]},
        )

    def test_time_window_status_is_preserved_without_claiming_measurement(self) -> None:
        entry = _entry("remediation", "postAuditRemediation", "implementation")
        entry["metrics"]["elapsedWallMs"] = _metric("TIME_WINDOW_ONLY", 412_139)
        source = build_release_accounting_source("2.6.0", [entry])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json_create(root / "source.json", source)
            accounting = build_release_accounting("2.6.0", [Path("source.json")], project_root=root)

        elapsed = accounting["views"]["postAuditRemediation"]["metrics"]["elapsedWallMs"]
        self.assertEqual(elapsed, {"status": "TIME_WINDOW_ONLY", "value": 412_139})


def _entry(
    entry_id: str,
    view: str,
    category: str,
    *,
    tokens: int = 100,
    wall: int = 10,
    compute: int = 20,
    scope_additive: bool = True,
) -> dict:
    return {
        "entryId": entry_id,
        "view": view,
        "costCategory": category,
        "scope": {"kind": "release", "id": "2.6.0", "additive": scope_additive},
        "metrics": {
            "tokens": _metric("MEASURED", tokens),
            "steps": _metric("MEASURED", 1),
            "elapsedWallMs": _metric("MEASURED", wall),
            "computeMs": _metric("MEASURED", compute),
        },
    }


def _unavailable_entry(entry_id: str, view: str, category: str) -> dict:
    return {
        "entryId": entry_id,
        "view": view,
        "costCategory": category,
        "scope": {"kind": "release", "id": "2.6.0", "additive": True},
        "metrics": {
            key: _metric("UNAVAILABLE", None, additive=False)
            for key in ("tokens", "steps", "elapsedWallMs", "computeMs")
        },
    }


def _metric(status: str, value: int | None, *, additive: bool = True) -> dict:
    return {"status": status, "value": value, "additive": additive}


def _phase(phase_id: str, phase_kind: str, total_tokens: int) -> dict:
    return {
        "phaseId": phase_id,
        "phaseKind": phase_kind,
        "tokens": {"input": total_tokens, "output": 0, "total": total_tokens},
        "steps": 1,
        "resources": {},
        "durationMs": 10,
        "receiptDigests": [],
    }


if __name__ == "__main__":
    unittest.main()

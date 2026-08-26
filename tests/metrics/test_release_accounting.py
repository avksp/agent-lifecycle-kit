from __future__ import annotations

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
        accounting["provenance"]["sourceArtifactDigests"].append(
            accounting["sourceArtifacts"][0]["sha256"]
        )
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

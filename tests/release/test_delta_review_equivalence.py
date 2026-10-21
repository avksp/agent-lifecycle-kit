from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.release.validate_delta_review_equivalence import FIXTURES, validate_equivalence

from agent_lifecycle.contracts import LifecycleError, canonical_digest


class DeltaReviewEquivalenceTests(unittest.TestCase):
    def test_paired_workload_and_all_refusals_are_checked(self):
        report = validate_equivalence()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["caseCount"], 25)
        pairs = report["planReviewComparison"]["pairs"]
        self.assertEqual(len(pairs), 6)
        for pair in pairs:
            for field in ("findings", "readiness", "blockingGates"):
                self.assertEqual(pair["full"][field], pair["delta"][field])
        seeded = [p for p in pairs if p["caseId"].endswith("omission")]
        self.assertTrue(all(p["full"]["readiness"] == "CHANGES_REQUIRED" for p in seeded))
        reasons = {r["caseId"]: r["reason"] for r in report["refusalCases"]}
        self.assertEqual(reasons["duplicate-seat"], "review-duplicate-seat")
        self.assertEqual(reasons["chain-depth-cap"], "review-chain-limit")
        self.assertEqual(reasons["replayed-delivery"], "DEDUPLICATED_WITHOUT_NEW_VOICE")
        self.assertFalse(report["actualModelGeneration"])
        self.assertIsNone(report["modelTokens"])
        self.assertIsNone(report["modelTokenReductionPercent"])

    def test_fixture_subject_drift_cannot_be_reported_as_equivalent(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for source in FIXTURES.glob("delta-review-*.json"):
                (directory / source.name).write_bytes(source.read_bytes())
            path = directory / "delta-review-full.json"
            value = json.loads(path.read_bytes())
            value["review"]["subject"]["manifest"]["planRevision"] = 99
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(LifecycleError):
                validate_equivalence(directory)

    def test_eligible_and_full_really_share_the_same_current_inputs(self):
        full = json.loads((FIXTURES / "delta-review-full.json").read_bytes())
        eligible = json.loads((FIXTURES / "delta-review-eligible.json").read_bytes())
        self.assertEqual(full["review"]["subject"], eligible["subject"])
        before = eligible["baseline"]["subject"]
        after = eligible["subject"]
        self.assertEqual(before["runtimeInputs"], after["runtimeInputs"])
        self.assertEqual(before["manifest"]["specification"], after["manifest"]["specification"])
        roles = {Path(p).name for p in after["fileDigests"]}
        self.assertIn("review-budget.md", roles)
        self.assertIn("plan.manifest.json", roles)
        self.assertTrue(set(before["manifest"]["forbiddenWrites"]) < set(after["manifest"]["forbiddenWrites"]))

    def test_mismatch_report_is_not_forged_into_success(self):
        from agent_lifecycle.metrics.audit_efficiency import (
            build_audit_efficiency_report,
            validate_audit_efficiency_report,
        )

        report = validate_equivalence()
        pairs = copy.deepcopy(report["planReviewComparison"]["pairs"])
        pairs[0]["delta"]["blockingGates"] = ["missing-gate"]
        baseline = FIXTURES.parents[1] / "metrics/fixtures/release-2-6-accounting-baseline.json"
        measurement = json.loads(baseline.read_bytes())
        efficiency = build_audit_efficiency_report(measurement, plan_review_pairs=pairs)
        self.assertEqual(efficiency["status"], "FAIL")
        efficiency["status"] = "PASS"
        efficiency["reportDigest"] = canonical_digest({k: v for k, v in efficiency.items() if k != "reportDigest"})
        self.assertEqual(validate_audit_efficiency_report(efficiency)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CONFORMANCE_ROOT = ROOT / "conformance"
FIXTURES_ROOT = ROOT / "fixtures" / "synthetic"
EVALS_ROOT = ROOT / "evals" / "synthetic"

PROJECT_MARKERS = (
    "board" + "-app",
    "board" + "2.0",
    "Dot" + "Space",
    "/Vol" + "umes/",
    "/Us" + "ers/",
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain a JSON object")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SyntheticConformanceTests(unittest.TestCase):
    def test_fixture_index_is_content_addressed(self) -> None:
        index = load_json(CONFORMANCE_ROOT / "fixtures.index.json")
        entries = index.get("fixtures")
        self.assertIsInstance(entries, list)
        self.assertGreaterEqual(len(entries), 6)

        indexed_paths = set()
        for entry in entries:
            with self.subTest(path=entry.get("path")):
                path = ROOT / entry["path"]
                self.assertTrue(path.is_file())
                self.assertEqual(entry["bytes"], path.stat().st_size)
                self.assertEqual(entry["sha256"], sha256(path))
                indexed_paths.add(entry["path"])

        for path in FIXTURES_ROOT.glob("*.json"):
            self.assertIn(path.relative_to(ROOT).as_posix(), indexed_paths)

    def test_synthetic_scenarios_cover_required_taxonomy(self) -> None:
        taxonomy = load_json(CONFORMANCE_ROOT / "core" / "scenario-taxonomy.v1.json")
        tags: set[str] = set()
        tiers: set[str] = set()
        operating_systems: set[str] = set()

        for path in FIXTURES_ROOT.glob("*.json"):
            fixture = load_json(path)
            tags.update(fixture.get("tags", []))
            tiers.add(fixture.get("sddTier", ""))
            operating_systems.update(tag for tag in fixture.get("tags", []) if tag in {"linux", "macos", "windows"})
            for case in fixture.get("cases", []):
                tags.update(case.get("tags", []))

        self.assertTrue(set(taxonomy["requiredSddTiers"]).issubset(tiers))
        self.assertTrue(set(taxonomy["requiredOperatingSystems"]).issubset(operating_systems))
        self.assertTrue(set(taxonomy["requiredCoverageTags"]).issubset(tags))

    def test_adapter_baseline_is_offline_and_fail_closed(self) -> None:
        baseline = load_json(CONFORMANCE_ROOT / "core" / "adapter-baseline.v1.json")
        hosts = {item["host"]: item for item in baseline["hostMatrix"]}

        self.assertEqual(set(hosts), {"codex", "claude-code", "cursor", "hermes", "opencode"})
        self.assertEqual(baseline["maturityRules"]["requiredReleaseMaturity"], "EXPERIMENTAL")
        self.assertIsNone(baseline["maturityRules"]["liveTestedHostRange"])
        self.assertEqual(baseline["maturityRules"]["unsupportedOperationPolicy"], "fail-closed")
        self.assertEqual(baseline["contractCompatibility"]["rangeKind"], "closed-offline")

        required_operations = set(baseline["requiredOperations"])
        self.assertIn("install", required_operations)
        self.assertIn("discover", required_operations)
        self.assertIn("final-audit", required_operations)
        for host in hosts.values():
            self.assertTrue(host["offlineInstallDiscoveryRequired"])
            self.assertEqual(host["declaredMaturity"], "EXPERIMENTAL")

    def test_cost_baseline_has_two_hundred_zero_live_runs_under_targets(self) -> None:
        targets = load_json(CONFORMANCE_ROOT / "core" / "budget-targets.v1.json")
        baseline = load_json(EVALS_ROOT / "cost-baseline.v1.json")
        replay_plan = load_json(EVALS_ROOT / "replay-plan.v1.json")

        self.assertEqual(baseline["liveModelInvocations"], 0)
        self.assertEqual(replay_plan["liveModelInvocations"], 0)
        self.assertEqual(baseline["qualityRegressionCount"], 0)

        expected_runs = (
            len(targets["corpus"])
            * len(targets["cohorts"])
            * targets["runsPerScenarioCohort"]
        )
        self.assertGreaterEqual(expected_runs, 200)
        self.assertEqual(baseline["totalReplayRuns"], expected_runs)

        seen_scenarios = set()
        total_runs = 0
        for metric in baseline["metrics"]:
            tier = metric["sddTier"]
            p95_target = targets["absoluteP95Targets"][tier]
            hard = targets["hardCeilings"][tier]
            seen_scenarios.add(metric["scenarioId"])
            for cohort in metric["cohorts"]:
                self.assertGreaterEqual(cohort["sampleCount"], 20)
                total_runs += cohort["sampleCount"]
                for name, value in cohort["p95"].items():
                    self.assertLessEqual(value, p95_target[name])
                    self.assertLessEqual(value, hard[name])

        self.assertEqual(seen_scenarios, set(targets["corpus"]))
        self.assertEqual(total_runs, expected_runs)

    def test_small_context_fixture_and_profile_are_present(self) -> None:
        fixture_4k = load_json(FIXTURES_ROOT / "s1-small-context-4k-strict-01.json")
        fixture_8k = load_json(FIXTURES_ROOT / "s1-small-context-8k-01.json")
        profile = load_json(ROOT / "profiles/small-context-profile.v1.json")
        self.assertIn("4k-strict", profile["windows"])
        self.assertEqual(fixture_4k["contextProfile"], profile["profileId"])
        self.assertEqual(fixture_4k["targetContextWindow"], "4k-strict")
        self.assertIn("small-context-4k", fixture_4k["tags"])
        self.assertEqual(fixture_8k["contextProfile"], profile["profileId"])
        self.assertEqual(fixture_8k["targetContextWindow"], profile["defaultWindow"])
        self.assertIn("small-context", fixture_8k["tags"])

    def test_model_routing_profile_is_present_and_provider_neutral(self) -> None:
        profile = load_json(ROOT / "profiles/model-routing-profile.v1.json")
        self.assertEqual(profile["schemaVersion"], "agent-lifecycle-model-routing-profile.v1")
        self.assertIn("budget", profile["classes"])
        self.assertIn("local-strong-review", profile["classes"])
        self.assertEqual(profile["phaseRules"]["final-audit"], "strong-reasoning")
        self.assertNotIn("providerModel", json.dumps(profile))

    def test_conformance_files_are_project_neutral(self) -> None:
        roots = [CONFORMANCE_ROOT, FIXTURES_ROOT, EVALS_ROOT, ROOT / "profiles"]
        for root in roots:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                text = path.read_text(encoding="utf-8")
                with self.subTest(path=path.relative_to(ROOT).as_posix()):
                    for marker in PROJECT_MARKERS:
                        self.assertNotIn(marker, text)


if __name__ == "__main__":
    unittest.main()

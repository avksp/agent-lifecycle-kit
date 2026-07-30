from __future__ import annotations

import unittest

from agent_lifecycle.quality import build_default_quality_pack, run_behavior_checks, validate_quality_pack


class OptionalQualityPackTests(unittest.TestCase):
    def test_default_quality_pack_is_optional_and_resource_capped(self) -> None:
        manifest = build_default_quality_pack()

        validation = validate_quality_pack(manifest)

        self.assertEqual(validation["schemaVersion"], "agent-optional-quality-pack-validation.v1")
        self.assertEqual(validation["status"], "PASS")
        self.assertFalse(validation["productionPromotionClaimed"])
        self.assertFalse(manifest["enabledByDefault"])
        self.assertEqual(manifest["defaultCommandFootprint"]["extraCommands"], 0)
        self.assertTrue(all(command["resourceCaps"] for command in manifest["commands"]))

    def test_quality_pack_rejects_default_enablement_and_missing_caps(self) -> None:
        manifest = build_default_quality_pack()
        manifest["enabledByDefault"] = True
        manifest["commands"][0]["resourceCaps"] = {}

        validation = validate_quality_pack(manifest)

        self.assertEqual(validation["status"], "FAIL")
        codes = {item["code"] for item in validation["blockers"]}
        self.assertIn("quality-pack-default-enabled", codes)
        self.assertIn("quality-pack-resource-caps-missing", codes)

    def test_behavior_checks_pass_when_negative_fixtures_are_detected(self) -> None:
        fixtures = [
            _fixture("positive", "PASS", completion="PASS", event_capture="PASS", review="PASS"),
            _fixture("false-done", "FAIL", completion="FAIL", event_capture="PASS", review="PASS"),
            _fixture("missing-event-stream", "FAIL", completion="PASS", event_capture="FAIL", review="PASS"),
            _fixture("external-action", "BLOCKED", external_action="BLOCKED"),
        ]

        result = run_behavior_checks(build_default_quality_pack(), fixtures)

        self.assertEqual(result["schemaVersion"], "agent-behavior-check-run.v1")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["failedExpectationCount"], 0)
        outcomes = {item["fixtureId"]: item["actualOutcome"] for item in result["checks"]}
        self.assertEqual(outcomes["false-done"], "FAIL")
        self.assertEqual(outcomes["missing-event-stream"], "FAIL")
        self.assertEqual(outcomes["external-action"], "BLOCKED")
        self.assertFalse(result["productionPromotionClaimed"])

    def test_behavior_checks_fail_when_expected_outcome_is_wrong(self) -> None:
        fixtures = [_fixture("hidden-failure", "PASS", completion="FAIL")]

        result = run_behavior_checks(build_default_quality_pack(), fixtures)

        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["failedExpectationCount"], 1)
        self.assertIn("behavior-check-expectation-failed", {item["code"] for item in result["blockers"]})

    def test_behavior_checks_fail_on_malformed_negative_fixture(self) -> None:
        fixtures = [
            {
                "schemaVersion": "wrong.v1",
                "fixtureId": "malformed-negative",
                "expectedOutcome": "FAIL",
                "signals": {},
            }
        ]

        result = run_behavior_checks(build_default_quality_pack(), fixtures)

        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["failedExpectationCount"], 0)
        self.assertIn("behavior-check-fixture-schema-invalid", {item["code"] for item in result["blockers"]})


def _fixture(
    fixture_id: str,
    expected: str,
    *,
    completion: str | None = None,
    goal: str | None = None,
    budget: str | None = None,
    event_capture: str | None = None,
    external_action: str | None = None,
    review: str | None = None,
) -> dict:
    signals = {}
    for key, status in {
        "completion": completion,
        "goal": goal,
        "budget": budget,
        "eventCapture": event_capture,
        "externalAction": external_action,
        "review": review,
    }.items():
        if status:
            signals[key] = {"status": status}
    return {
        "schemaVersion": "agent-behavior-check-fixture.v1",
        "fixtureId": fixture_id,
        "expectedOutcome": expected,
        "signals": signals,
    }


if __name__ == "__main__":
    unittest.main()

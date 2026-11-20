from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.cli.helpers import _run_cli

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "tests/planning/fixtures/full-s2-plan.json"


class PlanCheckOutputTests(unittest.TestCase):
    def test_named_checks_are_projection_of_existing_completeness(self) -> None:
        code, result = _run_cli(["plan", "check", "--manifest", str(_FIXTURE)])
        self.assertEqual(code, 0, result)
        self.assertEqual(result["schemaVersion"], "agent-plan-check.v1")
        self.assertIsNone(result["lock"])
        self.assertEqual(result["requiredChecks"], result["manifest"]["completeness"]["requiredChecks"])
        self.assertEqual(result["blockers"], [])

    def test_failed_completeness_keeps_original_details_and_adds_projection(self) -> None:
        manifest = json.loads(_FIXTURE.read_bytes())
        manifest["workstreams"][0]["evidenceIds"] = []
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "plan.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            code, result = _run_cli(["plan", "check", "--manifest", str(path)])
        self.assertEqual((code, result["code"]), (2, "plan-completeness-failed"))
        details = result["details"]
        for key in ("requiredChecks", "blockers"):
            self.assertEqual(details[key], details["validation"][key])
        rule = next(b for b in details["blockers"] if b["code"] == "traceability-owner-count")
        self.assertTrue(rule["context"]["reference"].endswith("#one-owner-per-id"))

    def test_profiles_present_rule_in_both_languages(self) -> None:
        code, result = _run_cli(["plan", "package-profiles"])
        self.assertEqual(code, 0, result)
        rule = result["traceabilityOwnerRule"]
        self.assertIn("exactly one", rule["en"])
        self.assertIn("ровно один", rule["ru"])

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError  # noqa: E402
from agent_lifecycle.planning import (  # noqa: E402
    build_plan_completeness_profile,
    load_plan_completeness_profile,
    validate_plan_completeness,
    validate_plan_manifest,
)


class PlanCompletenessTests(unittest.TestCase):
    def test_default_profile_contains_all_tiers(self) -> None:
        profile = build_plan_completeness_profile()

        self.assertEqual(profile["schemaVersion"], "agent-plan-completeness-profile.v1")
        self.assertEqual(set(profile["profiles"]), {"S0", "S1", "S2"})
        self.assertEqual(load_plan_completeness_profile(ROOT / "profiles/plan-completeness-profile.v1.json")["profileDigest"], profile["profileDigest"])

    def test_s0_plan_stays_lightweight(self) -> None:
        payload = validate_plan_completeness(_manifest("S0"))

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["tier"], "S0")
        self.assertIn("single-workstream", payload["requiredChecks"])

    def test_s1_compact_plan_is_complete_without_s2_fields(self) -> None:
        payload = validate_plan_completeness(_manifest("S1"))

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["tier"], "S1")
        self.assertIn("release-impact", payload["requiredChecks"])

    def test_s2_complete_plan_passes_structural_profile(self) -> None:
        payload = validate_plan_completeness(_manifest("S2"))

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["tier"], "S2")
        self.assertIn("budget-policy", payload["requiredChecks"])
        self.assertIn("final-audit-gates", payload["requiredChecks"])

    def test_incomplete_s2_plan_returns_actionable_blockers(self) -> None:
        manifest = _manifest("S2")
        manifest["specification"].pop("requirements")
        manifest["acceptance"]["criteria"][0]["evidenceIds"] = ["EV-MISSING"]
        manifest["workstreams"][0]["writes"] = []
        manifest.pop("budgets")
        manifest.pop("contextLimits")
        manifest["specification"].pop("tierResolutionRequest")
        manifest.pop("finalAuditGates")

        payload = validate_plan_completeness(manifest)

        self.assertEqual(payload["status"], "FAIL")
        codes = {item["code"] for item in payload["blockers"]}
        self.assertIn("missing-requirements", codes)
        self.assertIn("missing-evidence-route", codes)
        self.assertIn("missing-write-ownership", codes)
        self.assertIn("missing-budget-policy", codes)
        self.assertIn("missing-context-limits", codes)
        self.assertIn("s2-final-audit-gate-missing", codes)

    def test_plan_validation_require_completeness_fails_closed(self) -> None:
        manifest = _manifest("S2")
        manifest.pop("budgets")

        with self.assertRaises(LifecycleError) as raised:
            validate_plan_manifest(manifest, require_completeness=True)

        self.assertEqual(raised.exception.code, "plan-completeness-failed")


def _manifest(tier: str) -> dict:
    base = {
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "p"},
        "specification": {
            "tier": tier,
            "requirements": [{"id": "REQ-1", "description": "Do the work"}],
            "tierResolutionRequest": {
                "schemaVersion": "agent-sdd-tier-resolution-request.v1",
                "taskCount": 1,
                "executableOwners": ["worker"],
                "capabilityHints": ["bounded-mechanical"] if tier == "S0" else ["planning"],
                "riskFlags": {
                    "architecture": tier == "S2",
                    "security": False,
                    "performance": False,
                    "browser": False,
                    "externalEnvironment": False,
                },
                "requirementsBytes": 1024,
                "externalSpecification": False,
            },
        },
        "acceptance": {"criteria": [{"id": "AC-1", "requirementIds": ["REQ-1"], "evidenceIds": ["EV-1"]}]},
        "workstreams": [
            {
                "id": "WS-01",
                "dependsOn": [],
                "writes": ["src/example.py"],
                "acceptanceIds": ["AC-1"],
                "evidenceIds": ["EV-1"],
            }
        ],
        "validation": {"commands": ["python -m unittest"], "extraEvidence": []},
        "releaseImpact": "none",
    }
    if tier == "S0":
        base["specification"].pop("requirements")
        base.pop("acceptance")
        base["workstreams"][0].pop("acceptanceIds")
        base["workstreams"][0].pop("evidenceIds")
        base.pop("releaseImpact")
    if tier == "S2":
        base["budgets"] = {"maxInvocations": 33, "maxWallSeconds": 1800}
        base["contextLimits"] = {"targetTokens": 4096}
        base["forbiddenWrites"] = [".git", "secrets"]
        base["releaseTarget"] = {"targetVersion": "1.0.0"}
        base["finalAuditGates"] = ["security gates pass", "release validation passes"]
    return json.loads(json.dumps(base))


if __name__ == "__main__":
    unittest.main()

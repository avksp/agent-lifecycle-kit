from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError  # noqa: E402
from agent_lifecycle.model_routing import (  # noqa: E402
    validate_host_model_profile,
    validate_model_routing_profile,
)


class ModelRoutingProfileTests(unittest.TestCase):
    def test_bundled_routing_profile_validates(self) -> None:
        profile = _load(ROOT / "profiles/model-routing-profile.v1.json")
        result = validate_model_routing_profile(profile)
        self.assertEqual(result["schemaVersion"], "agent-lifecycle-model-routing-profile-validation.v1")
        self.assertIn("local-strong-review", result["classes"])
        self.assertIn("final-audit", result["criticalReviewPhases"])

    def test_host_profile_validation_redacts_provider_model(self) -> None:
        result = validate_host_model_profile(_host_profile())
        self.assertEqual(result["schemaVersion"], "agent-lifecycle-host-model-profile-validation.v1")
        self.assertEqual(result["host"], "local-host")
        self.assertIn("local-strong-review", result["classes"])
        self.assertNotIn("providerModel", json.dumps(result))

    def test_host_profile_rejects_unknown_class(self) -> None:
        profile = _host_profile()
        profile["bindings"]["provider-model-name"] = profile["bindings"]["standard-code"]
        with self.assertRaises(LifecycleError):
            validate_host_model_profile(profile)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _host_profile() -> dict:
    return {
        "schemaVersion": "agent-lifecycle-host-model-profile.v1",
        "host": "local-host",
        "profileId": "test-host-profile",
        "bindings": {
            "standard-code": {
                "providerModel": "host-specific-standard",
                "contextWindow": "32k",
                "capabilities": ["text", "json", "tool-use", "code-edit"],
                "jsonReliability": "strict",
                "toolUse": "supported",
                "allowedForTiers": ["S0", "S1"],
                "allowedForPhases": ["task-implementation"],
                "usageAccounting": "host-attested",
                "dataPolicy": "local-only",
                "calibrationStatus": "PASSED",
            },
            "local-strong-review": {
                "providerModel": "host-specific-local-review",
                "contextWindow": "32k",
                "capabilities": ["text", "json", "tool-use", "deep-review"],
                "jsonReliability": "strict",
                "toolUse": "supported",
                "allowedForTiers": ["S1", "S2"],
                "allowedForPhases": ["final-audit", "security-review", "performance-review", "independent-review"],
                "usageAccounting": "host-attested",
                "dataPolicy": "local-only",
                "calibrationStatus": "PASSED",
                "reviewStrategy": "large-context-or-sliced-review",
            },
        },
    }


if __name__ == "__main__":
    unittest.main()

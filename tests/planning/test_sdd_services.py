from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError, canonical_digest  # noqa: E402
from agent_lifecycle.freeze import verify_plan_lock  # noqa: E402
from agent_lifecycle.planning import resolve_sdd_tier, validate_plan_manifest  # noqa: E402
from agent_lifecycle.review import validate_independent_review  # noqa: E402
from agent_lifecycle.specification import validate_specification  # noqa: E402


class SddServiceTests(unittest.TestCase):
    def test_validate_specification_returns_requirement_digest(self) -> None:
        result = validate_specification({
            "tier": "S2",
            "status": "FROZEN",
            "requirements": [{"id": "REQ-1", "required": True}],
        })
        self.assertEqual(result["tier"], "S2")
        self.assertEqual(result["requirementCount"], 1)

    def test_plan_validation_rejects_write_overlap(self) -> None:
        with self.assertRaises(LifecycleError):
            validate_plan_manifest(_manifest(overlap=True))

    def test_review_validation_rejects_open_medium_finding(self) -> None:
        with self.assertRaises(LifecycleError):
            validate_independent_review({
                "verdict": "READY_TO_FREEZE",
                "reviewer": {"independent": True},
                "findings": [{"id": "F-1", "status": "open", "severity": "MEDIUM"}],
            })

    def test_verify_plan_lock_binds_manifest_digest(self) -> None:
        manifest = _manifest(overlap=False)
        result = verify_plan_lock(
            manifest,
            {
                "schemaVersion": "agent-plan-lock.v1",
                "planRevision": 1,
                "manifestHash": canonical_digest(manifest),
            },
        )
        self.assertEqual(result["manifestHash"], canonical_digest(manifest))

    def test_tier_resolver_selects_s0_for_bounded_mechanical_work(self) -> None:
        result = resolve_sdd_tier(_tier_request(capability_hints=["bounded-mechanical"]))
        self.assertEqual(result["tier"], "S0")

    def test_tier_resolver_selects_s2_for_security_or_multi_owner_risk(self) -> None:
        result = resolve_sdd_tier(_tier_request(owners=["a", "b"], risk_flags={"security": True}))
        self.assertEqual(result["tier"], "S2")
        self.assertIn("multiple-executable-owners", result["reasons"])
        self.assertIn("security-risk", result["reasons"])


def _manifest(*, overlap: bool) -> dict:
    second_write = "src/core/internal" if overlap else "tests/core"
    return {
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "p"},
        "workstreams": [
            {"id": "WS-01", "writes": ["src/core"]},
            {"id": "WS-02", "writes": [second_write]},
        ],
    }


def _tier_request(
    *,
    owners: list[str] | None = None,
    capability_hints: list[str] | None = None,
    risk_flags: dict[str, bool] | None = None,
) -> dict:
    return {
        "schemaVersion": "agent-sdd-tier-resolution-request.v1",
        "taskCount": 1,
        "executableOwners": owners or ["worker"],
        "capabilityHints": capability_hints or [],
        "riskFlags": risk_flags or {},
        "requirementsBytes": 2048,
        "externalSpecification": False,
    }


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.project.merge import build_effective_project_profile, require_profile_digest
from tests.project.test_profile import _profile


class ProjectProfileMergeTests(unittest.TestCase):
    def test_merge_is_deterministic_and_preserves_unbound_defaults(self) -> None:
        first = build_effective_project_profile(_profile())
        second = build_effective_project_profile(_profile())

        self.assertEqual(first, second)
        self.assertEqual(first["defaultRisk"], "S0")
        self.assertEqual(first["authority"]["planBound"], False)
        self.assertEqual(first["threadBridge"]["mode"], "off")
        self.assertFalse(first["productionPromotionClaimed"])

    def test_frozen_plan_is_the_risk_floor(self) -> None:
        plan = {
            "status": "FROZEN",
            "tierResolution": {"tier": "S2"},
            "workstreams": [{"writes": ["src/example.py"]}],
            "requiredGates": ["implementation-audit"],
        }
        lock = {"manifestHash": canonical_digest(plan)}

        effective = build_effective_project_profile(_profile(defaultRisk="auto"), plan=plan, lock=lock)

        self.assertEqual(effective["defaultRisk"], "S2")
        self.assertEqual(effective["authority"]["writeScope"], ["src/example.py"])

        with self.assertRaisesRegex(LifecycleError, "downgrade"):
            build_effective_project_profile(_profile(defaultRisk="S0"), plan=plan, lock=lock)

    def test_safe_cli_override_can_tighten_but_not_lower_plan(self) -> None:
        plan = {"status": "FROZEN", "tierResolution": {"tier": "S1"}}
        lock = {"manifestHash": canonical_digest(plan)}

        effective = build_effective_project_profile(
            _profile(defaultRisk="auto"),
            plan=plan,
            lock=lock,
            cli_overrides={"defaultRisk": "S2"},
        )
        self.assertEqual(effective["defaultRisk"], "S2")

        with self.assertRaisesRegex(LifecycleError, "downgrade"):
            build_effective_project_profile(
                _profile(defaultRisk="auto"),
                plan=plan,
                lock=lock,
                cli_overrides={"defaultRisk": "S0"},
            )

    def test_lock_mismatch_and_profile_drift_fail_closed(self) -> None:
        plan = {"status": "FROZEN", "tierResolution": {"tier": "S1"}}
        with self.assertRaisesRegex(LifecycleError, "lock"):
            build_effective_project_profile(_profile(), plan=plan, lock={"manifestHash": "0" * 64})

        effective = build_effective_project_profile(_profile())
        require_profile_digest(effective, effective["effectiveProfileDigest"])
        with self.assertRaisesRegex(LifecycleError, "digest"):
            require_profile_digest(effective, "f" * 64)

    def test_frozen_plan_can_require_read_only_thread_operation(self) -> None:
        plan = {
            "status": "FROZEN",
            "tierResolution": {"tier": "S1"},
            "threadBridge": {
                "mode": "read-only",
                "operations": {
                    "read": {"enabled": True, "scope": "explicit-target", "approval": "none", "blocking": "required"},
                    "list": {"enabled": False, "scope": "project", "approval": "none", "blocking": "non-blocking"},
                    "send": {"enabled": False, "scope": "explicit-target", "approval": "operator", "blocking": "required"},
                    "create": {"enabled": False, "scope": "project", "approval": "operator", "blocking": "required"},
                },
                "phaseRules": {},
                "limits": {"maxImportedBytes": 4096, "maxImportedTokens": 512},
            },
        }
        lock = {"manifestHash": canonical_digest(plan)}

        effective = build_effective_project_profile(_profile(), plan=plan, lock=lock)

        self.assertEqual(effective["threadBridge"]["mode"], "read-only")
        self.assertTrue(effective["threadBridge"]["operations"]["read"]["enabled"])
        self.assertFalse(effective["threadBridge"]["operations"]["send"]["enabled"])
        self.assertEqual(effective["threadBridge"]["limits"]["maxImportedTokens"], 512)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "validate_all_planning_launch_profiles",
    ROOT / "tools/release/validate_all_planning_launch_profiles.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AllPlanningLaunchProfileValidatorTests(unittest.TestCase):
    EXPECTED_STATUSES = {
        "claude": "CANDIDATE",
        "codex": "CANDIDATE",
        "cursor": "UNSUPPORTED",
        "gemini-cli": "CANDIDATE",
        "goose": "CANDIDATE",
        "grok-build": "UNSUPPORTED",
        "hermes": "UNSUPPORTED",
        "kimi-code": "UNSUPPORTED",
        "opencode": "UNSUPPORTED",
        "openinterpreter": "UNSUPPORTED",
        "pi": "UNSUPPORTED",
        "qwen-code": "UNSUPPORTED",
    }

    def test_all_bundled_profiles_are_truthful_and_independent(self) -> None:
        report = MODULE.validate_all_profiles(ROOT / "adapters", repository_root=ROOT)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["adapterCount"], 12)
        rows = {row["adapterId"]: row for row in report["profiles"]}
        self.assertEqual(set(rows), set(MODULE.TARGETS))
        self.assertTrue(all(row["planningSupportStatus"] == "PLANNING_ONLY_UNSUPPORTED" for row in rows.values()))
        self.assertEqual(
            {adapter_id: row["profileStatus"] for adapter_id, row in rows.items()},
            self.EXPECTED_STATUSES,
        )
        self.assertEqual(
            report["validationDigest"],
            canonical_digest({key: value for key, value in report.items() if key != "validationDigest"}),
        )

    def test_all_descriptors_remain_wrapper_only_and_digest_bound(self) -> None:
        for adapter_id in MODULE.TARGETS:
            with self.subTest(adapter=adapter_id):
                descriptor = self._json(f"adapters/{adapter_id}/adapter.descriptor.json")
                capabilities = self._json(f"adapters/{adapter_id}/capabilities.manifest.json")
                receipt = self._json(f"conformance/adapters/{adapter_id}/event-stream-receipt.json")
                self.assertEqual(descriptor["managedLaunch"]["status"], "WRAPPER_ONLY")
                self.assertEqual(capabilities["descriptorDigest"], canonical_digest(descriptor))
                self.assertEqual(receipt["descriptorDigest"], canonical_digest(descriptor))
                self.assertEqual(
                    receipt["receiptDigest"],
                    canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"}),
                )

    def test_all_live_harnesses_are_thin_shared_bindings(self) -> None:
        modules = {
            "claude": "claude",
            "codex": "codex",
            "cursor": "cursor",
            "gemini-cli": "gemini_cli",
            "goose": "goose",
            "grok-build": "grok_build",
            "hermes": "hermes",
            "kimi-code": "kimi_code",
            "opencode": "opencode",
            "openinterpreter": "openinterpreter",
            "pi": "pi",
            "qwen-code": "qwen_code",
        }
        for adapter_id, module_name in modules.items():
            with self.subTest(adapter=adapter_id):
                text = (ROOT / f"tools/live_hosts/{module_name}_launch_harness.py").read_text(encoding="utf-8")
                self.assertIn("planning_launch_harness import main", text)
                self.assertIn(f'main("{adapter_id}")', text)
                self.assertNotIn("subprocess", text)

    @staticmethod
    def _json(relative: str) -> dict:
        return json.loads((ROOT / relative).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

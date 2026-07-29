from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402

class ReleaseInventoryTests(unittest.TestCase):
    def test_release_inventory_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            inventory = out / "inventory.json"
            assembly = out / "release-assembly.json"
            verification = out / "release-verification.json"
            _run("tools/release/assemble_release_candidate.py", "--manifest", "plans/standalone-v1/plan.manifest.json", "--inventory", str(inventory), "--evidence", str(assembly))
            _run("tools/release/verify_release_candidate.py", "--inventory", str(inventory), "--evidence", str(verification))
            inventory_payload = json.loads(inventory.read_text(encoding="utf-8"))
            payload = json.loads(verification.read_text(encoding="utf-8"))
            self.assertIn("tools/release/validate_deferred_promotion.py", {item["path"] for item in inventory_payload["files"]})
            self.assertIn("tools/release/validate_live_calibration.py", {item["path"] for item in inventory_payload["files"]})
            self.assertIn("tools/release/validate_live_host_conformance.py", {item["path"] for item in inventory_payload["files"]})
            self.assertIn("tools/live_hosts/common.py", {item["path"] for item in inventory_payload["files"]})
            self.assertIn("tools/live_hosts/codex_harness.py", {item["path"] for item in inventory_payload["files"]})
            self.assertIn("tools/live_hosts/claude_code_harness.py", {item["path"] for item in inventory_payload["files"]})
            self.assertIn("tools/live_hosts/cursor_harness.py", {item["path"] for item in inventory_payload["files"]})
            self.assertIn("tools/live_hosts/hermes_harness.py", {item["path"] for item in inventory_payload["files"]})
            self.assertIn("tools/live_hosts/opencode_harness.py", {item["path"] for item in inventory_payload["files"]})
            self.assertIn("fixtures/synthetic/negative-matrix-01.json", {item["path"] for item in inventory_payload["files"]})
            self.assertIn("evals/synthetic/cost-baseline.v1.json", {item["path"] for item in inventory_payload["files"]})
            self.assertEqual(payload["status"], "PASS")
            self.assertFalse(payload["productionPromotionClaimed"])

    def test_release_payload_excludes_build_egg_info(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "src/agent_lifecycle"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            egg_info = root / "src/agent_lifecycle_kit.egg-info"
            egg_info.mkdir()
            (egg_info / "PKG-INFO").write_text("generated\n", encoding="utf-8")

            files = {path.as_posix() for path in iter_payload_files(root)}

            self.assertIn("src/agent_lifecycle/__init__.py", files)
            self.assertNotIn("src/agent_lifecycle_kit.egg-info/PKG-INFO", files)

    def test_support_matrix_and_deferred_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            matrix_evidence = out / "support-matrix-contract.json"
            deferred_evidence = out / "deferred-promotion-contract.json"
            _run("tools/release/validate_support_matrix.py", "--support-matrix", "docs/adapters/support-matrix.md", "--profile", "plans/standalone-v1/.agent-plan/standalone-v1/ci-matrix-profile.v2.json", "--evidence", str(matrix_evidence))
            _run("tools/release/validate_deferred_promotion.py", "--profile", "plans/standalone-v1/.agent-plan/standalone-v1/benchmark-authority-profile.v1.json", "--evidence", str(deferred_evidence))
            matrix = json.loads(matrix_evidence.read_text(encoding="utf-8"))
            deferred = json.loads(deferred_evidence.read_text(encoding="utf-8"))
            self.assertEqual(matrix["adapterMaturity"], "HOST_SPECIFIC")
            self.assertEqual(matrix["adapterMaturityByHost"]["Claude Code"], "VERIFIED")
            self.assertEqual(matrix["adapterMaturityByHost"]["Codex"], "VERIFIED")
            self.assertEqual(matrix["adapterMaturityByHost"]["OpenCode"], "VERIFIED")
            self.assertEqual(matrix["adapterMaturityByHost"]["Hermes"], "VERIFIED")
            self.assertEqual(matrix["adapterMaturityByHost"]["qwen-code"], "VERIFIED")
            self.assertEqual(set(matrix["verifiedHosts"]), {"Codex", "Claude Code", "OpenCode", "Hermes", "qwen-code"})
            self.assertTrue(deferred["deferredProductionPromotion"])
            self.assertFalse(deferred["liveModelExecutionClaimed"])

    def test_support_matrix_rejects_verified_host_missing_descriptor_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            support_matrix = out / "support-matrix.md"
            evidence = out / "support-matrix-contract.json"
            marker = "tasks/release-0-6/evidence/codex-live-promotion/full-lifecycle/final/final-proof.json"
            support_matrix.write_text(
                (ROOT / "docs/adapters/support-matrix.md")
                .read_text(encoding="utf-8")
                .replace(marker, "tasks/release-0-6/evidence/codex-live-promotion/full-lifecycle/final/missing-proof.json"),
                encoding="utf-8",
            )

            result = _run_no_check(
                "tools/release/validate_support_matrix.py",
                "--support-matrix",
                str(support_matrix),
                "--profile",
                "plans/standalone-v1/.agent-plan/standalone-v1/ci-matrix-profile.v2.json",
                "--evidence",
                str(evidence),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires descriptor evidence markers", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()

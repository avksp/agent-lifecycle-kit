from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import _run_cli
except ImportError:
    from helpers import _run_cli

try:
    from tests.planning.test_plan_completeness import _manifest
except ImportError:
    from planning.test_plan_completeness import _manifest

try:
    from tests.planning.test_completeness import _manifest as _canonical_manifest
except ImportError:
    from planning.test_completeness import _manifest as _canonical_manifest


class CliPlanCompletenessTests(unittest.TestCase):
    def test_plan_completeness_check_cli_writes_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "plan.manifest.json"
            manifest_path.write_text(json.dumps(_manifest("S2")), encoding="utf-8")
            out_path = root / "plan-completeness.json"

            code, payload = _run_cli([
                "plan",
                "completeness-check",
                "--manifest",
                str(manifest_path),
                "--out",
                str(out_path),
            ])

            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-plan-completeness-validation.v1")
            self.assertEqual(payload["status"], "PASS")
            saved = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["validationDigest"], payload["validationDigest"])

    def test_plan_completeness_check_cli_reports_fail_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = _manifest("S2")
            manifest.pop("budgets")
            manifest_path = root / "plan.manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            code, payload = _run_cli(["plan", "completeness-check", "--manifest", str(manifest_path)])

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("missing-budget-policy", {item["code"] for item in payload["blockers"]})

    def test_plan_check_require_completeness_fails_incomplete_s2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = _manifest("S2")
            manifest.pop("finalAuditGates")
            manifest_path = root / "plan.manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            code, payload = _run_cli(["plan", "check", "--manifest", str(manifest_path), "--require-completeness"])

            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "plan-completeness-failed")

    def test_plan_check_require_completeness_embeds_pass_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "plan.manifest.json"
            manifest_path.write_text(json.dumps(_manifest("S2")), encoding="utf-8")

            code, payload = _run_cli(["plan", "check", "--manifest", str(manifest_path), "--require-completeness"])

            self.assertEqual(code, 0)
            self.assertEqual(payload["manifest"]["completeness"]["status"], "PASS")

    def test_plan_check_and_verify_report_the_same_traceability_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = _canonical_manifest()
            manifest["status"] = "DRAFT"
            manifest["workstreams"][0]["acceptanceIds"] = ["AC-02"]
            manifest_path = root / "plan.manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            check_code, check_payload = _run_cli(
                ["plan", "check", "--manifest", str(manifest_path), "--require-completeness"]
            )
            verify_code, verify_payload = _run_cli(
                ["plan", "verify", "--manifest", str(manifest_path), "--repository-root", str(root)]
            )

            check_blockers = check_payload["details"]["validation"]["blockers"]
            verify_blockers = verify_payload["details"]["verification"]["checks"]["completeness"]["blockers"]
            self.assertEqual(check_code, 2)
            self.assertEqual(verify_code, 2)
            self.assertEqual(check_payload["code"], "plan-completeness-failed")
            self.assertEqual(verify_payload["code"], "plan-verification-failed")
            self.assertEqual(check_blockers, verify_blockers)
            self.assertEqual({item["code"] for item in check_blockers}, {"traceability-owner-count"})


if __name__ == "__main__":
    unittest.main()

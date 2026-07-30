from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.diagnostics import build_readiness_report
from agent_lifecycle.host_protocol.scaffold import scaffold_adapter

ROOT = Path(__file__).resolve().parents[2]


class ReadinessDiagnosticsTests(unittest.TestCase):
    def test_readiness_report_is_redacted_read_only_and_promotion_safe(self) -> None:
        report = build_readiness_report(
            project_root=ROOT,
            adapter_paths=[Path("adapters/codex/adapter.descriptor.json")],
            include_install_plans=True,
        )

        rendered = json.dumps(report, sort_keys=True)
        self.assertEqual(report["schemaVersion"], "agent-readiness-report.v1")
        self.assertIn(report["status"], {"PASS", "WARN"})
        self.assertEqual(report["projectRoot"], "<checkout>")
        self.assertFalse(report["liveCallsStarted"])
        self.assertFalse(report["productionPromotionClaimed"])
        self.assertFalse(report["maturityChangesClaimed"])
        self.assertEqual(report["summary"]["adapterCount"], 1)
        self.assertEqual(report["adapters"][0]["host"], "codex")
        self.assertFalse(report["adapters"][0]["productionPromotionClaimed"])
        self.assertFalse(report["adapters"][0]["maturityChangeClaimed"])
        self.assertEqual(report["installPlans"][0]["status"], "DRY_RUN")
        self.assertNotIn(str(ROOT), rendered)

    def test_host_probe_cap_is_recorded_without_expanding_to_all_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scaffold_adapter(host="alpha-host", target=root)
            scaffold_adapter(host="beta-host", target=root)
            baseline = ROOT / "conformance/core/adapter-baseline.v1.json"

            report = build_readiness_report(
                project_root=root,
                include_host_probes=True,
                max_host_probes=1,
                adapter_baseline=baseline,
            )

            self.assertEqual(report["hostProbePolicy"]["maxInvocations"], 1)
            self.assertEqual(report["hostProbePolicy"]["invocationsUsed"], 1)
            self.assertEqual([item["hostProbeUsed"] for item in report["adapters"]], [True, False])
            self.assertFalse(report["liveCallsStarted"])

    def test_missing_descriptor_becomes_failed_check_in_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            report = build_readiness_report(
                project_root=root,
                adapter_paths=[Path("adapters/missing/adapter.descriptor.json")],
            )

            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["adapters"][0]["validationStatus"], "FAIL")
            self.assertEqual(report["checks"][-1]["status"], "FAIL")
            self.assertFalse(report["productionPromotionClaimed"])


if __name__ == "__main__":
    unittest.main()

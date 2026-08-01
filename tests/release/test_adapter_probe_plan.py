from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402


class AdapterProbePlanTests(unittest.TestCase):
    def test_generates_bounded_probe_plan_from_capability_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "adapter-probe-plan.json"

            _run(
                "tools/release/generate_adapter_probe_plan.py",
                "--profile",
                "conformance/core/adapter-probe-profile.v1.json",
                "--manifest",
                "adapters/goose/capabilities.manifest.json",
                "--manifest",
                "adapters/openinterpreter/capabilities.manifest.json",
                "--out",
                str(out),
            )

            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["schemaVersion"], "agent-adapter-probe-plan.v1")
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["hostCount"], 2)
            self.assertFalse(payload["liveCallsStarted"])
            self.assertFalse(payload["productionPromotionClaimed"])
            self.assertFalse(payload["maturityChangeClaimed"])
            for host in payload["hosts"]:
                self.assertGreater(host["requiredLiveOperationCount"], 0)
                self.assertEqual(host["promotionDecision"], "NOT_EVALUATED")


if __name__ == "__main__":
    unittest.main()

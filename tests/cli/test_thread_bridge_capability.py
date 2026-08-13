from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.cli import main


ROOT = Path(__file__).resolve().parents[2]


class ThreadBridgeCapabilityCliTests(unittest.TestCase):
    def test_capability_command_is_local_and_reports_non_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "capability.json"
            code = main(
                [
                    "adapter",
                    "thread-capability",
                    "--descriptor",
                    str(ROOT / "adapters/opencode/adapter.descriptor.json"),
                    "--manifest",
                    str(ROOT / "adapters/opencode/capabilities.manifest.json"),
                    "--out",
                    str(output),
                ]
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertEqual(payload["support"], "unsupported")
        self.assertFalse(payload["productionPromotionClaimed"])
        self.assertTrue(all(item["qualificationStatus"] == "UNQUALIFIED" for item in payload["operations"]))


if __name__ == "__main__":
    unittest.main()

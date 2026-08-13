from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.host_protocol import build_capability_manifest


ROOT = Path(__file__).resolve().parents[2]


class ThreadBridgeProfileReleaseTests(unittest.TestCase):
    def test_profile_validator_covers_all_bundled_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "thread-bridge-profiles.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_thread_bridge_profiles.py"),
                    "--adapter-root",
                    str(ROOT / "adapters"),
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                env={"PYTHONPATH": str(ROOT / "src"), **dict(__import__("os").environ)},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["adapterCount"], 12)
        self.assertEqual(payload["blockers"], [])
        self.assertTrue(all(row["declaredStatuses"] == ["UNSUPPORTED"] for row in payload["adapters"]))

    def test_profile_validator_rejects_a_positive_supported_claim(self) -> None:
        descriptor_path = ROOT / "adapters/opencode/adapter.descriptor.json"
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        descriptor["threadBridge"]["operations"][0]["declaredStatus"] = "SUPPORTED"
        with tempfile.TemporaryDirectory() as directory:
            adapter_root = Path(directory) / "adapters" / "opencode"
            adapter_root.mkdir(parents=True)
            (adapter_root / "adapter.descriptor.json").write_text(json.dumps(descriptor), encoding="utf-8")
            (adapter_root / "capabilities.manifest.json").write_text(
                json.dumps(build_capability_manifest(descriptor)),
                encoding="utf-8",
            )
            evidence = Path(directory) / "evidence.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_thread_bridge_profiles.py"),
                    "--adapter-root",
                    str(Path(directory) / "adapters"),
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                env={"PYTHONPATH": str(ROOT / "src"), **dict(__import__("os").environ)},
                capture_output=True,
                text=True,
                check=False,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["status"], "FAIL")
        self.assertTrue(any(item["code"] == "thread-bridge-positive-claim-without-receipt" for item in payload["blockers"]))


if __name__ == "__main__":
    unittest.main()

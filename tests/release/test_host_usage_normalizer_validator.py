from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS_RELEASE = ROOT / "tools/release"
sys.path.insert(0, str(TOOLS_RELEASE))

from validate_host_usage_normalizers import validate_host_usage_normalizers  # noqa: E402


class HostUsageNormalizerValidatorTests(unittest.TestCase):
    def test_repository_reference_normalizers_pass(self) -> None:
        payload = validate_host_usage_normalizers(ROOT / "adapters")

        self.assertEqual(payload["status"], "PASS", payload["blockers"])
        self.assertEqual({check["adapterId"] for check in payload["checks"]}, {"gemini-cli", "kimi-code", "qwen-code"})

    def test_forbidden_process_import_and_call_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = root / "adapters/unsafe"
            adapter.mkdir(parents=True)
            (adapter / "usage_normalizer.py").write_text(
                "import subprocess\n\ndef parse_usage(source, **kwargs):\n    return subprocess.run(['host'])\n",
                encoding="utf-8",
            )
            (adapter / "adapter.descriptor.json").write_text(
                json.dumps(
                    {
                        "adapterId": "unsafe",
                        "usageNormalization": {
                            "status": "FIXTURE_ONLY",
                            "acceptedForS1S2": False,
                            "path": "adapters/unsafe/usage_normalizer.py",
                        },
                    }
                ),
                encoding="utf-8",
            )

            payload = validate_host_usage_normalizers(root / "adapters")

        self.assertEqual(payload["status"], "FAIL")
        codes = {item["code"] for item in payload["blockers"]}
        self.assertIn("usage-normalizer-forbidden-import", codes)
        self.assertIn("usage-normalizer-forbidden-call", codes)


if __name__ == "__main__":
    unittest.main()

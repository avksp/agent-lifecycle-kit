from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "release"))

from validate_adapter_event_guidance import validate_adapter_event_guidance  # noqa: E402


class AdapterEventGuidanceValidatorTests(unittest.TestCase):
    def test_repository_event_guidance_passes(self) -> None:
        payload = validate_adapter_event_guidance(ROOT)

        self.assertEqual(payload["status"], "PASS")
        self.assertGreaterEqual(payload["declaredAdapterCount"], 12)
        self.assertFalse(payload["hostCallsStarted"])
        self.assertFalse(payload["modelCallsStarted"])

    def test_core_owned_hook_claim_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            shutil.copytree(
                ROOT,
                root,
                ignore=shutil.ignore_patterns(".git", ".alk", "work", "__pycache__", "*.pyc"),
            )
            matrix = root / "docs" / "adapters" / "event-capture-matrix.md"
            matrix.write_text(matrix.read_text(encoding="utf-8") + "\nALK installs hooks.\n", encoding="utf-8")

            payload = validate_adapter_event_guidance(root)

        self.assertEqual(payload["status"], "FAIL")
        self.assertIn("adapter-event-core-owned-hook-claim", {item["code"] for item in payload["blockers"]})


if __name__ == "__main__":
    unittest.main()

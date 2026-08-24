from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import _run_cli
except ImportError:
    from helpers import _run_cli  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[2]


class ExternalCheckCommandTests(unittest.TestCase):
    def test_cli_reports_unavailable_optional_tool_without_claiming_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "external-check.json"
            code, payload = _run_cli(
                [
                    "quality",
                    "external-check",
                    "--check-id",
                    "import-boundaries",
                    "--project-root",
                    str(ROOT),
                    "--plan-digest",
                    "1" * 64,
                    "--plan-lock-digest",
                    "2" * 64,
                    "--operation-id",
                    "cli-missing-tool-op",
                    "--out",
                    str(output),
                ]
            )

            self.assertEqual(code, 0)
            self.assertTrue(output.is_file())
            self.assertEqual(payload["status"], "UNAVAILABLE")
            self.assertFalse(payload["audit"]["blockingEligible"])
            self.assertFalse(payload["productionPromotionClaimed"])
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["status"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()

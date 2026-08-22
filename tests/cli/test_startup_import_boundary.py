from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from agent_lifecycle.cli.main import main


ROOT = Path(__file__).resolve().parents[2]


class CliStartupImportBoundaryTests(unittest.TestCase):
    def test_version_uses_small_parser_and_does_not_import_runtime_families(self) -> None:
        script = (
            "import json,sys; from agent_lifecycle.cli.main import main; "
            "code=main(['version']); "
            "print('MODULES='+json.dumps(sorted(name for name in sys.modules if name.startswith('agent_lifecycle.'))), file=sys.stderr); "
            "raise SystemExit(code)"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "src")
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertIsInstance(json.loads(result.stdout), dict)
        modules_line = next(line for line in result.stderr.splitlines() if line.startswith("MODULES="))
        modules = set(json.loads(modules_line.split("=", 1)[1]))
        self.assertNotIn("agent_lifecycle.neutrality.scanner", modules)
        self.assertNotIn("agent_lifecycle.adapter_sessions.launcher", modules)
        self.assertNotIn("agent_lifecycle.workflow.controller", modules)

    def test_full_parser_and_version_output_remain_compatible(self) -> None:
        code = main(["version"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()

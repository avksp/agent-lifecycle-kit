from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = 'def untyped_body():\n    count: int = "not an integer"\n    return count\n'


class TypingContractTests(unittest.TestCase):
    def test_configured_mypy_rejects_untyped_body_assignment(self) -> None:
        config_path = ROOT / "pyproject.toml"
        config = config_path.read_bytes()
        self.assertIs(tomllib.loads(config.decode())["tool"]["mypy"]["check_untyped_defs"], True)
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "untyped_body.py"
            fixture.write_text(FIXTURE, encoding="utf-8")
            argv = [
                sys.executable,
                "-m",
                "mypy",
                "--config-file",
                str(config_path),
                "--no-incremental",
                str(fixture),
            ]
            started = time.monotonic()
            result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=120, check=False)
            evidence = {
                "argv": argv,
                "cwd": str(ROOT),
                "exitCode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "elapsedSeconds": time.monotonic() - started,
                "fixturePath": str(fixture),
                "fixtureSource": FIXTURE,
                "fixtureSha256": hashlib.sha256(FIXTURE.encode()).hexdigest(),
                "configPath": str(config_path),
                "configSha256": hashlib.sha256(config).hexdigest(),
                "expectedExitCode": 1,
            }
            print("TYPING_CONTRACT_EVIDENCE=" + json.dumps(evidence, sort_keys=True), flush=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("untyped_body.py:2: error:", result.stdout)
            self.assertIn("Incompatible types in assignment", result.stdout)
            self.assertIn("[assignment]", result.stdout)
            self.assertIn("Found 1 error in 1 file", result.stdout)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.release.helpers import ROOT


class HostEnvHygieneValidatorTests(unittest.TestCase):
    def test_validator_accepts_redacted_report_without_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_value = "alk-fixture-" + "redaction-marker"
            env_file = tmp_path / "host.env"
            report = tmp_path / "report.json"
            evidence = tmp_path / "evidence.json"
            env_file.write_text(f"ALK_TEST_HOST_KEY={env_value}\n", encoding="utf-8")
            report.write_text(
                json.dumps(
                    {
                        "schemaVersion": "test-report.v1",
                        "status": "PASS",
                        "hostEnv": {
                            "schemaVersion": "agent-host-env-file-redacted.v1",
                            "source": "host-env-file",
                            "pathDigest": "digest",
                            "loadedVariables": ["ALK_TEST_HOST_KEY"],
                            "ignoredVariableCount": 0,
                            "variableCount": 1,
                            "valuesRedacted": True,
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = _run_validator(
                report=report,
                env_file=env_file,
                evidence=evidence,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = evidence.read_text(encoding="utf-8")
            self.assertNotIn(env_value, payload)
            self.assertEqual(json.loads(payload)["status"], "PASS")

    def test_validator_fails_when_report_contains_secret_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_value = "alk-fixture-" + "leaked-marker"
            env_file = tmp_path / "host.env"
            report = tmp_path / "report.json"
            evidence = tmp_path / "evidence.json"
            env_file.write_text(f"ALK_TEST_HOST_KEY={env_value}\n", encoding="utf-8")
            report.write_text(
                json.dumps(
                    {
                        "schemaVersion": "test-report.v1",
                        "status": "FAIL",
                        "stderr": env_value,
                        "hostEnv": {
                            "schemaVersion": "agent-host-env-file-redacted.v1",
                            "source": "host-env-file",
                            "pathDigest": "digest",
                            "loadedVariables": ["ALK_TEST_HOST_KEY"],
                            "ignoredVariableCount": 0,
                            "variableCount": 1,
                            "valuesRedacted": True,
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = _run_validator(
                report=report,
                env_file=env_file,
                evidence=evidence,
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "FAIL")
            self.assertEqual(payload["blockers"][0]["code"], "secret-value-leaked")
            self.assertNotIn(env_value, evidence.read_text(encoding="utf-8"))


def _run_validator(*, report: Path, env_file: Path, evidence: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "tools/release/validate_host_env_hygiene.py",
            "--report",
            str(report),
            "--host-env-file",
            str(env_file),
            "--host-env-allow",
            "ALK_TEST_HOST_KEY",
            "--require-host-env-report",
            "--evidence",
            str(evidence),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


if __name__ == "__main__":
    unittest.main()

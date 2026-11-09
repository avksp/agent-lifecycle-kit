"""Actual source/public-wheel CLI consumers; positive evidence is UNIT_ONLY.

ALK_EXTERNAL_CONSUMER_EXECUTABLE selects an installed console script. Its child
gets a disposable cwd and no PYTHONPATH. No source override enters that child.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from tests.model_routing.test_qualified_selection import build_unit_request

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "agent-qualified-route-ranking-request.v1"


class QualifiedRouteRankingCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cwd = Path(self.temporary.name)
        self.environment = dict(os.environ)
        self.environment.pop("PYTHONPATH", None)
        self.environment["PYTHONDONTWRITEBYTECODE"] = "1"
        external = os.environ.get("ALK_EXTERNAL_CONSUMER_EXECUTABLE")
        if external:
            self.command = [str(Path(external).absolute())]
        else:
            self.command = [sys.executable, "-m", "agent_lifecycle"]
            self.environment["PYTHONPATH"] = str(ROOT / "src")

    def call(self, *args: str) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [*self.command, "benchmark", "rank-qualified", *args],
            cwd=self.cwd,
            env=self.environment,
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertLessEqual(len(result.stdout), 65_536)
        self.assertLessEqual(len(result.stderr), 16_384)
        return result

    def write_request(self, request: dict) -> None:
        (self.cwd / "request.json").write_text(json.dumps(request), encoding="utf-8")

    def test_t01_actual_manual_omitted_off_and_create_only_output(self) -> None:
        for enabled in (None, False):
            request = {"schemaVersion": SCHEMA}
            if enabled is not None:
                request["enabled"] = enabled
            self.write_request(request)
            result = self.call("--request", "request.json")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["reasonCodes"], ["MANUAL_DEFAULT"])
            self.assertEqual(sorted(path.name for path in self.cwd.iterdir()), ["request.json"])
        output = self.call("--request", "request.json", "--out", "report.json")
        self.assertEqual(output.returncode, 0, output.stderr)
        original = (self.cwd / "report.json").read_bytes()
        self.assertEqual(original, output.stdout)
        self.assertNotEqual(self.call("--request", "request.json", "--out", "report.json").returncode, 0)
        self.assertEqual((self.cwd / "report.json").read_bytes(), original)

    def test_t02_no_model_and_t03_unit_only_positive_actual_command(self) -> None:
        request = build_unit_request(observed=datetime.now(UTC))
        self.write_request(request)
        result = self.call("--request", "request.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["selectedCandidateId"], "cheap")
        self.assertEqual([row["metricTotal"] for row in report["ranking"]], [600, 1200])
        self.assertNotIn(b"UNIT_ONLY-private", result.stdout)
        request["modelRequest"]["phase"] = "schema-check"
        request["candidates"] = []
        self.write_request(request)
        result = self.call("--request", "request.json")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["reasonCodes"], ["NO_MODEL_REQUIRED"])

    def test_t11_missing_and_unknown_arguments(self) -> None:
        self.assertNotEqual(self.call().returncode, 0)
        self.write_request({"schemaVersion": SCHEMA})
        self.assertNotEqual(self.call("--request", "request.json", "--now", "2000-01-01").returncode, 0)

    def test_t11_malformed_duplicate_nonfinite_unknown_and_oversize(self) -> None:
        inputs = (
            b"{",
            b'{"schemaVersion":"x","schemaVersion":"y"}',
            b'{"schemaVersion":"agent-qualified-route-ranking-request.v1","enabled":NaN}',
            b'{"schemaVersion":"agent-qualified-route-ranking-request.v1","surprise":true}',
            b" " * 1_048_577,
        )
        for raw in inputs:
            with self.subTest(rawLength=len(raw)):
                (self.cwd / "request.json").write_bytes(raw)
                result = self.call("--request", "request.json", "--out", "forbidden.json")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.cwd / "forbidden.json").exists())

    def test_t11_links_and_containment_on_input_and_output(self) -> None:
        self.write_request({"schemaVersion": SCHEMA})
        (self.cwd / "link.json").symlink_to(self.cwd / "request.json")
        self.assertNotEqual(self.call("--request", "link.json").returncode, 0)
        self.assertNotEqual(self.call("--request", str(ROOT / "pyproject.toml")).returncode, 0)
        self.assertNotEqual(self.call("--request", "request.json", "--out", "link.json").returncode, 0)
        self.assertNotEqual(self.call("--request", "request.json", "--out", "../escaped.json").returncode, 0)
        self.assertEqual(json.loads((self.cwd / "request.json").read_bytes())["schemaVersion"], SCHEMA)

    def test_t14_suggestion_stays_data_and_t15_missing_real_evidence_refuses(self) -> None:
        request = build_unit_request(observed=datetime.now(UTC))
        request["candidates"][0]["hostProfile"]["bindings"]["standard-code"]["providerModel"] = (
            "$(touch SHOULD_NOT_EXIST); secret-suggestion"
        )
        self.write_request(request)
        before = (self.cwd / "request.json").read_bytes()
        result = self.call("--request", "request.json")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "NO_RECOMMENDATION")
        self.assertNotIn(b"secret-suggestion", result.stdout)
        self.assertFalse((self.cwd / "SHOULD_NOT_EXIST").exists())
        self.assertEqual((self.cwd / "request.json").read_bytes(), before)
        request["candidates"] = []
        request["trustedReceiptDigests"] = []
        self.write_request(request)
        result = self.call("--request", "request.json")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "NO_RECOMMENDATION")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


class FoundationTests(unittest.TestCase):
    def test_package_metadata_is_stable(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = pyproject["project"]
        self.assertEqual(project["name"], "agent-lifecycle-kit")
        self.assertEqual(project["version"], "0.1.1")
        self.assertEqual(project["requires-python"], ">=3.11,<3.14")
        self.assertEqual(project["license"]["text"], "Apache-2.0")
        self.assertEqual(project["dependencies"], [])

    def test_version_module_matches_pyproject(self) -> None:
        from agent_lifecycle import __version__

        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(__version__, pyproject["project"]["version"])

    def test_required_foundation_files_exist(self) -> None:
        for path in [
            ".editorconfig",
            ".gitignore",
            "NOTICE",
            "LICENSE",
            "uv.lock",
            "profiles/small-context-profile.v1.json",
        ]:
            self.assertTrue((ROOT / path).is_file(), path)

    def test_uv_lock_declares_runtime_graph(self) -> None:
        lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
        self.assertEqual(lock["version"], 1)
        self.assertEqual(lock["requires-python"], ">=3.11,<3.14")
        packages = {package["name"]: package for package in lock["package"]}
        self.assertIn("agent-lifecycle-kit", packages)
        self.assertEqual(packages["agent-lifecycle-kit"]["version"], "0.1.1")

    def test_foundation_ci_uses_stdlib_unittest(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertNotIn("pytest", pyproject.get("tool", {}))
        self.assertNotIn("optional-dependencies", pyproject["project"])
        workflow = (ROOT / ".github/workflows/neutrality.yml").read_text(encoding="utf-8")
        self.assertIn("python -m unittest discover", workflow)
        self.assertNotIn("pytest", workflow)

    def test_controller_unittest_runner_uses_stdlib_only(self) -> None:
        from agent_lifecycle.neutrality.test_runner import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            suite = root / "suite"
            suite.mkdir()
            (suite / "test_sample.py").write_text(
                "import unittest\n\n"
                "class SampleTests(unittest.TestCase):\n"
                "    def test_ok(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            _operation_request(root / "request.json", "out/report.json")
            cwd = Path.cwd()
            try:
                os.chdir(root)
                result = main(
                    [
                        "--operation-request",
                        "request.json",
                        "--start-directory",
                        "suite",
                        "--pattern",
                        "test*.py",
                        "--report",
                        "out/report.json",
                    ]
                )
            finally:
                os.chdir(cwd)
            self.assertEqual(result, 0)
            report = json.loads((root / "out/report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["schemaVersion"], "agent-lifecycle-unittest-report.v1")
            self.assertEqual(report["suite"]["testsRun"], 1)


def _operation_request(path: Path, output_path: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "agent-controller-validation-operation-request.v1",
                "claimsDigest": "0" * 64,
                "claims": {
                    "runId": "run",
                    "packageId": "package",
                    "taskId": "task",
                    "attempt": 1,
                    "operationId": "validation",
                    "commandId": "command",
                    "commandOperationId": "command-operation",
                    "planDigest": "0" * 64,
                    "sourceRevision": "source",
                    "projectionDigest": "1" * 64,
                    "protocolOutputs": [
                        {
                            "id": "report",
                            "role": "report",
                            "kind": "artifact",
                            "path": output_path,
                            "schemaVersion": "agent-lifecycle-unittest-report.v1",
                            "minBytes": 2,
                            "createNoReplace": True,
                        }
                    ],
                    "generatedAt": "2026-07-22T00:00:00Z",
                },
                "signerFingerprint": "0" * 64,
                "signatureDomain": "test",
                "signature": "",
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()

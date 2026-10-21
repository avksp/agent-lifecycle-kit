"""Actual root CLI collection preserves ordinary output and failed exits."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import write_json_create
from tests.cli.helpers import _run_cli
from tests.metrics.test_command_resources import request


class CommandResourceCliTests(unittest.TestCase):
    def test_post_effect_publication_error_preserves_real_stdout_and_explains_no_retry(self) -> None:
        import contextlib
        from io import StringIO
        from unittest.mock import patch

        from agent_lifecycle.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json_create(root / "request.json", request(root))
            stdout, stderr = StringIO(), StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), \
                 patch("agent_lifecycle.metrics.command_resources.write_json_create", side_effect=OSError("private-secret")):
                code = main(["--measure-request", str(root / "request.json"),
                             "--measure-out", str(root / "receipt.json"), "version"])
            self.assertEqual(json.loads(stdout.getvalue()), _run_cli(["version"])[1])
            error = json.loads(stderr.getvalue())
        self.assertEqual(code, 2)
        self.assertTrue(error["details"]["commandExecuted"])
        self.assertEqual(error["details"]["commandExitCode"], 0)
        self.assertNotIn("private-secret", str(error))
    def test_equals_options_are_measured_and_goal_progress_is_a_read_only_view(self) -> None:
        from tests.metrics.test_goal_progress import progress_inputs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json_create(root / "request.json", request(root))
            self.assertEqual(_run_cli([f"--measure-request={root / 'request.json'}",
                                       f"--measure-out={root / 'receipt.json'}", "version"])[0], 0)
            self.assertTrue((root / "receipt.json").is_file())
            context, observations, receipts = progress_inputs(3)
            write_json_create(root / "input.json", {"context": context, "observations": observations,
                                                    "qualifiedReceipts": receipts})
            code, result = _run_cli(["metrics", "goal-progress", "--input", str(root / "input.json"),
                                      "--now", "100", "--out", str(root / "progress.json")])
            self.assertEqual(code, 0)
            self.assertEqual(result["state"], "STALLED")
            self.assertFalse(result["authorityClaimed"])
    def test_measured_command_can_write_ordinary_output_in_receipt_directory(self) -> None:
        from tests.metrics.test_goal_progress import progress_inputs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json_create(root / "request.json", request(root))
            context, observations, receipts = progress_inputs(3)
            write_json_create(root / "input.json", {"context": context,
                "observations": observations, "qualifiedReceipts": receipts})
            code, result = _run_cli([
                "--measure-request", str(root / "request.json"),
                "--measure-out", str(root / "receipt.json"),
                "metrics", "goal-progress", "--input", str(root / "input.json"),
                "--now", "100", "--out", str(root / "ordinary-output.json"),
            ])
            self.assertEqual(code, 0)
            self.assertEqual(result["state"], "STALLED")
            self.assertEqual(json.loads((root / "ordinary-output.json").read_bytes()), result)
            self.assertEqual(json.loads((root / "receipt.json").read_bytes())["exitCode"], 0)

    def test_opt_in_version_stdout_is_unchanged_and_output_create_only(self) -> None:
        ordinary = _run_cli(["version"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json_create(root / "request.json", request(root))
            argv = ["--measure-request", str(root / "request.json"),
                    "--measure-out", str(root / "receipt.json"), "version"]
            self.assertEqual(_run_cli(argv), ordinary)
            receipt = json.loads((root / "receipt.json").read_bytes())
            self.assertEqual(receipt["exitCode"], 0)
            self.assertEqual(_run_cli(argv)[1]["code"], "command-measurement-output-exists")

    def test_failed_actual_dispatch_is_recorded_and_not_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json_create(root / "request.json", request(root))
            code, error = _run_cli([
                "--measure-request", str(root / "request.json"),
                "--measure-out", str(root / "receipt.json"), "version", "--unknown-option",
            ])
            receipt = json.loads((root / "receipt.json").read_bytes())
        self.assertEqual(code, 2)
        self.assertEqual(receipt["exitCode"], 2)
        self.assertEqual(receipt["outcome"], "FAILED")
        self.assertIn("code", error)


if __name__ == "__main__":
    unittest.main()

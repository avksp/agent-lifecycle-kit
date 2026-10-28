"""Exercise the actual direct CLI route."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import write_json_create
from agent_lifecycle.workflow.state import load_state
from tests.workflow.test_authorization_renewal import build_fixture, renewal


class RenewalCliTests(unittest.TestCase):
    def call(self, path, command, *options):
        root = Path(__file__).resolve().parents[2]
        return subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "agent_lifecycle",
                "workflow",
                command,
                "--state",
                str(path),
                "--operation-id",
                "cli-" + command,
                "--expected-revision",
                str(load_state(path)["stateRevision"]),
                "--source-revision",
                "source",
                "--reason",
                "fixture-only",
                *options,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=dict(os.environ, PYTHONPATH=str(root / "src")),
        )

    def test_actual_expired_refusal_renewal_and_same_review_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, review, audit = build_fixture(root, "v5")
            before = path.read_bytes(), (root / "events.jsonl").read_bytes()
            options = ("--task", "WS-01", "--review", review, "--implementation-audit", audit)
            expired = self.call(path, "task-review-apply", *options)
            self.assertEqual(expired.returncode, 2, expired.stderr)
            self.assertIn("authorization-expired", expired.stdout + expired.stderr)
            self.assertEqual((path.read_bytes(), (root / "events.jsonl").read_bytes()), before)
            state = load_state(path)
            write_json_create(root / "renewal.json", renewal(state))
            result = self.call(path, "authorization-renew", "--receipt", "renewal.json")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["phase"], "RUNNING")
            self.assertEqual(load_state(path)["tasks"], state["tasks"])
            accepted = self.call(path, "task-review-apply", *options)
            self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
            self.assertEqual(load_state(path)["phase"], "FINAL_AUDIT")

    def test_direct_command_help(self):
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, "-B", "-m", "agent_lifecycle", "workflow", "authorization-renew", "--help"],
            capture_output=True,
            text=True,
            env=dict(os.environ, PYTHONPATH=str(root / "src")),
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--receipt", result.stdout)

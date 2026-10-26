"""Tests for bounded baseline collection."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.authority_io import open_authority_read
from agent_lifecycle.contracts.performance_limits import performance_limits_to_json
from tools.performance.run_performance_baseline import (
    _invoke,
    _operation_specs,
    _p95,
    _run_bounded,
    collect_baseline,
    source_identity,
)


def _policy() -> dict:
    return {
        "schemaVersion": "agent-performance-budgets.v1",
        "revision": 1,
        "sourceRevision": "dbf0ffbc6a3f8bd53f7408f58cb4475d3aef2350",
        "limits": performance_limits_to_json(),
        "benchmark": {
            "warmupSamples": 1,
            "samplesPerCase": 1,
            "maxCommandWallSeconds": 5,
            "maxTotalWallSeconds": 20,
            "maxOutputBytes": 4096,
        },
        "operations": ["canonical-digest"],
        "productionPromotionClaimed": False,
    }


class PerformanceBaselineTests(unittest.TestCase):
    def test_in_process_baseline_is_bounded_and_revision_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = root / "policy.json"
            output = root / "evidence" / "baseline.json"
            policy.write_text(json.dumps(_policy()), encoding="utf-8")
            result = collect_baseline(policy_path=policy, repository_root=Path.cwd(), output_path=output)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["comparability"]["status"], "COMPARABLE")
            self.assertEqual(result["operations"][0]["summary"]["sampleCount"], 1)
            self.assertTrue(output.is_file())
            self.assertEqual(result["productionPromotionClaimed"], False)

    def test_nearest_rank_p95_uses_the_largest_of_seven_samples(self) -> None:
        self.assertEqual(_p95([4, 1, 7, 2, 5, 3, 6]), 7)
        self.assertIsNone(_p95([]))

    def test_worker_environment_replaces_inherited_python_configuration(self) -> None:
        root = Path.cwd()
        operation = _operation_specs(root, root, ["workflow-status-small"])[0]
        with mock.patch.dict(os.environ, {"PYTHONPATH": "poison", "PYTHONHOME": "poison"}):
            with mock.patch(
                "tools.performance.run_performance_baseline._run_bounded",
                return_value={"status": "PASS"},
            ) as runner:
                _invoke(operation, root, 5, 4096, time.monotonic() + 5)
        env = runner.call_args.kwargs["env"]
        self.assertNotIn("PYTHONHOME", env)
        self.assertEqual(env["PYTHONPATH"], str(root / "src"))
        self.assertIn("--source-root", runner.call_args.args[0])

    def test_expired_deadline_does_not_start_a_process(self) -> None:
        operation = _operation_specs(Path.cwd(), Path.cwd(), ["cli-version"])[0]
        with mock.patch("subprocess.Popen") as launch:
            result = _invoke(operation, Path.cwd(), 5, 4096, 0)
        launch.assert_not_called()
        self.assertEqual(result["status"], "FAIL")

    def test_bounded_child_retains_output_limit_refusal(self) -> None:
        launched = []
        original = subprocess.Popen

        def launch(*args, **kwargs):
            process = original(*args, **kwargs)
            launched.append(process)
            return process

        with mock.patch("subprocess.Popen", side_effect=launch):
            result = _run_bounded(
                [sys.executable, "-c", "print('x' * 65536)"],
                cwd=Path.cwd(),
                env=os.environ.copy(),
                timeout=5,
                max_output_bytes=16,
            )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("performance-output-limit", [item["code"] for item in result["blockers"]])
        self.assertTrue(launched[0].stdout.closed)
        self.assertTrue(launched[0].stderr.closed)
        self.assertIsNotNone(launched[0].poll())

    def test_nonregular_source_refuses_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root / "sample.py"
            if hasattr(os, "mkfifo"):
                os.mkfifo(path)
            else:
                path.mkdir()
            program = """
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from agent_lifecycle.contracts import LifecycleError
from tools.performance.run_performance_baseline import source_identity
with patch('subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=b'sample.py\\0')):
    try:
        source_identity(Path(sys.argv[1]))
    except LifecycleError:
        raise SystemExit(0)
raise SystemExit(1)
"""
            result = subprocess.run(
                [sys.executable, "-B", "-c", program, str(root)],
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_source_swap_is_bound_to_the_open_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root / "sample.py"
            path.write_bytes(b"same contents")

            @contextmanager
            def swapped(target, *, root):
                with open_authority_read(target, root=root) as stream:
                    yield stream
                    replacement = root / "replacement.py"
                    replacement.write_bytes(b"same contents")
                    replacement.replace(target)

            with mock.patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=b"sample.py\0")):
                with mock.patch("tools.performance.run_performance_baseline.open_authority_read", swapped):
                    with self.assertRaises((LifecycleError, PermissionError)):
                        source_identity(root)

    def test_source_deadline_refuses_before_inventory_launch(self) -> None:
        with mock.patch("subprocess.run") as launch:
            with self.assertRaises(LifecycleError) as raised:
                source_identity(Path.cwd(), deadline=0)
        launch.assert_not_called()
        self.assertEqual(raised.exception.code, "performance-source-deadline-exceeded")

    def test_source_deadline_is_checked_between_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "sample.py").write_bytes(b"content")
            clock = [0.0]

            @contextmanager
            def delayed(target, *, root):
                with open_authority_read(target, root=root) as stream:

                    def read(limit):
                        value = stream.read(limit)
                        clock[0] = 10.0
                        return value

                    yield SimpleNamespace(read=read, fileno=stream.fileno)

            with mock.patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=b"sample.py\0")):
                with mock.patch("tools.performance.run_performance_baseline.open_authority_read", delayed):
                    with mock.patch("time.monotonic", side_effect=lambda: clock[0]):
                        with self.assertRaises(LifecycleError) as raised:
                            source_identity(root, deadline=5)
            self.assertEqual(raised.exception.code, "performance-source-deadline-exceeded")


if __name__ == "__main__":
    unittest.main()

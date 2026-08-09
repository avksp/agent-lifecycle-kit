from __future__ import annotations

import unittest

from .run_packaging_smoke import ROOT, _portable_argv, _portable_path, _stream_identity


class PackagingSmokePortabilityTests(unittest.TestCase):
    def test_external_executable_paths_are_reduced_to_stable_labels(self) -> None:
        external_python = "/" + "Users/example/venv/bin/python3.12"
        self.assertEqual(
            _portable_argv([external_python, "-m", "build"]),
            ["python", "-m", "build"],
        )
        self.assertEqual(
            _portable_argv(["/private/tmp/venv/bin/agent-lifecycle", "version"]),
            ["agent-lifecycle", "version"],
        )
        self.assertEqual(
            _portable_argv([r"C:\Users\example\venv\Scripts\python.exe", "-m", "build"]),
            ["python", "-m", "build"],
        )

    def test_repository_paths_remain_relative(self) -> None:
        self.assertEqual(_portable_path(ROOT / "dist"), "dist")

    def test_process_output_is_represented_only_by_identity(self) -> None:
        identity = _stream_identity("sensitive process output")

        self.assertEqual(identity["bytes"], 24)
        self.assertEqual(len(identity["sha256"]), 64)
        self.assertNotIn("output", identity)


if __name__ == "__main__":
    unittest.main()

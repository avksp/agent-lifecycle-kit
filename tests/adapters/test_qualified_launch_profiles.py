from __future__ import annotations

import json
import contextlib
import os
import tempfile
import unittest
from io import StringIO
from pathlib import Path

from agent_lifecycle.adapter_sessions.local_launch_profile import validate_local_launch_profile
from agent_lifecycle.adapter_sessions.qualification import load_shipped_launch_profile, qualified_profile_output_path
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.cli import main

ROOT = Path(__file__).resolve().parents[2]


class QualifiedLaunchProfileTests(unittest.TestCase):
    def test_profiles_are_literal_version_bound_and_preserve_wrapper_only(self) -> None:
        expected = {"codex": "0.147.0", "claude": "2.1.226", "opencode": "1.18.15"}
        for adapter_id, version in expected.items():
            with self.subTest(adapter=adapter_id):
                profile = load_shipped_launch_profile(adapter_id, repository_root=ROOT)
                descriptor = json.loads((ROOT / f"adapters/{adapter_id}/adapter.descriptor.json").read_text(encoding="utf-8"))
                self.assertEqual(validate_local_launch_profile(profile)["status"], "PASS")
                self.assertEqual(profile["qualification"]["expectedVersion"], version)
                self.assertEqual(descriptor["managedLaunch"]["status"], "WRAPPER_ONLY")
                self.assertFalse(descriptor["qualifiedLaunch"]["publicSupportClaimed"])
                self.assertNotIn("--dangerously-skip-permissions", profile["argvTemplate"])
                self.assertNotIn("--auto", profile["argvTemplate"])

    def test_profile_loader_rejects_executable_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = root / "adapters/codex"
            adapter.mkdir(parents=True)
            (adapter / "launch_profile.py").write_text("import os\nPROFILE = {}\n", encoding="utf-8")
            with self.assertRaises(LifecycleError) as raised:
                load_shipped_launch_profile("codex", repository_root=root)
        self.assertEqual(raised.exception.code, "qualified-launch-profile-not-literal")

    def test_generated_profile_output_is_local_and_flat(self) -> None:
        self.assertEqual(qualified_profile_output_path(".alk/host-launch/codex.json").as_posix(), ".alk/host-launch/codex.json")
        for path in ("/tmp/codex.json", ".alk/host-launch/nested/codex.json", "codex.json"):
            with self.subTest(path=path), self.assertRaises(LifecycleError):
                qualified_profile_output_path(path)

    def test_cli_generates_ignored_local_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = Path.cwd()
            stdout = StringIO()
            try:
                os.chdir(root)
                with contextlib.redirect_stdout(stdout):
                    code = main([
                        "adapter", "launch-profile", "--adapter", "codex",
                        "--repository-root", str(ROOT),
                        "--out", ".alk/host-launch/codex.json",
                    ])
                payload = json.loads(stdout.getvalue())
                generated = json.loads((root / ".alk/host-launch/codex.json").read_text(encoding="utf-8"))
            finally:
                os.chdir(previous)
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(generated["qualification"]["expectedVersion"], "0.147.0")

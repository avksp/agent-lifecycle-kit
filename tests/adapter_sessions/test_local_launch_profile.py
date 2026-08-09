from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.adapter_sessions.local_launch_profile import (
    load_local_launch_profile,
    render_local_launch_argv,
    validate_local_launch_profile,
)
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.schemas import get_schema

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/adapter_sessions/fixtures/local_launch_profiles"


class LocalLaunchProfileTests(unittest.TestCase):
    def test_valid_profile_passes_and_public_schemas_are_registered(self) -> None:
        profile = _fixture("valid.json")

        validation = validate_local_launch_profile(profile)

        self.assertEqual(validation["status"], "PASS", validation["blockers"])
        self.assertEqual(len(validation["profileDigest"]), 64)
        for schema_id in (
            "agent-local-host-launch-profile.v1",
            "agent-local-host-launch-profile-validation.v1",
            "agent-local-host-launch-profile-receipt.v1",
            "agent-local-host-launch-probe-receipt.v1",
        ):
            self.assertEqual(get_schema(schema_id)["$id"], schema_id)

    def test_invalid_fixtures_fail_closed(self) -> None:
        expected = {
            "path-escape.json": "local-launch-profile-executable",
            "shell-command.json": "local-launch-profile-shell-executable",
            "unknown-placeholder.json": "local-launch-profile-placeholder",
            "env-wildcard.json": "local-launch-profile-env-pattern",
        }
        for name, code in expected.items():
            with self.subTest(name=name):
                validation = validate_local_launch_profile(_fixture(name))
                self.assertEqual(validation["status"], "FAIL")
                self.assertIn(code, {item["code"] for item in validation["blockers"]})

    def test_loader_requires_ignored_local_root_and_rejects_outside_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local = root / ".alk/host-launch/codex.json"
            local.parent.mkdir(parents=True)
            local.write_text(json.dumps(_fixture("valid.json")), encoding="utf-8")
            outside = root / "codex.json"
            outside.write_text(json.dumps(_fixture("valid.json")), encoding="utf-8")

            relative, profile, validation = load_local_launch_profile(local, project_root=root)
            self.assertEqual(relative.as_posix(), ".alk/host-launch/codex.json")
            self.assertEqual(profile["adapterId"], "codex")
            self.assertEqual(validation["status"], "PASS")
            with self.assertRaises(LifecycleError) as raised:
                load_local_launch_profile(outside, project_root=root)

        self.assertEqual(raised.exception.code, "local-launch-profile-path-outside-root")

    def test_loader_rejects_symlinked_local_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside"
            outside.mkdir()
            profile = outside / "codex.json"
            profile.write_text(json.dumps(_fixture("valid.json")), encoding="utf-8")
            (root / ".alk").mkdir()
            (root / ".alk/host-launch").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(LifecycleError) as raised:
                load_local_launch_profile(root / ".alk/host-launch/codex.json", project_root=root)

        self.assertEqual(raised.exception.code, "local-launch-profile-path-invalid")

    def test_version_probe_is_read_only_and_bare_executable_requires_path(self) -> None:
        profile = _fixture("valid.json")
        profile["versionProbeArgs"] = ["run", "task.md"]
        validation = validate_local_launch_profile(profile)
        self.assertIn("local-launch-profile-version-probe", {item["code"] for item in validation["blockers"]})

        profile = _fixture("valid.json")
        profile["env"]["allow"] = ["HOME"]
        validation = validate_local_launch_profile(profile)
        self.assertIn("local-launch-profile-path-env-required", {item["code"] for item in validation["blockers"]})

    def test_renderer_accepts_only_whole_token_frozen_placeholders(self) -> None:
        profile = _fixture("valid.json")
        profile["argvTemplate"] = ["--state", "{state_path}", "--task", "{task_id}"]

        argv = render_local_launch_argv(profile, {"state_path": "work/state.json", "task_id": "WS-01"})

        self.assertEqual(argv, ["codex", "--state", "work/state.json", "--task", "WS-01"])
        profile["argvTemplate"] = ["prefix-{task_id}"]
        validation = validate_local_launch_profile(profile)
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("local-launch-profile-placeholder-shape", {item["code"] for item in validation["blockers"]})


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

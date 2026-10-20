from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.launch_qualification import version_policy_bounds
from agent_lifecycle.host_protocol.inspection import inspect_adapter_descriptor
from agent_lifecycle.host_protocol.inspection_common import CommandRun
from agent_lifecycle.host_protocol.opencode_compatibility import (
    effective_qualification,
    help_commands,
    model_arguments,
    opencode_family,
    run_arguments,
)

ROOT = Path(__file__).resolve().parents[2]


class OpenCodeCompatibilityTests(unittest.TestCase):
    def test_distinct_stable_families_and_unsupported_discovery(self) -> None:
        for version, family in (("1.18.9", 1), ("1.19.3", 1), ("2.0.32", 2)):
            with self.subTest(version=version):
                self.assertEqual(opencode_family(f"opencode {version}\n"), (version, family))
                self.assertEqual(effective_qualification(version, surfaces_ok=True)["status"], "COMPATIBLE_UNVERIFIED")
        for text in ("3.0.0", "0.1.0", "2.0", "02.0.32", "2.0.32-rc.1", "2.0.32+build", "2.0.32 1.18.9", "not a version"):
            with self.subTest(text=text), self.assertRaises(LifecycleError):
                opencode_family(text)

    def test_live_evidence_requires_matching_source_operation_and_same_major_range(self) -> None:
        evidence = {"status": "ACCEPTED", "sourceRevision": "a" * 40, "operation": "run",
                    "hostVersionPolicy": {"mode": "range", "accepted": "1.18.9..1.19.3"}, "evidenceIds": ["native-receipt"]}
        for version in ("1.18.9", "1.19.0", "1.19.3"):
            self.assertEqual(effective_qualification(version, surfaces_ok=True, operation="run", source_revision="a" * 40, accepted_evidence=evidence)["status"], "VERIFIED")
        for version in ("1.18.8", "1.19.4", "2.0.32"):
            self.assertEqual(effective_qualification(version, surfaces_ok=True, operation="run", source_revision="a" * 40, accepted_evidence=evidence)["status"], "COMPATIBLE_UNVERIFIED")
        for changes in ({"source_revision": "b" * 40}, {"operation": "export"}, {"surfaces_ok": False}):
            kwargs = dict(surfaces_ok=True, operation="run", source_revision="a" * 40, accepted_evidence=evidence)
            kwargs.update(changes)
            self.assertNotEqual(effective_qualification("1.18.9", **kwargs)["status"], "VERIFIED")
        evidence["hostVersionPolicy"] = {"mode": "exact", "accepted": "2.0.32"}
        self.assertEqual(effective_qualification("2.0.32", surfaces_ok=True, operation="run", source_revision="a" * 40, accepted_evidence=evidence)["status"], "VERIFIED")
        self.assertNotEqual(effective_qualification("2.0.33", surfaces_ok=True, operation="run", source_revision="a" * 40, accepted_evidence=evidence)["status"], "VERIFIED")

    def test_invalid_ranges_never_create_verification(self) -> None:
        for accepted in ("2.0.32..2.0.30", "1.19.3..2.0.32", "2.0.32-rc..2.0.32", "*", "2.0.0"):
            with self.subTest(accepted=accepted), self.assertRaises(ValueError):
                version_policy_bounds({"mode": "range", "accepted": accepted})
            self.assertEqual(effective_qualification("2.0.32", surfaces_ok=True, accepted_evidence={"hostVersionPolicy": {"mode": "range", "accepted": accepted}})["status"], "UNSUPPORTED")

    def test_family_argv_preserves_message_attachment_title_and_model_identity(self) -> None:
        for major in (1, 2):
            argv = run_arguments(binary="opencode", major=major, message="Review the assignment", directory="/work with spaces",
                                 title="attempt-unique-1", model="provider/model", variant="high", files=("/input with spaces.json",))
            self.assertEqual(argv[:3], ["opencode", "run", "Review the assignment"])
            self.assertIn("--file=/input with spaces.json", argv)
            self.assertEqual(argv[argv.index("--title") + 1], "attempt-unique-1")
            self.assertNotIn("--auto", argv)
            if major == 1:
                self.assertIn("--dir", argv)
                self.assertEqual(argv[argv.index("--variant") + 1], "high")
            else:
                self.assertIn("--standalone", argv)
                self.assertIn("provider/model#high", argv)
                self.assertNotIn("--dir", argv)
                self.assertNotIn("--variant", argv)
        malformed = (("provider/model#low", "high"), (None, "high"), ("provider/model#", None),
                     ("--help", None), ("model", None), ("provider/model\0", None),
                     ("provider/model", "high\0"), ("provider/model", "--help"),
                     ("", None), ("provider/model", ""), ("provider/model name", None),
                     ("provider/model", "high extra"), ("provider//model", None))
        for major in (1, 2):
            for model, variant in malformed:
                with self.subTest(major=major, model=model, variant=variant), self.assertRaises(LifecycleError):
                    model_arguments(major, model, variant)
            self.assertEqual(model_arguments(major, None, None), [])
            self.assertIn("openrouter/vendor/model:free", model_arguments(major, "openrouter/vendor/model:free", None))

    def test_real_inspection_uses_family_routes_and_rejects_zero_exit_root_help(self) -> None:
        descriptor = json.loads((ROOT / "adapters/opencode/adapter.descriptor.json").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = root / "adapters/opencode"
            adapter.mkdir(parents=True)
            descriptor_path = adapter / "adapter.descriptor.json"
            descriptor_path.write_text(json.dumps(descriptor))
            shutil.copyfile(ROOT / "adapters/opencode/inspection_profile.py", adapter / "inspection_profile.py")
            (adapter / "opencode.json").write_text(json.dumps({"plugin": ["./plugins/agent-lifecycle-kit.js"]}))
            (root / "opencode.json").write_text(json.dumps({"plugin": ["./adapters/opencode/plugins/agent-lifecycle-kit.js"]}))
            for version, major in (("1.18.9", 1), ("1.19.3", 1), ("2.0.32", 2)):
                for root_help in (False, True):
                    calls = []
                    def run(argv, _timeout, calls=calls, version=version, major=major, root_help=root_help):
                        calls.append(argv)
                        if argv[1:] == ["--version"]:
                            return CommandRun(0, version, "")
                        if argv[1:] == ["auth", "--help"]:
                            return CommandRun(0, "opencode auth login logout", "")
                        for name, (arguments, markers) in help_commands(major).items():
                            if argv[1:] == arguments:
                                text = "opencode [command]\nCommands: run export stats" if name == "export" and root_help else " ".join(markers)
                                return CommandRun(0, text, "")
                        return CommandRun(1, "", "unexpected route")
                    with self.subTest(version=version, root_help=root_help):
                        payload = inspect_adapter_descriptor(descriptor, descriptor_path=descriptor_path, project_root=root, command_runner=run)
                        self.assertEqual(payload["status"], "FAIL" if root_help else "PASS")
                        self.assertEqual(payload["descriptorMaturity"], "VERIFIED")
                        self.assertEqual(payload["effectiveVersionQualification"]["status"], "UNSUPPORTED" if root_help else "COMPATIBLE_UNVERIFIED")
                        self.assertIn(["opencode", *help_commands(major)["export"][0]], calls)


if __name__ == "__main__":
    unittest.main()

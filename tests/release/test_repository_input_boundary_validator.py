from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.release.validate_repository_input_boundaries import (
    _authority_checks,
    _authority_runtime_checks,
    _delegation_errors,
    _inspect_source,
    validate_sources,
)

from agent_lifecycle.contracts import authority_io, paths

ROOT = Path(__file__).resolve().parents[2]


class RepositoryInputBoundaryValidatorTests(unittest.TestCase):
    def copy_authority_sources(self, root):
        target = root / "contracts"
        target.mkdir(parents=True)
        for name in ("canonical.py", "paths.py", "authority_io.py"):
            shutil.copy2(ROOT / "src/agent_lifecycle/contracts" / name, target / name)

    def test_current_sources_pass_boundary_validator(self) -> None:
        payload = validate_sources(ROOT / "src/agent_lifecycle")

        self.assertEqual(payload["status"], "PASS", payload["blockers"])
        self.assertEqual(payload["schemaVersion"], "agent-repository-input-boundary-validation.v1")
        self.assertTrue(payload["requiredProperties"]["gitRevisionOptionBoundary"])
        self.assertTrue(payload["requiredProperties"]["stableRegularFileContainment"])
        self.assertTrue(payload["requiredProperties"]["symlinksRejected"])
        self.assertTrue(payload["requiredProperties"]["artifactRecognitionSeparateFromValidation"])

    def test_validator_requires_each_boundary_source_and_regression_test(self) -> None:
        payload = validate_sources(ROOT / "src/agent_lifecycle")

        checked = {item["id"] for item in payload["checks"]}
        self.assertLessEqual(
            {"source-paths", "source-git", "source-changeSummary", "source-evidenceIndex", "security-regression-tests"},
            checked,
        )
        self.assertLessEqual(
            {"authority-canonical", "authority-paths", "authority-backend", "authority-source-freshness"}, checked
        )

    def test_facade_delegation_accepts_import_alias_but_not_dead_or_unused_calls(self):
        prefix = "from agent_lifecycle.contracts.authority_io import read_authority_bytes as guarded\n"
        contract = {"read": {"agent_lifecycle.contracts.authority_io.read_authority_bytes"}}
        self.assertEqual(
            _delegation_errors(prefix + "def read(path):\n return guarded(path)\n", contract, facade=True), []
        )
        for body in (
            " return b''\n",
            " if False:\n  return guarded(path)\n return b''\n",
            " def unused():\n  return guarded(path)\n return b''\n",
            " return b''\n guarded(path)\n",
        ):
            with self.subTest(body=body):
                self.assertTrue(
                    any(
                        "missing-call" in e
                        for e in _delegation_errors(prefix + "def read(path):\n" + body, contract, facade=True)
                    )
                )
        errors = _delegation_errors(
            prefix + "def read(path):\n guarded(path)\n return path.read_bytes()\n", contract, facade=True
        )
        self.assertTrue(any("unguarded-io" in e for e in errors))

    def test_removed_backend_protections_fail_for_specific_reasons_with_markers_retained(self):
        source = (ROOT / "src/agent_lifecycle/contracts/authority_io.py").read_text()
        for old, new, reason in (
            ("os.O_NOFOLLOW", "0", "_Directory.open_child:missing-primitive:os.O_NOFOLLOW"),
            ("stat.S_ISREG(info.st_mode)", "True", "_require_regular:missing-call:stat.S_ISREG"),
            ('"st_mtime_ns"', '"REMOVED"', "_same_identity:missing-primitive:st_mtime_ns"),
            (
                "_same_identity(before_path, before, content=True)",
                "pass",
                "open_authority_read:missing-descriptor-binding:before_path/before",
            ),
        ):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.copy_authority_sources(root)
                (root / "contracts/authority_io.py").write_text(source.replace(old, new) + f"\n# {old}\n")
                checks = _authority_checks(root)["checks"]
                backend = next(c for c in checks if c["id"] == "authority-backend")
                self.assertEqual(backend["status"], "FAIL")
                self.assertIn(reason, backend["errors"])

    def test_marker_only_backend_cannot_earn_a_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_authority_sources(root)
            (root / "contracts/authority_io.py").write_text("# O_NOFOLLOW dir_fd st_mtime_ns _require_regular\n")
            check = next(c for c in _authority_checks(root)["checks"] if c["id"] == "authority-backend")
            self.assertIn("open_authority_read:missing-function", check["errors"])

    def test_source_copy_does_not_attest_installed_runtime_and_does_not_execute(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "MUST_NOT_EXIST"
            source = root / "authority_io.py"
            source.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
            _, _, errors = _inspect_source(source, authority_io)
            self.assertIn("source-runtime-origin-mismatch", errors)
            self.assertFalse(marker.exists())
            shutil.copy2(Path(authority_io.__file__), source)
            _, _, errors = _inspect_source(source, authority_io)
            self.assertIn("source-runtime-origin-mismatch", errors)

    def test_live_runtime_replacement_cannot_be_attested_from_unchanged_disk(self):
        with patch.object(paths, "read_stable_repository_file", lambda *_a, **_kw: b"unsafe"):
            payload = validate_sources(ROOT / "src/agent_lifecycle")
        self.assertEqual(payload["status"], "FAIL")
        self.assertFalse(any(payload["requiredProperties"].values()))
        check = next(c for c in payload["checks"] if c["id"] == "authority-paths")
        self.assertIn("source-runtime-code-mismatch", check["errors"])

    def test_forged_module_file_cannot_rebind_code_loaded_from_another_path(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "authority_io.py"
            shutil.copy2(Path(authority_io.__file__), source)
            with patch.object(authority_io, "__file__", str(source)):
                _, _, errors = _inspect_source(source, authority_io)
            self.assertIn("source-runtime-code-mismatch", errors)

    def test_missing_and_outside_backend_are_not_discovered_on_sys_path(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "authority_io.py"
            for exists in (False, True):
                if exists:
                    shutil.copy2(Path(authority_io.__file__), target)
                check = next(
                    c
                    for c in _authority_checks(ROOT / "src/agent_lifecycle", target)["checks"]
                    if c["id"] == "authority-backend"
                )
                self.assertIn("backend-outside-source-context", check["errors"])
                self.assertEqual(check["status"], "FAIL")

    def test_backend_symlink_is_rejected_before_attributing_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_authority_sources(root)
            backend = root / "contracts/authority_io.py"
            backend.unlink()
            try:
                backend.symlink_to(Path(authority_io.__file__))
            except OSError:
                self.skipTest("native symlink privilege unavailable")
            check = next(c for c in _authority_checks(root)["checks"] if c["id"] == "authority-backend")
            self.assertIn("source-unavailable-or-invalid", check["errors"])

    def test_native_behavior_checks_cover_actual_readers_and_substitution(self):
        checks = _authority_runtime_checks()
        self.assertFalse([c for c in checks if c["status"] == "FAIL"], checks)
        self.assertLessEqual(
            {"authority-runtime-leaf-race", "authority-runtime-parent-race", "authority-runtime-cap"},
            {c["id"] for c in checks},
        )


if __name__ == "__main__":
    unittest.main()

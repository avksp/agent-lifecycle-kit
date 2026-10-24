"""Current source authority remains bound after implementation extraction."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_lifecycle.adapter_sessions import attempt_authority as authority
from agent_lifecycle.adapter_sessions import bootstrap_r11 as legacy
from agent_lifecycle.adapter_sessions import codex_exact_prompt as exact
from agent_lifecycle.adapter_sessions import private_input
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from tests.windows_test_support import unsafe_private_access


class ExtractedAttemptAuthorityTests(unittest.TestCase):
    def test_public_compatibility_aliases_are_original_callable_objects(self):
        for name in (
            "capture_attempt_authority",
            "verify_attempt_reservation",
            "claim_attempt_start",
            "record_uncertain_attempt",
            "require_positive_attempt_result",
            "reserve_attempt_result",
            "publish_attempt_result",
            "read_attempt_result",
        ):
            self.assertIs(getattr(legacy, name), getattr(authority, name))
        for name in ("_private_dir", "_verify_private_ancestors", "_write_exclusive", "_read_private"):
            self.assertIs(getattr(exact, name), getattr(private_input, name))

    def test_both_new_implementation_files_are_pinned_and_mutation_refuses(self):
        for changed in ("attempt_authority.py", "private_input.py", "input_lifecycle.py", "codex_input_diagnostics.py"):
            with self.subTest(changed=changed), TemporaryDirectory() as tmp:
                root = Path(tmp)
                for name in authority._SOURCES:
                    target = root / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(name.encode())
                manifest = {"status": "FROZEN", "planRevision": 82}
                manifest_path = root / "plan.manifest.json"
                manifest_path.write_bytes(canonical_bytes(manifest))
                lock = root / "plan.lock.json"
                lock.write_bytes(b'{"fixture":true}')
                selected = authority.capture_attempt_authority(root, lock_path=lock, manifest_path=manifest_path)
                import hashlib

                intent = {
                    **selected,
                    "lockDigest": hashlib.sha256(lock.read_bytes()).hexdigest(),
                    "planDigest": canonical_digest(manifest),
                }
                authority._current_authority(root, intent)
                name = "src/agent_lifecycle/adapter_sessions/" + changed
                self.assertIn(name, selected["authoritySourceSha256"])
                (root / name).write_bytes(b"changed implementation")
                with self.assertRaises(LifecycleError) as caught:
                    authority._current_authority(root, intent)
                self.assertEqual(caught.exception.code, "r11-result-authority-stale")

    def test_private_read_refuses_mode_symlink_and_byte_overflow(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "private/input.raw"
            private_input._write_exclusive(path, b"abc", root=root)
            self.assertEqual(private_input._read_private(path, root=root), b"abc")
            with unsafe_private_access(path), self.assertRaises(LifecycleError):
                private_input._read_private(path, root=root)
            with self.assertRaises(LifecycleError):
                private_input._read_private(path, root=root, max_bytes=2)
            link = path.with_name("alias.raw")
            link.symlink_to(path.name)
            with self.assertRaises(LifecycleError):
                private_input._read_private(link, root=root)


class R1054PinsTests(unittest.TestCase):
    def test_each_direct_process_owner_mutation_invalidates_current_authority(self):
        import hashlib

        for changed in ("process_capture.py", "process_control.py", "process_groups.py", "process_telemetry.py"):
            with self.subTest(owner=changed), TemporaryDirectory() as tmp:
                root = Path(tmp)
                for name in authority._SOURCES:
                    target = root / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(name.encode())
                manifest = root / "plan.manifest.json"
                manifest.write_bytes(canonical_bytes({"status": "FROZEN"}))
                lock = root / "plan.lock.json"
                lock.write_bytes(b'{"lock":true}')
                selected = authority.capture_attempt_authority(root, lock_path=lock, manifest_path=manifest)
                owner = "src/agent_lifecycle/adapter_sessions/" + changed
                self.assertIn(owner, selected["authoritySourceSha256"])
                intent = {
                    **selected,
                    "lockDigest": hashlib.sha256(lock.read_bytes()).hexdigest(),
                    "planDigest": canonical_digest({"status": "FROZEN"}),
                }
                authority._current_authority(root, intent)
                (root / owner).write_bytes(b"changed process implementation")
                with self.assertRaises(LifecycleError) as caught:
                    authority._current_authority(root, intent)
                self.assertEqual(caught.exception.code, "r11-result-authority-stale")


class AttemptDurabilityBoundaryTests(unittest.TestCase):
    def test_condition_is_public_contract(self):
        from agent_lifecycle.contracts.errors import require_condition

        self.assertIs(authority._require, require_condition)

    def test_platforms_use_existing_authority_barrier_and_propagate_failure(self):
        from unittest.mock import patch

        path = Path("fixture")
        for platform in ("posix", "nt"):
            failure = OSError("durability failed")
            with (
                self.subTest(platform=platform),
                patch.object(authority.os, "name", platform),
                patch.object(authority, "sync_authority_directory", side_effect=failure) as barrier,
                patch.object(authority, "hasattr", return_value=True, create=True),
            ):
                with self.assertRaises(OSError) as caught:
                    authority._sync_directory(path)
                self.assertIs(caught.exception, failure)
                barrier.assert_called_once_with(path)

    def test_missing_posix_primitive_preserves_refusal(self):
        from unittest.mock import patch

        path = Path("fixture")
        with (
            patch.object(authority.os, "name", "posix"),
            patch.object(authority, "hasattr", return_value=False, create=True),
            self.assertRaises(LifecycleError) as caught,
        ):
            authority._sync_directory(path)
        self.assertEqual(caught.exception.code, "r11-durable-storage-unavailable")
        self.assertEqual(str(caught.exception), "directory durability is unavailable on this route")

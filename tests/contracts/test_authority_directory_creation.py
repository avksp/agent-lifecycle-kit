"""Exercise create-only directory publication with benign temporary files."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError, authority_io


class AuthorityDirectoryCreationTests(unittest.TestCase):
    def test_publish_complete_directory_and_refuse_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "package"
            files = {"plan.json": b"draft", "notes.md": b"notes"}
            authority_io.create_authority_directory(target, files, root=root)
            self.assertEqual({item.name: item.read_bytes() for item in target.iterdir()}, files)
            self.assertEqual(list(root.iterdir()), [target])
            with self.assertRaises(LifecycleError) as raised:
                authority_io.create_authority_directory(target, {"different": b"new"}, root=root)
            self.assertEqual(raised.exception.code, "authority-directory-exists")
            self.assertEqual({item.name: item.read_bytes() for item in target.iterdir()}, files)
            self.assertEqual(list(root.iterdir()), [target])

    def test_native_primitive_preserves_an_existing_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source, target = root / "prepared", root / "occupied"
            source.mkdir()
            target.mkdir()
            (source / "note").write_bytes(b"synthetic")
            source_identity = source.stat()
            target_identity = target.stat()
            with authority_io.hold_authority_directory(root, writable=True) as parent:
                publish = authority_io._directory_no_replace(parent)
                with self.assertRaises(FileExistsError):
                    publish(source.name, target.name)
            self.assertTrue(os.path.samestat(source_identity, source.stat()))
            self.assertTrue(os.path.samestat(target_identity, target.stat()))
            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual((source / "note").read_bytes(), b"synthetic")

    def test_prepare_failure_has_no_visible_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "package"
            with (
                patch.object(authority_io._Directory, "write_child", side_effect=OSError("injected write failure")),
                self.assertRaises(LifecycleError) as raised,
            ):
                authority_io.create_authority_directory(target, {"plan.json": b"draft"}, root=root)
            self.assertEqual(raised.exception.code, "authority-directory-publish-failed")
            self.assertFalse(target.exists())
            stage = root / raised.exception.details["stagingName"]
            self.assertTrue(stage.is_dir())

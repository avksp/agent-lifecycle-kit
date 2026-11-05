"""File-only pinning preserves boundary checks while parents remain writable."""

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent_lifecycle.contracts import LifecycleError, authority_io


class AuthorityReadFdTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.path = self.root / "claim.json"
        authority_io.create_authority_bytes(self.path, b"owned", root=self.root)

    def test_parent_writes_keep_readonly_fd_and_close_it(self):
        identity = self.path.stat()
        with authority_io.hold_authority_read_fd(self.path, root=self.root) as fd:
            self.assertFalse(os.get_inheritable(fd))
            self.assertTrue(os.path.samestat(identity, os.fstat(fd)))
            self.assertEqual(os.read(fd, 5), b"owned")
            with self.assertRaises(OSError):
                os.write(fd, b"foreign")
            sibling = self.root / "head.json"
            authority_io.create_authority_bytes(sibling, b"old", root=self.root)
            authority_io.replace_authority_bytes(sibling, b"new", root=self.root)
            authority_io.sync_authority_directory(self.root)
            self.assertEqual(sibling.read_bytes(), b"new")
        with self.assertRaises(OSError):
            os.fstat(fd)
        self.assertEqual(self.path.read_bytes(), b"owned")

    def test_same_byte_replacement_refuses_or_records_os_denial(self):
        foreign = self.root / "foreign.json"
        foreign.write_bytes(b"owned")
        foreign_identity = foreign.stat()
        denied = False
        fd = None
        try:
            with authority_io.hold_authority_read_fd(self.path, root=self.root) as fd:
                try:
                    foreign.replace(self.path)
                except PermissionError:
                    denied = True
        except LifecycleError as exc:
            self.assertFalse(denied)
            self.assertEqual(exc.code, "authority-input-changed")
        else:
            self.assertTrue(denied, "Successful foreign replacement must be refused")
        self.assertIsNotNone(fd)
        with self.assertRaises(OSError):
            os.fstat(fd)
        self.assertEqual(self.path.read_bytes(), b"owned")
        observed = foreign if denied else self.path
        self.assertTrue(os.path.samestat(foreign_identity, observed.stat()))

    def test_changed_file_metadata_refuses(self):
        facade = SimpleNamespace(**vars(os))
        held = None

        def changed(fd):
            info = os.fstat(fd)
            if fd != held:
                return info
            values = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
            values["st_mtime_ns"] += 1
            return SimpleNamespace(**values)

        facade.fstat = changed
        with (
            patch.object(authority_io, "os", facade),
            self.assertRaises(LifecycleError) as caught,
            authority_io.hold_authority_read_fd(self.path, root=self.root) as fd,
        ):
            held = fd
        self.assertEqual(caught.exception.code, "authority-input-changed")
        with self.assertRaises(OSError):
            os.fstat(held)

    def test_changed_parent_identity_refuses(self):
        original = Path.lstat
        active = False

        def changed(path):
            info = original(path)
            if active and path == self.root.parent:
                return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino + 1, st_mode=info.st_mode)
            return info

        with (
            patch.object(Path, "lstat", changed),
            self.assertRaises(LifecycleError) as caught,
            authority_io.hold_authority_read_fd(self.path, root=self.root) as fd,
        ):
            active = True
        self.assertEqual(caught.exception.code, "authority-input-changed")
        with self.assertRaises(OSError):
            os.fstat(fd)

    def test_initial_guard_or_caller_failure_closes_duplicate(self):
        original = authority_io.open_authority_read

        @contextmanager
        def failed_exit(*args, **kwargs):
            with original(*args, **kwargs) as stream:
                yield stream
            raise LifecycleError("authority-input-changed", "Injected initial exit failure")

        for fault in ("initial-exit", "runtime", "os-error"):
            with self.subTest(fault=fault):
                facade = SimpleNamespace(**vars(os))
                created = []

                def duplicate(fd, created=created):
                    created.append(os.dup(fd))
                    return created[-1]

                facade.dup = Mock(side_effect=duplicate)
                facade.close = Mock(side_effect=os.close)
                guard = failed_exit if fault == "initial-exit" else original
                expected = RuntimeError if fault == "runtime" else LifecycleError
                entered = False
                with (
                    patch.object(authority_io, "os", facade),
                    patch.object(authority_io, "open_authority_read", guard),
                    self.assertRaises(expected) as caught,
                    authority_io.hold_authority_read_fd(self.path, root=self.root),
                ):
                    entered = True
                    if fault == "runtime":
                        raise RuntimeError("Injected caller failure")
                    raise OSError("Injected caller I/O failure")
                self.assertEqual(entered, fault != "initial-exit")
                self.assertEqual(facade.dup.call_count, 1)
                duplicates = [call.args[0] for call in facade.close.call_args_list]
                closed = created[0]
                self.assertEqual(duplicates.count(closed), 1)
                with self.assertRaises(OSError):
                    os.fstat(closed)
                if fault != "runtime":
                    self.assertEqual(
                        caught.exception.code,
                        "authority-input-changed" if not entered else "authority-input-unavailable",
                    )

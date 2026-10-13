"""Lower-layer imports and preserved private legacy archive read guarantees."""

from pathlib import Path
from types import SimpleNamespace
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent_lifecycle.accounting import declared_ledger_legacy as legacy
from agent_lifecycle.contracts import LifecycleError


class DeclaredLedgerTests(unittest.TestCase):
    def test_accounting_reads_private_legacy_without_adapter_import(self):
        script = '''import builtins, os, tempfile
from pathlib import Path
original = builtins.__import__
def independent(name, *args, **kwargs):
    if name.startswith("agent_lifecycle.adapter_sessions"):
        raise AssertionError("accounting imported adapter: " + name)
    return original(name, *args, **kwargs)
builtins.__import__ = independent
from agent_lifecycle.accounting.declared_ledger import read_coordinator_cost_head
from agent_lifecycle.accounting.declared_ledger_legacy import _r11_review_private
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    folder = root / "private"
    folder.mkdir(mode=0o700)
    path = folder / "record.json"
    path.write_bytes(b'{"retained":true}')
    path.chmod(0o600)
    assert _r11_review_private(root, path) == b'{"retained":true}'
'''
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True,
                                timeout=15, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def private_file(self, root):
        folder = root / 'private'
        folder.mkdir(mode=0o700)
        path = folder / 'record.json'
        path.write_bytes(b'original')
        path.chmod(0o600)
        return path

    def test_unsafe_parent_mode_file_mode_symlink_and_size_refuse(self):
        for case in ('parent-mode', 'file-mode', 'symlink', 'size'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = self.private_file(root)
                if case == 'parent-mode':
                    path.parent.chmod(0o755)
                elif case == 'file-mode':
                    path.chmod(0o644)
                elif case == 'symlink':
                    target = path.with_suffix('.target')
                    path.rename(target)
                    path.symlink_to(target.name)
                else:
                    path.write_bytes(b'x' * 131073)
                with self.assertRaises(LifecycleError) as caught:
                    legacy._r11_review_private(root, path)
                self.assertEqual('codex-exact-private-path-unsafe', caught.exception.code)
                self.assertIn('private parent is not mode 0700' if case == 'parent-mode'
                              else 'private file has unsafe mode, type or size', str(caught.exception))

    def test_changed_descriptor_identity_before_and_during_read_refuses(self):
        real_fstat = os.fstat
        for case in ('before', 'during'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = self.private_file(root)
                calls = 0
                def observed(fd):
                    nonlocal calls
                    calls += 1
                    value = real_fstat(fd)
                    changed = case == 'before' or calls == 2
                    return SimpleNamespace(st_dev=value.st_dev, st_ino=value.st_ino,
                                           st_mode=value.st_mode, st_size=value.st_size,
                                           st_mtime_ns=value.st_mtime_ns + int(changed))
                with patch.object(legacy.os, 'fstat', side_effect=observed):
                    with self.assertRaises(LifecycleError) as caught:
                        legacy._r11_review_private(root, path)
                self.assertEqual('codex-exact-private-path-unsafe', caught.exception.code)
                self.assertIn('before reading' if case == 'before' else 'while reading',
                              str(caught.exception))

    def test_bootstrap_compatibility_exports_use_preserved_lower_functions(self):
        from agent_lifecycle.accounting import declared_ledger, declared_ledger_records
        from agent_lifecycle.adapter_sessions import bootstrap_r11
        self.assertIs(bootstrap_r11.read_coordinator_cost_head, declared_ledger.read_coordinator_cost_head)
        self.assertIs(bootstrap_r11.advance_coordinator_cost_head, declared_ledger.advance_coordinator_cost_head)
        self.assertIs(bootstrap_r11._r11_role_identity, declared_ledger_records._r11_role_identity)


class DeclaredLedgerContextTests(unittest.TestCase):
    def context(self):
        from tests.workflow.test_limited_usage import DeclaredFixture
        from agent_lifecycle.accounting.declared_ledger import resolve_declared_ledger_context
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        fixture = DeclaredFixture(Path(directory.name).resolve())
        context = resolve_declared_ledger_context(fixture.root, fixture.manifest,
                                                  fixture.policy['openingRef'])
        return fixture, context

    def test_registered_context_preserves_head_source_and_duplicate_advance(self):
        import hashlib
        from dataclasses import FrozenInstanceError
        from agent_lifecycle.accounting.declared_ledger import (
            read_declared_ledger, read_declared_source, advance_declared_ledger,
        )
        fixture, context = self.context()
        before = read_declared_ledger(context)
        value, raw = read_declared_source(context, before['head'])
        self.assertEqual(before['head']['sourceSha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(before['head']['unknownHolds'], value['unknownHoldsIncludingThisWindow'])
        with self.assertRaises(LifecycleError):
            advance_declared_ledger(context, before['head']['sourcePath'])
        unchanged = read_declared_ledger(context)
        self.assertEqual(before['headSha256'], unchanged['headSha256'])
        self.assertEqual(before['head']['unknownHolds'], unchanged['head']['unknownHolds'])
        with self.assertRaises(FrozenInstanceError):
            context.route_id = 'another-route'

    def test_unsupported_package_and_rebound_opening_refuse(self):
        from copy import deepcopy
        from agent_lifecycle.accounting.declared_ledger import resolve_declared_ledger_context
        fixture, _ = self.context()
        other = deepcopy(fixture.manifest)
        other['package']['id'] = 'unsupported-package'
        with self.assertRaises(LifecycleError) as caught:
            resolve_declared_ledger_context(fixture.root, other, fixture.policy['openingRef'])
        self.assertEqual('declared-ledger-route-unsupported', caught.exception.code)
        rebound = {**fixture.policy['openingRef'], 'sha256': '0' * 64}
        with self.assertRaises(LifecycleError) as caught:
            resolve_declared_ledger_context(fixture.root, fixture.manifest, rebound)
        self.assertEqual('declared-ledger-opening-mismatch', caught.exception.code)

    def test_unverified_context_and_changed_seed_refuse(self):
        from agent_lifecycle.accounting.declared_ledger import (
            read_declared_ledger, resolve_declared_ledger_context, _R11_COORDINATOR_SEED,
        )
        fixture, context = self.context()
        with self.assertRaises(LifecycleError) as caught:
            read_declared_ledger(object())
        self.assertEqual('declared-ledger-context-required', caught.exception.code)
        seed = fixture.root / _R11_COORDINATOR_SEED
        seed.write_bytes(seed.read_bytes().rstrip() + b' ')
        with self.assertRaises(LifecycleError) as caught:
            resolve_declared_ledger_context(fixture.root, fixture.manifest, fixture.policy['openingRef'])
        self.assertEqual('r11-opening-origin', caught.exception.code)

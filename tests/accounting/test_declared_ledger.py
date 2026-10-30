"""Lower-layer imports and preserved private legacy archive read guarantees."""

from pathlib import Path
from types import SimpleNamespace
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from agent_lifecycle.accounting import declared_ledger_legacy as legacy
from agent_lifecycle.contracts import LifecycleError
from tests.contracts.test_private_storage import unsafe_private_access


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
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                path = self.private_file(root)
                if case in ('parent-mode', 'file-mode'):
                    stack.enter_context(unsafe_private_access(path.parent if case == 'parent-mode' else path))
                elif case == 'symlink':
                    target = path.with_suffix('.target')
                    path.rename(target)
                    path.symlink_to(target.name)
                else:
                    path.write_bytes(b'x' * 131073)
                with self.assertRaises(LifecycleError) as caught:
                    legacy._r11_review_private(root, path)
                self.assertEqual('codex-exact-private-path-unsafe', caught.exception.code)
                if os.name == 'nt':
                    self.assertIn(caught.exception.code, ('codex-exact-private-path-unsafe',))
                    self.assertTrue(caught.exception.message)
                else:
                    self.assertIn('private parent is not mode 0700' if case == 'parent-mode'
                                  else 'private file has unsafe mode, type or size', str(caught.exception))
                stack.close()

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
                    changed = case == 'before' or (calls >= 2 if os.name == 'nt' else calls == 2)
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


class CoordinatorDurabilityTests(unittest.TestCase):
    """Real local Git roots, files, cumulative UNKNOWN holds and crash phases."""

    def fixture(self):
        import json
        from agent_lifecycle.accounting import declared_ledger as ledger
        from agent_lifecycle.contracts import canonical_bytes
        from agent_lifecycle.contracts.private_storage import create_private_bytes
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True, timeout=15)
        raw = (Path(__file__).resolve().parents[2] / 'fixtures/accounting/r11-coordinator-seed-cost.json').read_bytes()
        create_private_bytes(root / ledger._R11_COORDINATOR_SEED, raw, root=root)
        seed = json.loads(raw)
        relative = ledger._R11_COORDINATOR_BASE + '/r500-windows-io/admission.json'
        value = {**seed, 'status': 'ADMITTED_PREAPPROVED_BY_USER', 'tokenCap': 10000, 'protectedCloseoutTokens': 2000,
                 'priorUnknownHolds': seed['unknownHoldsIncludingThisWindow'],
                 'unknownHoldsIncludingThisWindow': seed['unknownHoldsIncludingThisWindow'] + 10000,
                 'priorLedgerLowerBound': seed['ledgerLowerBoundIncludingThisHold'],
                 'ledgerLowerBoundIncludingThisHold': seed['ledgerLowerBoundIncludingThisHold'] + 10000}
        create_private_bytes(root / relative, canonical_bytes(value), root=root)
        return root, ledger, relative, value

    def test_real_coordinator_creation_reopen_and_full_hold_close(self):
        from agent_lifecycle.contracts import canonical_bytes
        from agent_lifecycle.contracts.private_storage import create_private_bytes
        root, ledger, relative, value = self.fixture()
        initial = ledger.advance_coordinator_cost_head(root, source_path=ledger._R11_COORDINATOR_SEED)
        opened = ledger.advance_coordinator_cost_head(root, source_path=relative)
        self.assertEqual(opened['head']['unknownHolds'], initial['head']['unknownHolds'] + 10000)
        self.assertEqual(ledger.read_coordinator_cost_head(root)['headSha256'], opened['headSha256'])
        closed_path = relative.replace('/admission.json', '/cost.json')
        create_private_bytes(root / closed_path, canonical_bytes({**value, 'status': 'UNAVAILABLE_FULL_HOLD_RETAINED'}), root=root)
        closed = ledger.advance_coordinator_cost_head(root, source_path=closed_path)
        self.assertEqual(closed['head']['unknownHolds'], opened['head']['unknownHolds'])
        self.assertEqual(closed['head']['exposureLowerBound'], opened['head']['exposureLowerBound'])
        history = ledger.read_coordinator_cost_head(root, ancestor_head_sha256=initial['headSha256'])
        self.assertIn(initial['headSha256'], history['ancestryHeadSha256s'])
        with self.assertRaises(LifecycleError):
            ledger.advance_coordinator_cost_head(root, source_path=relative)
        self.assertEqual(ledger.read_coordinator_cost_head(root)['headSha256'], closed['headSha256'])

    def test_directory_preflight_failure_does_not_create_pending_claim(self):
        root, ledger, _relative, _value = self.fixture()
        with patch.object(ledger, '_sync_directory', side_effect=LifecycleError('injected-sync-failure', 'test barrier')) as sync:
            with self.assertRaises(LifecycleError):
                ledger.advance_coordinator_cost_head(root, source_path=ledger._R11_COORDINATOR_SEED)
        self.assertEqual(sync.call_count, 1)
        path = root / ledger._R11_COORDINATOR_HEAD
        self.assertFalse(path.exists())
        self.assertFalse(path.with_suffix('.pending.json').exists())
        self.assertFalse(path.with_suffix('.next.json').exists())

    def test_crash_phases_retain_claim_history_and_every_unknown_hold(self):
        import json
        for fail_at in (2, 3, 4, 5, 6):
            with self.subTest(failedDurabilityBarrier=fail_at):
                root, ledger, relative, value = self.fixture()
                seed = ledger.advance_coordinator_cost_head(root, source_path=ledger._R11_COORDINATOR_SEED)
                original = ledger._sync_directory
                count = 0
                def fail(path):
                    nonlocal count
                    count += 1
                    if count == fail_at:
                        raise OSError('injected postwrite durability fault')
                    original(path)
                with patch.object(ledger, '_sync_directory', side_effect=fail):
                    with self.assertRaises(OSError):
                        ledger.advance_coordinator_cost_head(root, source_path=relative)
                path = root / ledger._R11_COORDINATOR_HEAD
                self.assertEqual(count, fail_at)
                observed = json.loads(path.read_bytes())
                self.assertEqual(observed['unknownHolds'], seed['head']['unknownHolds'] if fail_at < 5 else value['unknownHoldsIncludingThisWindow'])
                self.assertEqual(path.with_suffix('.pending.json').exists(), fail_at < 6)
                if fail_at < 6:
                    with self.assertRaises(LifecycleError) as caught:
                        ledger.read_coordinator_cost_head(root)
                    self.assertEqual(caught.exception.code, 'r11-opening-pending')
                    with self.assertRaises((LifecycleError, FileExistsError)):
                        ledger.advance_coordinator_cost_head(root, source_path=relative)
                    self.assertTrue(path.with_suffix('.pending.json').exists())
                else:
                    self.assertEqual(ledger.read_coordinator_cost_head(root)['head']['unknownHolds'], value['unknownHoldsIncludingThisWindow'])

    def test_concurrent_coordinator_claim_has_one_winner_and_no_double_charge(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        root, ledger, relative, value = self.fixture()
        ledger.advance_coordinator_cost_head(root, source_path=ledger._R11_COORDINATOR_SEED)
        gate = threading.Barrier(2, timeout=15)
        local = threading.local()
        original = ledger._r11_coordinator_transition
        def synchronized(*args, **kwargs):
            original(*args, **kwargs)
            if args[2] == relative and not getattr(local, 'entered', False):
                local.entered = True
                gate.wait()
        def advance(_):
            try:
                return ledger.advance_coordinator_cost_head(root, source_path=relative)
            except (OSError, LifecycleError) as exc:
                return exc
        with patch.object(ledger, '_r11_coordinator_transition', side_effect=synchronized), ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(advance, range(2)))
        self.assertEqual(sum(isinstance(v, dict) for v in outcomes), 1, outcomes)
        self.assertEqual(sum(isinstance(v, Exception) for v in outcomes), 1, outcomes)
        self.assertEqual(ledger.read_coordinator_cost_head(root)['head']['unknownHolds'], value['unknownHoldsIncludingThisWindow'])


class GitLaunchContractTests(unittest.TestCase):
    def test_git_launch_mode_preserves_captured_bytes(self):
        root = Path("unused-mocked-root")
        for platform in ("win32", "linux"):
            with self.subTest(platform=platform):
                completed = SimpleNamespace(returncode=0, stdout=b"checked\n", stderr=b"")
                with (
                    patch.object(legacy, "sys", SimpleNamespace(platform=platform)),
                    patch.object(legacy.subprocess, "CREATE_NO_WINDOW", 134217728, create=True),
                    patch.object(legacy.subprocess, "run", return_value=completed) as call,
                ):
                    self.assertEqual(b"checked\n", legacy._r11_git(root, "rev-parse"))
                self.assertEqual((["git", "rev-parse"],), call.call_args.args)
                kwargs = call.call_args.kwargs
                self.assertEqual(root, kwargs["cwd"])
                self.assertTrue(kwargs["capture_output"])
                self.assertFalse(kwargs["check"])
                self.assertEqual(15, kwargs["timeout"])
                self.assertTrue(
                    kwargs["env"] == {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}, "Git child environment differs"
                )
                self.assertEqual(134217728 if platform == "win32" else 0, kwargs.get("creationflags", 0))

    def test_git_errors_and_output_bounds_remain_source_unavailable(self):
        cases = (
            OSError("missing Git"),
            subprocess.TimeoutExpired(["git"], 15),
            SimpleNamespace(returncode=1, stdout=b"", stderr=b"failure"),
            SimpleNamespace(returncode=0, stdout=b"x" * 8388609, stderr=b""),
            SimpleNamespace(returncode=0, stdout=b"", stderr=b"x" * 65537),
        )
        for number, value in enumerate(cases):
            with self.subTest(case=number):
                behavior = {"side_effect": value} if isinstance(value, Exception) else {"return_value": value}
                with patch.object(legacy.subprocess, "run", **behavior), self.assertRaises(LifecycleError) as caught:
                    legacy._r11_git(Path("unused-mocked-root"), "rev-parse")
                self.assertEqual("r11-source-unavailable", caught.exception.code)

    def test_actual_git_captured_output_remains_available(self):
        with tempfile.TemporaryDirectory() as directory:
            value = legacy._r11_git(Path(directory), "--version")
        self.assertTrue(value.startswith(b"git version "))

    def test_timeout_still_terminates_and_waits_for_own_child(self):
        real_run, real_popen = (subprocess.run, subprocess.Popen)
        children = []

        def launch(argv, **kwargs):
            self.assertEqual(["git", "--version"], argv)
            child = real_popen([sys.executable, "-c", "import time; time.sleep(5)"], **kwargs)
            children.append(child)
            return child

        def bounded(argv, **kwargs):
            self.assertEqual(15, kwargs["timeout"])
            return real_run(argv, **{**kwargs, "timeout": 0.1})

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(legacy.subprocess, "Popen", side_effect=launch),
            patch.object(legacy.subprocess, "run", side_effect=bounded),
            self.assertRaises(LifecycleError) as caught,
        ):
            legacy._r11_git(Path(directory), "--version")
        self.assertEqual("r11-source-unavailable", caught.exception.code)
        self.assertEqual(1, len(children))
        self.assertIsNotNone(children[0].poll())

    def test_primary_checkout_still_requires_two_matching_git_observations(self):
        for changed in (False, True):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                common = root / ".git"
                common.mkdir()
                raw = (str(common) + "\n").encode("utf-8")
                second = b"different-primary\n" if changed else raw
                with patch.object(legacy, "_r11_git", side_effect=[raw, second]) as call:
                    if changed:
                        with self.assertRaises(LifecycleError) as caught:
                            legacy._r11_coordinator_root(root)
                        self.assertEqual("r11-opening-origin", caught.exception.code)
                    else:
                        self.assertEqual(root, legacy._r11_coordinator_root(root))
                self.assertEqual(2, call.call_count)
                self.assertEqual(root, call.call_args_list[0].args[0])
                self.assertEqual(root, call.call_args_list[1].args[0])

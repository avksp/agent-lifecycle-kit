"""Opt-in real macOS scheduler/CLI probe; isolated history, no model calls."""
from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from agent_lifecycle.accounting.contracts import RunClosure, canonical, digest
from agent_lifecycle.accounting.journal import Journal
from tests.accounting.test_journal import PROOF, operation
from tests.accounting.test_normalization import observation
from tests.accounting.test_opening_balances import import_data, paid

ROOT = Path(__file__).resolve().parents[2]
ADMISSION = os.environ.get('ALK_RETENTION_TARGET_ADMISSION')


@unittest.skipUnless(ADMISSION, 'Real installed target requires finite release admission')
class RetentionMaintenanceTargetTests(unittest.TestCase):
    def test_installed_hourly_target_and_real_maintenance(self):
        self.assertEqual(platform.system(), 'Darwin', 'Other targets require their own real qualification')
        admission_path = Path(ADMISSION).resolve(strict=True)
        a = json.loads(admission_path.read_bytes())
        self.assertEqual(a['schemaVersion'], 'alk-retention-target-admission.v1')
        self.assertEqual(a['maxTargetMaintenanceInvocations'], 4)
        self.assertEqual(a['maxSchedulerReadbacks'], 2)
        self.assertLess(datetime.now(UTC), datetime.fromisoformat(a['absoluteDeadlineUtc']))
        state = json.loads((ROOT / a['statePath']).read_bytes())
        task = next(t for t in state['tasks'] if t['id'] == 'WS216-03')
        self.assertEqual((state['runId'], task['status'], task['attempt']), (a['runId'], 'RUNNING', 1))
        manifest = (ROOT / state['manifestPath']).read_bytes()
        self.assertEqual(digest(json.loads(manifest)), state['planDigest'])
        self.assertEqual(state['planDigest'], a['planDigest'])
        root = Path(a['probeRoot'])
        self.assertTrue(root.is_absolute())
        self.assertEqual(root.resolve(), root)
        root.mkdir(mode=0o700)
        self.root = root
        self.stop = min(time.monotonic() + 180, time.monotonic() +
                        (datetime.fromisoformat(a['absoluteDeadlineUtc']) - datetime.now(UTC)).total_seconds())
        self.commands = []
        self.invocations = []
        self.readbacks = []
        self.sources = {}
        try:
            with Journal(root / 'journal.db', PROOF) as journal:
                self.j = journal
                (root / 'journal.db').chmod(0o600)
                manifest_ref = self.write('plan/manifest.json', manifest)
                lock_ref = self.write('plan/lock.json', (ROOT / 'tasks/release-2-16/plan.lock.json').read_bytes())
                authority = dict(schemaVersion='alk-r68b-maintenance-authority.v1',
                    rootPathSha256=hashlib.sha256(os.fsencode(str(root))).hexdigest(),
                    rootFileIdentity=self.file_id(root), journalPath='journal.db',
                    journalFileIdentity=self.file_id(root / 'journal.db'), journalIdentity=journal.journal_identity,
                    storageVersion=journal._storage_version, writerDigest=digest(asdict(PROOF)),
                    planDigest=state['planDigest'], manifestRef=manifest_ref, lockRef=lock_ref, allowedAction='RAW_RETENTION')
                self.authority_ref = self.write('maintenance-authority.json', canonical(authority).encode())
                self.write('maintenance-authority.json.writer.json', canonical(asdict(PROOF)).encode())
                self.seed('target-not-due', 0)
                guide = (ROOT / 'docs/operations/retention-maintenance.md').read_text()
                wrapper = guide.split('```python alk-maintenance-wrapper\n', 1)[1].split('\n```', 1)[0]
                wrapper = wrapper.replace('/absolute/private/root/maintenance-authority.json', str(root / self.authority_ref['path']))
                wrapper = wrapper.replace('<exact-64-hex-sha256>', self.authority_ref['sha256'])
                self.write('maintain.py', wrapper.encode())
                label = a['schedulerLabel']
                service = f'gui/{os.getuid()}/{label}'
                stdout = root / 'stdout.jsonl'
                stderr = root / 'stderr.txt'
                self.write(stdout.name, b'')
                self.write(stderr.name, b'')
                config = dict(Label=label, ProgramArguments=[sys.executable, '-B', str(root / 'maintain.py')],
                    StartInterval=3600, RunAtLoad=False, WorkingDirectory=str(ROOT),
                    EnvironmentVariables=dict(PYTHONPATH=str(ROOT / 'src'), PYTHONDONTWRITEBYTECODE='1'),
                    StandardOutPath=str(stdout), StandardErrorPath=str(stderr))
                config_raw = plistlib.dumps(config, sort_keys=True)
                agents = Path.home() / 'Library/LaunchAgents'
                agents.mkdir(parents=True, exist_ok=True)
                target = agents / f'{label}.plist'
                with target.open('xb') as f:
                    f.write(config_raw)
                target.chmod(0o600)
                self.call(['/bin/launchctl', 'bootstrap', f'gui/{os.getuid()}', str(target)])
                first_readback = self.call(['/bin/launchctl', 'print', service])
                self.readbacks.append(first_readback)
                self.assertIn(str(root / 'maintain.py'), first_readback['stdout'])
                self.assertIn('3600', first_readback['stdout'])
                first = self.invoke(service, stdout)
                self.assertEqual(self.row(first, 'target-not-due')['status'], 'NOT_DUE')
                self.assertTrue(all(p.exists() for p in self.sources['target-not-due']))
                due_closure = self.seed('target-due', 31)
                due = self.invoke(service, stdout)
                self.assertEqual(self.row(due, 'target-due')['status'], 'DONE')
                self.assertTrue(all(not p.exists() for p in self.sources['target-due']))
                self.assertEqual(journal.closed_run('target-due'), due_closure)
                self.assertEqual(journal.snapshot('target-due').known_spent, 10)
                self.assertEqual(journal.ingest_usage('target-due', self.observations['target-due']).status, 'ALREADY_SETTLED')
                overdue_closure = self.seed('target-overdue', 32)
                refused_file = self.sources['target-overdue'][0]
                refused_file.chmod(0o644)
                refused = self.invoke(service, stdout)
                self.assertEqual(refused['status'], 'PARTIAL')
                self.assertEqual(self.row(refused, 'target-overdue')['after'], ['OVERDUE'])
                self.assertTrue(refused_file.exists())
                refused_file.chmod(0o600)
                recovered = self.invoke(service, stdout)
                self.assertEqual(self.row(recovered, 'target-overdue')['status'], 'DONE')
                self.assertTrue(all(not p.exists() for p in self.sources['target-overdue']))
                self.assertEqual(journal.closed_run('target-overdue'), overdue_closure)
                self.assertEqual(journal.snapshot('target-overdue').known_spent, 10)
                final_readback = self.call(['/bin/launchctl', 'print', service])
                self.readbacks.append(final_readback)
                self.assertEqual(target.read_bytes(), config_raw)
                self.assertTrue(all(p.exists() for p in self.sources['target-not-due']))
                for run in ('target-due', 'target-overdue'):
                    self.assertTrue(all(r['status'] == 'DONE' for r in journal.raw_obligations(run, datetime.now(UTC).isoformat())))
                receipt = dict(schemaVersion='alk-retention-target-probe.v1', status='PASS_TARGET_OBSERVATIONS_ONLY',
                    runId=state['runId'], taskId='WS216-03', planDigest=state['planDigest'],
                    admissionSha256=hashlib.sha256(admission_path.read_bytes()).hexdigest(),
                    target=dict(os=platform.platform(), scheduler='launchd', label=label, intervalSeconds=3600,
                        configurationPath=str(target), configurationSha256=hashlib.sha256(config_raw).hexdigest(),
                        command=config['ProgramArguments'], commandSha256=digest(config['ProgramArguments']),
                        pythonExecutableSha256=hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest()),
                    authority=self.authority_ref, journalIdentity=journal.journal_identity,
                    privateRootFileIdentity=self.file_id(root), journalFileIdentity=self.file_id(root / 'journal.db'),
                    privateRootPathSha256=authority['rootPathSha256'], commands=self.commands,
                    schedulerReadbacks=self.readbacks, invocations=self.invocations,
                    cases=[dict(caseId=c, status='PASS') for c in [
                        'retention.schedule.hourly-target-install', 'retention.schedule.target-nodue-due-overdue',
                        'retention.schedule.platform-equivalence-or-refusal']],
                    supportedTargetActualDeletion=True, everyDueObligationDone=True,
                    totalsAndDedupPreserved=True, currentNotDueRawPreserved=True,
                    historicalFixturePreparation='Only fixture API event seeding uses historical timestamps; all scheduled CLI processes use unpatched real current UTC',
                    financialFixtureOnly=True, hostFinancialQualificationClaimed=False,
                    combinedRB11=dict(status='PENDING_INDEPENDENT_FINAL_AUDIT',
                                      reason='Exact PRE and eleven runtime joins plus independent final assessment still required'),
                    retentionReadinessClaimed=False, newModelCalls=0, actualWholeHostTokens=None)
                out = ROOT / a['receiptPath']
                out.parent.mkdir(parents=True, exist_ok=True)
                with out.open('xb') as f:
                    f.write(canonical(receipt).encode() + b'\n')
        except BaseException as exc:
            self.write('ACTUAL-PROBE-FAILURE.json', canonical(dict(type=type(exc).__name__, message=str(exc),
                commands=self.commands, invocations=self.invocations, schedulerReadbacks=self.readbacks,
                originalDeadlineUtc=a['absoluteDeadlineUtc'], retryAuthorized=False)).encode())
            raise

    def file_id(self, path):
        info = path.lstat()
        return dict(device=info.st_dev, inode=info.st_ino)

    def write(self, name, raw):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with p.open('xb') as f:
            f.write(raw)
        p.chmod(0o600)
        return dict(path=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())

    def seed(self, run, age):
        now = datetime.now(UTC)
        # Explicit historical fixture authority only, never a patched scheduler,
        # maintenance CLI, deletion clock or target process.
        with patch('agent_lifecycle.accounting.journal.datetime', wraps=datetime) as history:
            history.now.return_value = now - timedelta(days=age + 2)
            self.assertEqual(self.j.import_opening(*import_data(scope=run)).status, 'IMPORTED')
            op = paid(self.j, operation(scope=run, name=run))
            obs = observation([op], [10], event=run)
            self.assertEqual(self.j.ingest_usage(run, obs).status, 'SETTLED')
        if not hasattr(self, 'observations'):
            self.observations = {}
        self.observations[run] = obs
        entries = []
        paths = []
        for name, kind in [('request.json', 'sealed-request'), ('diagnostic.json', 'diagnostic'),
                           ('effective-config.json', 'effective-config')]:
            ref = self.write(f'{run}/{name}', canonical(dict(fixture=run, kind=kind)).encode())
            p = self.root / ref['path']
            paths.append(p)
            entries.append(dict(**ref, kind=kind, fileIdentity=self.file_id(p),
                                pathSha256=hashlib.sha256(os.fsencode(str(p))).hexdigest()))
        authority = json.loads((self.root / self.authority_ref['path']).read_bytes())
        inventory = dict(schemaVersion='alk-r68b-raw-inventory.v1', runId=run, taskId='task', attemptId=run,
            planDigest=authority['planDigest'], journalAuthorityKind='SQLITE_ACCOUNTING_JOURNAL',
            journalIdentity=self.j.journal_identity, eventLog='journal.db', eventLogFileIdentity=authority['journalFileIdentity'],
            rootPathSha256=authority['rootPathSha256'], rootFileIdentity=authority['rootFileIdentity'],
            workflowStateDigest=digest(dict(localFixture=True)), sources=entries)
        ref = self.write(f'{run}/raw-inventory.json', canonical(inventory).encode())
        self.assertEqual(self.j.register_raw_inventory(run, ref, private_root=self.root,
                         authority_ref=self.authority_ref)['status'], 'PENDING')
        self.sources[run] = paths + [self.root / ref['path']]
        closure = RunClosure('closure:' + run, run, 'reportedTokens:fixture:v1',
            (now - timedelta(days=age)).isoformat(), ((run, self.j.snapshot(run).journal_revision),), PROOF, PROOF)
        self.assertEqual(self.j.close_run(closure, datetime.now(UTC).isoformat()).status, 'CLOSED')
        return self.j.closed_run(run)

    def call(self, argv):
        self.assertLess(time.monotonic(), self.stop)
        result = subprocess.run(argv, capture_output=True, timeout=min(20, self.stop - time.monotonic()), check=False)
        row = dict(argv=argv, exitCode=result.returncode, stdout=result.stdout.decode(), stderr=result.stderr.decode())
        self.commands.append(row)
        self.assertEqual(result.returncode, 0, row)
        return row

    def invoke(self, service, stdout):
        self.assertLess(len(self.invocations), 4)
        offset = stdout.stat().st_size
        launch = self.call(['/bin/launchctl', 'kickstart', '-p', service])
        pid = int(launch['stdout'].strip())
        until = min(self.stop, time.monotonic() + 20)
        while time.monotonic() < until:
            raw = stdout.read_bytes()[offset:]
            self.assertLessEqual(len(raw), 65536)
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeError):
                time.sleep(0.05)
                continue
            self.assertEqual(value['authoritySha256'], self.authority_ref['sha256'])
            self.assertEqual(value['journalIdentity'], self.j.journal_identity)
            while time.monotonic() < until:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                self.fail('Completed receipt process did not terminate within the original bound')
            self.invocations.append(dict(ordinal=len(self.invocations) + 1, actualReceipt=value,
                stdoutSha256=hashlib.sha256(raw).hexdigest(), stdoutBytes=len(raw)))
            self.write(f'invocation-{len(self.invocations)}.stdout.json', raw)
            return value
        self.fail('Installed target produced no complete bounded receipt; no automatic retry')

    def row(self, result, run):
        key = hashlib.sha256(run.encode()).hexdigest()
        return next(r for r in result['outcomes'] if r['runIdSha256'] == key)

"""Run two qualified, isolated full-suite groups; refuse incomplete evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import time
import traceback
import unittest
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

import run_unittest as serial

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from agent_lifecycle.changesets.git_io import BoundedProcess, run_bounded_command

HOT_MODULE = 'tests.workflow.test_limited_usage'
MAX_BYTES = 8388608


def partition(suite, discovered):
    """Remove only one complete module subtree, preserving every original child."""
    if type(suite) is not unittest.TestSuite:
        return None
    groups = [list(serial.inventory(child)) if isinstance(child, unittest.TestSuite)
              else [dict(id=child.id(), module=type(child).__module__,
                         **{'class': type(child).__qualname__})] for child in suite]
    hot = [i for i, group in enumerate(groups) if any(x['module'] == HOT_MODULE for x in group)]
    if len(hot) != 1 or not groups[hot[0]] or any(x['module'] != HOT_MODULE for x in groups[hot[0]]):
        return None
    index = hot[0]
    if not isinstance(list(suite)[index], unittest.TestSuite):
        return None
    before = [item for group in groups[:index] for item in group]
    after = [item for group in groups[index + 1:] for item in group]
    if not before and not after:
        return None
    if before and after and before[-1]['module'] == after[0]['module']:
        return None
    if [item for group in groups for item in group] != discovered:
        return None
    return [[index], [i for i in range(len(groups)) if i != index]]


def write_report(stream, value):
    stream.seek(0)
    json.dump(value, stream, indent=2, allow_nan=False)
    stream.write('\n')
    stream.truncate()
    stream.flush()


def write_new(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.write('\n')


def command(argv, root, deadline):
    result = run_bounded_command(argv, cwd=root,
                                 timeout_seconds=min(120, deadline - time.monotonic()),
                                 max_stdout_bytes=MAX_BYTES, max_stderr_bytes=MAX_BYTES)
    if result.returncode:
        raise RuntimeError(f'{argv[0]} failed: {result.stderr.decode(errors="replace")}')
    return result.stdout


def restore_fixture(root):
    target = root / 'tasks/release-2-16'
    with zipfile.ZipFile(root / 'fixtures/release-2-16-tests.zip') as archive:
        members = archive.infolist()
        if len(members) > 10000 or sum(x.file_size for x in members) > 67108864:
            raise ValueError('Fixture archive exceeds bounds')
        for entry in members:
            path = PurePosixPath(entry.filename)
            if (path.is_absolute() or '..' in path.parts or '\\' in entry.filename
                    or ':' in entry.filename or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('Unsafe fixture archive member')
        archive.extractall(target)


def clone_source(source, root, head, deadline):
    command(['git', 'clone', '--quiet', '--no-hardlinks', '--no-checkout', str(source), str(root)],
            source, deadline)
    command(['git', '-C', str(root), 'checkout', '--quiet', '--detach', head], source, deadline)
    actual = command(['git', 'rev-parse', 'HEAD'], root, deadline).decode().strip()
    if actual != head:
        raise ValueError('Clone HEAD differs')
    restore_fixture(root)


def drain(process, folder):
    chunks = []
    value = {'exitCode': None, 'transportError': None}
    try:
        while data := process.stdout.read(65536):
            chunks.append(data)
        value['exitCode'] = process.wait()
    except Exception as exc:  # noqa: BLE001 - preserve failure logs; coordinator still waits both workers
        value['transportError'] = f'{type(exc).__name__}: {exc}'
    finally:
        stdout = b''.join(chunks)
        stderr = bytes(process.stderr)
        for name, raw in [('stdout.log', stdout), ('stderr.log', stderr)]:
            with (folder / name).open('xb') as stream:
                stream.write(raw)
        value.update(stdoutBytes=len(stdout), stderrBytes=len(stderr))
    return value


def run_workers(jobs, deadline):
    """Parent owns cleanup; threads only drain bounded pipes and wait."""
    processes = []
    futures = []
    cleanup_errors = []
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        for argv, root, folder in jobs:
            process = BoundedProcess(argv, cwd=root, deadline=deadline,
                                     max_stdout_bytes=MAX_BYTES, max_stderr_bytes=MAX_BYTES)
            processes.append(process)
            futures.append(pool.submit(drain, process, folder))
        # Transport deadlines stop tests; allow bounded reader/log cleanup to report that failure.
        return [future.result(timeout=max(0.001, deadline - time.monotonic()) + 10) for future in futures]
    finally:
        for process in processes:
            # Release blocked readers before closing owned process trees on interruption.
            process.fail('ci-worker-supervision-finished')
        for process in processes:
            try:
                process.close()
            except Exception as exc:  # noqa: BLE001 - cleanup failure must prevent success
                cleanup_errors.append(f'{type(exc).__name__}: {exc}')
        pool.shutdown(wait=True, cancel_futures=True)
        if cleanup_errors:
            raise RuntimeError('Worker cleanup failed: ' + '; '.join(cleanup_errors))


def validate_worker(path, roster, outcome, head):
    if path.is_symlink() or path.stat().st_size > MAX_BYTES:
        raise ValueError('Unsafe or oversized worker report')
    raw = path.read_bytes()
    value = json.loads(raw)
    if (outcome['exitCode'] != 0 or outcome['transportError'] is not None
            or value['schemaVersion'] != 'alk-ci-test-timings.v1' or value['status'] != 'PASS'
            or value['sourceHead'] != head or value['inventory'] != roster['selectedInventory']
            or not value['coverage']['complete'] or value['loaderErrors'] or value['interrupted']
            or value['errors'] or value['failures'] or value['unexpectedSuccesses']):
        raise ValueError('Worker failed or its source/inventory differs')
    for key in ('GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB', 'RUNNER_OS'):
        if value['environment'][key] != os.environ.get(key):
            raise ValueError('Worker Actions identity differs')
    expected = Counter(item['id'] for item in roster['selectedInventory'])
    observed = Counter(item['id'] for item in value['cases'])
    for item in value['coverage']['notStarted']:
        if item['reason'] != 'fixtureSkip':
            raise ValueError('Unexplained unstarted test')
        observed[item['id']] += 1
    if observed != expected or value['testsRun'] != len(value['cases']):
        raise ValueError('Worker coverage differs')
    if not all(x['completed'] and math.isfinite(x['seconds']) and x['seconds'] >= 0
               for x in value['cases']):
        raise ValueError('Worker timing is incomplete')
    return value, dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))


def execute(args, report):
    started = time.perf_counter()
    deadline = time.monotonic() + args.timeout_seconds
    payload = dict(schemaVersion='alk-ci-test-timings.parallel.v1', status='RUNNING',
                   mode='parallel', workers=[], python=serial.platform.python_version(),
                   platform=serial.platform.platform(), logicalCPUs=os.cpu_count(),
                   environment={key: os.environ.get(key) for key in (
                       'GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'RUNNER_OS',
                       'RUNNER_ARCH', 'ImageOS', 'ImageVersion')})
    write_report(report, payload)
    try:
        source = Path.cwd().resolve()
        dirty = command(['git', 'status', '--porcelain', '--untracked-files=all'], source, deadline)
        if dirty:
            raise ValueError('Parallel execution requires a clean committed source tree')
        head = command(['git', 'rev-parse', 'HEAD'], source, deadline).decode().strip()
        payload['sourceHead'] = head
        loader = unittest.TestLoader()
        suite = loader.discover(args.start, pattern=args.pattern, top_level_dir=args.top)
        discovered = list(serial.inventory(suite))
        groups = None if loader.errors else partition(suite, discovered)
        if groups is None:
            report.seek(0)
            report.truncate()
            result = serial.run(args, report, prepared=(loader, suite, started))
            report.seek(0)
            fallback = json.load(report)
            fallback.update(mode='serial', parallelQualification='Conservative partition unavailable before worker launch')
            write_report(report, fallback)
            return result
        payload['inventory'] = discovered
        folder = Path(args.out).resolve().with_suffix('')
        folder.mkdir()
        children = list(suite)
        if sorted(index for group in groups for index in group) != list(range(len(children))):
            raise ValueError('Partition does not cover each original subtree exactly once')
        with tempfile.TemporaryDirectory(prefix='alk-ci-') as temporary:
            jobs, rosters, folders = [], [], []
            for number, indices in enumerate(groups):
                clone = (Path(temporary) / str(number)).resolve()
                clone_source(source, clone, head, deadline)
                scratch = (Path(temporary) / f'tmp{number}').resolve()
                scratch.mkdir()
                destination = folder / str(number)
                destination.mkdir()
                roster = dict(schemaVersion='alk-ci-worker-roster.v1', sourceHead=head,
                              fullInventory=discovered, indices=indices,
                              selectedInventory=[item for i in indices
                                                 for item in serial.inventory(children[i])])
                roster_path = destination / 'roster.json'
                write_new(roster_path, roster)
                options = dict(root=str(clone), scratch=str(scratch),
                               runner=str(clone / 'tools/ci/run_unittest.py'),
                               args=['--start', args.start, '--top', args.top, '--pattern', args.pattern,
                                     '--worker-roster', str(roster_path),
                                     '--out', str(destination / 'test-timings.json')])
                # No shell/env mutation in the parent or shared user-home changes.
                bootstrap = (
                    'import json,os,runpy,sys; v=json.loads(sys.argv[1]); '
                    'os.chdir(v["root"]); '
                    'os.environ.update(PYTHONPATH=os.path.join(v["root"],"src"),'
                    'GITHUB_WORKSPACE=v["root"],PYTHONDONTWRITEBYTECODE="1",'
                    'TMPDIR=v["scratch"],TEMP=v["scratch"],TMP=v["scratch"]); '
                    'sys.path[:0]=[v["root"],os.path.join(v["root"],"src")]; '
                    'sys.argv=[v["runner"],*v["args"]]; runpy.run_path(v["runner"],run_name="__main__")'
                )
                jobs.append(([sys.executable, '-B', '-c', bootstrap, json.dumps(options)], clone, destination))
                rosters.append(roster)
                folders.append(destination)
            payload['setupSeconds'] = time.perf_counter() - started
            wait_start = time.perf_counter()
            outcomes = run_workers(jobs, deadline)
            payload['workerWindowSeconds'] = time.perf_counter() - wait_start
            payload['outcomes'] = outcomes
            payload['workerFolders'] = [str(path.relative_to(folder.parent)) for path in folders]
            for destination in folders:
                sys.stdout.buffer.write((destination / 'stdout.log').read_bytes())
                sys.stderr.buffer.write((destination / 'stderr.log').read_bytes())
            sys.stdout.flush()
            sys.stderr.flush()
            covered = Counter()
            totals = Counter()
            for destination, roster, outcome in zip(folders, rosters, outcomes, strict=True):
                value, reference = validate_worker(destination / 'test-timings.json', roster, outcome, head)
                reference['path'] = str((destination / 'test-timings.json').relative_to(folder.parent))
                covered.update(item['id'] for item in value['inventory'])
                for key in ('testsRun', 'skips', 'expectedFailures', 'failures', 'errors', 'unexpectedSuccesses'):
                    totals[key] += value[key]
                payload['workers'].append(dict(report=reference, outcome=outcome,
                                               wallSeconds=value['wallSeconds'],
                                               caseSeconds=sum(x['seconds'] for x in value['cases']),
                                               outsideCaseSeconds=value['unassignedSeconds']))
            if covered != Counter(x['id'] for x in discovered):
                raise ValueError('Combined worker coverage differs')
            payload.update(status='PASS', coverageComplete=True, **dict(totals))
            payload['summedWorkerWallSeconds'] = sum(x['wallSeconds'] for x in payload['workers'])
            payload['summedCaseSeconds'] = sum(x['caseSeconds'] for x in payload['workers'])
    except BaseException as exc:  # noqa: BLE001 - retain negative/interruption evidence; never rerun tests
        payload.update(status='FAIL', failure=f'{type(exc).__name__}: {exc}')
        traceback.print_exc()
    payload['parallelWallSeconds'] = time.perf_counter() - started
    payload['verificationAndCleanupSeconds'] = max(
        0.0, payload['parallelWallSeconds'] - payload.get('setupSeconds', 0)
        - payload.get('workerWindowSeconds', 0),
    )
    write_report(report, payload)
    return 0 if payload['status'] == 'PASS' else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default='tests')
    parser.add_argument('--top', default='.')
    parser.add_argument('--pattern', default='test*.py')
    parser.add_argument('--out', required=True)
    parser.add_argument('--timeout-seconds', type=float, default=3600)
    args = parser.parse_args(argv)
    if (args.start, args.top, args.pattern) != ('tests', '.', 'test*.py'):
        parser.error('parallel coordinator accepts only canonical tests discovery from the repository root')
    if not math.isfinite(args.timeout_seconds) or not 0 < args.timeout_seconds <= 7200:
        parser.error('timeout must be finite, positive and at most7200seconds')
    try:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('x+', encoding='utf-8') as report:
            return execute(args, report)
    except (OSError, ValueError) as exc:
        print(f'Parallel evidence failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

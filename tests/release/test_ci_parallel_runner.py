from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import zipfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / 'tools/ci/run_parallel_unittest.py'


def module():
    sys.path.insert(0, str(RUNNER.parent))
    try:
        spec = importlib.util.spec_from_file_location('ci_parallel_test_subject', RUNNER)
        value = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(value)
        return value
    finally:
        sys.path.pop(0)


@contextmanager
def repository(hot=None, rest=None):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        bodies = {
            '.gitignore': 'out/\n*.json\nshared.txt\n__pycache__/\n',
            'tests/__init__.py': '', 'tests/workflow/__init__.py': '',
            'tests/workflow/test_limited_usage.py': hot or '''
                import os, pathlib, unittest
                class Hot(unittest.TestCase):
                    def test_isolated(self):
                        root=pathlib.Path.cwd()
                        self.assertEqual(pathlib.Path(os.environ['GITHUB_WORKSPACE']),root)
                        self.assertEqual((root/'tasks/release-2-16/seed.txt').read_text(),'seed')
                        (root/'shared.txt').write_text('hot')
            ''',
            'tests/test_other.py': rest or '''
                import pathlib, unittest
                class Other(unittest.TestCase):
                    def test_isolated(self):
                        p=pathlib.Path('shared.txt')
                        self.assertFalse(p.exists())
                        p.write_text('other')
            ''',
        }
        for name, body in bodies.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(body), encoding='utf-8')
        for name in ['run_unittest.py', 'run_parallel_unittest.py']:
            path = root / 'tools/ci' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(RUNNER.parent / name, path)
        archive = root / 'fixtures/release-2-16-tests.zip'
        archive.parent.mkdir()
        with zipfile.ZipFile(archive, 'w') as stream:
            stream.writestr('seed.txt', 'seed')
        for arguments in [('init', '-q'), ('config', 'user.email', 'ci@example.invalid'),
                          ('config', 'user.name', 'CI fixture'), ('config', 'core.autocrlf', 'false'),
                          ('add', '.'), ('commit', '-qm', 'isolated runner fixture')]:
            subprocess.run(['git', '-c', 'maintenance.auto=false', '-c', 'gc.auto=0', *arguments],
                           cwd=root, check=True, capture_output=True)
        yield root


class CiParallelRunnerTests(unittest.TestCase):
    def test_fixture_git_never_launches_detached_maintenance(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory).resolve() / 'git-trace.jsonl'
            environment = dict(GIT_TRACE2_EVENT=str(trace), GIT_CONFIG_COUNT='2',
                               GIT_CONFIG_KEY_0='maintenance.auto', GIT_CONFIG_VALUE_0='true',
                               GIT_CONFIG_KEY_1='maintenance.autoDetach', GIT_CONFIG_VALUE_1='true')
            with patch.dict(os.environ, environment), repository():
                pass
            events = [json.loads(line) for line in trace.read_text().splitlines()]
            self.assertTrue(any(event.get('event') == 'start' and 'commit' in event.get('argv', [])
                                for event in events))
            automatic = [event for event in events if event.get('event') == 'child_start'
                         and ('maintenance' in event.get('argv', [])
                              or ('gc' in event.get('argv', []) and '--auto' in event.get('argv', [])))]
            self.assertFalse(automatic, automatic)

    def run_fixture(self, root, *arguments):
        result = subprocess.run(
            [sys.executable, '-B', str(RUNNER), '--out', 'out/test-timings.json', *arguments],
            cwd=root, capture_output=True, text=True, timeout=60,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
        )
        path = root / 'out/test-timings.json'
        return result, json.loads(path.read_text()) if path.exists() else None

    def test_two_workers_preserve_coverage_and_isolate_mutations(self):
        with repository() as root:
            before = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root)
            result, value = self.run_fixture(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(value['mode'], 'parallel')
            self.assertEqual(value['testsRun'], 2)
            self.assertTrue(value['coverageComplete'])
            self.assertEqual(len(value['workers']), 2)
            self.assertFalse((root / 'shared.txt').exists())
            self.assertEqual(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root), before)
            for number in range(2):
                folder = root / 'out/test-timings' / str(number)
                self.assertTrue((folder / 'stderr.log').exists())
                self.assertEqual(json.loads((folder / 'test-timings.json').read_text())['status'], 'PASS')

    def test_whole_nested_module_preserves_duplicate_ids_and_fixtures(self):
        hot = '''
            import unittest
            events=[]
            def setUpModule(): events.append('module')
            def tearDownModule(): assert events==['module','class','body','body','endclass']
            class Hot(unittest.TestCase):
                @classmethod
                def setUpClass(cls): events.append('class')
                @classmethod
                def tearDownClass(cls): events.append('endclass')
                def test_case(self): events.append('body')
            def load_tests(loader,tests,pattern):
                return unittest.TestSuite([unittest.TestSuite([Hot('test_case'),Hot('test_case')])])
        '''
        with repository(hot=hot) as root:
            result, value = self.run_fixture(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(value['testsRun'], 3)
            self.assertEqual(sum(x['id'].endswith('Hot.test_case') for x in value['inventory']), 2)

    def test_worker_failure_waits_other_group_without_serial_retry(self):
        hot = '''
            import unittest
            class Hot(unittest.TestCase):
                def test_failure(self): self.fail('intentional worker failure')
        '''
        rest = '''
            import pathlib,time,unittest
            class Other(unittest.TestCase):
                def test_completed(self):
                    time.sleep(0.1)
                    pathlib.Path('shared.txt').write_text('completed')
        '''
        with repository(hot, rest) as root:
            result, value = self.run_fixture(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(value['status'], 'FAIL')
            reports = [json.loads(p.read_text()) for p in (root / 'out/test-timings').glob('*/test-timings.json')]
            self.assertEqual(sorted(x['status'] for x in reports), ['FAIL', 'PASS'])
            self.assertEqual(sum(x['testsRun'] for x in reports), 2)
            self.assertFalse((root / 'shared.txt').exists())

    def test_unqualified_suite_runs_original_serial_once(self):
        with repository() as root:
            (root / 'tests/workflow/test_limited_usage.py').unlink()
            subprocess.run(['git', 'add', '-u'], cwd=root, check=True, capture_output=True)
            subprocess.run(['git', 'commit', '-qm', 'no qualifying module'], cwd=root,
                           check=True, capture_output=True)
            result, value = self.run_fixture(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(value['mode'], 'serial')
            self.assertEqual(value['testsRun'], 1)
            self.assertEqual((root / 'shared.txt').read_text(), 'other')
            self.assertFalse((root / 'out/test-timings').exists())

    def test_dirty_source_and_unsafe_selection_refuse_before_tests(self):
        with repository() as root:
            (root / 'tests/test_other.py').write_text('raise AssertionError("must not import")')
            result, value = self.run_fixture(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('clean committed', value['failure'])
            self.assertFalse((root / 'shared.txt').exists())
        with repository() as root:
            result, value = self.run_fixture(root, '--start', '../outside')
            self.assertNotEqual(result.returncode, 0)
            self.assertIsNone(value)
            output = root / 'out/test-timings.json'
            output.parent.mkdir(exist_ok=True)
            original = '{"status":"PASS","stale":true}'
            output.write_text(original)
            result, _ = self.run_fixture(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_text(), original)
            self.assertFalse((root / 'shared.txt').exists())

    def test_ambiguous_or_fixture_merging_partitions_are_not_qualified(self):
        value = module()

        class Other(unittest.TestCase):
            def test_case(self):
                pass

        class Hot(Other):
            pass

        Other.__module__ = 'controlled.same_module'
        Hot.__module__ = value.HOT_MODULE
        def other():
            return unittest.TestSuite([Other('test_case')])

        def hot():
            return unittest.TestSuite([Hot('test_case')])
        suites = [unittest.TestSuite([other(), hot(), other()]),
                  unittest.TestSuite([other(), hot(), hot()]),
                  unittest.TestSuite([unittest.TestSuite([Hot('test_case'), Other('test_case')]), other()])]
        for suite in suites:
            with self.subTest(suite=suite):
                self.assertIsNone(value.partition(suite, list(value.serial.inventory(suite))))

    def test_worker_roster_mismatch_refuses_before_body(self):
        value = module()
        with repository() as root:
            head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
            clone = root / 'out/clone'
            clone.parent.mkdir()
            value.clone_source(root, clone, head, time.monotonic() + 30)
            inspect_suite = (
                'import sys,json,unittest;sys.path.insert(0,"tools/ci");import run_unittest as r;'
                's=unittest.TestLoader().discover("tests",top_level_dir=".");'
                'groups=[list(r.inventory(c)) for c in s];'
                'i=next(i for i,g in enumerate(groups) if g and '
                'g[0]["module"]=="tests.workflow.test_limited_usage");'
                'print(json.dumps(dict(fullInventory=list(r.inventory(s)),indices=[i],selectedInventory=groups[i])))'
            )
            baseline = json.loads(subprocess.check_output(
                [sys.executable, '-B', '-c', inspect_suite], cwd=clone, timeout=30,
            ))
            valid = {
                'schemaVersion': 'alk-ci-worker-roster.v1', 'sourceHead': head,
                **baseline,
            }
            changes = [{'sourceHead': '0' * 40}, {'fullInventory': []},
                       {'selectedInventory': []}, {'indices': baseline['indices'] * 2}]
            for number, change in enumerate(changes):
                with self.subTest(change=change):
                    (clone / 'bad-roster.json').write_text(json.dumps({**valid, **change}))
                    output = f'bad-report-{number}.json'
                    result = subprocess.run(
                        [sys.executable, '-B', str(clone / 'tools/ci/run_unittest.py'),
                         '--worker-roster', 'bad-roster.json', '--out', output],
                        cwd=clone, capture_output=True, timeout=30,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse((clone / 'shared.txt').exists())
                    self.assertEqual(json.loads((clone / output).read_text())['status'], 'FAIL')

    def test_import_fixture_unexpected_success_and_fixture_skip_outcomes(self):
        examples = [
            ('import-error', 'raise ImportError("controlled import")', False),
            ('fixture-error', '''
                import unittest
                class Hot(unittest.TestCase):
                    @classmethod
                    def setUpClass(cls): raise RuntimeError('controlled fixture')
                    def test_case(self): pass
            ''', False),
            ('unexpected-success', '''
                import unittest
                class Hot(unittest.TestCase):
                    @unittest.expectedFailure
                    def test_case(self): pass
            ''', False),
            ('fixture-skip', '''
                import unittest
                class Hot(unittest.TestCase):
                    @classmethod
                    def setUpClass(cls): raise unittest.SkipTest('capability')
                    def test_case(self): pass
            ''', True),
        ]
        for name, source, passing in examples:
            with self.subTest(name=name), repository(hot=source) as root:
                result, value = self.run_fixture(root)
                self.assertEqual(result.returncode == 0, passing, result.stderr)
                self.assertEqual(value['status'], 'PASS' if passing else 'FAIL')
                if passing:
                    self.assertEqual(value['skips'], 1)
                    self.assertTrue(value['coverageComplete'])

    def test_clone_objects_are_independent_and_zip_paths_are_bounded(self):
        import_path_before = list(sys.path)
        value = module()
        self.assertEqual(sys.path, import_path_before)
        with repository() as root:
            head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
            clone = root / 'out/clone'
            clone.parent.mkdir()
            value.clone_source(root, clone, head, time.monotonic() + 30)
            original = next(p for p in (root / '.git/objects').glob('*/*') if p.is_file())
            self.assertFalse(original.samefile(clone / original.relative_to(root)))
            with zipfile.ZipFile(clone / 'fixtures/release-2-16-tests.zip', 'w') as stream:
                stream.writestr('../escaped.txt', 'must not write')
            with self.assertRaises(ValueError):
                value.restore_fixture(clone)
            self.assertFalse((clone / 'tasks/escaped.txt').exists())

    def test_timeout_kills_worker_descendants_and_retains_failure_logs(self):
        value = module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / 'survived'
            ready = root / 'descendant-started'
            child = ('import pathlib,time,sys;pathlib.Path(sys.argv[2]).write_text("ready");'
                     'time.sleep(1.5);pathlib.Path(sys.argv[1]).write_text("bad")')
            script = ('import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",'
                      + repr(child) + ',sys.argv[1],sys.argv[2]]);time.sleep(30)')
            real_clock = time.monotonic
            deadline = real_clock() + 20
            # Advance the observed clock only after a real descendant has started.
            # This avoids making slow Windows interpreter startup the assertion.
            def observed_clock():
                return real_clock() + (60 if ready.exists() else 0)

            clock = SimpleNamespace(monotonic=observed_clock, sleep=time.sleep)
            with patch.object(value, 'time', clock), patch('agent_lifecycle.changesets.git_io.time', clock):
                outcomes = value.run_workers(
                    [([sys.executable, '-c', script, str(marker), str(ready)], root, root)], deadline,
                )
            self.assertTrue(ready.exists(), 'a real descendant must start before the simulated deadline')
            self.assertIsNotNone(outcomes[0]['transportError'])
            time.sleep(1.6)
            self.assertFalse(marker.exists())
            self.assertTrue((root / 'stderr.log').exists())

    def test_missing_partial_stale_or_wrong_source_reports_cannot_pass(self):
        value = module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'report.json'
            roster = dict(selectedInventory=[])
            for content in [None, '{', json.dumps({'schemaVersion': 'alk-ci-test-timings.v1',
                                                'status': 'RUNNING'})]:
                with self.subTest(content=content):
                    if content is not None:
                        path.write_text(content)
                    with self.assertRaises((ValueError, KeyError, OSError)):
                        value.validate_worker(path, roster, dict(exitCode=0, transportError=None), 'a' * 40)
            with path.open('w') as stream, self.assertRaises(ValueError):
                value.write_report(stream, dict(seconds=float('nan')))
        stream = io.StringIO()
        stream.close()
        with self.assertRaises(ValueError):
            value.write_report(stream, dict(status='PASS'))


if __name__ == '__main__':
    unittest.main()

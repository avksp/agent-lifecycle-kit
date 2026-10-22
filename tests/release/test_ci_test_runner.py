from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tools/ci/run_unittest.py"


class CiTestRunnerTests(unittest.TestCase):
    def compare(self, source, *, modules=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tests = root / "tests"
            tests.mkdir()
            (tests / "__init__.py").write_text("", encoding="utf-8")
            (tests / "test_case.py").write_text(textwrap.dedent(source), encoding="utf-8")
            for name, body in (modules or {}).items():
                (tests / name).write_text(textwrap.dedent(body), encoding="utf-8")
            env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
            common = dict(cwd=root, env=env, capture_output=True, text=True, timeout=30)
            canonical = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"], **common,
            )
            timed = subprocess.run(
                [sys.executable, str(RUNNER), "--out", "timings.json"], **common,
            )
            payload = json.loads((root / "timings.json").read_text(encoding="utf-8"))
            return canonical, timed, payload

    def test_duplicate_ids_and_nested_fixture_execution_are_preserved(self):
        source = '''
            import unittest
            events = []
            def setUpModule(): events.append('module')
            def tearDownModule(): assert events == ['module', 'class', 'body', 'body', 'endclass']
            class Case(unittest.TestCase):
                @classmethod
                def setUpClass(cls): events.append('class')
                @classmethod
                def tearDownClass(cls): events.append('endclass')
                def test_case(self): events.append('body')
            def load_tests(loader, tests, pattern):
                return unittest.TestSuite([unittest.TestSuite([Case('test_case'), Case('test_case')])])
        '''
        canonical, timed, payload = self.compare(source)
        self.assertEqual(canonical.returncode, 0, canonical.stderr)
        self.assertEqual(timed.returncode, 0, timed.stderr)
        self.assertEqual(payload["testsRun"], 2)
        self.assertEqual([r["id"] for r in payload["inventory"]], [r["id"] for r in payload["cases"]])
        self.assertEqual(payload["cases"][0]["id"], payload["cases"][1]["id"])
        self.assertTrue(payload["coverage"]["complete"])

    def test_outcomes_and_failure_exits_match_canonical(self):
        sources = {
            "success": "def test_case(self): pass",
            "failure": "def test_case(self): self.fail('fixture')",
            "error": "def test_case(self): raise RuntimeError('fixture')",
            "skip": "@unittest.skip('capability')\ndef test_case(self): pass",
            "expectedFailure": "@unittest.expectedFailure\ndef test_case(self): self.fail('expected')",
            "unexpectedSuccess": "@unittest.expectedFailure\ndef test_case(self): pass",
            "subtestFailure": "def test_case(self):\n    with self.subTest(n=1): self.fail('fixture')",
            "subtestSkip": "def test_case(self):\n    with self.subTest(n=1): self.skipTest('capability')",
        }
        for label, body in sources.items():
            with self.subTest(label=label):
                source = "import unittest\nclass Case(unittest.TestCase):\n" + textwrap.indent(body, "    ")
                canonical, timed, payload = self.compare(source)
                self.assertEqual(timed.returncode, canonical.returncode, timed.stderr)
                self.assertEqual(payload["status"], "PASS" if canonical.returncode == 0 else "FAIL")
                self.assertEqual(payload["testsRun"], 1)
                self.assertTrue(payload["events"])

    def test_import_and_fixture_errors_cannot_pass(self):
        sources = [
            "raise ImportError('fixture import')",
            "import unittest\ndef setUpModule(): raise RuntimeError('fixture module')\nclass Case(unittest.TestCase):\n    def test_case(self): pass",
            "import unittest\nclass Case(unittest.TestCase):\n    @classmethod\n    def setUpClass(cls): raise RuntimeError('fixture class')\n    def test_case(self): pass",
            "import unittest\nclass Case(unittest.TestCase):\n    @classmethod\n    def tearDownClass(cls): raise RuntimeError('fixture class cleanup')\n    def test_case(self): pass",
        ]
        for source in sources:
            with self.subTest(source=source):
                canonical, timed, payload = self.compare(source)
                self.assertNotEqual(canonical.returncode, 0)
                self.assertNotEqual(timed.returncode, 0)
                self.assertEqual(payload["status"], "FAIL")
                self.assertGreater(payload["errors"], 0)
                if "setUpClass" in source or "setUpModule" in source:
                    self.assertTrue(any(e["caseIndex"] is None for e in payload["events"]))

    def test_fixture_skips_have_explicit_unstarted_cases(self):
        for fixture in ("class", "module"):
            source = (
                "import unittest\nclass Case(unittest.TestCase):\n    def test_case(self): pass\n"
                + ("def setUpModule(): raise unittest.SkipTest('capability')\n" if fixture == "module" else
                   "    @classmethod\n    def setUpClass(cls): raise unittest.SkipTest('capability')\n")
            )
            with self.subTest(fixture=fixture):
                canonical, timed, payload = self.compare(source)
                self.assertEqual(canonical.returncode, 0, canonical.stderr)
                self.assertEqual(timed.returncode, 0, timed.stderr)
                self.assertEqual(payload["testsRun"], 0)
                self.assertEqual(payload["skips"], 1)
                self.assertEqual(payload["coverage"]["notStarted"][0]["reason"], "fixtureSkip")

    def test_per_case_setup_and_cleanup_are_timed_but_class_fixture_is_overhead(self):
        canonical, timed, payload = self.compare('''
            import unittest, time
            class Case(unittest.TestCase):
                @classmethod
                def setUpClass(cls): time.sleep(0.03)
                def setUp(self):
                    time.sleep(0.03)
                    self.addCleanup(time.sleep, 0.03)
                def test_case(self): time.sleep(0.03)
        ''')
        self.assertEqual(timed.returncode, canonical.returncode, timed.stderr)
        self.assertGreaterEqual(payload["cases"][0]["seconds"], 0.09)
        self.assertGreaterEqual(payload["unassignedSeconds"], 0.03)
        self.assertGreaterEqual(payload["wallSeconds"], payload["suiteSeconds"])

    def test_interruption_and_silently_incomplete_suite_fail(self):
        for body in (
            "class Case(unittest.TestCase):\n    def test_case(self): raise KeyboardInterrupt()",
            "class Case(unittest.TestCase):\n    def test_case(self): pass\nclass Incomplete(unittest.TestSuite):\n    def run(self, result, debug=False): return result\ndef load_tests(loader, tests, pattern): return Incomplete([Case('test_case')])",
        ):
            with self.subTest(body=body):
                _, timed, payload = self.compare("import unittest\n" + body)
                self.assertNotEqual(timed.returncode, 0)
                self.assertEqual(payload["status"], "FAIL")

    def test_late_report_write_failure_cannot_return_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tests = root / "tests"
            tests.mkdir()
            (tests / "__init__.py").write_text("", encoding="utf-8")
            (tests / "test_case.py").write_text(
                "import unittest\nclass Case(unittest.TestCase):\n    def test_case(self): pass\n",
                encoding="utf-8",
            )
            probe = (
                "import importlib.util, sys\n"
                f"spec=importlib.util.spec_from_file_location('timed_runner', {str(RUNNER)!r})\n"
                "runner=importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)\n"
                "original=runner.json.dump; calls=0\n"
                "def failing_dump(*args, **kwargs):\n"
                "    global calls\n"
                "    calls+=1\n"
                "    if calls>1: raise OSError('controlled late report failure')\n"
                "    return original(*args, **kwargs)\n"
                "runner.json.dump=failing_dump\n"
                "sys.exit(runner.main(['--out','timings.json']))\n"
            )
            p = subprocess.run([sys.executable, "-c", probe], cwd=root,
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode, 2, p.stderr)
            self.assertIn("Ran 1 test", p.stderr)
            self.assertIn("controlled late report failure", p.stderr)
            self.assertEqual(json.loads((root / "timings.json").read_text())["status"], "RUNNING")

    def test_report_refusal_never_runs_suite_or_reuses_old_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "timings.json"
            report.write_text('{"status":"PASS","prior":true}', encoding="utf-8")
            old = report.read_bytes()
            for target in (report, root):
                with self.subTest(target=target):
                    p = subprocess.run(
                        [sys.executable, str(RUNNER), "--start", "missing", "--out", str(target)],
                        cwd=root, capture_output=True, text=True, timeout=30,
                    )
                    self.assertEqual(p.returncode, 2)
                    self.assertIn("Timing report failed", p.stderr)
                    self.assertEqual(report.read_bytes(), old)


if __name__ == "__main__":
    unittest.main()

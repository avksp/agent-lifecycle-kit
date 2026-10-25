"""Controlled local regressions for the real measurement runner; no Windows claim."""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import time
import unittest
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "tools/ci/measure_limited_usage.py"


def subject():
    spec = importlib.util.spec_from_file_location("limited_measurement_subject", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def checkout(body=None):
    with tempfile.TemporaryDirectory() as directory:
        parent = Path(directory).resolve()
        root = parent / "checkout"
        root.mkdir()
        files = {
            "tests/__init__.py": "",
            "tests/workflow/__init__.py": "",
            "src/agent_lifecycle/__init__.py": "__version__ = 'controlled'\n",
            "tests/workflow/test_limited_usage.py": body
            or """
                import os, pathlib, unittest
                calls=[]
                def setUpModule(): calls.append('module')
                def tearDownModule(): assert calls==['module','class','first','second','endclass']
                class Controlled(unittest.TestCase):
                    @classmethod
                    def setUpClass(cls): calls.append('class')
                    @classmethod
                    def tearDownClass(cls): calls.append('endclass')
                    def test_first(self):
                        self.assertNotIn('ALK_MEASUREMENT_SECRET',os.environ)
                        self.assertNotIn('PYTHONPATH',os.environ)
                        self.assertNotIn('PYTHONHOME',os.environ)
                        calls.append('first')
                    def test_second(self):
                        import agent_lifecycle
                        self.assertTrue(pathlib.Path(agent_lifecycle.__file__).is_relative_to(pathlib.Path.cwd()))
                        calls.append('second')
            """,
        }
        for name, data in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(data), encoding="utf-8")
        runner = root / "tools/ci/run_unittest.py"
        runner.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / "tools/ci/run_unittest.py", runner)
        for args in (
            ("init", "-q"),
            ("config", "user.name", "Controlled"),
            ("config", "user.email", "test@example.invalid"),
            ("add", "."),
            ("commit", "-qm", "controlled source"),
        ):
            subprocess.run(
                ["git", "-c", "maintenance.auto=false", "-c", "gc.auto=0", *args],
                cwd=root,
                check=True,
                capture_output=True,
            )
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        subprocess.run(["git", "checkout", "--detach", head], cwd=root, check=True, capture_output=True)
        yield parent, root, head


class LimitedUsageMeasurementTests(unittest.TestCase):
    def invoke_sample(self, module, parent, root, head):
        names = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().strip("\0").split("\0")
        inputs = module.input_manifest(root, names)
        destination = parent / "sample"
        destination.mkdir()
        scratch = parent / "scratch"
        scratch.mkdir()
        request = {
            "root": str(root),
            "output": str(destination / "timings.json"),
            "sourceHead": head,
            "trackedInputs": names,
            "inputSha256": inputs["sha256"],
            "testContract": module.test_contract(root),
            "expectedTests": 2,
        }
        request_path = destination / "request.json"
        module.write_new(request_path, request)
        records = []
        with patch.dict(os.environ, ALK_MEASUREMENT_SECRET="must-not-reach-tests", PYTHONPATH="poison"):
            module.command(
                module.worker_argv(HELPER, request_path, root, scratch),
                root,
                time.monotonic() + 60,
                records,
                logs=destination,
            )
        return request, module.read_object(destination / "timings.json"), records

    def test_real_worker_executes_full_original_suite_and_isolates_imports_and_environment(self):
        module = subject()
        with checkout() as (parent, root, head):
            request, value, records = self.invoke_sample(module, parent, root, head)
            join = module.validate_sample(value, request)
            self.assertEqual(value["testsRun"], 2)
            self.assertEqual([item["outcome"] for item in join["events"]], ["success", "success"])
            self.assertTrue(value["inputHashesUnchanged"])
            self.assertEqual(records[0]["exitCode"], 0)
            self.assertTrue((parent / "sample/stderr.log").exists())
            self.assertIsNone(value["immutableGitSeedPreparationSeconds"])
            with patch.dict(
                os.environ,
                ALK_MEASUREMENT_SECRET="exclude",
                GIT_CONFIG_COUNT="1",
                GIT_CONFIG_KEY_0="core.bare",
                GIT_CONFIG_VALUE_0="true",
            ):
                raw = module.git(["status", "--porcelain"], root, time.monotonic() + 30, records)
            self.assertEqual(raw, b"")
            self.assertEqual(records[-1]["gitArgv"], ["git", "status", "--porcelain"])
            for change in (
                {"sourceHead": "0" * 40},
                {"inputHashesUnchanged": False},
                {"testContract": {}},
                {"cases": []},
                {"wallSeconds": float("nan")},
                {"status": "RUNNING"},
                {"failures": 1},
            ):
                with self.subTest(change=change), self.assertRaises((ValueError, KeyError)):
                    module.validate_sample({**value, **change}, request)

    def test_real_worker_source_mutation_is_failure_with_logs_and_no_retry(self):
        module = subject()
        body = """
            import pathlib,unittest
            class Mutation(unittest.TestCase):
                def test_first(self): pathlib.Path('src/agent_lifecycle/__init__.py').write_text('changed')
                def test_second(self): pass
        """
        with checkout(body) as (parent, root, head):
            with self.assertRaises(ValueError):
                self.invoke_sample(module, parent, root, head)
            value = json.loads((parent / "sample/timings.json").read_bytes())
            self.assertEqual(value["testsRun"], 2)
            self.assertEqual(value["status"], "FAIL")
            self.assertTrue(value["inputMutation"])
            self.assertTrue((parent / "sample/stdout.log").exists())

    def test_three_pair_join_refuses_changed_outcomes_environment_roster_and_missing_samples(self):
        module = subject()
        join = {
            "inventory": [{"id": "controlled.case"}],
            "events": [{"outcome": "success"}],
            "skips": 0,
            "environment": {"ImageVersion": "controlled"},
        }
        samples = [
            {"side": side, "wallSeconds": 10 if side == "baseline" else 7, "join": deepcopy(join)}
            for side in module.ORDER
        ]
        self.assertEqual(module.compare_samples(samples)["status"], "MEASURED_IMPROVEMENT")
        slower = deepcopy(samples)
        for item in slower:
            if item["side"] == "candidate":
                item["wallSeconds"] = 11
        self.assertEqual(module.compare_samples(slower)["status"], "NO_IMPROVEMENT")
        for change in (
            {"inventory": []},
            {"events": [{"outcome": "skip"}]},
            {"skips": 1},
            {"environment": {"ImageVersion": "different"}},
        ):
            changed = deepcopy(samples)
            changed[1]["join"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                module.compare_samples(changed)
        with self.assertRaises(ValueError):
            module.compare_samples(samples[:-1])
        changed = deepcopy(samples)
        changed[2]["side"] = "baseline"
        with self.assertRaises(ValueError):
            module.compare_samples(changed)

    def test_contract_binds_full_methods_and_normalizes_only_proven_line_selectors(self):
        module = subject()
        original = (ROOT / module.HOT_PATH).read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / module.HOT_PATH
            path.parent.mkdir(parents=True)
            path.write_text(original)
            before = module.test_contract(root)
            tree = ast.parse(original)
            events = []
            for cls in (node for node in tree.body if isinstance(node, ast.ClassDef)):
                for method in (node for node in cls.body if isinstance(node, ast.FunctionDef)):
                    key = f"{module.HOT_MODULE}.{cls.name}.{method.name}"
                    if key not in module.LINE_SELECTORS:
                        continue
                    for loop in (node for node in ast.walk(method) if isinstance(node, ast.For)):
                        if isinstance(loop.iter, ast.Tuple) and all(
                            isinstance(node, ast.Lambda) for node in loop.iter.elts
                        ):
                            for choice in loop.iter.elts:
                                events.append(
                                    {
                                        "id": f"{key} ({module.LINE_SELECTORS[key]}={choice.lineno})",
                                        "outcome": "subtest:success",
                                        "caseIndex": 0,
                                    }
                                )
            joined = module.canonical_events(root, events)
            path.write_text("\n\n" + original)
            shifted = [
                {
                    **event,
                    "id": event["id"].rsplit("=", 1)[0] + "=" + str(int(event["id"].rsplit("=", 1)[1][:-1]) + 2) + ")",
                }
                for event in events
            ]
            self.assertEqual(joined, module.canonical_events(root, shifted))
            self.assertEqual(before, module.test_contract(root))
            with self.assertRaises(ValueError):
                module.canonical_events(root, events)
            path.write_text(
                original.replace("def denied(self, callback, code=None):", "def denied(self, callback, code=False):")
            )
            self.assertNotEqual(before, module.test_contract(root))

    def test_shell_refs_non_windows_and_stale_reports_refuse_without_measurement(self):
        module = subject()
        for value in ("HEAD", "main", "a" * 39, "A" * 40, "$(echo bad)", "a" * 40 + ";echo bad"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.source_sha(value)
        args = SimpleNamespace(
            baseline=module.BASELINE, candidate="1" * 40, experiment=1, out="unused.json", mode="paired"
        )
        stream = io.StringIO()
        with patch.object(module.platform, "system", return_value="Linux"):
            self.assertEqual(module.execute(args, stream), 1)
        value = json.loads(stream.getvalue())
        self.assertEqual(value["status"], "FAIL")
        self.assertEqual(value["commands"], [])
        self.assertFalse(value["performanceAcceptanceClaimed"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_bytes(b"original")
            self.assertEqual(
                module.main(
                    ["--baseline", module.BASELINE, "--candidate", "1" * 40, "--experiment", "1", "--out", str(path)]
                ),
                2,
            )
            self.assertEqual(path.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()

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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "tools/ci/measure_limited_usage.py"


def subject():
    spec = importlib.util.spec_from_file_location("limited_measurement_subject", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clock_events(module, first=None):
    first = first or datetime(2026, 10, 25, 23, 59, 59, 123456, tzinfo=UTC)
    return [
        {"id": f"{module.CLOCK_ID} (observed={observed!r})", "caseIndex": 46, "outcome": "subtest:success"}
        for observed in (first, first + timedelta(seconds=1))
    ] + [{"id": module.CLOCK_ID, "caseIndex": 46, "outcome": "success"}]


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

    def test_candidate_profile_keeps_true_source_role_and_refuses_baseline_relabelling(self):
        module = subject()
        body = """
            import unittest
            setups=[]
            class LimitedUsageTests(unittest.TestCase):
                def setUp(self): setups.append('fresh')
                def test_current_registry_capacity_preserves_large_original_interval(self):
                    self.assertEqual(len(setups),4)
        """
        with checkout(body) as (parent, root, head):
            names = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().strip("\0").split("\0")
            destination = parent / "profile"
            destination.mkdir()
            scratch = parent / "scratch"
            scratch.mkdir()
            request = {
                "root": str(root),
                "output": str(destination / "profile.json"),
                "sourceHead": head,
                "trackedInputs": names,
                "inputSha256": module.input_manifest(root, names)["sha256"],
                "testContract": module.test_contract(root),
                "profileOnly": True,
                "profileSourceRole": "candidate",
                "profileMode": "PROFILE_FEASIBILITY",
            }
            path = destination / "request.json"
            module.write_new(path, request)
            records = []
            with patch.dict(os.environ, GITHUB_SHA=head):
                module.command(
                    module.worker_argv(HELPER, path, root, scratch),
                    root,
                    time.monotonic() + 60,
                    records,
                    logs=destination,
                )
            value = module.read_object(destination / "profile.json")
            self.assertEqual((value["sourceHead"], value["sourceRole"]), (head, "candidate"))
            self.assertEqual(value["actualTestsRun"], 1)
            self.assertFalse(value["performanceAcceptanceClaimed"])
            denied = parent / "denied"
            denied.mkdir()
            bad = {**request, "output": str(denied / "profile.json"), "profileSourceRole": "baseline"}
            bad_path = denied / "request.json"
            module.write_new(bad_path, bad)
            with patch.dict(os.environ, GITHUB_SHA=head), self.assertRaises(ValueError):
                module.command(
                    module.worker_argv(HELPER, bad_path, root, scratch),
                    root,
                    time.monotonic() + 60,
                    records,
                    logs=denied,
                )
            self.assertFalse((denied / "profile.json").exists())

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
        original = (ROOT / module.HOT_PATH).read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / module.HOT_PATH
            path.parent.mkdir(parents=True)
            path.write_text(original, encoding="utf-8")
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
            clock = clock_events(module)
            joined = module.canonical_events(root, events + clock)
            path.write_text("\n\n" + original, encoding="utf-8")
            shifted = [
                {
                    **event,
                    "id": event["id"].rsplit("=", 1)[0] + "=" + str(int(event["id"].rsplit("=", 1)[1][:-1]) + 2) + ")",
                }
                for event in events
            ]
            self.assertEqual(joined, module.canonical_events(root, shifted + clock))
            self.assertEqual(before, module.test_contract(root))
            with self.assertRaises(ValueError):
                module.canonical_events(root, events)
            path.write_text(
                original.replace("def denied(self, callback, code=None):", "def denied(self, callback, code=False):"),
                encoding="utf-8",
            )
            self.assertNotEqual(before, module.test_contract(root))

    def test_exact_clock_channel_preserves_raw_events_and_rejects_other_shapes(self):
        module = subject()
        original = (ROOT / module.HOT_PATH).read_bytes()
        tree = ast.parse(original)
        events = clock_events(module)
        saved = deepcopy(events)
        joined = module.canonical_clock_events(tree, events)
        self.assertEqual(events, saved)
        self.assertEqual(
            [item["id"] for item in joined[:2]],
            [module.CLOCK_ID + " (observed=deadline)", module.CLOCK_ID + " (observed=deadline+1s)"],
        )
        self.assertEqual(joined[-1], events[-1])
        self.assertEqual(
            joined, module.canonical_clock_events(tree, clock_events(module, datetime(2026, 1, 1, 0, 0, tzinfo=UTC)))
        )
        malformed = [
            events[:1] + events[2:],
            [events[1], events[0], events[2]],
            [events[0], events[0], events[2]],
            events + [events[1]],
            [events[0], {"id": "other", "outcome": "success", "caseIndex": 45}, *events[1:]],
        ]
        for change in (
            {"caseIndex": 45},
            {"outcome": "skip"},
            {"id": events[0]["id"].replace("observed=", "unexpected=")},
            {"id": events[0]["id"].replace(module.CLOCK_ID, "unexpected.method")},
            {"id": module.CLOCK_ID + " (observed=__import__('os').system('bad'))"},
        ):
            variant = deepcopy(events)
            variant[0].update(change)
            malformed.append(variant)
        wrong_delta = deepcopy(events)
        wrong_delta[1]["id"] = wrong_delta[1]["id"].replace("0, 0, 0, 123456", "0, 0, 1, 123456")
        malformed.append(wrong_delta)
        for variant in malformed:
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                module.canonical_clock_events(tree, variant)
        changed = ast.parse(
            original.replace(b"with self.subTest(observed=observed)", b"with self.subTest(observed=False)")
        )
        with self.assertRaises(ValueError):
            module.canonical_clock_events(changed, events)
        for text in (
            "datetime.datetime(2026, 1, 1, 0, 0)",
            "datetime.datetime(True, 1, 1, 0, 0, tzinfo=datetime.timezone.utc)",
            "datetime.datetime(2026, 99, 1, 0, 0, tzinfo=datetime.timezone.utc)",
            "datetime.datetime(2026,1,1,0,0,tzinfo=datetime.timezone.utc)",
            "(lambda: 1)()",
            "datetime.datetime(*[2026,1,1,0,0],tzinfo=datetime.timezone.utc)",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                module.utc_datetime_repr(text)

    def test_clock_binding_preserves_empty_schema_fields_and_rejects_new_semantics(self):
        module = subject()
        tree = ast.parse((ROOT / module.HOT_PATH).read_bytes())
        events = clock_events(module)
        expected = module.canonical_clock_events(tree, events)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                if "type_params" not in node._fields:
                    node._fields = (*node._fields, "type_params")
                node.type_params = []
        self.assertEqual(expected, module.canonical_clock_events(tree, events))
        method = next(
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == module.CLOCK_METHOD
        )
        method.type_params = [ast.Name(id="Unreviewed", ctx=ast.Load())]
        with self.assertRaises(ValueError):
            module.canonical_clock_events(tree, events)
        method.type_params = []
        method._fields = (*method._fields, "unreviewed_field")
        method.unreviewed_field = []
        with self.assertRaises(ValueError):
            module.canonical_clock_events(tree, events)

    def test_clock_binding_normalizes_only_eager_import_defaults(self):
        module = subject()
        tree = ast.parse((ROOT / module.HOT_PATH).read_bytes())
        events = clock_events(module)
        expected = module.canonical_clock_events(tree, events)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if "is_lazy" not in node._fields:
                    node._fields = (*node._fields, "is_lazy")
                node.is_lazy = 0
        self.assertEqual(expected, module.canonical_clock_events(tree, events))
        for flag in (1, False, None):
            variant = deepcopy(tree)
            method = next(
                node
                for node in ast.walk(variant)
                if isinstance(node, ast.FunctionDef) and node.name == module.CLOCK_METHOD
            )
            node = next(item for item in ast.walk(method) if isinstance(item, (ast.Import, ast.ImportFrom)))
            node.is_lazy = flag
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                module.canonical_clock_events(variant, events)
        for target in ("import", "method"):
            variant = deepcopy(tree)
            method = next(
                node
                for node in ast.walk(variant)
                if isinstance(node, ast.FunctionDef) and node.name == module.CLOCK_METHOD
            )
            if target == "import":
                node = next(item for item in ast.walk(method) if isinstance(item, (ast.Import, ast.ImportFrom)))
                node._fields = (*node._fields, "future_semantics")
                node.future_semantics = []
            else:
                method._fields = (*method._fields, "is_lazy")
                method.is_lazy = 0
            with self.subTest(target=target), self.assertRaises(ValueError):
                module.canonical_clock_events(variant, events)

        class OptionalImport(ast.Import):
            is_lazy = None

        optional = OptionalImport(names=[])
        optional._fields = ("names", "is_lazy")
        optional.is_lazy = None
        self.assertIn("is_lazy=None", module.clock_ast_dump(optional))

    def test_measured_authority_stat_has_only_the_approved_migration_exception(self):
        source = (ROOT / "src/agent_lifecycle/contracts/authority_io.py").read_text(encoding="utf-8")
        expected = "return os.stat(os.path.join(self.path, name), follow_symlinks=False)  # noqa: PTH116, PTH118"
        self.assertEqual(source.count("# noqa:"), 1)
        self.assertEqual([line.strip() for line in source.splitlines() if "# noqa:" in line], [expected])
        self.assertNotIn("# ruff: noqa", source)

    def test_full_trial_uses_all_pairs_without_accepting_a_diagnostic_prefix(self):
        module = subject()
        samples = []
        for side, seconds in zip(module.ORDER, (10, 9, 7, 10, 10, 7.5), strict=False):
            samples.append({"side": side, "wallSeconds": seconds, "join": {"events": ["same"]}})
        self.assertEqual(module.viability_prefix(samples[:2])["status"], "INCOMPLETE")
        observed = module.viability_prefix(samples[:2], ratio_stop=False)
        self.assertEqual(observed["status"], "PREFIX_OBSERVED_ONLY")
        self.assertFalse(observed["performanceAcceptanceClaimed"])
        self.assertFalse(observed["ratioGateEnforced"])
        with self.assertRaises(ValueError):
            module.compare_samples(samples[:2])
        self.assertEqual(module.compare_samples(samples)["status"], "MEASURED_IMPROVEMENT")
        for item in samples:
            if item["side"] == "candidate":
                item["wallSeconds"] = 9
        self.assertEqual(module.compare_samples(samples)["status"], "NO_IMPROVEMENT")
        samples[1]["join"] = {"events": ["different"]}
        self.assertEqual(module.viability_prefix(samples[:2], ratio_stop=False)["status"], "INCOMPLETE")

    def test_prefix_is_continuation_only_and_deadline_is_finite_and_native_capped(self):
        module = subject()
        samples = [
            {"side": "baseline", "wallSeconds": 10, "join": {"events": ["same"]}},
            {"side": "candidate", "wallSeconds": 8, "join": {"events": ["same"]}},
        ]
        prefix = module.viability_prefix(samples)
        self.assertEqual(prefix["status"], "PREFIX_ELIGIBLE_TO_CONTINUE")
        self.assertFalse(prefix["performanceAcceptanceClaimed"])
        with self.assertRaises(ValueError):
            module.compare_samples(samples)
        samples[1]["wallSeconds"] = 8.01
        self.assertEqual(module.viability_prefix(samples)["status"], "INCOMPLETE")
        samples[1]["join"] = {"events": ["changed"]}
        self.assertEqual(module.viability_prefix(samples)["reason"], "prefix-join-mismatch")
        with self.assertRaises(ValueError):
            module.viability_prefix(list(reversed(samples)))

        class FixedClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 10, 26, 7, tzinfo=UTC)

        with patch.object(module, "datetime", FixedClock):
            self.assertEqual(module.experiment3_seconds("2026-10-26T14:46:31Z"), 18000)
            self.assertEqual(module.experiment3_seconds("2026-10-26T08:00:00Z"), 3600)
            ceiling_exceeded = (module.EXPERIMENT3_DEADLINE + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            for value in (None, "", ceiling_exceeded, "2026-10-26T06:00:00Z", "2026-10-26T08:00:00+00:00", "bad"):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    module.experiment3_seconds(value)
        records = []
        with self.assertRaises(LifecycleError):
            module.command(["must-not-launch"], ROOT, time.monotonic() - 1, records)
        self.assertIs(records[0]["processStarted"], False)

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
        args.mode = "feasibility"
        stream = io.StringIO()
        with patch.object(module.platform, "system", return_value="Linux"):
            self.assertEqual(module.execute(args, stream), 1)
        feasibility = json.loads(stream.getvalue())
        self.assertEqual(feasibility["experimentTimeoutSeconds"], 600)
        self.assertEqual(feasibility["validationUnits"]["profileChildrenStarted"], 0)
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


class Release234MeasurementTests(unittest.TestCase):
    def test_exact_runtime_candidate_refuses_every_other_ast_and_source_change(self):
        module = subject()
        legacy = "src/agent_lifecycle/accounting/declared_ledger_legacy.py"
        candidate = (ROOT / legacy).read_text()
        tree = ast.parse(candidate)
        method = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_r11_git")
        method.body = method.body[2:]
        call = next(n for n in ast.walk(method) if isinstance(n, ast.Call) and ast.unparse(n.func) == "subprocess.run")
        call.args[0].elts[0] = ast.Constant(value="git")
        baseline = ast.unparse(tree)
        with tempfile.TemporaryDirectory() as directory:
            roots = {side: Path(directory) / side for side in ("baseline", "candidate")}
            inputs = {
                side: {
                    "files": [
                        {"path": name, "sha256": "same"}
                        for name in (
                            legacy,
                            module.HOT_PATH,
                            "tests/workflow/limited_usage_fixture_support.py",
                            "src/other.py",
                        )
                    ]
                }
                for side in roots
            }
            for side, text in (("baseline", baseline), ("candidate", candidate)):
                path = roots[side] / legacy
                path.parent.mkdir(parents=True)
                path.write_text(text)
            module.release234_contract(roots, inputs)
            path = roots["candidate"] / legacy
            for changed in (
                candidate.replace("timeout=15", "timeout=14"),
                candidate.replace("Path(executable).is_absolute()", "True"),
                candidate.replace('executable if executable is not None else "git"', '"git"'),
            ):
                path.write_text(changed)
                with self.assertRaises(ValueError):
                    module.release234_contract(roots, inputs)
            path.write_text(candidate)
            inputs["candidate"]["files"][-1]["sha256"] = "changed"
            with self.assertRaises(ValueError):
                module.release234_contract(roots, inputs)

    def test_new_threshold_uses_each_versions_baseline_mad_and_original_deadline(self):
        module = subject()
        samples = [
            {"side": side, "wallSeconds": 100 if side == "baseline" else 94, "join": {}} for side in module.ORDER
        ]
        self.assertEqual(module.release234_comparison(samples)["status"], "MEASURED_IMPROVEMENT")
        samples[1]["wallSeconds"] = samples[2]["wallSeconds"] = samples[5]["wallSeconds"] = 95
        self.assertEqual(module.release234_comparison(samples)["status"], "STOP_NO_BENEFIT")
        samples[0]["wallSeconds"], samples[3]["wallSeconds"], samples[4]["wallSeconds"] = 80, 100, 120
        self.assertEqual(module.release234_comparison(samples)["requiredRelativeGainExclusive"], 0.2)

        class FixedClock(datetime):
            @classmethod
            def now(cls, _tz=None):
                return module.RELEASE234_DEADLINE - timedelta(hours=2)

        with patch.object(module, "datetime", FixedClock):
            self.assertEqual(module.release234_seconds("2026-10-31T01:47:46Z"), 7200)
            for value in (None, "bad", "2026-10-31T01:47:47Z", "2026-10-31T01:47:45Z"):
                with self.assertRaises(ValueError):
                    module.release234_seconds(value)
        with patch.object(module.sys, "platform", "linux"):
            self.assertEqual(
                module.process_peak(), {"scope": "worker-process-only", "bytes": None, "status": "UNAVAILABLE"}
            )

    def test_contract_probe_preserves_inputs_and_rejects_a_wrong_locked_interpreter(self):
        module = subject()
        with checkout() as (parent, root, head):
            names = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().strip("\0").split("\0")
            before = module.input_manifest(root, names)
            scratch = parent / "scratch"
            scratch.mkdir()
            expected = list(__import__("sys").version_info[:2])
            path = parent / "probe-request.json"
            request = {
                "root": str(root),
                "output": str(parent / "contract.json"),
                "sourceHead": head,
                "trackedInputs": names,
                "inputSha256": before["sha256"],
                "testContract": {"wrong-schema": True},
                "contractOnly": True,
                "expectedVersion": expected,
            }
            module.write_new(path, request)
            records = []
            module.command(
                module.worker_argv(HELPER, path, root, scratch, version=expected), root, time.monotonic() + 30, records
            )
            value = module.read_object(Path(request["output"]))
            self.assertEqual(value, {"testContract": module.test_contract(root), "version": expected})
            self.assertEqual(module.input_manifest(root, names), before)
            wrong = [3, 11] if expected == [3, 15] else [3, 15]
            rejected = parent / "wrong-request.json"
            module.write_new(
                rejected, {**request, "output": str(parent / "wrong.json"), "experiment": 5, "expectedVersion": wrong}
            )
            with self.assertRaises(ValueError):
                module.command(
                    module.worker_argv(HELPER, rejected, root, scratch, version=wrong),
                    root,
                    time.monotonic() + 30,
                    records,
                )
            self.assertFalse((parent / "wrong.json").exists())
            malformed = parent / "missing-version-request.json"
            module.write_new(malformed, {**request, "output": str(parent / "missing.json"), "experiment": 5})
            with self.assertRaises(ValueError):
                module.command(
                    module.worker_argv(HELPER, malformed, root, scratch), root, time.monotonic() + 30, records
                )
            self.assertFalse((parent / "missing.json").exists())

    def test_candidate_treatment_is_the_only_worker_environment_difference(self):
        module = subject()
        key = "ALK_ACCOUNTING_GIT_EXECUTABLE"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            backend = str(root / "selected Git Ω.exe")
            environments = {}
            with patch.dict(os.environ, {key: backend, "GIT_TRACE2_EVENT": "must-not-reach-workload"}):
                for side in ("baseline", "candidate"):
                    request = root / (side + ".json")
                    module.write_new(request, {"accountingGitExecutable": backend if side == "candidate" else None})
                    argv = module.worker_argv(HELPER, request, root, root, version=[3, 11])
                    options = json.loads(argv[-1])
                    environments[side] = options["environment"]
                    self.assertNotIn("GIT_TRACE2_EVENT", options["environment"])
            self.assertNotIn(key, environments["baseline"])
            self.assertEqual(environments["candidate"].pop(key), backend)
            self.assertEqual(environments["baseline"], environments["candidate"])

    def test_workflow_backend_selection_and_postcheck_preserve_path_and_refuse_drift(self):
        from contextlib import redirect_stdout

        workflow = (ROOT / ".github/workflows/ci-timing-control.yml").read_text()
        setup, after = [textwrap.dedent(part.split("'@", 1)[0]) for part in workflow.split("$code = @'")[1:]]
        for scenario in ("positive", "version-mismatch", "binary-drift"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                prefix = root / "Git spaced Ω"
                core = prefix / "libexec/git-core"
                core.mkdir(parents=True)
                wrapper, backend = prefix / "cmd/git.exe", prefix / "bin/git.exe"
                for path in (wrapper, backend):
                    path.parent.mkdir(parents=True)
                    path.write_bytes(b"fixed mocked binary")
                (root / "work/ci").mkdir(parents=True)
                previous = Path.cwd()
                original_path = os.environ["PATH"]

                def git_output(argv, *, scenario=scenario, wrapper=wrapper, backend=backend, core=core, **_kwargs):
                    self.assertIn(argv[0], (str(wrapper), str(backend)))
                    if argv[1:] == ["--exec-path"]:
                        return str(core).encode()
                    self.assertEqual(argv[1:], ["--version"])
                    return (
                        b"different"
                        if scenario == "version-mismatch" and argv[0] == str(backend)
                        else b"git version fixture"
                    )

                try:
                    os.chdir(root)
                    with (
                        patch.dict(os.environ, GITHUB_SHA="f" * 40, GITHUB_OUTPUT=str(root / "outputs")),
                        patch("shutil.which", return_value=str(wrapper)),
                        patch("subprocess.check_output", side_effect=git_output),
                        redirect_stdout(io.StringIO()),
                    ):
                        if scenario == "version-mismatch":
                            with self.assertRaises(AssertionError):
                                exec(compile(setup, "<workflow-backend-setup>", "exec"), {})
                            self.assertFalse((root / "work/ci/release234-git-backend.json").exists())
                            continue
                        exec(compile(setup, "<workflow-backend-setup>", "exec"), {})
                        metadata = json.loads((root / "work/ci/release234-git-backend.json").read_bytes())
                        self.assertEqual(metadata["backend"]["path"], str(backend))
                        self.assertEqual(os.environ["PATH"], original_path)
                        if scenario == "binary-drift":
                            backend.write_bytes(b"changed binary")
                            with self.assertRaises(AssertionError):
                                exec(compile(after, "<workflow-backend-after>", "exec"), {})
                        else:
                            exec(compile(after, "<workflow-backend-after>", "exec"), {})
                        result = json.loads((root / "work/ci/release234-git-backend-after.json").read_bytes())
                        self.assertTrue(result["pathUnchanged"])
                        self.assertEqual(
                            all(item["unchanged"] for item in result["executables"]), scenario == "positive"
                        )
                finally:
                    os.chdir(previous)

    def test_two_version_barrier_stops_without_full_samples_and_preserves_all_twelve_pairs(self):
        module = subject()
        candidate = "1" * 40
        for benefit in (False, True):
            with self.subTest(benefit=benefit), tempfile.TemporaryDirectory() as directory:
                source = Path(directory)
                for version in ("311", "315"):
                    exe = source / f"work/ci/release234-py{version}/Scripts/python.exe"
                    exe.parent.mkdir(parents=True)
                    exe.touch()
                backend_record = source / "work/ci/release234-git-backend.json"
                backend_record.write_text(
                    json.dumps({"sourceHead": candidate, "backend": {"path": str(source / "selected backend.exe")}})
                )
                started = []

                def git(arguments, root, _deadline, _records):
                    if arguments[0] == "clone":
                        root = Path(arguments[-1])
                        root.mkdir()
                        for name in (
                            ".gitattributes",
                            module.HOT_PATH,
                            "src/agent_lifecycle/contracts/authority_io.py",
                        ):
                            path = root / name
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_text("same")
                    if arguments[0] == "rev-parse":
                        return (module.RELEASE234_BASELINE if root.name == "baseline" else candidate).encode()
                    if arguments[0] == "diff":
                        return "\n".join(sorted(module.RELEASE234_OWNED)).encode()
                    return b"tracked\0" if arguments[0] == "ls-files" else b""

                def command(argv, _root, _deadline, records, *, started=started, benefit=benefit, **_kwargs):
                    options = json.loads(argv[-1])
                    request = module.read_object(Path(options["request"]))
                    side, version = request["profileSourceRole"], str(options["version"][1])
                    phase = (
                        "contract"
                        if request.get("contractOnly")
                        else "profile"
                        if request["profileOnly"]
                        else "regression"
                        if request["regressionOnly"]
                        else "module"
                    )
                    started.append((version, side, phase))
                    contract = {
                        "testAndFixtureAstSha256": "schema-" + version,
                        "assertionAstSha256": "same",
                        "assertionSites": 287,
                    }
                    if phase == "contract":
                        module.write_new(
                            Path(request["output"]),
                            {
                                "testContract": contract,
                                "version": options["version"],
                                "sourceHead": request["sourceHead"],
                                "inputSha256": request["inputSha256"],
                            },
                        )
                        records.append({"processStarted": True, "exitCode": 0})
                        return
                    self.assertEqual(request["testContract"], contract)
                    self.assertEqual(request["expectedVersion"], options["version"])
                    seconds = 100 if side == "baseline" else 90 if benefit or version == "11" else 99
                    value = {
                        "status": "PASS",
                        "testsRun": request["expectedTests"],
                        "inputHashesUnchanged": True,
                        "sourceHead": request["sourceHead"],
                        "sourceRole": side,
                        "mode": request["profileMode"],
                        "testContract": request["testContract"],
                        "testId": f"{module.HOT_MODULE}.{module.SLOW_CASE}",
                        "python": version,
                        "inputSha256": "same",
                        "environment": module.environment_identity(),
                        "performanceAcceptanceClaimed": False,
                        "phases": [{"phase": "slow-case", "elapsedSeconds": seconds}],
                        "runtimeProvenance": {"executable": argv[0]},
                        "lockedEnvironment": {"version": version},
                        "wallSeconds": seconds,
                        "immutableGitSeedPreparationSeconds": 0,
                    }
                    if phase == "profile":
                        value["status"] = "PROFILE_COMPLETE"
                    module.write_new(Path(request["output"]), value)
                    records.append({"processStarted": True, "exitCode": 0})

                args = SimpleNamespace(
                    baseline=module.RELEASE234_BASELINE,
                    candidate=candidate,
                    experiment=5,
                    mode="paired",
                    deadline_utc="2026-10-31T01:47:46Z",
                    out=str(source / "report.json"),
                )
                with (
                    patch.object(module.Path, "cwd", return_value=source),
                    patch.object(module, "git", side_effect=git),
                    patch.object(module, "command", side_effect=command),
                    patch.object(module, "input_manifest", return_value={"sha256": "same", "files": []}),
                    patch.object(module, "test_contract", return_value={}),
                    patch.object(module, "restore_fixture"),
                    patch.object(module, "release234_contract", return_value={}),
                    patch.object(module, "release234_seconds", return_value=10000),
                    patch.object(module, "validate_sample", return_value={}),
                    patch.object(module.platform, "system", return_value="Windows"),
                    patch.object(module.sys, "version_info", (3, 11)),
                    patch.dict(
                        os.environ,
                        {
                            **{key: "bound" for key in module.IDENTITY_KEYS},
                            "RUNNER_OS": "Windows",
                            "GITHUB_SHA": candidate,
                            "ALK_ACCOUNTING_GIT_EXECUTABLE": str(source / "selected backend.exe"),
                        },
                    ),
                ):
                    report = io.StringIO()
                    code = module.execute(args, report)
                value = json.loads(report.getvalue())
                self.assertEqual(code, 0 if benefit else 1, value.get("failure"))
                self.assertEqual(
                    [phase for _, _, phase in started[:8]], ["contract"] * 2 + ["regression"] * 2 + ["profile"] * 4
                )
                self.assertEqual(value["validationUnits"]["contractChildrenStarted"], 2)
                full = [(version, side) for version, side, phase in started if phase == "module"]
                self.assertEqual(
                    full, [(version, side) for version in ("11", "15") for side in module.ORDER] if benefit else []
                )
                self.assertEqual(value["validationUnits"]["moduleChildrenStarted"], 12 if benefit else 0)
                self.assertEqual(value["status"], "MEASURED_IMPROVEMENT" if benefit else "STOP_NO_PRELIMINARY_BENEFIT")


if __name__ == "__main__":
    unittest.main()

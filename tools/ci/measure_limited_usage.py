"""Measure three alternating serial hot-module pairs at exact Windows source SHAs."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
import platform
import re
import runpy
import statistics
import sys
import tempfile
import time
import traceback
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

BASELINE = "ec5d8e5b118dc8a7f86de3b683ff2ed9a20993e5"
RELEASE234_BASELINE = "e6cd9a0f3524b55a9197bc543d629b6bc2ed3fd2"
RELEASE234_DEADLINE = datetime(2026, 10, 31, 3, 37, 52, tzinfo=UTC)
RELEASE234_OWNED = frozenset(
    (
        ".github/workflows/ci-timing-control.yml",
        "src/agent_lifecycle/accounting/declared_ledger_legacy.py",
        "tests/accounting/test_declared_ledger.py",
        "tests/release/test_limited_usage_measurement.py",
        "tools/ci/measure_limited_usage.py",
    )
)
# AST prefix from this accepted commit's DeclaredFixture.__init__, before seed_path.
BASELINE_PREFIX_SHA256 = "704b517fcb7e82163e1feb9a41ae29318281da312cd454d2dc35eef4518b9791"
HOT_MODULE = "tests.workflow.test_limited_usage"
HOT_PATH = "tests/workflow/test_limited_usage.py"
MAX_BYTES = 8_388_608
SAMPLE_SECONDS = 2400
EXPERIMENT_SECONDS = 18_000
PROFILE_SECONDS = 1150
FEASIBILITY_SECONDS = 600
SLOW_CASE = "LimitedUsageTests.test_current_registry_capacity_preserves_large_original_interval"
ORDER = ("baseline", "candidate", "candidate", "baseline", "baseline", "candidate")
CLOCK_METHOD = "test_expired_admission_live_run_task_and_exact_deadline_refuse"
CLOCK_ID = f"{HOT_MODULE}.ProspectiveAdmissionProcedureTests.{CLOCK_METHOD}"
CLOCK_METHOD_SHA256 = "5a8e553113f598b415429e13bca8d75e50c390d02dcb6239aeba9f369b6a4aa6"
CLOCK_LOOP_SHA256 = "5bc591fa37ac1a27dedc4822fc55fca1e666597d069366050f8d24aaa6ceca89"
EXPERIMENT3_DEADLINE = datetime(2026, 10, 26, 16, 4, 34, tzinfo=UTC)
LINE_SELECTORS = {
    (
        f"{HOT_MODULE}.AccountingOnlyClockTests."
        "test_accounting_only_cannot_authorize_current_receipt_frontier_or_refresh"
    ): "consumer",
    f"{HOT_MODULE}.SourceConflictRecoveryTests.test_recovery_unknown_or_edited_disposition_denied": "mutation",
}
OWNED = frozenset(
    (
        f"{HOT_PATH} tests/workflow/limited_usage_fixture_support.py "
        "tests/release/test_parallel_unittest.py tests/release/test_limited_usage_measurement.py "
        "tools/ci/run_parallel_unittest.py tools/ci/measure_limited_usage.py .github/workflows/ci-timing-control.yml "
        "src/agent_lifecycle/contracts/authority_io.py tests/contracts/test_windows_authority_bindings.py"
    ).split()
)
ENV_KEYS = tuple(
    (
        "PATH SystemRoot SYSTEMROOT WINDIR COMSPEC PATHEXT HOME USERPROFILE "
        "APPDATA LOCALAPPDATA PROGRAMFILES GITHUB_SHA GITHUB_RUN_ID GITHUB_RUN_ATTEMPT "
        "GITHUB_JOB RUNNER_OS RUNNER_ARCH ImageOS ImageVersion"
    ).split()
)
IDENTITY_KEYS = tuple(
    ("GITHUB_SHA GITHUB_RUN_ID GITHUB_RUN_ATTEMPT GITHUB_JOB RUNNER_OS RUNNER_ARCH ImageOS ImageVersion").split()
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def reference(path):
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.write("\n")


def read_object(path):
    if path.is_symlink() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Unsafe or oversized measurement input")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Measurement object required")
    return value


def source_sha(value):
    if not isinstance(value, str) or re.fullmatch("[0-9a-f]{40}", value) is None:
        raise ValueError("Source ref must be a full lowercase 40-hex commit SHA")
    return value


def test_contract(root):
    """Bind the full module AST, allowing only the declared Git seed replacement."""
    tree = ast.parse((root / HOT_PATH).read_bytes())
    seed_import = ast.parse("from tests.workflow.limited_usage_fixture_support import install_git_seed").body[0]
    tree.body = [node for node in tree.body if ast.dump(node) != ast.dump(seed_import)]
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if isinstance(node, ast.ClassDef) and node.name == "DeclaredFixture":
                for method in node.body:
                    if isinstance(method, ast.FunctionDef) and method.name == "__init__":
                        boundary = next(
                            index
                            for index, statement in enumerate(method.body)
                            if isinstance(statement, ast.Assign)
                            and any(
                                isinstance(target, ast.Name) and target.id == "seed_path"
                                for target in statement.targets
                            )
                        )
                        prefix = digest([ast.dump(statement) for statement in method.body[:boundary]])
                        replacement = ast.parse("self.root = root\nself.revision = install_git_seed(root)").body
                        if prefix not in (BASELINE_PREFIX_SHA256, digest([ast.dump(item) for item in replacement])):
                            raise ValueError("Undeclared fixture initialization change")
                        method.body = [method.body[0], *method.body[boundary:]]
    if not any(isinstance(node, (ast.FunctionDef, ast.ClassDef)) for node in tree.body):
        raise ValueError("Hot module contract is empty")
    assertions = [
        ast.dump(node, include_attributes=False)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assert)
        or (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr.startswith("assert"))
    ]
    return {
        "testAndFixtureAstSha256": digest(ast.dump(tree, include_attributes=False)),
        "assertionAstSha256": digest(assertions),
        "assertionSites": len(assertions),
    }


def utc_datetime_repr(text):
    """Parse only the canonical UTC datetime repr produced by the bound test."""
    if not isinstance(text, str) or len(text) > 200:
        raise ValueError("Invalid UTC datetime label")
    try:
        value = ast.parse(text, mode="eval").body
        expected = ast.parse("datetime.datetime", mode="eval").body
        utc = ast.parse("datetime.timezone.utc", mode="eval").body
        if (
            not isinstance(value, ast.Call)
            or ast.dump(value.func) != ast.dump(expected)
            or not 5 <= len(value.args) <= 7
            or len(value.keywords) != 1
            or value.keywords[0].arg != "tzinfo"
            or ast.dump(value.keywords[0].value) != ast.dump(utc)
            or any(not isinstance(arg, ast.Constant) or type(arg.value) is not int for arg in value.args)
        ):
            raise ValueError("Unrecognized datetime expression")
        observed = datetime(*(arg.value for arg in value.args), tzinfo=UTC)
        if repr(observed) != text:
            raise ValueError("Datetime label is not canonical")
        return observed
    except (SyntaxError, TypeError, OverflowError) as exc:
        raise ValueError("Malformed UTC datetime label") from exc


def clock_ast_dump(value):
    """Keep the bound 3.11 shape, omitting only proven default schema fields."""
    if isinstance(value, ast.AST):
        fields = []
        for name, child in ast.iter_fields(value):
            if (
                (name != "is_lazy" and child is None and getattr(type(value), name, ...) is None)
                or (name == "type_params" and child == [])
                or (
                    name == "is_lazy"
                    and isinstance(value, (ast.Import, ast.ImportFrom))
                    and type(child) is int
                    and child == 0
                )
            ):
                continue
            fields.append(f"{name}={clock_ast_dump(child)}")
        return f"{type(value).__name__}({', '.join(fields)})"
    if isinstance(value, list):
        return "[" + ", ".join(clock_ast_dump(child) for child in value) + "]"
    return repr(value)


def canonical_clock_events(tree, events):
    """Normalize only the two exact, AST-bound deadline observations."""
    classes = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ProspectiveAdmissionProcedureTests"
    ]
    indices = [index for index, event in enumerate(events) if event["id"].split(" (", 1)[0] == CLOCK_ID]
    if any(" (observed=" in event["id"] and event["id"].split(" (", 1)[0] != CLOCK_ID for event in events):
        raise ValueError("Datetime observations occurred in an unexpected method")
    if not classes:
        if indices:
            raise ValueError("Clock events have no source method")
        return events
    methods = [node for node in classes[0].body if isinstance(node, ast.FunctionDef) and node.name == CLOCK_METHOD]
    if len(classes) != 1 or len(methods) != 1:
        raise ValueError("Clock method is missing or duplicated")
    method = methods[0]
    loops = [node for node in method.body if isinstance(node, ast.For)]
    if (
        hashlib.sha256(clock_ast_dump(method).encode()).hexdigest() != CLOCK_METHOD_SHA256
        or len(loops) != 1
        or hashlib.sha256(clock_ast_dump(loops[0]).encode()).hexdigest() != CLOCK_LOOP_SHA256
    ):
        raise ValueError("Clock method/loop AST changed")
    if len(indices) != 3 or indices != list(range(indices[0], indices[0] + 3)):
        raise ValueError("Clock events are missing, duplicated, extra or reordered")
    selected = [events[index] for index in indices]
    if (
        any(item["caseIndex"] != 46 for item in selected)
        or [item["outcome"] for item in selected] != ["subtest:success", "subtest:success", "success"]
        or selected[2]["id"] != CLOCK_ID
    ):
        raise ValueError("Clock case/order/outcomes changed")
    observed = []
    for item in selected[:2]:
        prefix = CLOCK_ID + " (observed="
        if not item["id"].startswith(prefix) or not item["id"].endswith(")"):
            raise ValueError("Clock parameters changed")
        observed.append(utc_datetime_repr(item["id"][len(prefix) : -1]))
    if observed[1] - observed[0] != timedelta(seconds=1):
        raise ValueError("Clock observations are not ordered one second apart")
    result = [dict(item) for item in events]
    for index, label in zip(indices[:2], ("deadline", "deadline+1s"), strict=True):
        result[index]["id"] = f"{CLOCK_ID} (observed={label})"
    return result


def canonical_events(root, events):
    """Join proven lambda selectors by AST when formatting changes source lines."""
    tree = ast.parse((root / HOT_PATH).read_bytes())
    selectors = {}
    for cls in (node for node in tree.body if isinstance(node, ast.ClassDef)):
        for method in (node for node in cls.body if isinstance(node, ast.FunctionDef)):
            for loop in (node for node in ast.walk(method) if isinstance(node, ast.For)):
                if not isinstance(loop.iter, ast.Tuple) or not all(
                    isinstance(node, ast.Lambda) for node in loop.iter.elts
                ):
                    continue
                for call in (node for node in ast.walk(loop) if isinstance(node, ast.Call)):
                    if not isinstance(call.func, ast.Attribute) or call.func.attr != "subTest":
                        continue
                    for keyword in call.keywords:
                        if (
                            isinstance(keyword.value, ast.Attribute)
                            and keyword.value.attr == "co_firstlineno"
                            and isinstance(keyword.value.value, ast.Attribute)
                            and keyword.value.value.attr == "__code__"
                            and isinstance(keyword.value.value.value, ast.Name)
                            and isinstance(loop.target, ast.Name)
                            and keyword.value.value.value.id == loop.target.id
                        ):
                            key = f"{HOT_MODULE}.{cls.name}.{method.name}"
                            if key in selectors or LINE_SELECTORS.get(key) != keyword.arg:
                                raise ValueError("Unrecognized source-line selector channel")
                            selectors[key] = keyword.arg, loop.iter.elts
    positions, result = {}, []
    for event in events:
        item = dict(event)
        base = item["id"].split(" (", 1)[0]
        if base in selectors and item["outcome"].startswith("subtest:"):
            parameter, choices = selectors[base]
            offset = positions.get(base, 0)
            if offset >= len(choices):
                raise ValueError("Unexpected source-line subtest selector")
            choice = choices[offset]
            pattern = rf"\b{parameter}=(\d+)\b"
            match = re.search(pattern, item["id"])
            if match is None or int(match[1]) != choice.lineno:
                raise ValueError("Subtest line label does not select the proven lambda")
            selector = digest({"parent": base, "lambdaAst": ast.dump(choice), "occurrence": offset})
            item["id"] = re.sub(pattern, f"{parameter}=ast:{selector}", item["id"])
            positions[base] = offset + 1
        result.append(item)
    if any(positions.get(base, 0) != len(choices) for base, (_, choices) in selectors.items()):
        raise ValueError("Missing source-line subtest selector outcomes")
    return canonical_clock_events(tree, result)


def input_manifest(root, names):
    items = []
    for name in names:
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name or not name:
            raise ValueError("Unsafe tracked input path")
        path = root / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError("Tracked input is not an ordinary contained file")
        items.append(
            {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
        )
    return {"files": items, "sha256": digest(items)}


def environment_identity():
    return {name: os.environ.get(name) for name in IDENTITY_KEYS}


def sanitized_environment(scratch):
    value = {name: os.environ[name] for name in ENV_KEYS if name in os.environ}
    value.update(
        TMP=str(scratch),
        TEMP=str(scratch),
        TMPDIR=str(scratch),
        PYTHONDONTWRITEBYTECODE="1",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
        GIT_NO_LAZY_FETCH="1",
    )
    return value


def command(argv, root, deadline, records, *, timeout=120, logs=None):
    from agent_lifecycle.changesets.git_io import BoundedProcess

    started = time.perf_counter()
    record = {
        "argv": argv,
        "cwd": str(root),
        "exitCode": None,
        "timeoutSeconds": min(timeout, deadline - time.monotonic()),
        "processStarted": None,
    }
    records.append(record)
    chunks, process = [], None
    try:
        process = BoundedProcess(
            argv,
            cwd=root,
            deadline=min(deadline, time.monotonic() + timeout),
            max_stdout_bytes=MAX_BYTES,
            max_stderr_bytes=MAX_BYTES,
        )
        record["processStarted"] = True
        while data := process.stdout.read(65536):
            chunks.append(data)
        record["exitCode"] = process.wait()
        if record["exitCode"]:
            raise ValueError("Measurement child command failed; retained exit and output hashes")
        return b"".join(chunks)
    except BaseException as exc:
        if (
            getattr(exc, "code", None)
            in ("bounded-process-timeout", "bounded-process-argv-invalid", "bounded-process-limit-invalid")
            and process is None
        ):
            record["processStarted"] = False
        record["transportError"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        cleanup_error = None
        if process is not None:
            process.fail("measurement-supervision-finished")
            try:
                process.close()
            except BaseException as exc:
                cleanup_error = exc
                record["cleanupError"] = f"{type(exc).__name__}: {exc}"
        stdout = b"".join(chunks)
        stderr = bytes(process.stderr) if process is not None else b""
        record.update(
            stdoutBytes=len(stdout),
            stderrBytes=len(stderr),
            stdoutSha256=hashlib.sha256(stdout).hexdigest(),
            stderrSha256=hashlib.sha256(stderr).hexdigest(),
        )
        if logs is not None:
            for name, data in (("stdout.log", stdout), ("stderr.log", stderr)):
                path = logs / name
                with path.open("xb") as stream:
                    stream.write(data)
                record[name] = reference(path)
        record["elapsedSeconds"] = time.perf_counter() - started
        if cleanup_error is not None:
            raise cleanup_error


def git(arguments, root, deadline, records):
    argv = ["git", *arguments]
    options = {"argv": argv, "environment": sanitized_environment(Path(tempfile.gettempdir()))}
    bootstrap = (
        "import json,subprocess,sys;v=json.loads(sys.argv[1]);"
        "sys.exit(subprocess.run(v['argv'],env=v['environment'],shell=False).returncode)"
    )
    try:
        return command([sys.executable, "-I", "-B", "-c", bootstrap, json.dumps(options)], root, deadline, records)
    finally:
        records[-1]["gitArgv"] = argv


def restore_fixture(root):
    import zipfile

    with zipfile.ZipFile(root / "fixtures/release-2-16-tests.zip") as archive:
        members = archive.infolist()
        if len(members) > 10000 or sum(entry.file_size for entry in members) > 67_108_864:
            raise ValueError("Fixture archive exceeds bounds")
        for entry in members:
            path = PurePosixPath(entry.filename)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in entry.filename
                or ":" in entry.filename
                or (entry.external_attr >> 16) & 0o170000 == 0o120000
            ):
                raise ValueError("Unsafe fixture archive member")
        archive.extractall(root / "tasks/release-2-16")


def sample(request_path):
    """Execute the original full module once, using only this checkout's imports."""
    request = read_object(request_path)
    root = Path(request["root"]).resolve(strict=True)
    output = Path(request["output"])
    head = root / ".git/HEAD"
    if head.is_symlink() or head.read_text(encoding="ascii").strip() != source_sha(request["sourceHead"]):
        raise ValueError("Sample requires the exact detached source commit")
    before = input_manifest(root, request["trackedInputs"])
    contract = test_contract(root)
    if before["sha256"] != request["inputSha256"] or (
        not request.get("contractOnly") and contract != request["testContract"]
    ):
        raise ValueError("Sample input or assertion contract differs")
    if request.get("contractOnly"):
        write_new(output, {"testContract": contract, "version": list(sys.version_info[:2])})
        return 0
    package = importlib.import_module("agent_lifecycle")
    if not Path(package.__file__).resolve().is_relative_to(root / "src"):
        raise ValueError("Sample imported a different installed runtime")
    serial = runpy.run_path(str(root / "tools/ci/run_unittest.py"))
    loader = unittest.TestLoader()
    started = time.perf_counter()
    selected = (
        "tests.accounting.test_declared_ledger.GitLaunchContractTests" if request.get("regressionOnly") else HOT_MODULE
    )
    suite = loader.loadTestsFromName(selected)
    roster = list(serial["inventory"](suite))
    if (
        loader.errors
        or not roster
        or len(roster) != request["expectedTests"]
        or any(
            item["module"] != selected.rsplit(".", 1)[0]
            if request.get("regressionOnly")
            else item["module"] != HOT_MODULE
            for item in roster
        )
    ):
        raise ValueError("Full hot-module roster differs or failed to load")
    args = argparse.Namespace(start=HOT_MODULE, top=".", pattern="test_limited_usage.py", worker_roster=None)
    with output.open("x+", encoding="utf-8") as stream:
        code = serial["run"](args, stream, prepared=(loader, suite, started))
    result = read_object(output)
    after = input_manifest(root, request["trackedInputs"])
    seed = sys.modules.get("tests.workflow.limited_usage_fixture_support")
    seed_seconds = None
    if seed is not None and seed.git_seed.cache_info().currsize:
        seed_seconds = seed.git_seed()[2]
    result.update(
        sourceHead=request["sourceHead"],
        inputSha256=before["sha256"],
        inputHashesUnchanged=before == after,
        testContract=request["testContract"],
        measurementEnvironment=environment_identity(),
        runtimeProvenance={
            "executable": sys.executable,
            "version": sys.version,
            "packageFile": str(Path(package.__file__).resolve()),
            "installedVersion": importlib.metadata.version("agent-lifecycle-kit"),
        },
        immutableGitSeedPreparationSeconds=seed_seconds,
        comparisonEvents=result["events"]
        if request.get("regressionOnly")
        else canonical_events(root, result["events"]),
    )
    if request.get("experiment") == 5:
        result["peakWorkingSet"] = process_peak()
        result["lockedEnvironment"] = locked_environment()
    if before != after:
        result.update(status="FAIL", inputMutation=True)
        code = 1
    # The original serial report exists before enrichment; atomicity is not claimed.
    with output.open("w", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return code


def profile_sample(request_path):
    """Profile the requested detached role without a whole-module performance verdict."""
    import cProfile
    import pstats

    request = read_object(request_path)
    root = Path(request["root"]).resolve(strict=True)
    expected = source_sha(request["sourceHead"])
    role = request["profileSourceRole"]
    baseline = RELEASE234_BASELINE if request.get("experiment") == 5 else BASELINE
    if (
        (root / ".git/HEAD").is_symlink()
        or (root / ".git/HEAD").read_text(encoding="ascii").strip() != expected
        or role not in ("baseline", "candidate")
        or (role == "baseline" and expected != baseline)
        or (role == "candidate" and (expected == baseline or expected != os.environ.get("GITHUB_SHA")))
    ):
        raise ValueError("Profile requires its exact detached baseline/candidate source role")
    before = input_manifest(root, request["trackedInputs"])
    if before["sha256"] != request["inputSha256"] or test_contract(root) != request["testContract"]:
        raise ValueError("Profile input or contract differs")
    package = importlib.import_module("agent_lifecycle")
    if not Path(package.__file__).resolve().is_relative_to(root / "src"):
        raise ValueError("Profile imported a different runtime")
    module = importlib.import_module(HOT_MODULE)
    calls = []

    def observe(event, arguments):
        if event == "subprocess.Popen":
            calls.append(list(arguments[1]))

    sys.addaudithook(observe)
    phases = []
    passed = True
    for phase in ("constructors", "slow-case"):
        profile = cProfile.Profile()
        offset, started = len(calls), time.perf_counter()
        profile.enable()
        if phase == "constructors":
            for _ in range(3):
                case = module.LimitedUsageTests(SLOW_CASE.split(".")[1])
                try:
                    case.setUp()
                finally:
                    case.doCleanups()
        else:
            suite = unittest.TestLoader().loadTestsFromName(f"{HOT_MODULE}.{SLOW_CASE}")
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            passed = result.wasSuccessful() and result.testsRun == 1
        profile.disable()
        elapsed = time.perf_counter() - started
        path = Path(request["output"]).with_name(phase + ".pstats")
        profile.dump_stats(str(path))
        stats = pstats.Stats(profile)
        rows = [
            {
                "file": key[0],
                "line": key[1],
                "name": key[2],
                "calls": value[1],
                "selfSeconds": value[2],
                "cumulativeSeconds": value[3],
            }
            for key, value in stats.stats.items()
        ]
        phases.append(
            {
                "phase": phase,
                "elapsedSeconds": elapsed,
                "subprocesses": calls[offset:],
                "profile": reference(path),
                "rows": sorted(rows, key=lambda row: -row["cumulativeSeconds"]),
            }
        )
    unchanged = input_manifest(root, request["trackedInputs"]) == before
    value = {
        "schemaVersion": "alk-limited-usage-profile.v1",
        "mode": request["profileMode"],
        "sourceRole": role,
        "status": "PROFILE_COMPLETE" if passed and unchanged else "FAIL",
        "sourceHead": expected,
        "inputSha256": before["sha256"],
        "inputHashesUnchanged": unchanged,
        "testContract": request["testContract"],
        "environment": environment_identity(),
        "python": sys.version,
        "runtimeProvenance": {
            "packageFile": str(Path(package.__file__).resolve()),
            "executable": sys.executable,
            "installedVersion": importlib.metadata.version("agent-lifecycle-kit"),
        },
        "phases": phases,
        "testId": f"{HOT_MODULE}.{SLOW_CASE}",
        "performanceAcceptanceClaimed": False,
        "actualTestsRun": 1,
        "actualFixtureSetUps": 4,
        "actualTokens": None,
        "actualCost": None,
    }
    if request.get("experiment") == 5:
        value["lockedEnvironment"] = locked_environment()
    write_new(Path(request["output"]), value)
    return 0 if value["status"] == "PROFILE_COMPLETE" else 1


def worker_argv(helper, request_path, root, scratch, *, executable=None, version=None):
    options = {
        "environment": sanitized_environment(scratch),
        "root": str(root),
        "helper": str(helper),
        "request": str(request_path),
        "version": version,
    }
    bootstrap = (
        "import json,os,runpy,sys;v=json.loads(sys.argv[1]);"
        "assert v['version'] is None or list(sys.version_info[:2])==v['version'];"
        "os.environ.clear();os.environ.update(v['environment']);os.chdir(v['root']);"
        "sys.path[:0]=[os.path.join(v['root'],'src'),v['root']];"
        "r=__import__('pathlib').Path(v['request']);"
        "q=json.loads(r.read_bytes());assert q.get('experiment')!=5 or "
        "(q.get('expectedVersion')==v['version'] and v['version'] in ([3,11],[3,15]));"
        "f='profile_sample' if q.get('profileOnly') else 'sample';"
        "sys.exit(runpy.run_path(v['helper'],run_name='alk_measurement_worker')[f](r))"
    )
    return [str(executable or sys.executable), "-I", "-B", "-c", bootstrap, json.dumps(options)]


def validate_sample(value, request):
    if (
        value.get("schemaVersion") != "alk-ci-test-timings.v1"
        or value.get("status") != "PASS"
        or value.get("sourceHead") != request["sourceHead"]
        or value.get("inputSha256") != request["inputSha256"]
        or value.get("testContract") != request["testContract"]
        or value.get("measurementEnvironment") != environment_identity()
        or not value.get("inputHashesUnchanged")
        or value.get("loaderErrors")
        or value.get("interrupted")
        or any(value.get(key) for key in ("errors", "failures", "unexpectedSuccesses"))
        or not value["coverage"]["complete"]
        or value["coverage"]["notStarted"]
        or value["testsRun"] != request["expectedTests"]
        or (request["expectedTests"] == 78 and (len(value["events"]) != 376 or len(value["comparisonEvents"]) != 376))
        or len(value["inventory"]) != request["expectedTests"]
        or len(value["cases"]) != request["expectedTests"]
        or [item["id"] for item in value["cases"]] != [item["id"] for item in value["inventory"]]
        or any(
            not item["completed"] or not math.isfinite(item["seconds"]) or item["seconds"] < 0
            for item in value["cases"]
        )
        or not math.isfinite(value["wallSeconds"])
        or value["wallSeconds"] <= 0
    ):
        raise ValueError("Incomplete, mutated, wrong-source or failing hot-module sample")
    if value["comparisonEvents"] != canonical_events(Path(request["root"]), value["events"]):
        raise ValueError("Canonical events differ from the preserved raw source-bound events")
    return {
        "inventory": value["inventory"],
        "events": value["comparisonEvents"],
        "skips": value["skips"],
        "expectedFailures": value["expectedFailures"],
        "testContract": value["testContract"],
        "python": value["python"],
        "platform": value["platform"],
        "environment": value["measurementEnvironment"],
    }


def compare_samples(samples):
    if len(samples) != 6 or tuple(item["side"] for item in samples) != ORDER:
        raise ValueError("Exactly three alternating A/B pairs required")
    if any(item["join"] != samples[0]["join"] for item in samples):
        raise ValueError("Roster, outcomes, skips, assertions, fixtures or environment differs")
    medians = {
        side: statistics.median(item["wallSeconds"] for item in samples if item["side"] == side)
        for side in ("baseline", "candidate")
    }
    ratios = []
    for offset in (0, 2, 4):
        pair = {item["side"]: item["wallSeconds"] for item in samples[offset : offset + 2]}
        ratios.append(pair["candidate"] / pair["baseline"])
    ratio = medians["candidate"] / medians["baseline"]
    return {
        "status": "MEASURED_IMPROVEMENT" if ratio <= 0.80 else "NO_IMPROVEMENT",
        "medianWallSeconds": medians,
        "candidateBaselineMedianRatio": ratio,
        "pairRatios": ratios,
        "medianPairRatio": statistics.median(ratios),
        "targetRatio": 0.80,
    }


def viability_prefix(samples, *, ratio_stop=True):
    """The prefix permits continuation only; it cannot establish a median verdict."""
    if len(samples) != 2 or tuple(item["side"] for item in samples) != ORDER[:2]:
        raise ValueError("Viability requires the first baseline/candidate full-module pair")
    if samples[0]["join"] != samples[1]["join"]:
        return {"status": "INCOMPLETE", "reason": "prefix-join-mismatch"}
    if any(not math.isfinite(item["wallSeconds"]) or item["wallSeconds"] <= 0 for item in samples):
        raise ValueError("Invalid viability wall time")
    ratio = samples[1]["wallSeconds"] / samples[0]["wallSeconds"]
    result = {
        "status": "PREFIX_ELIGIBLE_TO_CONTINUE" if ratio <= 0.80 else "INCOMPLETE",
        "candidateBaselineRatio": ratio,
        "targetRatio": 0.80,
        "performanceAcceptanceClaimed": False,
        "reason": "prefix-ratio",
    }
    if not ratio_stop:
        result.update(status="PREFIX_OBSERVED_ONLY", ratioGateEnforced=False)
    return result


def experiment3_seconds(deadline_text):
    if not isinstance(deadline_text, str) or re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", deadline_text) is None:
        raise ValueError("Experiment3 requires an explicit UTC absolute deadline")
    requested = datetime.strptime(deadline_text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    if requested > EXPERIMENT3_DEADLINE:
        raise ValueError("Experiment3 deadline exceeds the native authorized ceiling")
    remaining = (requested - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        raise ValueError("Experiment3 absolute deadline expired")
    return min(EXPERIMENT_SECONDS, remaining)


def release234_seconds(deadline_text):
    if not isinstance(deadline_text, str) or re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", deadline_text) is None:
        raise ValueError("Release234 requires the explicit native UTC task deadline")
    requested = datetime.strptime(deadline_text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    remaining = (requested - datetime.now(UTC)).total_seconds()
    if requested != RELEASE234_DEADLINE or not 0 < remaining <= 43200:
        raise ValueError("Release234 native task deadline differs, expired or exceeds twelve hours")
    return remaining


def release234_contract(roots, inputs):
    legacy = "src/agent_lifecycle/accounting/declared_ledger_legacy.py"
    maps = {side: {item["path"]: item["sha256"] for item in value["files"]} for side, value in inputs.items()}
    names = set(maps["baseline"]) | set(maps["candidate"])
    fixed = {name for name in names if name.startswith("src/") and name != legacy}
    fixed.update((HOT_PATH, "tests/workflow/limited_usage_fixture_support.py"))
    if any(maps["baseline"].get(name) != maps["candidate"].get(name) for name in fixed):
        raise ValueError("Release234 runtime, original tests or seed bytes changed")
    trees = {side: ast.parse((root / legacy).read_bytes()) for side, root in roots.items()}
    method = next(
        node for node in trees["candidate"].body if isinstance(node, ast.FunctionDef) and node.name == "_r11_git"
    )
    calls = [
        node for node in ast.walk(method) if isinstance(node, ast.Call) and ast.unparse(node.func) == "subprocess.run"
    ]
    expected = ast.parse("subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0", mode="eval").body
    flags = [key for call in calls for key in call.keywords if key.arg == "creationflags"]
    if len(calls) != 1 or len(flags) != 1 or ast.dump(flags[0].value) != ast.dump(expected):
        raise ValueError("Release234 requires only the exact Git creationflags candidate")
    calls[0].keywords.remove(flags[0])
    if ast.dump(trees["baseline"]) != ast.dump(trees["candidate"]):
        raise ValueError("Release234 legacy AST changed outside the exact creationflags keyword")
    return {"unchangedFiles": len(fixed), "normalizedLegacyAstSha256": digest(ast.dump(trees["baseline"]))}


def release234_comparison(samples):
    compare_samples(samples)  # Retain the exact six-sample order and complete outcome join guards.
    base = [item["wallSeconds"] for item in samples if item["side"] == "baseline"]
    candidate = statistics.median(item["wallSeconds"] for item in samples if item["side"] == "candidate")
    median = statistics.median(base)
    mad = statistics.median(abs(value - median) for value in base)
    gain, threshold = 1 - candidate / median, max(0.05, mad / median)
    return {
        "status": "MEASURED_IMPROVEMENT" if candidate < median * (1 - threshold) else "STOP_NO_BENEFIT",
        "medianWallSeconds": {"baseline": median, "candidate": candidate},
        "baselineMadSeconds": mad,
        "relativeGain": gain,
        "requiredRelativeGainExclusive": threshold,
    }


def locked_environment():
    return {
        "executable": sys.executable,
        "python": sys.version,
        "platform": platform.platform(),
        "logicalCPUs": os.cpu_count(),
        "processor": platform.processor(),
        "packages": sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions()),
    }


def process_peak():
    """Observe only this worker's PeakWorkingSetSize; failure is unavailable."""
    value = {"scope": "worker-process-only", "bytes": None, "status": "UNAVAILABLE"}
    if sys.platform != "win32":
        return value
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t)
                for name in (
                    "PeakWorkingSetSize WorkingSetSize QuotaPeakPagedPoolUsage QuotaPagedPoolUsage "
                    "QuotaPeakNonPagedPoolUsage QuotaNonPagedPoolUsage PagefileUsage PeakPagefileUsage"
                ).split()
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel, psapi = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise OSError(ctypes.get_last_error())
        value.update(bytes=int(counters.PeakWorkingSetSize), status="OBSERVED")
    except (OSError, AttributeError, ValueError) as exc:
        value["failure"] = f"{type(exc).__name__}: {exc}"
    return value


def measurement_child(args, payload, sources, output, selection, deadline, limit):
    roots, inputs, contracts = sources
    folder, directory = output
    number, version, side, phase, executable = selection
    release234, profile_mode = args.experiment == 5, phase == "profile"
    records, samples = payload["commands"], payload["samples"]
    root = roots[side]
    destination = folder / str(number)
    destination.mkdir()
    scratch = Path(directory).resolve() / f"scratch-{number}"
    scratch.mkdir()
    request = {
        "root": str(root),
        "output": str(destination / "test-timings.json"),
        "sourceHead": args.baseline if side == "baseline" else args.candidate,
        "trackedInputs": [item["path"] for item in inputs[side]["files"]],
        "inputSha256": inputs[side]["sha256"],
        "testContract": contracts[version] if release234 and phase != "contract" else contracts[side],
        "expectedTests": 5 if phase == "regression" else 78,
        "profileOnly": profile_mode,
        "profileSourceRole": side,
        "profileMode": payload["mode"],
        "experiment": args.experiment,
        "regressionOnly": phase == "regression",
        "contractOnly": phase == "contract",
        "expectedVersion": [3, int(version[1:])] if release234 else None,
    }
    request_path = destination / "request.json"
    write_new(request_path, request)
    argv = worker_argv(
        Path(__file__).resolve(),
        request_path,
        root,
        scratch,
        executable=executable,
        version=request["expectedVersion"],
    )
    counter = {
        "contract": "contractChildrenStarted",
        "profile": "profileChildrenStarted",
        "regression": "regressionChildrenStarted",
        "module": "moduleChildrenStarted",
    }[phase]
    payload["validationUnits"].setdefault(counter, 0)
    try:
        command(
            argv,
            root,
            deadline,
            records,
            timeout=min(limit if profile_mode else SAMPLE_SECONDS, deadline - time.monotonic()),
            logs=destination,
        )
    finally:
        if records[-1]["processStarted"] is True:
            payload["validationUnits"][counter] += 1
        elif records[-1]["processStarted"] is None:
            payload["validationUnits"]["unknownChildStartHolds"] += 1
        payload["validationUnits"]["setupCommands"] = sum("gitArgv" in item for item in records)
    value = read_object(destination / "test-timings.json")
    if phase == "contract":
        if (
            value["version"] != request["expectedVersion"]
            or input_manifest(root, request["trackedInputs"])["sha256"] != request["inputSha256"]
        ):
            raise ValueError("Wrong-interpreter or mutated-input contract probe")
        contracts[version] = value["testContract"]
        payload.setdefault("versionTestContracts", {})[version] = value
        return False
    if profile_mode:
        if (
            value["status"] != "PROFILE_COMPLETE"
            or value["sourceHead"] != request["sourceHead"]
            or value["sourceRole"] != side
            or value["mode"] != payload["mode"]
            or value["testContract"] != request["testContract"]
            or value["testId"] != f"{HOT_MODULE}.{SLOW_CASE}"
            or (not release234 and value["python"] != sys.version)
            or value["inputSha256"] != request["inputSha256"]
            or value["environment"] != environment_identity()
            or not value["inputHashesUnchanged"]
            or value["performanceAcceptanceClaimed"]
            or (release234 and Path(value["runtimeProvenance"]["executable"]).resolve() != executable.resolve())
        ):
            raise ValueError("Incomplete or wrong-source feasibility profile")
        if release234 and value["lockedEnvironment"] != payload["versions"][version]["lockedEnvironment"]:
            raise ValueError("Release234 profile locked environment differs")
        profile = {
            "side": side,
            "sourceHead": request["sourceHead"],
            "report": reference(destination / "test-timings.json"),
            "inputSha256": request["inputSha256"],
        }
        if release234:
            profile.update(
                version=version,
                lockedEnvironment=value["lockedEnvironment"],
                commonCaseSeconds=next(p["elapsedSeconds"] for p in value["phases"] if p["phase"] == "slow-case"),
            )
        payload["profiles"].append(profile)
        return False
    if release234:
        provenance = value["runtimeProvenance"]
        if Path(provenance["executable"]).resolve() != executable.resolve():
            raise ValueError("Release234 worker executable differs")
        identity = value["lockedEnvironment"]
        if version in payload["versions"] and payload["versions"][version]["lockedEnvironment"] != identity:
            raise ValueError("Release234 locked environment changed between workloads")
        payload["versions"].setdefault(
            version,
            {"lockedEnvironment": identity},
        )
    if phase == "regression":
        if value["status"] != "PASS" or value["testsRun"] != 5 or not value["inputHashesUnchanged"]:
            raise ValueError("Actual Windows Git launch/timeout/own-child safety unresolved")
        payload.setdefault("regressions", []).append(
            {"version": version, "report": reference(destination / "test-timings.json")}
        )
        return False
    join = validate_sample(value, request)
    samples.append(
        {
            "side": side,
            "pair": (len(samples) % 6 + 2) // 2,
            **({"version": version} if release234 else {}),
            "sourceHead": request["sourceHead"],
            "wallSeconds": value["wallSeconds"],
            "join": join,
            "immutableGitSeedPreparationSeconds": value["immutableGitSeedPreparationSeconds"],
            "report": reference(destination / "test-timings.json"),
        }
    )
    if git(["status", "--porcelain", "--untracked-files=all"], root, deadline, records):
        raise ValueError("Sample mutated its isolated source checkout")
    if args.experiment in (3, 4) and len(samples) == 2:
        payload["viabilityPrefix"] = viability_prefix(samples, ratio_stop=args.experiment == 3)
        if payload["viabilityPrefix"]["status"] == "INCOMPLETE":
            payload["status"] = "INCOMPLETE"
            return True
    return False


def execute(args, report):
    started = time.perf_counter()
    release234 = args.experiment == 5
    profile_mode = args.mode in ("profile", "feasibility")
    limit = (
        FEASIBILITY_SECONDS if args.mode == "feasibility" else PROFILE_SECONDS if profile_mode else EXPERIMENT_SECONDS
    )
    deadline = time.monotonic() + limit
    source = Path.cwd().resolve()
    records, samples = [], []
    payload = {
        "schemaVersion": "alk-limited-usage-comparison.v1",
        "status": "RUNNING",
        "baseline": args.baseline,
        "candidate": args.candidate,
        "experiment": args.experiment,
        "mode": {"profile": "PROFILE_ONLY", "feasibility": "PROFILE_FEASIBILITY", "paired": "PAIRED_COMPARISON"}[
            args.mode
        ],
        "profiles": [],
        "environment": environment_identity(),
        "python": sys.version,
        "samples": samples,
        "commands": records,
        "actualTokens": None,
        "actualCost": None,
        "sampleTimeoutSeconds": SAMPLE_SECONDS,
        "experimentTimeoutSeconds": limit,
        "performanceAcceptanceClaimed": False,
        "validationUnits": {
            "outer": 1,
            "moduleChildrenStarted": 0,
            "profileChildrenStarted": 0,
            "unknownChildStartHolds": 0,
        },
    }
    try:
        baseline = RELEASE234_BASELINE if release234 else BASELINE
        if (
            args.baseline != baseline
            or source_sha(args.candidate) == baseline
            or args.experiment not in (1, 2, 3, 4, 5)
        ):
            raise ValueError("Exact accepted baseline and a declared candidate experiment required")
        if args.experiment in (3, 4):
            if args.mode != "paired":
                raise ValueError("Experiment3 permits no additional profiles")
            limit = experiment3_seconds(args.deadline_utc)
            deadline = min(deadline, time.monotonic() + limit)
            payload.update(absoluteDeadlineUtc=args.deadline_utc, experimentTimeoutSeconds=limit)
        if release234:
            if args.mode != "paired":
                raise ValueError("Release234 permits only the gated paired route")
            limit = min(20700, release234_seconds(args.deadline_utc) - 900)
            if limit <= 0:
                raise ValueError("Release234 closeout reserve reached")
            deadline = time.monotonic() + limit
            payload.update(absoluteDeadlineUtc=args.deadline_utc, experimentTimeoutSeconds=limit, versions={})
            payload["gitVersion"] = git(["--version"], source, deadline, records).decode().strip()
        source_sha(args.baseline)
        if (
            platform.system() != "Windows"
            or sys.version_info[:2] not in (((3, 11), (3, 15)) if release234 else ((3, 11),))
            or os.environ.get("RUNNER_OS") != "Windows"
            or any(not os.environ.get(name) for name in IDENTITY_KEYS)
        ):
            raise ValueError("Performance proof requires real Windows Actions/image/Python 3.11 identity")
        if (
            git(["rev-parse", "HEAD"], source, deadline, records).decode().strip() != args.candidate
            or os.environ["GITHUB_SHA"] != args.candidate
            or git(["status", "--porcelain", "--untracked-files=all"], source, deadline, records)
        ):
            raise ValueError("Coordinator must be the exact clean dispatched candidate commit")
        changed = (
            git(["diff", "--name-only", args.baseline, args.candidate, "--"], source, deadline, records)
            .decode()
            .splitlines()
        )
        if not changed or set(changed) - (RELEASE234_OWNED if release234 else OWNED):
            raise ValueError("Candidate changes exceed the exact WS-01 ownership boundary")
        folder = Path(args.out).resolve().with_suffix("")
        folder.mkdir()
        payload["helper"] = reference(Path(__file__).resolve())
        payload["changedPaths"] = changed
        with tempfile.TemporaryDirectory(prefix="alk-limited-pairs-") as directory:
            roots, inputs, contracts = {}, {}, {}
            sources = [("baseline", args.baseline)]
            if args.mode != "profile":
                sources.append(("candidate", args.candidate))
            for side, sha in sources:
                root = Path(directory).resolve() / side
                git(
                    ["clone", "--quiet", "--no-hardlinks", "--no-checkout", str(source), str(root)],
                    source,
                    deadline,
                    records,
                )
                git(["checkout", "--quiet", "--detach", sha], root, deadline, records)
                if git(["rev-parse", "HEAD"], root, deadline, records).decode().strip() != sha:
                    raise ValueError("Isolated checkout source differs")
                names = git(["ls-files", "-z"], root, deadline, records).decode().strip("\0").split("\0")
                inputs[side] = input_manifest(root, names)
                materialization = []
                for name in (".gitattributes", HOT_PATH, "src/agent_lifecycle/contracts/authority_io.py"):
                    raw_blob = git(["show", sha + ":" + name], root, deadline, records)
                    raw_file = (root / name).read_bytes()
                    materialization.append(
                        {
                            "path": name,
                            "sourceHead": sha,
                            "gitBlobSha256": hashlib.sha256(raw_blob).hexdigest(),
                            "gitBlobBytes": len(raw_blob),
                            "worktree": reference(root / name),
                            "blobCRLF": raw_blob.count(b"\r\n"),
                            "worktreeCRLF": raw_file.count(b"\r\n"),
                            "worktreeLF": raw_file.count(b"\n"),
                            "normalized": False,
                        }
                    )
                inputs[side]["materialization"] = materialization
                contracts[side] = test_contract(root)
                roots[side] = root
                restore_fixture(root)
                write_new(folder / f"{side}-inputs.json", inputs[side])
            if args.mode != "profile" and contracts["baseline"] != contracts["candidate"]:
                raise ValueError("Existing tests, assertions or post-initialization fixture behavior changed")
            if release234:
                payload["runtimeContract"] = release234_contract(roots, inputs)
            payload["testContract"] = contracts["baseline"]
            payload["setupSeconds"] = time.perf_counter() - started
            order = (
                ("baseline", "candidate") if args.mode == "feasibility" else ("baseline",) if profile_mode else ORDER
            )
            executions = [(None, side, "profile" if profile_mode else "module") for side in order]
            if release234:
                versions = ("311", "315")
                executions = [(v, "baseline", "contract") for v in versions]
                executions += [(v, "candidate", "regression") for v in versions]
                executions += [(v, side, "profile") for v in versions for side in ("baseline", "candidate")]
                executions += [(v, side, "module") for v in versions for side in ORDER]
            for number, (version, side, phase) in enumerate(executions, 1):
                if release234 and number == 9:
                    screens = {
                        v: [p["commonCaseSeconds"] for p in payload["profiles"] if p["version"] == v] for v in versions
                    }
                    payload["preliminary"] = {
                        v: {"relativeGain": 1 - t[1] / t[0], "passed": t[1] / t[0] <= 0.95} for v, t in screens.items()
                    }
                    if not all(item["passed"] for item in payload["preliminary"].values()):
                        payload.update(status="STOP_NO_PRELIMINARY_BENEFIT", stopBeforeFullSamples=True)
                        break
                executable = (
                    source / f"work/ci/release234-py{version}/Scripts/python.exe"
                    if release234
                    else Path(sys.executable)
                )
                if release234 and (not executable.is_file() or executable.is_symlink()):
                    raise ValueError("Release234 requires both internally located locked Python environments")
                if measurement_child(
                    args,
                    payload,
                    (roots, inputs, contracts),
                    (folder, directory),
                    (number, version, side, phase, executable),
                    deadline,
                    limit,
                ):
                    break
            if release234:
                if len(samples) == 12:
                    for version in versions:
                        payload["versions"][version].update(
                            release234_comparison([s for s in samples if s["version"] == version])
                        )
                    passed = all(v["status"] == "MEASURED_IMPROVEMENT" for v in payload["versions"].values())
                    payload.update(
                        status="MEASURED_IMPROVEMENT" if passed else "STOP_NO_BENEFIT",
                        performanceAcceptanceClaimed=passed,
                    )
            elif args.mode == "paired":
                if payload["status"] != "INCOMPLETE":
                    payload.update(compare_samples(samples))
                    payload["performanceAcceptanceClaimed"] = payload["status"] == "MEASURED_IMPROVEMENT"
            elif len(payload["profiles"]) == len(order):
                payload["status"] = "FEASIBILITY_COMPLETE" if args.mode == "feasibility" else "PROFILE_COMPLETE"
    except BaseException as exc:
        payload.update(
            status="STOP_UNRESOLVED" if release234 else "INCOMPLETE" if args.experiment in (3, 4) else "FAIL",
            failure=f"{type(exc).__name__}: {exc}",
        )
        traceback.print_exc()
    payload["totalSeconds"] = time.perf_counter() - started
    payload["validationUnits"]["setupCommands"] = sum("gitArgv" in item for item in records)
    payload["validationUnits"]["total"] = (
        1
        + payload["validationUnits"]["moduleChildrenStarted"]
        + payload["validationUnits"]["profileChildrenStarted"]
        + payload["validationUnits"].get("regressionChildrenStarted", 0)
        + payload["validationUnits"].get("contractChildrenStarted", 0)
        + payload["validationUnits"]["unknownChildStartHolds"]
    )
    if payload["totalSeconds"] > limit:
        payload.update(
            status="STOP_UNRESOLVED" if release234 else "INCOMPLETE" if args.experiment in (3, 4) else "FAIL",
            failure="Experiment deadline exceeded; partial evidence retained",
        )
    json.dump(payload, report, sort_keys=True, allow_nan=False)
    report.write("\n")
    return 0 if payload["status"] in ("MEASURED_IMPROVEMENT", "PROFILE_COMPLETE", "FEASIBILITY_COMPLETE") else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=source_sha)
    parser.add_argument("--candidate", required=True, type=source_sha)
    parser.add_argument("--experiment", required=True, type=int, choices=(1, 2, 3, 4, 5))
    parser.add_argument("--deadline-utc")
    parser.add_argument("--mode", choices=("paired", "profile", "feasibility"), default="paired")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    output = Path(args.out)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as report:
            return execute(args, report)
    except (OSError, ValueError) as exc:
        print(f"Measurement refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

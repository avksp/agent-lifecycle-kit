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
from pathlib import Path, PurePosixPath

BASELINE = "ec5d8e5b118dc8a7f86de3b683ff2ed9a20993e5"
# AST prefix from this accepted commit's DeclaredFixture.__init__, before seed_path.
BASELINE_PREFIX_SHA256 = "704b517fcb7e82163e1feb9a41ae29318281da312cd454d2dc35eef4518b9791"
HOT_MODULE = "tests.workflow.test_limited_usage"
HOT_PATH = "tests/workflow/test_limited_usage.py"
MAX_BYTES = 8_388_608
SAMPLE_SECONDS = 2400
EXPERIMENT_SECONDS = 18_000
PROFILE_SECONDS = 1150
SLOW_CASE = "LimitedUsageTests.test_current_registry_capacity_preserves_large_original_interval"
ORDER = ("baseline", "candidate", "candidate", "baseline", "baseline", "candidate")
LINE_SELECTORS = {
    (
        f"{HOT_MODULE}.AccountingOnlyClockTests."
        "test_accounting_only_cannot_authorize_current_receipt_frontier_or_refresh"
    ): "consumer",
    f"{HOT_MODULE}.SourceConflictRecoveryTests.test_recovery_unknown_or_edited_disposition_denied": "mutation",
}
OWNED = frozenset(
    (
        HOT_PATH,
        "tests/workflow/limited_usage_fixture_support.py",
        "tests/release/test_parallel_unittest.py",
        "tests/release/test_limited_usage_measurement.py",
        "tools/ci/run_parallel_unittest.py",
        "tools/ci/measure_limited_usage.py",
        ".github/workflows/ci-timing-control.yml",
    )
)
ENV_KEYS = (
    "PATH",
    "SystemRoot",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMFILES",
    "GITHUB_SHA",
    "GITHUB_RUN_ID",
    "GITHUB_RUN_ATTEMPT",
    "GITHUB_JOB",
    "RUNNER_OS",
    "RUNNER_ARCH",
    "ImageOS",
    "ImageVersion",
)
IDENTITY_KEYS = (
    "GITHUB_SHA",
    "GITHUB_RUN_ID",
    "GITHUB_RUN_ATTEMPT",
    "GITHUB_JOB",
    "RUNNER_OS",
    "RUNNER_ARCH",
    "ImageOS",
    "ImageVersion",
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
    return result


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
        while data := process.stdout.read(65536):
            chunks.append(data)
        record["exitCode"] = process.wait()
        if record["exitCode"]:
            raise ValueError("Measurement child command failed; retained exit and output hashes")
        return b"".join(chunks)
    except BaseException as exc:
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
    bootstrap = "import json,os,sys;v=json.loads(sys.argv[1]);os.execvpe(v['argv'][0],v['argv'],v['environment'])"
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
    if before["sha256"] != request["inputSha256"] or test_contract(root) != request["testContract"]:
        raise ValueError("Sample input or assertion contract differs")
    package = importlib.import_module("agent_lifecycle")
    if not Path(package.__file__).resolve().is_relative_to(root / "src"):
        raise ValueError("Sample imported a different installed runtime")
    serial = runpy.run_path(str(root / "tools/ci/run_unittest.py"))
    loader = unittest.TestLoader()
    started = time.perf_counter()
    suite = loader.loadTestsFromName(HOT_MODULE)
    roster = list(serial["inventory"](suite))
    if (
        loader.errors
        or not roster
        or len(roster) != request["expectedTests"]
        or any(item["module"] != HOT_MODULE for item in roster)
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
        comparisonEvents=canonical_events(root, result["events"]),
    )
    if before != after:
        result.update(status="FAIL", inputMutation=True)
        code = 1
    # The original serial report exists before enrichment; atomicity is not claimed.
    with output.open("w", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return code


def profile_sample(request_path):
    """Feasibility evidence on the unchanged baseline; no A/B performance verdict."""
    import cProfile
    import pstats

    request = read_object(request_path)
    root = Path(request["root"]).resolve(strict=True)
    if (
        (root / ".git/HEAD").is_symlink()
        or (root / ".git/HEAD").read_text(encoding="ascii").strip() != BASELINE
        or request["sourceHead"] != BASELINE
    ):
        raise ValueError("Profile requires the exact detached accepted baseline")
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
        "mode": "PROFILE_ONLY",
        "status": "PROFILE_COMPLETE" if passed and unchanged else "FAIL",
        "sourceHead": BASELINE,
        "inputSha256": before["sha256"],
        "inputHashesUnchanged": unchanged,
        "testContract": request["testContract"],
        "environment": environment_identity(),
        "python": sys.version,
        "phases": phases,
        "testId": f"{HOT_MODULE}.{SLOW_CASE}",
        "performanceAcceptanceClaimed": False,
        "actualTestsRun": 1,
        "actualFixtureSetUps": 4,
        "actualTokens": None,
        "actualCost": None,
    }
    write_new(Path(request["output"]), value)
    return 0 if value["status"] == "PROFILE_COMPLETE" else 1


def worker_argv(helper, request_path, root, scratch):
    options = {
        "environment": sanitized_environment(scratch),
        "root": str(root),
        "helper": str(helper),
        "request": str(request_path),
    }
    bootstrap = (
        "import json,os,runpy,sys;v=json.loads(sys.argv[1]);"
        "os.environ.clear();os.environ.update(v['environment']);os.chdir(v['root']);"
        "sys.path[:0]=[os.path.join(v['root'],'src'),v['root']];"
        "r=__import__('pathlib').Path(v['request']);"
        "f='profile_sample' if json.loads(r.read_bytes()).get('profileOnly') else 'sample';"
        "sys.exit(runpy.run_path(v['helper'],run_name='alk_measurement_worker')[f](r))"
    )
    return [sys.executable, "-I", "-B", "-c", bootstrap, json.dumps(options)]


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


def execute(args, report):
    started = time.perf_counter()
    limit = PROFILE_SECONDS if args.mode == "profile" else EXPERIMENT_SECONDS
    deadline = time.monotonic() + limit
    source = Path.cwd().resolve()
    records, samples = [], []
    payload = {
        "schemaVersion": "alk-limited-usage-comparison.v1",
        "status": "RUNNING",
        "baseline": args.baseline,
        "candidate": args.candidate,
        "experiment": args.experiment,
        "mode": "PROFILE_ONLY" if args.mode == "profile" else "PAIRED_COMPARISON",
        "environment": environment_identity(),
        "python": sys.version,
        "samples": samples,
        "commands": records,
        "actualTokens": None,
        "actualCost": None,
        "sampleTimeoutSeconds": SAMPLE_SECONDS,
        "experimentTimeoutSeconds": limit,
        "performanceAcceptanceClaimed": False,
        "validationUnits": {"outer": 1, "moduleChildrenStarted": 0, "profileChildrenStarted": 0},
    }
    try:
        if args.baseline != BASELINE or source_sha(args.candidate) == BASELINE or args.experiment not in (1, 2):
            raise ValueError("Exact accepted baseline and one of two candidate experiments required")
        source_sha(args.baseline)
        if (
            platform.system() != "Windows"
            or sys.version_info[:2] != (3, 11)
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
        if not changed or set(changed) - OWNED:
            raise ValueError("Candidate changes exceed the exact WS-01 ownership boundary")
        folder = Path(args.out).resolve().with_suffix("")
        folder.mkdir()
        helper = Path(__file__).resolve()
        payload["helper"] = reference(helper)
        payload["changedPaths"] = changed
        with tempfile.TemporaryDirectory(prefix="alk-limited-pairs-") as directory:
            roots, inputs, contracts = {}, {}, {}
            sources = [("baseline", args.baseline)]
            if args.mode == "paired":
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
                contracts[side] = test_contract(root)
                roots[side] = root
                restore_fixture(root)
                write_new(folder / f"{side}-inputs.json", inputs[side])
            if args.mode == "paired" and contracts["baseline"] != contracts["candidate"]:
                raise ValueError("Existing tests, assertions or post-initialization fixture behavior changed")
            payload["testContract"] = contracts["baseline"]
            payload["setupSeconds"] = time.perf_counter() - started
            order = ("baseline",) if args.mode == "profile" else ORDER
            for number, side in enumerate(order, 1):
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
                    "testContract": contracts[side],
                    "expectedTests": 78,
                    "profileOnly": args.mode == "profile",
                }
                request_path = destination / "request.json"
                write_new(request_path, request)
                argv = worker_argv(helper, request_path, root, scratch)
                counter = "profileChildrenStarted" if args.mode == "profile" else "moduleChildrenStarted"
                payload["validationUnits"][counter] += 1
                try:
                    command(
                        argv,
                        root,
                        deadline,
                        records,
                        timeout=PROFILE_SECONDS if args.mode == "profile" else SAMPLE_SECONDS,
                        logs=destination,
                    )
                finally:
                    payload["validationUnits"]["setupCommands"] = sum("gitArgv" in item for item in records)
                value = read_object(destination / "test-timings.json")
                if args.mode == "profile":
                    if (
                        value["status"] != "PROFILE_COMPLETE"
                        or value["sourceHead"] != args.baseline
                        or value["inputSha256"] != request["inputSha256"]
                        or value["environment"] != environment_identity()
                        or not value["inputHashesUnchanged"]
                        or value["performanceAcceptanceClaimed"]
                    ):
                        raise ValueError("Incomplete or wrong-source feasibility profile")
                    payload.update(status="PROFILE_COMPLETE", profile=reference(destination / "test-timings.json"))
                    continue
                join = validate_sample(value, request)
                samples.append(
                    {
                        "side": side,
                        "pair": (number + 1) // 2,
                        "sourceHead": request["sourceHead"],
                        "wallSeconds": value["wallSeconds"],
                        "join": join,
                        "immutableGitSeedPreparationSeconds": value["immutableGitSeedPreparationSeconds"],
                        "report": reference(destination / "test-timings.json"),
                    }
                )
                if git(["status", "--porcelain", "--untracked-files=all"], root, deadline, records):
                    raise ValueError("Sample mutated its isolated source checkout")
            if args.mode == "paired":
                payload.update(compare_samples(samples))
                payload["performanceAcceptanceClaimed"] = payload["status"] == "MEASURED_IMPROVEMENT"
    except BaseException as exc:
        payload.update(status="FAIL", failure=f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
    payload["totalSeconds"] = time.perf_counter() - started
    payload["validationUnits"]["setupCommands"] = sum("gitArgv" in item for item in records)
    payload["validationUnits"]["total"] = (
        1 + payload["validationUnits"]["moduleChildrenStarted"] + payload["validationUnits"]["profileChildrenStarted"]
    )
    if payload["totalSeconds"] > limit:
        payload.update(status="FAIL", failure="Experiment deadline exceeded; partial evidence retained")
    json.dump(payload, report, sort_keys=True, allow_nan=False)
    report.write("\n")
    return 0 if payload["status"] in ("MEASURED_IMPROVEMENT", "PROFILE_COMPLETE") else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=source_sha)
    parser.add_argument("--candidate", required=True, type=source_sha)
    parser.add_argument("--experiment", required=True, type=int, choices=(1, 2))
    parser.add_argument("--mode", choices=("paired", "profile"), default="paired")
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

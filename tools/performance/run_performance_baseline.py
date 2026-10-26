"""Collect bounded, revision-bound performance evidence without model calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from statistics import median
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.authority_io import open_authority_read
from agent_lifecycle.contracts.canonical import write_json_replace_private
from agent_lifecycle.contracts.performance_limits import validate_performance_policy

BASELINE_SCHEMA = "agent-performance-baseline.v1"
_CHUNK_BYTES = 8192
LIFECYCLE_OPERATIONS = (
    "workflow-status-small",
    "workflow-status-growing",
    "accounting-read-small",
    "accounting-read-growing",
)
METRIC_DEFINITIONS = {
    "wallSeconds": "entire subprocess, or in-process digest",
    "operationWallSeconds": "named lifecycle read and its validation",
    "setupWallSeconds": "private fixture and preflight validation",
    "subprocessOverheadSeconds": "subprocess wall minus worker wall",
    "p50": "statistics.median",
    "p95": "nearest-rank, descriptive sample only",
    "rss": "process high-water mark, null when unavailable",
}


def collect_baseline(*, policy_path: Path, repository_root: Path, output_path: Path) -> dict[str, Any]:
    """Run the closed benchmark set and return a redacted evidence document."""

    started = time.monotonic()
    blockers: list[dict[str, Any]] = []
    body: dict[str, Any]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        policy = read_json_object(policy_path, label="performance policy")
        limits = validate_performance_policy(policy)
        deadline = started + int(policy["benchmark"]["maxTotalWallSeconds"])
        inputs = source_identity(repository_root, deadline=deadline)
        source_revision = _git_revision(repository_root)
        dirty = _git_dirty(repository_root)
        benchmark = policy["benchmark"]
        samples = int(benchmark["samplesPerCase"])
        warmups = int(benchmark["warmupSamples"])
        with tempfile.TemporaryDirectory(prefix="alk-performance-", dir=output_path.parent) as temporary:
            operations = _operation_specs(repository_root, Path(temporary), policy["operations"])
            results = []
            for operation in operations:
                if time.monotonic() >= deadline:
                    blockers.append({"code": "performance-total-deadline-exceeded", "operation": operation["id"]})
                    break
                result = _measure_operation(
                    operation,
                    repository_root=repository_root,
                    warmups=warmups,
                    samples=samples,
                    command_timeout=int(benchmark["maxCommandWallSeconds"]),
                    max_output_bytes=min(int(benchmark["maxOutputBytes"]), limits.max_benchmark_output_bytes),
                    deadline=deadline,
                )
                results.append(result)
                if result["status"] != "PASS":
                    blockers.extend({**item, "operation": operation["id"]} for item in result["blockers"])
        if source_identity(repository_root, deadline=deadline) != inputs:
            blockers.append({"code": "performance-lineage-inputs-changed"})
        if time.monotonic() > deadline:
            blockers.append({"code": "performance-total-deadline-exceeded"})
        body = {
            "schemaVersion": BASELINE_SCHEMA,
            "status": "PASS" if not blockers and len(results) == len(operations) else "FAIL",
            "sourceRevision": source_revision,
            "dirtyState": dirty,
            "sourceInputs": inputs,
            "totalWallSeconds": time.monotonic() - started,
            "metricDefinitions": METRIC_DEFINITIONS,
            "environment": {
                "platform": platform.platform(aliased=True),
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "cpuCount": os.cpu_count() or 1,
                "warmupSamples": warmups,
                "samplesPerCase": samples,
            },
            "policy": {
                "path": _relative_path(policy_path, repository_root),
                "schemaVersion": policy["schemaVersion"],
                "revision": policy["revision"],
                "digest": canonical_digest(policy),
            },
            "operations": results,
            "comparability": {
                "status": "COMPARABLE" if results and not blockers else "NO_RECOMMENDATION",
                "reason": None if results and not blockers else "baseline did not complete all bounded operations",
            },
            "blockers": blockers,
            "productionPromotionClaimed": False,
        }
    except (LifecycleError, OSError, subprocess.TimeoutExpired) as exc:
        body = {
            "schemaVersion": BASELINE_SCHEMA,
            "status": "FAIL",
            "sourceRevision": None,
            "dirtyState": None,
            "environment": {},
            "policy": {"path": _relative_path(policy_path, repository_root)},
            "operations": [],
            "comparability": {"status": "NO_RECOMMENDATION", "reason": "policy or source input invalid"},
            "blockers": [
                {
                    "code": exc.code if isinstance(exc, LifecycleError) else "performance-input-process-unavailable",
                    "message": exc.message
                    if isinstance(exc, LifecycleError)
                    else "Bounded source or process input is unavailable",
                }
            ],
            "productionPromotionClaimed": False,
        }
    result = {**body, "baselineDigest": canonical_digest(body)}
    write_json_replace_private(output_path, result)
    return result


def _operation_specs(root: Path, temporary: Path, requested: Iterable[str]) -> list[dict[str, Any]]:
    requested_items = list(requested)
    specs: dict[str, dict[str, Any]] = {
        "cli-version": {
            "id": "cli-version",
            "kind": "command",
            "argv": [sys.executable, "-m", "agent_lifecycle", "version"],
        },
        "canonical-digest": {"id": "canonical-digest", "kind": "in-process", "argv": ["canonical_digest"]},
    }
    if "neutrality-tracked" in requested_items:
        specs["neutrality-tracked"] = {
            "id": "neutrality-tracked",
            "kind": "command",
            "argv": [
                sys.executable,
                "-m",
                "agent_lifecycle.neutrality",
                "scan",
                "--scope",
                "tracked-release",
                "--policy",
                "policy/neutrality.policy.json",
                "--report",
                str((temporary / "neutrality-report.json").resolve().relative_to(root.resolve())),
                "--require-zero-findings",
            ],
        }
        specs["neutrality-tracked"]["identityArgv"] = [
            *specs["neutrality-tracked"]["argv"][:-3],
            "--report",
            "<benchmark-output>",
            "--require-zero-findings",
        ]
    for name in LIFECYCLE_OPERATIONS:
        specs[name] = {
            "id": name,
            "kind": "lifecycle-command",
            "argv": [
                sys.executable,
                "-B",
                str(root / "tools/performance/lifecycle_cases.py"),
                "--source-root",
                str(root.resolve()),
                "--operation",
                name,
            ],
        }
    unknown = sorted(set(requested_items) - set(specs))
    if unknown:
        raise LifecycleError(
            "performance-operation-unknown", "performance policy names an unknown operation", {"operations": unknown}
        )
    return [specs[item] for item in requested_items]


def _measure_operation(
    operation: dict[str, Any],
    *,
    repository_root: Path,
    warmups: int,
    samples: int,
    command_timeout: int,
    max_output_bytes: int,
    deadline: float,
) -> dict[str, Any]:
    sample_values: list[dict[str, Any]] = []
    warmup_values: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for _ in range(warmups):
        measured = _invoke(operation, repository_root, command_timeout, max_output_bytes, deadline)
        warmup_values.append(measured)
        if measured["status"] != "PASS":
            blockers.extend(measured["blockers"])
            break
    if not blockers:
        for _ in range(samples):
            measured = _invoke(operation, repository_root, command_timeout, max_output_bytes, deadline)
            sample_values.append(measured)
            if measured["status"] != "PASS":
                blockers.extend(measured["blockers"])
                break
    walls = [float(item["wallSeconds"]) for item in sample_values]
    rss = [int(item["maxRssBytes"]) for item in sample_values if item["maxRssBytes"] is not None]
    lifecycle = [item["lifecycle"] for item in sample_values if "lifecycle" in item]
    workload = lifecycle[0]["workload"] if lifecycle else None
    if any(item["workload"] != workload for item in lifecycle):
        blockers.append({"code": "performance-comparability-workload-changed"})
    detail = {}
    for key in ("operationWallSeconds", "setupWallSeconds", "subprocessOverheadSeconds"):
        values = [float(item[key]) for item in lifecycle]
        detail[key] = {"median": float(median(values)) if values else None, "p95": _p95(values)}
    return {
        "id": operation["id"],
        "kind": operation["kind"],
        "status": "PASS" if not blockers and len(sample_values) == samples else "FAIL",
        "commandArgvDigest": canonical_digest(operation.get("identityArgv", operation["argv"])),
        "samples": sample_values,
        "warmupSamples": warmup_values,
        "workload": workload,
        "summary": {
            "sampleCount": len(sample_values),
            "medianWallSeconds": float(median(walls)) if walls else None,
            "p95WallSeconds": _p95(walls),
            "maxRssBytes": max(rss) if rss else None,
            "lifecycleMetrics": detail,
        },
        "operationCounts": {
            "invocations": len(sample_values),
            "warmups": len(warmup_values),
            "subprocesses": sum(item.get("processStarted") is True for item in sample_values + warmup_values),
        },
        "blockers": blockers,
    }


def _invoke(operation: dict[str, Any], root: Path, timeout: int, max_output: int, deadline: float) -> dict[str, Any]:
    remaining = min(float(timeout), deadline - time.monotonic())
    if remaining <= 0:
        return _failed_sample("performance-total-deadline-exceeded")
    if operation["kind"] == "in-process":
        started = time.monotonic()
        payload = {"kind": "performance", "values": list(range(512)), "source": "deterministic"}
        canonical_digest(payload)
        return {
            "status": "PASS",
            "wallSeconds": round(time.monotonic() - started, 6),
            "maxRssBytes": _self_rss_bytes(),
            "stdoutBytes": 0,
            "stderrBytes": 0,
            "stdoutSha256": hashlib.sha256(b"").hexdigest(),
            "stderrSha256": hashlib.sha256(b"").hexdigest(),
            "returncode": 0,
        }
    env = os.environ.copy()
    source_root = str((root / "src").resolve())
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PYTHONPATH"] = source_root
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    argv = list(operation["argv"])
    if "--report" in argv:
        report_index = argv.index("--report") + 1
        report_path = Path(argv[report_index])
        argv[report_index] = report_path.with_name(f"{report_path.stem}-{time.time_ns()}.json").as_posix()
    return _run_bounded(
        argv,
        cwd=root,
        env=env,
        timeout=remaining,
        max_output_bytes=max_output,
        lifecycle_operation=operation["id"] if operation["kind"] == "lifecycle-command" else None,
    )


def _run_bounded(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    max_output_bytes: int,
    lifecycle_operation: str | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    before_rss = _children_rss_bytes()
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            start_new_session=os.name != "nt",
        )
    except OSError as exc:
        return _failed_sample("process-start-failed", message=type(exc).__name__)
    captured: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    stream_queue: queue.Queue[tuple[str, bytes | None]] = queue.Queue(maxsize=64)
    stopped = threading.Event()
    threads = [
        threading.Thread(target=_read_stream, args=(name, stream, stream_queue, stopped), daemon=True)
        for name, stream in (("stdout", process.stdout), ("stderr", process.stderr))
    ]
    for thread in threads:
        thread.start()
    ended = {"stdout": False, "stderr": False}
    blockers: list[dict[str, Any]] = []
    while not all(ended.values()):
        if time.monotonic() - started > timeout:
            blockers.append({"code": "performance-command-timeout"})
            _terminate_process(process)
            break
        try:
            name, chunk = stream_queue.get(timeout=0.05)
        except queue.Empty:
            continue
        if chunk is None:
            ended[name] = True
            continue
        captured[name].extend(chunk)
        if len(captured[name]) > max_output_bytes:
            blockers.append({"code": "performance-output-limit", "stream": name})
            _terminate_process(process)
            break
    _terminate_process(process) if process.poll() is None else None
    try:
        returncode = process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        _terminate_process(process, force=True)
        try:
            returncode = process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            returncode = -9
            blockers.append({"code": "performance-process-cleanup-failed"})
    stopped.set()
    for thread in threads:
        thread.join(timeout=1)
    if any(thread.is_alive() for thread in threads):
        blockers.append({"code": "performance-reader-cleanup-failed"})
    if returncode != 0 and not blockers:
        blockers.append({"code": "performance-command-failed", "returncode": returncode})
    result = {
        "status": "PASS" if not blockers else "FAIL",
        "wallSeconds": round(time.monotonic() - started, 6),
        "maxRssBytes": _children_rss_bytes(),
        "stdoutBytes": len(captured["stdout"]),
        "stderrBytes": len(captured["stderr"]),
        "stdoutSha256": hashlib.sha256(captured["stdout"]).hexdigest(),
        "stderrSha256": hashlib.sha256(captured["stderr"]).hexdigest(),
        "returncode": returncode,
        "processStarted": True,
        "blockers": blockers,
    }
    if before_rss is not None and result["maxRssBytes"] is not None:
        result["maxRssBytes"] = max(before_rss, result["maxRssBytes"])
    if lifecycle_operation is not None and not blockers:
        try:
            value = json.loads(captured["stdout"])
            expected = "agent-lifecycle-performance-case.v1"
            if (
                value["schemaVersion"] != expected
                or value["status"] != "PASS"
                or value["operation"] != lifecycle_operation
                or value["fixtureArtifactsUnchanged"] is not True
                or value["productionPromotionClaimed"] is not False
                or not isinstance(value["workload"], dict)
            ):
                raise ValueError("Lifecycle worker contract mismatch")
            for key in (
                "setupWallSeconds",
                "operationWallSeconds",
                "validationWallSeconds",
                "workerWallSeconds",
            ):
                if type(value[key]) not in (float, int) or not math.isfinite(value[key]) or value[key] < 0:
                    raise ValueError("Lifecycle worker timing is invalid")
            value["subprocessOverheadSeconds"] = max(0.0, result["wallSeconds"] - value["workerWallSeconds"])
            result["lifecycle"] = value
        except (KeyError, TypeError, ValueError):
            result["status"] = "FAIL"
            blockers.append({"code": "performance-worker-output-invalid"})
    return result


def _put_stream(
    output: queue.Queue[tuple[str, bytes | None]],
    item: tuple[str, bytes | None],
    stopped: threading.Event,
) -> None:
    while not stopped.is_set():
        try:
            output.put(item, timeout=0.05)
            return
        except queue.Full:
            continue


def _read_stream(
    name: str,
    stream: Any,
    output: queue.Queue[tuple[str, bytes | None]],
    stopped: threading.Event,
) -> None:
    try:
        while not stopped.is_set():
            chunk = stream.read(_CHUNK_BYTES)
            if not chunk:
                break
            _put_stream(output, (name, chunk), stopped)
    finally:
        stream.close()
        _put_stream(output, (name, None), stopped)


def _terminate_process(process: subprocess.Popen[bytes], *, force: bool = False) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        else:
            process.kill() if force else process.terminate()
    except OSError:
        pass


def _git_revision(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        shell=False,
        check=False,
        timeout=10,
    )
    value = result.stdout.decode("ascii", errors="ignore").strip()
    if result.returncode != 0 or len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise LifecycleError("performance-source-unavailable", "current Git revision is unavailable")
    return value


def _git_dirty(root: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        shell=False,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        raise LifecycleError("performance-source-unavailable", "current Git status is unavailable")
    return bool(result.stdout.strip())


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return "<outside-repository>"


def source_identity(root: Path, *, deadline: float | None = None) -> dict[str, Any]:
    """Hash the current tracked and nonignored source, including dirty files."""
    if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)):
        raise LifecycleError("performance-source-deadline-invalid", "Source deadline is invalid")
    cutoff = min(deadline, time.monotonic() + 120) if deadline is not None else time.monotonic() + 120
    remaining = cutoff - time.monotonic()
    if remaining <= 0:
        raise LifecycleError("performance-source-deadline-exceeded", "Source capture deadline expired")
    try:
        command = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            check=False,
            timeout=min(10, remaining),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise LifecycleError("performance-source-unavailable", "Source inventory unavailable") from error
    if command.returncode or len(command.stdout) > 8_388_608:
        raise LifecycleError("performance-source-unavailable", "Source inventory unavailable")
    names = sorted(set(os.fsdecode(item) for item in command.stdout.split(b"\0") if item))
    if len(names) > 10_000:
        raise LifecycleError("performance-source-unavailable", "Source inventory exceeds limit")
    files = []
    total = 0
    for name in names:
        if time.monotonic() >= cutoff:
            raise LifecycleError("performance-source-deadline-exceeded", "Source capture deadline expired")
        digest, size = hashlib.sha256(), 0
        with open_authority_read(root / name, root=root) as stream:
            if os.fstat(stream.fileno()).st_size > 16 * 1024 * 1024:
                raise LifecycleError("performance-source-too-large", "Source file exceeds limit")
            while True:
                if time.monotonic() >= cutoff:
                    raise LifecycleError("performance-source-deadline-exceeded", "Source capture deadline expired")
                chunk = stream.read(256 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                total += len(chunk)
                if size > 16 * 1024 * 1024 or total > 128 * 1024 * 1024:
                    raise LifecycleError("performance-source-too-large", "Source bytes exceed limit")
                digest.update(chunk)
        # Successful context exit binds actual fd bytes to pre/post path identity.
        if time.monotonic() >= cutoff:
            raise LifecycleError("performance-source-deadline-exceeded", "Source capture deadline expired")
        files.append({"path": name, "bytes": size, "sha256": digest.hexdigest()})
    return {"files": files, "digest": canonical_digest(files)}


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = math.ceil(len(ordered) * 0.95) - 1
    return float(ordered[index])


def _self_rss_bytes() -> int | None:
    try:
        import resource
    except ImportError:
        return None
    return _rss_bytes(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def _children_rss_bytes() -> int | None:
    try:
        import resource
    except ImportError:
        return None
    return _rss_bytes(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)


def _rss_bytes(value: int | float) -> int:
    raw = int(value)
    return raw if sys.platform == "darwin" else raw * 1024


def _failed_sample(code: str, *, message: str | None = None) -> dict[str, Any]:
    blocker: dict[str, Any] = {"code": code}
    if message:
        blocker["message"] = message
    return {
        "status": "FAIL",
        "wallSeconds": 0.0,
        "maxRssBytes": 0,
        "stdoutBytes": 0,
        "stderrBytes": 0,
        "stdoutSha256": hashlib.sha256(b"").hexdigest(),
        "stderrSha256": hashlib.sha256(b"").hexdigest(),
        "returncode": None,
        "processStarted": False,
        "blockers": [blocker],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--repository-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = collect_baseline(
        policy_path=Path(args.policy),
        repository_root=Path(args.repository_root).resolve(),
        output_path=Path(args.output),
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Collect bounded, revision-bound performance evidence without model calls."""

from __future__ import annotations

import argparse
import hashlib
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
from agent_lifecycle.contracts.canonical import write_json_replace_private
from agent_lifecycle.contracts.performance_limits import validate_performance_policy

BASELINE_SCHEMA = "agent-performance-baseline.v1"
_CHUNK_BYTES = 8192


def collect_baseline(*, policy_path: Path, repository_root: Path, output_path: Path) -> dict[str, Any]:
    """Run the closed benchmark set and return a redacted evidence document."""

    blockers: list[dict[str, Any]] = []
    body: dict[str, Any]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        policy = read_json_object(policy_path, label="performance policy")
        limits = validate_performance_policy(policy)
        source_revision = _git_revision(repository_root)
        dirty = _git_dirty(repository_root)
        benchmark = policy["benchmark"]
        samples = int(benchmark["samplesPerCase"])
        warmups = int(benchmark["warmupSamples"])
        deadline = time.monotonic() + int(benchmark["maxTotalWallSeconds"])
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
        body = {
            "schemaVersion": BASELINE_SCHEMA,
            "status": "PASS" if not blockers and len(results) == len(operations) else "FAIL",
            "sourceRevision": source_revision,
            "dirtyState": dirty,
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
    except LifecycleError as exc:
        body = {
            "schemaVersion": BASELINE_SCHEMA,
            "status": "FAIL",
            "sourceRevision": None,
            "dirtyState": None,
            "environment": {},
            "policy": {"path": _relative_path(policy_path, repository_root)},
            "operations": [],
            "comparability": {"status": "NO_RECOMMENDATION", "reason": "policy or source input invalid"},
            "blockers": [{"code": exc.code, "message": exc.message}],
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
    blockers: list[dict[str, Any]] = []
    for _ in range(warmups):
        measured = _invoke(operation, repository_root, command_timeout, max_output_bytes, deadline)
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
    rss = [int(item["maxRssBytes"]) for item in sample_values]
    return {
        "id": operation["id"],
        "kind": operation["kind"],
        "status": "PASS" if not blockers and len(sample_values) == samples else "FAIL",
        "commandArgvDigest": canonical_digest(operation["argv"]),
        "samples": sample_values,
        "summary": {
            "sampleCount": len(sample_values),
            "medianWallSeconds": float(median(walls)) if walls else None,
            "p95WallSeconds": _p95(walls),
            "maxRssBytes": max(rss) if rss else None,
        },
        "operationCounts": {"invocations": len(sample_values), "warmups": warmups},
        "blockers": blockers,
    }


def _invoke(operation: dict[str, Any], root: Path, timeout: int, max_output: int, deadline: float) -> dict[str, Any]:
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
    remaining = max(0.01, min(float(timeout), deadline - time.monotonic()))
    if remaining <= 0:
        return _failed_sample("performance-total-deadline-exceeded")
    env = os.environ.copy()
    source_root = str((root / "src").resolve())
    old_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = source_root if not old_pythonpath else source_root + os.pathsep + old_pythonpath
    argv = list(operation["argv"])
    if "--report" in argv:
        report_index = argv.index("--report") + 1
        report_path = Path(argv[report_index])
        argv[report_index] = report_path.with_name(f"{report_path.stem}-{time.time_ns()}.json").as_posix()
    return _run_bounded(argv, cwd=root, env=env, timeout=remaining, max_output_bytes=max_output)


def _run_bounded(
    argv: list[str], *, cwd: Path, env: dict[str, str], timeout: float, max_output_bytes: int
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
    threads = [
        threading.Thread(target=_read_stream, args=(name, stream, stream_queue), daemon=True)
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
        returncode = process.returncode if process.returncode is not None else -9
    for thread in threads:
        thread.join(timeout=1)
    if returncode != 0 and not blockers:
        blockers.append({"code": "performance-command-failed", "returncode": returncode})
    return {
        "status": "PASS" if not blockers else "FAIL",
        "wallSeconds": round(time.monotonic() - started, 6),
        "maxRssBytes": max(_children_rss_bytes(), before_rss),
        "stdoutBytes": len(captured["stdout"]),
        "stderrBytes": len(captured["stderr"]),
        "stdoutSha256": hashlib.sha256(captured["stdout"]).hexdigest(),
        "stderrSha256": hashlib.sha256(captured["stderr"]).hexdigest(),
        "returncode": returncode,
        "blockers": blockers,
    }


def _read_stream(name: str, stream: Any, output: queue.Queue[tuple[str, bytes | None]]) -> None:
    try:
        while True:
            chunk = stream.read(_CHUNK_BYTES)
            if not chunk:
                break
            output.put((name, chunk))
    finally:
        output.put((name, None))


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


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * 0.95)))
    return float(ordered[index])


def _self_rss_bytes() -> int:
    try:
        import resource
    except ImportError:
        return 0
    return _rss_bytes(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def _children_rss_bytes() -> int:
    try:
        import resource
    except ImportError:
        return 0
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

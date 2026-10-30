#!/usr/bin/env python3
"""Run the pinned Python quality tools with bounded subprocesses."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

if __package__:
    from .release_common import digest_value, write_json
else:
    from release_common import digest_value, write_json


SCHEMA = "agent-python-quality-run.v1"
DEFAULT_TIMEOUT_SECONDS = 900
DEFAULT_OUTPUT_BYTES = 16 * 1024 * 1024


def quality_command_argv(policy: dict[str, Any], package_root: Path) -> dict[str, list[str]]:
    """One selected-scope command inventory, used by runner and receipt validator."""
    python = [sys.executable, "-m"]
    scopes = [package_root.as_posix(), *policy.get("tooling", {}).get("paths", [])]
    ruff = policy.get("ruff", {})
    commands = {
        "ruff-correctness": [
            *python,
            "ruff",
            "check",
            *scopes,
            "--select",
            ",".join(ruff.get("correctnessSelectors", [])),
            "--output-format",
            "json",
        ],
        "ruff-migration": [
            *python,
            "ruff",
            "check",
            *scopes,
            "--select",
            ",".join(ruff.get("migrationSelectors", [])),
            "--output-format",
            "json",
        ],
        "ruff-format": [*python, "ruff", "format", *scopes, "--check", "--output-format", "json"],
        "ruff-line-length": [*python, "ruff", "check", *scopes, "--select", "E501", "--output-format", "json"],
        "mypy": [*python, "mypy", package_root.as_posix(), "--show-error-codes"],
    }
    strict = [*policy.get("mypy", {}).get("strictClean", []), *policy.get("tooling", {}).get("paths", [])]
    if strict:
        commands["mypy-strict"] = [*python, "mypy", "--strict", *strict, "--show-error-codes"]
    return commands


def source_inventory(root: Path, policy_path: Path, package: Path, policy: dict[str, Any]) -> dict[str, str]:
    """Bind all checked sources and their command/policy inputs to this invocation."""
    paths = set(package.rglob("*.py")) | {policy_path}
    paths.update(root / name for name in policy.get("tooling", {}).get("paths", []))
    paths.update(root / name for name in policy.get("mypy", {}).get("strictClean", []))
    paths.update(
        root / name
        for name in (
            "tools/release/run_python_quality.py",
            "tools/release/validate_python_quality.py",
            "tools/release/release_common.py",
            "pyproject.toml",
        )
    )
    return {
        path.resolve().relative_to(root.resolve()).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def run_quality(
    *,
    repository_root: Path,
    policy_path: Path,
    package_root: Path,
    tests_root: Path,
    test_top_level: Path,
    base_sha: str,
    work_root: Path,
) -> dict[str, Any]:
    policy = _read_object(policy_path)
    limits = policy.get("limits", {})
    timeout = int(limits.get("maxWallSeconds", DEFAULT_TIMEOUT_SECONDS))
    output_limit = int(limits.get("maxOutputBytes", DEFAULT_OUTPUT_BYTES))
    work_root.mkdir(parents=True, exist_ok=True)
    # Never reuse a previous invocation's database or raw tool output.
    requested_work_root = work_root
    work_root = Path(tempfile.mkdtemp(prefix="run-", dir=work_root)).resolve()

    commands: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    ruff = policy.get("toolchain", {}).get("ruff", "")
    mypy = policy.get("toolchain", {}).get("mypy", "")
    coverage = policy.get("toolchain", {}).get("coverage", "")

    for tool, expected in (("ruff", ruff), ("mypy", mypy), ("coverage", coverage)):
        result = _run_command(
            [sys.executable, "-m", tool, "--version"],
            cwd=repository_root,
            timeout_seconds=timeout,
            output_limit=output_limit,
            expected_exit_codes={0},
        )
        version = result["stdout"].strip().splitlines()[0] if result["stdout"].strip() else ""
        commands.append(_command_record(f"{tool}-version", [sys.executable, "-m", tool, "--version"], result))
        if result["status"] != "PASS" or expected not in version:
            blockers.append(
                {
                    "code": "quality-tool-version-mismatch",
                    "tool": tool,
                    "expected": expected,
                    "reported": version,
                }
            )

    inventory = source_inventory(repository_root, policy_path, package_root, policy) if "tooling" in policy else None
    selected = []
    for identifier, argv in quality_command_argv(policy, package_root).items():
        selected.append(
            _run_tool(
                identifier,
                argv,
                repository_root,
                work_root,
                timeout,
                output_limit,
                expected_exit_codes={0} if identifier == "mypy-strict" else {0, 1},
            )
        )

    coverage_file = work_root / "coverage.data"
    coverage_json = work_root / "coverage.json"
    coverage_env = os.environ.copy()
    coverage_env["COVERAGE_FILE"] = str(coverage_file)
    coverage_result = _run_tool(
        "coverage",
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            "--branch",
            "--source=src/agent_lifecycle",
            "-m",
            "unittest",
            "discover",
            "-s",
            tests_root.as_posix(),
            "-t",
            test_top_level.as_posix(),
            "-q",
        ],
        repository_root,
        work_root,
        timeout,
        output_limit,
        expected_exit_codes={0},
        env=coverage_env,
    )
    if coverage_file.is_file():
        json_result = _run_tool(
            "coverage-json",
            [sys.executable, "-m", "coverage", "json", "-o", coverage_json.as_posix()],
            repository_root,
            work_root,
            timeout,
            output_limit,
            expected_exit_codes={0},
            env=coverage_env,
        )
        if json_result["status"] != "PASS":
            blockers.append({"code": "coverage-json-failed"})
        commands.append(json_result)
    else:
        blockers.append({"code": "coverage-data-missing"})

    for record in (*selected, coverage_result):
        commands.append(record)
        if record["status"] == "FAIL":
            blockers.append({"code": "quality-command-failed", "id": record["id"]})

    changed_paths = _changed_paths(repository_root, base_sha)
    body = {
        "schemaVersion": SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "sourceRevision": base_sha,
        "packageRoot": _relative(repository_root, package_root),
        "sourceInventory": inventory,
        "workRoot": _relative(repository_root, requested_work_root),
        "runDirectory": _relative(repository_root, work_root),
        "toolchain": {"ruff": ruff, "mypy": mypy, "coverage": coverage},
        "environment": {
            "os": platform.platform(),
            "pythonImplementation": platform.python_implementation(),
            "pythonVersion": platform.python_version(),
        },
        "changedPaths": changed_paths,
        "commands": commands,
        "artifacts": {
            "ruffCorrectness": _relative(repository_root, work_root / "ruff-correctness.stdout.json"),
            "ruffMigration": _relative(repository_root, work_root / "ruff-migration.stdout.json"),
            "ruffFormat": _relative(repository_root, work_root / "ruff-format.stdout.json"),
            "ruffLineLength": _relative(repository_root, work_root / "ruff-line-length.stdout.json"),
            "mypy": _relative(repository_root, work_root / "mypy.stdout.txt"),
            "coverage": _relative(repository_root, coverage_json),
            "coverageData": _relative(repository_root, coverage_file),
        },
        "blockers": blockers,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "runDigest": digest_value(body)}


def _run_tool(
    identifier: str,
    argv: list[str],
    cwd: Path,
    work_root: Path,
    timeout: int,
    output_limit: int,
    *,
    expected_exit_codes: set[int],
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    result = _run_command(
        argv,
        cwd=cwd,
        timeout_seconds=timeout,
        output_limit=output_limit,
        expected_exit_codes=expected_exit_codes,
        env=env,
    )
    suffix = "stdout.json" if "json" in argv else "stdout.txt"
    output_path = work_root / f"{identifier}.{suffix}"
    output_path.write_text(result["stdout"], encoding="utf-8")
    error_path = work_root / f"{identifier}.stderr.txt"
    error_path.write_text(result["stderr"], encoding="utf-8")
    return {
        **_command_record(identifier, argv, result),
        "stdoutPath": _relative(cwd, output_path),
        "stderrPath": _relative(cwd, error_path),
    }


def _run_command(
    argv: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    output_limit: int,
    expected_exit_codes: set[int],
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            start_new_session=(os.name != "nt"),
        )
    except OSError as exc:
        return {
            "returncode": None,
            "status": "FAIL",
            "stdout": "",
            "stderr": str(exc),
            "timedOut": False,
            "outputLimited": False,
            "elapsedSeconds": round(time.monotonic() - started, 3),
        }
    stdout_drain = _drain(process.stdout, output_limit)
    stderr_drain = _drain(process.stderr, output_limit)
    timed_out = False
    while process.poll() is None:
        if (
            time.monotonic() - started > timeout_seconds
            or stdout_drain.limited.is_set()
            or stderr_drain.limited.is_set()
        ):
            timed_out = True
            _terminate(process)
            break
        time.sleep(0.02)
    process.wait()
    stdout_drain.thread.join()
    stderr_drain.thread.join()
    if process.stdout is not None:
        process.stdout.close()
    if process.stderr is not None:
        process.stderr.close()
    elapsed = round(time.monotonic() - started, 3)
    output_overflow = stdout_drain.limited.is_set() or stderr_drain.limited.is_set()
    status = "PASS" if process.returncode in expected_exit_codes and not timed_out and not output_overflow else "FAIL"
    return {
        "returncode": process.returncode,
        "status": status,
        "stdout": bytes(stdout_drain.output).decode("utf-8", errors="replace"),
        "stderr": bytes(stderr_drain.output).decode("utf-8", errors="replace"),
        "timedOut": timed_out,
        "outputLimited": output_overflow,
        "elapsedSeconds": elapsed,
    }


def _drain(stream: Any, limit: int) -> "_Drain":
    output = bytearray()
    limited = threading.Event()

    def read() -> None:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                return
            if len(output) < limit:
                output.extend(chunk[: max(0, limit - len(output))])
            if len(output) >= limit or len(chunk) > max(0, limit - len(output)):
                limited.set()

    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    return _Drain(output, thread, limited)


class _Drain:
    def __init__(self, output: bytearray, thread: threading.Thread, limited: threading.Event) -> None:
        self.output = output
        self.thread = thread
        self.limited = limited


def _terminate(process: subprocess.Popen[bytes]) -> None:
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass


def _command_record(identifier: str, argv: list[str], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": identifier,
        "argv": argv,
        "status": result["status"],
        "returncode": result["returncode"],
        "timedOut": result["timedOut"],
        "outputLimited": result["outputLimited"],
        "elapsedSeconds": result["elapsedSeconds"],
    }


def _changed_paths(root: Path, base_sha: str) -> list[str]:
    if not base_sha or base_sha.startswith("-"):
        return []
    process = subprocess.run(
        ["git", "diff", "--name-only", base_sha, "--"],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        return []
    return sorted(item for item in process.stdout.splitlines() if item)


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--tests-root", type=Path, required=True)
    parser.add_argument("--test-top-level", type=Path, required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    result = run_quality(
        repository_root=Path.cwd().resolve(),
        policy_path=args.policy,
        package_root=args.package_root,
        tests_root=args.tests_root,
        test_top_level=args.test_top_level,
        base_sha=args.base_sha,
        work_root=args.work_root,
    )
    write_json(args.evidence, result)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

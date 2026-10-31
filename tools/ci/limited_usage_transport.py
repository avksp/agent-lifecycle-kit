"""Bounded transport for fixed CI limited-usage measurements; no host adapter."""

import hashlib
import json
import sys
import time
from pathlib import Path


def owned_gate_argv(argv, *, max_bytes):
    from agent_lifecycle.contracts import LifecycleError

    if not isinstance(argv, list) or not argv or any((not isinstance(value, str) or "\x00" in value for value in argv)):
        raise LifecycleError("bounded-process-argv-invalid", "A shell-free original argument vector is required")
    base = Path(sys._base_executable)
    if not base.is_absolute() or not base.is_file():
        raise ValueError("The actual base Python must be an absolute ordinary file")
    options = json.dumps({"argv": argv, "version": list(sys.version_info[:3])})
    if len(options.encode("utf-8")) > max_bytes:
        raise ValueError("Gate argument payload exceeds its byte bound")
    code = "import json,os,subprocess,sys;v=json.loads(sys.argv[1]);sys.exit(126) if list(sys.version_info[:3])!=v['version'] else None;sys.exit(125) if sys.stdin.buffer.read(1)!=b'G' else None;env=dict(os.environ);env.update({'GIT_NO_LAZY_FETCH':'1','GIT_TERMINAL_PROMPT':'0'} if os.path.splitext(os.path.basename(v['argv'][0]))[0].lower()=='git' else {});sys.exit(subprocess.run(v['argv'],shell=False,stdin=subprocess.DEVNULL,env=env).returncode)"
    return [str(base.resolve(strict=True)), "-I", "-B", "-S", "-c", code, options]


def command(argv, root, deadline, records, *, timeout=120, logs=None, owned_gate=False, max_bytes, reference):
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
    chunks, process = ([], None)
    try:
        if owned_gate:
            argv = owned_gate_argv(argv, max_bytes=max_bytes)
            record.update(gateArgv=argv, logicalProcessStarted=None, goSent=False)
        process = BoundedProcess(
            argv,
            cwd=root,
            deadline=min(deadline, time.monotonic() + timeout),
            max_stdout_bytes=max_bytes,
            max_stderr_bytes=max_bytes,
            writable=owned_gate,
        )
        record["processStarted"] = True
        if owned_gate:
            record["gatePid"] = process.process.pid
            process.write_request(b"G")
            record["goSent"] = True
            process.write_request(None)
        while data := process.stdout.read(65536):
            chunks.append(data)
        record["exitCode"] = process.wait()
        if owned_gate and record["exitCode"] == 0:
            record["logicalProcessStarted"] = True
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

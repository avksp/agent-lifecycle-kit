"""Secure process execution for managed adapter sessions."""

from __future__ import annotations

import subprocess
from typing import Any

from agent_lifecycle.contracts.redaction import redact_text


def run_process(argv: list[str], *, env: dict[str, str], timeout_seconds: float) -> dict[str, Any]:
    try:
        result = subprocess.run(
            argv,
            shell=False,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
        stdout_tail, stdout_redacted = redact_text(result.stdout[-2000:])
        stderr_tail, stderr_redacted = redact_text(result.stderr[-2000:])
        return {
            "status": "PASS" if result.returncode == 0 else "FAIL",
            "exitCode": result.returncode,
            "timedOut": False,
            "stdoutTail": stdout_tail,
            "stdoutRedacted": stdout_redacted,
            "stderrTail": stderr_tail,
            "stderrRedacted": stderr_redacted,
            "blockers": [] if result.returncode == 0 else [{"code": "adapter-process-nonzero-exit", "exitCode": result.returncode}],
        }
    except subprocess.TimeoutExpired as exc:
        stdout_tail, stdout_redacted = redact_text((exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else "")
        stderr_tail, stderr_redacted = redact_text((exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else "")
        return {
            "status": "FAIL",
            "exitCode": None,
            "timedOut": True,
            "stdoutTail": stdout_tail,
            "stdoutRedacted": stdout_redacted,
            "stderrTail": stderr_tail,
            "stderrRedacted": stderr_redacted,
            "blockers": [{"code": "adapter-process-timeout", "timeoutSeconds": timeout_seconds}],
        }

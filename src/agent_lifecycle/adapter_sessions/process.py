"""Secure process execution for managed adapter sessions."""

from __future__ import annotations

import subprocess
from typing import Any

from agent_lifecycle.adapter_sessions.redaction import redact_text


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
        return {
            "status": "PASS" if result.returncode == 0 else "FAIL",
            "exitCode": result.returncode,
            "timedOut": False,
            "stdoutTail": redact_text(result.stdout[-2000:]),
            "stderrTail": redact_text(result.stderr[-2000:]),
            "blockers": [] if result.returncode == 0 else [{"code": "adapter-process-nonzero-exit", "exitCode": result.returncode}],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "FAIL",
            "exitCode": None,
            "timedOut": True,
            "stdoutTail": redact_text((exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else ""),
            "stderrTail": redact_text((exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else ""),
            "blockers": [{"code": "adapter-process-timeout", "timeoutSeconds": timeout_seconds}],
        }

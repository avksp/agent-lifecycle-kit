"""Stdlib unittest runner for controller validation commands."""

from __future__ import annotations

import argparse
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_lifecycle.neutrality.canonical import load_json, write_json_create
from agent_lifecycle.neutrality.errors import NeutralityError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-lifecycle-unittest-runner")
    parser.add_argument("--operation-request", required=True)
    parser.add_argument("--start-directory", required=True)
    parser.add_argument("--pattern", default="test*.py")
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)

    try:
        _require_protocol_output(
            request_path=args.operation_request,
            output_path=args.report,
            schema_version="agent-lifecycle-unittest-report.v1",
        )
        result = _run_suite(args.start_directory, args.pattern)
        report = _build_report(args.operation_request, args.start_directory, args.pattern, result)
        write_json_create(Path(args.report), report)
        return 0 if report["verdict"] == "PASS" else 1
    except NeutralityError as exc:
        print(f"unittest-runner: {exc}", file=sys.stderr)
        return 2


def _run_suite(start_directory: str, pattern: str) -> unittest.TestResult:
    loader = unittest.defaultTestLoader
    suite = loader.discover(start_dir=start_directory, pattern=pattern)
    runner = unittest.TextTestRunner(stream=sys.stderr, verbosity=1)
    return runner.run(suite)


def _build_report(
    operation_request_path: str,
    start_directory: str,
    pattern: str,
    result: unittest.TestResult,
) -> dict[str, Any]:
    request = load_json(Path(operation_request_path).read_bytes())
    claims = request.get("claims")
    if not isinstance(claims, dict):
        raise NeutralityError("operation request claims are missing")
    operation_keys = [
        "runId",
        "packageId",
        "taskId",
        "attempt",
        "operationId",
        "commandId",
        "commandOperationId",
        "planDigest",
        "sourceRevision",
        "projectionDigest",
    ]
    return {
        "schemaVersion": "agent-lifecycle-unittest-report.v1",
        "operation": {
            "schemaVersion": "agent-local-unittest-operation.v1",
            "requestClaimsDigest": request.get("claimsDigest"),
            **{key: claims.get(key) for key in operation_keys},
        },
        "suite": {
            "startDirectory": start_directory,
            "pattern": pattern,
            "testsRun": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skipped": len(result.skipped),
            "expectedFailures": len(result.expectedFailures),
            "unexpectedSuccesses": len(result.unexpectedSuccesses),
        },
        "verdict": "PASS" if result.wasSuccessful() else "FAIL",
        "generatedAt": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def _require_protocol_output(
    *,
    request_path: str,
    output_path: str,
    schema_version: str,
) -> None:
    request = load_json(Path(request_path).read_bytes())
    claims = request.get("claims")
    outputs = claims.get("protocolOutputs") if isinstance(claims, dict) else None
    if not isinstance(outputs, list):
        raise NeutralityError("operation request protocolOutputs are missing")
    for item in outputs:
        if (
            isinstance(item, dict)
            and item.get("path") == output_path
            and item.get("schemaVersion") == schema_version
            and item.get("createNoReplace") is True
        ):
            return
    raise NeutralityError("report path is not authorized by operation request")


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from release_common import file_identity, write_json  # noqa: E402
from tools.live_hosts.common import HarnessError, load_host_env_file_from_args  # noqa: E402


HOST_ENV_REDACTION_SCHEMA = "agent-host-env-file-redacted.v1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="append", default=[])
    parser.add_argument("--host-env-file")
    parser.add_argument("--host-env-allow", action="append", default=[])
    parser.add_argument("--secret-marker", action="append", default=[])
    parser.add_argument("--require-host-env-report", action="store_true")
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args(argv)

    blockers: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    secret_values = _load_secret_values(args, blockers)
    if not args.report:
        blockers.append({"code": "missing-report", "message": "at least one --report is required"})

    for raw_path in args.report:
        report_path = Path(raw_path)
        reports.append(_validate_report(report_path, secret_values=secret_values, require_host_env_report=args.require_host_env_report, blockers=blockers))

    evidence = {
        "schemaVersion": "agent-host-env-secret-hygiene-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "reportCount": len(reports),
        "scannedSecretCount": len(secret_values),
        "reports": reports,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.evidence), evidence)
    return 0 if not blockers else 1


def _load_secret_values(args: argparse.Namespace, blockers: list[dict[str, Any]]) -> list[str]:
    values: list[str] = [value for value in args.secret_marker if value]
    if not args.host_env_file and not args.host_env_allow:
        return values
    try:
        host_env = load_host_env_file_from_args(args.host_env_file, args.host_env_allow)
    except HarnessError as error:
        blockers.append({"code": error.code, "message": error.message})
        return values
    if host_env is None:
        return values
    values.extend(value for value in host_env.values.values() if value)
    return values


def _validate_report(
    path: Path,
    *,
    secret_values: list[str],
    require_host_env_report: bool,
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "report": {"path": path.as_posix(), "missing": True},
        "status": "PASS",
        "hostEnvReportCount": 0,
    }
    before = len(blockers)
    if not path.is_file():
        blockers.append({"code": "missing-report", "report": path.as_posix()})
        report["status"] = "FAIL"
        return report

    text = path.read_text(encoding="utf-8", errors="ignore")
    secret_leaked = False
    for index, value in enumerate(secret_values):
        if value and value in text:
            secret_leaked = True
            blockers.append({"code": "secret-value-leaked", "report": path.as_posix(), "secretOrdinal": index})
    report["report"] = _safe_file_identity(path, omit_sha256=secret_leaked)

    payload = _loads_json(text)
    if payload is None:
        if require_host_env_report:
            blockers.append({"code": "report-json-unreadable", "report": path.as_posix()})
        report["status"] = "PASS" if len(blockers) == before else "FAIL"
        return report

    host_env_reports = list(_find_host_env_reports(payload))
    report["hostEnvReportCount"] = len(host_env_reports)
    if require_host_env_report and not host_env_reports:
        blockers.append({"code": "missing-host-env-redaction-report", "report": path.as_posix()})
    for item in host_env_reports:
        _validate_host_env_redaction(item, path=path, blockers=blockers)
    report["status"] = "PASS" if len(blockers) == before else "FAIL"
    return report


def _safe_file_identity(path: Path, *, omit_sha256: bool) -> dict[str, Any]:
    if not omit_sha256:
        return file_identity(path)
    return {
        "path": path.as_posix(),
        "bytes": len(path.read_bytes()),
        "sha256Omitted": True,
        "sha256OmittedReason": "secret-leak-detected",
    }


def _loads_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _find_host_env_reports(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if value.get("schemaVersion") == HOST_ENV_REDACTION_SCHEMA:
            yield value
        for child in value.values():
            yield from _find_host_env_reports(child)
    elif isinstance(value, list):
        for child in value:
            yield from _find_host_env_reports(child)


def _validate_host_env_redaction(item: dict[str, Any], *, path: Path, blockers: list[dict[str, Any]]) -> None:
    if item.get("valuesRedacted") is not True:
        blockers.append({"code": "host-env-values-not-redacted", "report": path.as_posix()})
    loaded = item.get("loadedVariables")
    if not isinstance(loaded, list) or not all(isinstance(value, str) and value for value in loaded):
        blockers.append({"code": "invalid-host-env-loaded-variables", "report": path.as_posix()})
    variable_count = item.get("variableCount")
    if not isinstance(variable_count, int) or variable_count != len(loaded or []):
        blockers.append({"code": "invalid-host-env-variable-count", "report": path.as_posix()})
    if not isinstance(item.get("pathDigest"), str) or not item["pathDigest"]:
        blockers.append({"code": "missing-host-env-path-digest", "report": path.as_posix()})
    ignored_count = item.get("ignoredVariableCount")
    if not isinstance(ignored_count, int) or ignored_count < 0:
        blockers.append({"code": "invalid-host-env-ignored-count", "report": path.as_posix()})
    forbidden_keys = sorted(set(_find_forbidden_redaction_keys(item)))
    for key in forbidden_keys:
        blockers.append({"code": "host-env-redaction-forbidden-key", "report": path.as_posix(), "key": key})


def _find_forbidden_redaction_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"path", "values", "ignoredVariables"}:
                yield key
            yield from _find_forbidden_redaction_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _find_forbidden_redaction_keys(child)


if __name__ == "__main__":
    raise SystemExit(main())

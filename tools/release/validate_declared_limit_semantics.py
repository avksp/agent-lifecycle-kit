"""Check architecture-limit classifications against actual producer observations."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tools.release.release_common import digest_value, write_json
else:
    try:
        from release_common import digest_value, write_json
    except ImportError:
        from .release_common import digest_value, write_json

LEGACY_LIMIT_SEMANTICS = {
    "targetFileLines": "WARNING",
    "targetFunctionLines": "WARNING",
    "hardFileLines": "BLOCKING",
    "hardFunctionLines": "BLOCKING",
    "hardSymbols": "BLOCKING",
}

LIMIT_SEMANTICS = {
    **LEGACY_LIMIT_SEMANTICS,
    "cliTargetFunctionLines": "WARNING",
    "cliHardFunctionLines": "BLOCKING",
}


def is_cli_path(path: Path, root: Path) -> bool:
    """Classify within the measured package, excluding unrelated ancestors."""
    relative = path.relative_to(root)
    if ".." in relative.parts:
        raise ValueError("observation path escapes package root")
    return "cli" in relative.parts or path.name == "cli.py"


def _declared_semantics(limits: dict[str, Any]) -> dict[str, str]:
    if set(limits) == set(LEGACY_LIMIT_SEMANTICS):
        semantics = LEGACY_LIMIT_SEMANTICS
    elif set(limits) == set(LIMIT_SEMANTICS):
        semantics = LIMIT_SEMANTICS
    else:
        raise ValueError("invalid limit declarations")
    if any(type(value) is not int or value < 1 for value in limits.values()):
        raise ValueError("invalid limit declarations")
    return semantics


def _observation_base(row: dict[str, Any], kind: str, current: bool) -> dict[str, str | int]:
    value = row["count" if kind == "symbol" else "lines"]
    if type(value) is not int or value < 0 or not isinstance(row["path"], str):
        raise ValueError("observation identity/value invalid")
    base: dict[str, str | int] = {"path": row["path"]}
    if kind == "function":
        if not isinstance(row["name"], str) or type(row["line"]) is not int or row["line"] < 1:
            raise ValueError("function observation identity invalid")
        base["name"] = row["name"]
        if current:
            base.update(line=row["line"], lines=value)
    return base


def _expected_diagnostics(report: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    limits = report["limits"]
    current = set(limits) == set(LIMIT_SEMANTICS)
    warnings: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for kind, rows, value_key, target, hard in (
        ("file", report["files"], "lines", "targetFileLines", "hardFileLines"),
        ("function", report["functions"], "lines", "targetFunctionLines", "hardFunctionLines"),
        ("symbol", report["symbols"], "count", None, "hardSymbols"),
    ):
        if not isinstance(rows, list):
            raise ValueError("observation inventory must be an array")
        for row in rows:
            base = _observation_base(row, kind, current)
            value = row[value_key]
            row_target, row_hard = target, hard
            if kind == "function" and current and is_cli_path(Path(row["path"]), Path(report["packageRoot"])):
                row_target, row_hard = "cliTargetFunctionLines", "cliHardFunctionLines"
            if row_target is not None and value > limits[row_target]:
                warning = {
                    **base,
                    "code": f"architecture-{kind}-target-exceeded",
                    "actualLines": value,
                    "targetLines": limits[row_target],
                }
                if kind == "function":
                    warning["line"] = row["line"]
                warnings.append(warning)
            if value > limits[row_hard]:
                blockers.append(
                    {
                        **base,
                        "code": f"architecture-hard-{kind}-limit-exceeded",
                        "actualSymbols" if kind == "symbol" else "actualLines": value,
                        "maxSymbols" if kind == "symbol" else "maxLines": limits[row_hard],
                    }
                )
    return warnings, blockers


def validate_limit_semantics(report: dict[str, Any]) -> dict[str, Any]:
    """Validate this report's behavior; a correct hard-limit FAIL stays a FAIL."""
    blockers: list[dict[str, Any]] = []
    semantics = LIMIT_SEMANTICS
    try:
        if report.get("schemaVersion") != "agent-architecture-complexity-validation.v1":
            raise ValueError("unsupported report schema")
        if report.get("validationDigest") != digest_value({k: v for k, v in report.items() if k != "validationDigest"}):
            blockers.append({"code": "limit-source-report-digest-mismatch"})
        semantics = _declared_semantics(report["limits"])
        if report.get("limitSemantics") != semantics:
            blockers.append({"code": "limit-classification-mismatch"})
        warnings, expected_blockers = _expected_diagnostics(report)
        if Counter(map(digest_value, report["warnings"])) != Counter(map(digest_value, warnings)):
            blockers.append({"code": "limit-warning-coverage-mismatch"})
        actual = [row for row in report["blockers"] if row.get("code", "").startswith("architecture-hard-")]
        if Counter(map(digest_value, actual)) != Counter(map(digest_value, expected_blockers)):
            blockers.append({"code": "limit-enforcement-coverage-mismatch"})
        failed = bool(report["blockers"])
        if report.get("status") != ("FAIL" if failed else "PASS"):
            blockers.append({"code": "limit-producer-status-mismatch"})
        if report.get("hardLimitConformance") != ("FAIL" if failed else "PASS"):
            blockers.append({"code": "limit-hard-conformance-mismatch"})
        for kind in ("File", "Function"):
            exceeded = any(row["code"] == f"architecture-{kind.lower()}-target-exceeded" for row in warnings)
            if report.get(f"target{kind}Conformance") != ("EXCEEDED" if exceeded else "PASS"):
                blockers.append({"code": f"limit-{kind.lower()}-conformance-mismatch"})
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        blockers.append({"code": "limit-report-invalid", "message": str(error)})
    body = {
        "schemaVersion": "agent-declared-limit-semantics-validation.v1",
        "status": "FAIL" if blockers else "PASS",
        "scope": "architecture-limit-report",
        "limitSemantics": semantics,
        "producerStatus": report.get("status") if isinstance(report, dict) else None,
        "sourceRecomputed": False,
        "productionPromotionClaimed": False,
        "blockers": blockers,
    }
    return {**body, "validationDigest": digest_value(body)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--complexity-report", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    result = validate_limit_semantics(json.loads(Path(args.complexity_report).read_text(encoding="utf-8")))
    write_json(Path(args.evidence), result)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

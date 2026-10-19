"""Check architecture-limit classifications against actual producer observations."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from release_common import digest_value, write_json
except ImportError:
    from .release_common import digest_value, write_json

LIMIT_SEMANTICS = {
    "targetFileLines": "WARNING",
    "targetFunctionLines": "WARNING",
    "hardFileLines": "BLOCKING",
    "hardFunctionLines": "BLOCKING",
    "hardSymbols": "BLOCKING",
}


def _expected_diagnostics(report: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    limits = report["limits"]
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
            value = row[value_key]
            if type(value) is not int or value < 0 or not isinstance(row["path"], str):
                raise ValueError("observation identity/value invalid")
            base = {"path": row["path"]}
            if kind == "function":
                base["name"] = row["name"]
            if target is not None and value > limits[target]:
                warning = {
                    **base,
                    "code": f"architecture-{kind}-target-exceeded",
                    "actualLines": value,
                    "targetLines": limits[target],
                }
                if kind == "function":
                    warning["line"] = row["line"]
                warnings.append(warning)
            if value > limits[hard]:
                blockers.append(
                    {
                        **base,
                        "code": f"architecture-hard-{kind}-limit-exceeded",
                        "actualSymbols" if kind == "symbol" else "actualLines": value,
                        "maxSymbols" if kind == "symbol" else "maxLines": limits[hard],
                    }
                )
    return warnings, blockers


def validate_limit_semantics(report: dict[str, Any]) -> dict[str, Any]:
    """Validate this report's behavior; a correct hard-limit FAIL stays a FAIL."""
    blockers: list[dict[str, Any]] = []
    try:
        if report.get("schemaVersion") != "agent-architecture-complexity-validation.v1":
            raise ValueError("unsupported report schema")
        if report.get("validationDigest") != digest_value({k: v for k, v in report.items() if k != "validationDigest"}):
            blockers.append({"code": "limit-source-report-digest-mismatch"})
        if report.get("limitSemantics") != LIMIT_SEMANTICS:
            blockers.append({"code": "limit-classification-mismatch"})
        limits = report["limits"]
        if set(limits) != set(LIMIT_SEMANTICS) or any(type(v) is not int or v < 1 for v in limits.values()):
            raise ValueError("invalid limit declarations")
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
        "limitSemantics": LIMIT_SEMANTICS,
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

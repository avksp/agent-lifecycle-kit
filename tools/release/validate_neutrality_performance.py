"""Validate bounded Git-batch and deny-matching performance invariants."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.canonical import load_json_object, write_json_replace_private
from agent_lifecycle.contracts.performance_limits import PERFORMANCE_POLICY_SCHEMA, validate_performance_policy
from agent_lifecycle.neutrality.matching import build_literal_matcher, validate_rule_limits
from agent_lifecycle.neutrality.policy import load_policy


def validate_neutrality_performance(*, scanner_path: Path, policy_path: Path) -> dict[str, Any]:
    """Check source shape, closed limits and differential matcher behavior."""

    scanner_source = scanner_path.read_text(encoding="utf-8")
    limits = _load_limits(policy_path)
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    source_tree = ast.parse(scanner_source)
    has_batch_route = "iter_git_objects" in scanner_source and "cat-file" not in scanner_source
    checks.append({"id": "constant-git-batch-route", "status": "PASS" if has_batch_route else "FAIL"})
    if not has_batch_route:
        blockers.append({"code": "neutrality-batch-route-missing"})
    try:
        validate_rule_limits(("literal",) * 64, ())
        simple = build_literal_matcher(("literal",) * 64)
        large_rules = tuple(f"literal-{index}" for index in range(65)) + ("literal-1",)
        multi = build_literal_matcher(large_rules)
        simple_result = simple.matching_indices("literal")
        multi_result = multi.matching_indices("literal-1")
        matcher_ok = simple_result == list(range(64)) and multi_result == [1, 65]
    except Exception as exc:
        matcher_ok = False
        checks.append({"id": "bounded-differential-matcher", "status": "FAIL", "errorType": type(exc).__name__})
    else:
        checks.append({"id": "bounded-differential-matcher", "status": "PASS" if matcher_ok else "FAIL"})
    if not matcher_ok:
        blockers.append({"code": "neutrality-matcher-differential-failed"})
    limits_ok = limits["maxObjectBytes"] > 0 and limits["maxFileBytes"] > 0
    checks.append({"id": "policy-resource-limits", "status": "PASS" if limits_ok else "FAIL"})
    if not limits_ok:
        blockers.append({"code": "neutrality-policy-limits-invalid"})
    body = {
        "schemaVersion": "agent-neutrality-performance-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "checks": checks,
        "limits": limits,
        "astFunctions": len([node for node in ast.walk(source_tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _load_limits(policy_path: Path) -> dict[str, int]:
    """Read either the legacy neutrality policy or the performance budget."""

    document = load_json_object(policy_path.read_bytes(), label="neutrality performance policy")
    if document.get("schemaVersion") == PERFORMANCE_POLICY_SCHEMA:
        performance_limits = validate_performance_policy(document)
        return {
            "maxObjectBytes": performance_limits.max_git_object_bytes,
            "maxFileBytes": performance_limits.max_git_object_bytes,
            "maxSimpleLiteralRules": performance_limits.max_simple_literal_rules,
            "maxGitProcessesPerFullScan": performance_limits.max_git_processes_per_full_scan,
            "maxGitInventoryBytes": performance_limits.max_git_inventory_bytes,
            "maxGitExpandedBytes": performance_limits.max_git_expanded_bytes,
            "maxGitBatchFramingBytes": performance_limits.max_git_batch_framing_bytes,
            "maxFullScanWallSeconds": performance_limits.max_full_scan_wall_seconds,
        }
    neutrality_policy = load_policy(policy_path)
    return {
        "maxObjectBytes": neutrality_policy.max_object_bytes,
        "maxFileBytes": neutrality_policy.max_file_bytes,
        "maxSimpleLiteralRules": 64,
        "maxGitProcessesPerFullScan": 2,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scanner", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    payload = validate_neutrality_performance(scanner_path=args.scanner, policy_path=args.policy)
    write_json_replace_private(args.evidence, payload)
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

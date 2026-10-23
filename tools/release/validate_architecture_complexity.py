from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tools.release.release_common import digest_value, file_identity, write_json
    from tools.release.validate_declared_limit_semantics import LIMIT_SEMANTICS, is_cli_path
else:
    try:
        from release_common import digest_value, file_identity, write_json
        from validate_declared_limit_semantics import LIMIT_SEMANTICS, is_cli_path
    except ImportError:
        from .release_common import digest_value, file_identity, write_json
        from .validate_declared_limit_semantics import LIMIT_SEMANTICS, is_cli_path

from agent_lifecycle.quality.architecture_policy import (
    branch_findings,
    function_branch_records,
    load_architecture_limits,
)

POLICY_PATH = Path(__file__).resolve().parents[2] / "policy/architecture-limits.json"
LIMIT_FLAGS = {
    "target_file_lines": "targetFileLines",
    "hard_file_lines": "hardFileLines",
    "target_function_lines": "targetFunctionLines",
    "hard_function_lines": "hardFunctionLines",
    "hard_symbols": "hardSymbols",
}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--policy", type=Path, default=POLICY_PATH)
    for flag in LIMIT_FLAGS:
        parser.add_argument("--" + flag.replace("_", "-"), type=int)
    parser.add_argument("--evidence", required=True)
    return parser.parse_args()


def _limits(args: argparse.Namespace, policy: dict[str, Any]) -> dict[str, int]:
    limits = dict(policy["limits"])
    production_root = POLICY_PATH.parent.parent / "src/agent_lifecycle"
    production = Path(args.package_root).resolve().is_relative_to(production_root)
    if production and args.policy.resolve() != POLICY_PATH:
        raise ValueError("Production architecture limits must use the repository policy")
    for flag, key in LIMIT_FLAGS.items():
        override = getattr(args, flag)
        if override is None:
            continue
        if override < 1 or (production and override != limits[key]):
            raise ValueError(f"--{flag.replace('_', '-')} must agree with the repository policy")
        limits[key] = override
    return limits


def _line_findings(
    record: dict[str, Any],
    actual: int,
    target: int,
    hard: int,
    kind: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    blockers, warnings = [], []
    if actual > hard:
        blockers.append(
            {"code": f"architecture-hard-{kind}-limit-exceeded", **record, "actualLines": actual, "maxLines": hard}
        )
    if actual > target:
        warnings.append(
            {"code": f"architecture-{kind}-target-exceeded", **record, "actualLines": actual, "targetLines": target}
        )
    return blockers, warnings


def _measure_file(path: Path, root: Path, limits: dict[str, int]) -> dict[str, Any]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=path.as_posix())
    lines = len(source.splitlines())
    blockers, warnings = _line_findings(
        {"path": path.as_posix()}, lines, limits["targetFileLines"], limits["hardFileLines"], "file"
    )
    count = _top_level_symbol_count(tree)
    if count > limits["hardSymbols"]:
        blockers.append(
            {
                "code": "architecture-hard-symbol-limit-exceeded",
                "path": path.as_posix(),
                "actualSymbols": count,
                "maxSymbols": limits["hardSymbols"],
            }
        )
    functions = []
    is_cli = is_cli_path(path, root)
    target = limits["cliTargetFunctionLines" if is_cli else "targetFunctionLines"]
    hard = limits["cliHardFunctionLines" if is_cli else "hardFunctionLines"]
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        length = (node.end_lineno or node.lineno) - node.lineno + 1
        record = {"path": path.as_posix(), "name": node.name, "line": node.lineno, "lines": length}
        functions.append(record)
        errors, notices = _line_findings(record, length, target, hard, "function")
        blockers.extend(errors)
        warnings.extend(notices)
    return {
        "file": {"path": path.as_posix(), "lines": lines, "identity": file_identity(path)},
        "functions": functions,
        "symbol": {"path": path.as_posix(), "count": count},
        "branches": function_branch_records(tree, path.relative_to(root).as_posix()),
        "blockers": blockers,
        "warnings": warnings,
    }


def main() -> int:
    args = _arguments()
    root = Path(args.package_root)
    blockers: list[dict[str, Any]] = []
    measurements: list[dict[str, Any]] = []
    limits: dict[str, int] = {}
    policy: dict[str, Any] = {}
    try:
        policy = load_architecture_limits(args.policy)
        limits = _limits(args, policy)
        if not root.is_dir():
            blockers.append({"code": "architecture-package-root-missing", "path": root.as_posix()})
        else:
            measurements = [_measure_file(path, root, limits) for path in sorted(root.rglob("*.py"))]
    except (OSError, ValueError, KeyError, TypeError, SyntaxError) as exc:
        blockers.append({"code": "architecture-policy-or-source-invalid", "message": str(exc)})
    body = _report(root, limits, policy, measurements, blockers, args.policy)
    write_json(Path(args.evidence), {**body, "validationDigest": digest_value(body)})
    return 0 if body["status"] == "PASS" else 1


def _report(
    root: Path,
    limits: dict[str, int],
    policy: dict[str, Any],
    measurements: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    policy_path: Path,
) -> dict[str, Any]:
    branches = [row for item in measurements for row in item["branches"]]
    if measurements:
        blockers.extend(branch_findings(branches, policy))
    blockers.extend(row for item in measurements for row in item["blockers"])
    warnings = [row for item in measurements for row in item["warnings"]]
    body = {
        "schemaVersion": "agent-architecture-complexity-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "packageRoot": root.as_posix(),
        "limits": limits,
        "policyIdentity": file_identity(policy_path) if policy_path.is_file() else None,
        "files": [item["file"] for item in measurements],
        "functions": [row for item in measurements for row in item["functions"]],
        "symbols": [item["symbol"] for item in measurements],
        "branches": branches,
        "branchBaselineDigest": policy.get("branchBaselineDigest"),
        "blockers": blockers,
        "warnings": warnings,
        "limitSemantics": LIMIT_SEMANTICS,
        "targetFileConformance": "EXCEEDED"
        if any(row["code"] == "architecture-file-target-exceeded" for row in warnings)
        else "PASS",
        "targetFunctionConformance": "EXCEEDED"
        if any(row["code"] == "architecture-function-target-exceeded" for row in warnings)
        else "PASS",
        "hardLimitConformance": "FAIL" if blockers else "PASS",
        "productionPromotionClaimed": False,
    }
    return body


def _top_level_symbol_count(tree: ast.AST) -> int:
    count = 0
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            count += 1
        elif isinstance(node, ast.Assign):
            count += len(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            count += 1
    return count


if __name__ == "__main__":
    raise SystemExit(main())

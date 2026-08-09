from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Any

from release_common import digest_value, file_identity, write_json

REQUIRED_COUNTERS = {
    "findings",
    "skippedInputs",
    "opaqueInputs",
    "readRaces",
    "incompleteScans",
    "unsupportedArchives",
    "archiveLimitBreaches",
    "occupiedOutputConflicts",
    "pathAliasConflicts",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    root = Path(args.path)
    receipt_path = root / "receipt.py" if root.is_dir() else root
    cli_path = root / "cli.py" if root.is_dir() else root.with_name("cli.py")
    blockers = _validate_sources(receipt_path, cli_path)
    body = {
        "schemaVersion": "agent-neutrality-receipt-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "receipt": file_identity(receipt_path) if receipt_path.exists() else None,
        "cli": file_identity(cli_path) if cli_path.exists() else None,
        "requiredCounters": sorted(REQUIRED_COUNTERS),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.evidence), {**body, "validationDigest": digest_value(body)})
    return 0 if not blockers else 1


def _validate_sources(receipt_path: Path, cli_path: Path) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if not receipt_path.exists():
        return [{"code": "neutrality-receipt-source-missing", "path": receipt_path.as_posix()}]
    if not cli_path.exists():
        return [{"code": "neutrality-cli-source-missing", "path": cli_path.as_posix()}]
    receipt_tree = ast.parse(receipt_path.read_text(encoding="utf-8"), filename=receipt_path.as_posix())
    cli_tree = ast.parse(cli_path.read_text(encoding="utf-8"), filename=cli_path.as_posix())
    counters = _declared_counter_names(receipt_tree)
    if counters != REQUIRED_COUNTERS:
        blockers.append({"code": "neutrality-completeness-counter-set", "actual": sorted(counters), "expected": sorted(REQUIRED_COUNTERS)})
    for function_name in ("build_claims", "verify_existing_receipt"):
        if not _function_calls(receipt_tree, function_name, "require_zero_completeness_counters"):
            blockers.append({"code": "neutrality-completeness-gate-missing", "function": function_name})
    if not _function_calls(cli_tree, "_bootstrap", "require_zero_completeness_counters"):
        blockers.append({"code": "neutrality-bootstrap-completeness-gate-missing"})
    return blockers


def _declared_counter_names(tree: ast.AST) -> set[str]:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "REQUIRED_COMPLETENESS_COUNTERS" for target in node.targets):
            if isinstance(node.value, (ast.Tuple, ast.List)):
                return {item.value for item in node.value.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)}
    return set()


def _function_calls(tree: ast.AST, function_name: str, call_name: str) -> bool:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == call_name:
                    return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())

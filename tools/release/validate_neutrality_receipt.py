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
    authority_path = root / "authority.py" if root.is_dir() else root.with_name("authority.py")
    blockers = _validate_sources(receipt_path, cli_path, authority_path)
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


def _validate_sources(receipt_path: Path, cli_path: Path, authority_path: Path) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if not receipt_path.exists():
        return [{"code": "neutrality-receipt-source-missing", "path": receipt_path.as_posix()}]
    if not cli_path.exists():
        return [{"code": "neutrality-cli-source-missing", "path": cli_path.as_posix()}]
    authority_tree: ast.AST | None = None
    if not authority_path.exists():
        blockers.append({"code": "neutrality-authority-source-missing", "path": authority_path.as_posix()})
    else:
        authority_tree = ast.parse(authority_path.read_text(encoding="utf-8"), filename=authority_path.as_posix())
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
    for literal in (
        "agent-neutrality-claims.v4",
        "agent-neutrality-receipt-envelope.v4",
        "agent-neutrality-detached-receipt.v4",
    ):
        if not _module_contains_literal(receipt_tree, literal):
            blockers.append({"code": "neutrality-v4-schema-missing", "value": literal})
    for function_name, required_literals in {
        "build_receipt": ("operation", "claims", "primaryArtifact", "signature"),
        "verify_existing_receipt": ("operation", "claims", "primaryArtifact", "signature"),
    }.items():
        for literal in required_literals:
            if not _function_contains_literal(receipt_tree, function_name, literal):
                blockers.append({"code": "neutrality-envelope-binding-missing", "function": function_name, "value": literal})
    if not _function_references_name(receipt_tree, "build_receipt", "canonical_bytes"):
        blockers.append({"code": "neutrality-envelope-canonicalization-missing", "function": "build_receipt"})
    if not _function_references_name(receipt_tree, "verify_existing_receipt", "canonical_bytes"):
        blockers.append({"code": "neutrality-envelope-canonicalization-missing", "function": "verify_existing_receipt"})
    if not _function_references_name(receipt_tree, "verify_existing_receipt", "RECEIPT_V4_DOMAIN"):
        blockers.append({"code": "neutrality-envelope-domain-missing"})
    if authority_tree is not None and not _function_calls(authority_tree, "sign_receipt_envelope", "canonical_bytes"):
        blockers.append({"code": "neutrality-authority-envelope-signing-missing"})
    if not _function_references_name(cli_tree, "_bootstrap", "sign_receipt_envelope"):
        blockers.append({"code": "neutrality-cli-envelope-signing-missing"})
    return blockers


def _declared_counter_names(tree: ast.AST) -> set[str]:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "REQUIRED_COMPLETENESS_COUNTERS" for target in node.targets):
            if isinstance(node.value, (ast.Tuple, ast.List)):
                return {item.value for item in node.value.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)}
    return set()


def _function_calls(tree: ast.AST, function_name: str, call_name: str) -> bool:
    for function in _function_nodes(tree, function_name):
        for child in ast.walk(function):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == call_name:
                return True
    return False


def _module_contains_literal(tree: ast.AST, value: str) -> bool:
    return any(isinstance(node, ast.Constant) and node.value == value for node in ast.walk(tree))


def _function_contains_literal(tree: ast.AST, function_name: str, value: str) -> bool:
    return any(
        isinstance(child, ast.Constant) and child.value == value
        for function in _function_nodes(tree, function_name)
        for child in ast.walk(function)
    )


def _function_references_name(tree: ast.AST, function_name: str, name: str) -> bool:
    for function in _function_nodes(tree, function_name):
        for node in ast.walk(function):
            if isinstance(node, ast.Name) and node.id == name:
                return True
            if isinstance(node, ast.Attribute) and node.attr == name:
                return True
    return False


def _function_nodes(tree: ast.AST, function_name: str) -> list[ast.AST]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
    ]


if __name__ == "__main__":
    raise SystemExit(main())

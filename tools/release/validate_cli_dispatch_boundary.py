from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Any

from release_common import digest_value, file_identity, write_json


REQUIRED_DELEGATES = {
    "dispatch_adapters": "agent_lifecycle.cli.dispatch_adapters",
    "dispatch_contracts": "agent_lifecycle.cli.dispatch_contracts",
    "dispatch_lifecycle": "agent_lifecycle.cli.dispatch_lifecycle",
    "dispatch_observability": "agent_lifecycle.cli.dispatch_observability",
    "dispatch_planning": "agent_lifecycle.cli.dispatch_planning",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--max-lines", required=True, type=int)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    path = Path(args.path)
    blockers: list[dict[str, Any]] = []
    if not path.is_file():
        blockers.append({"code": "cli-dispatch-path-missing", "path": path.as_posix()})
        body = _body(path, args.max_lines, None, [], [], blockers)
        write_json(Path(args.evidence), {**body, "validationDigest": digest_value(body)})
        return 1

    source = path.read_text(encoding="utf-8")
    line_count = len(source.splitlines())
    if args.max_lines < 1:
        blockers.append({"code": "cli-dispatch-invalid-line-limit", "maxLines": args.max_lines})
    elif line_count > args.max_lines:
        blockers.append(
            {
                "code": "cli-dispatch-line-limit-exceeded",
                "path": path.as_posix(),
                "actualLines": line_count,
                "maxLines": args.max_lines,
            }
        )

    tree = ast.parse(source, filename=path.as_posix())
    imported_delegates = _imported_delegates(tree)
    routed_delegates = _routed_delegates(tree)
    missing_imports = sorted(set(REQUIRED_DELEGATES).difference(imported_delegates))
    missing_routes = sorted(set(REQUIRED_DELEGATES).difference(routed_delegates))
    if missing_imports:
        blockers.append({"code": "cli-dispatch-delegate-import-missing", "delegates": missing_imports})
    if missing_routes:
        blockers.append({"code": "cli-dispatch-delegate-route-missing", "delegates": missing_routes})
    if any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("_dispatch_")
        for node in tree.body
    ):
        blockers.append({"code": "cli-dispatch-domain-handler-retained", "path": path.as_posix()})

    body = _body(path, args.max_lines, line_count, sorted(imported_delegates), sorted(routed_delegates), blockers)
    write_json(Path(args.evidence), {**body, "validationDigest": digest_value(body)})
    return 0 if not blockers else 1


def _imported_delegates(tree: ast.AST) -> set[str]:
    imported: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        for name, module in REQUIRED_DELEGATES.items():
            if node.module == module and any(alias.name == name for alias in node.names):
                imported.add(name)
    return imported


def _routed_delegates(tree: ast.AST) -> set[str]:
    routed: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id in REQUIRED_DELEGATES:
            routed.add(node.func.id)
    return routed


def _body(
    path: Path,
    max_lines: int,
    line_count: int | None,
    imported_delegates: list[str],
    routed_delegates: list[str],
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schemaVersion": "agent-cli-dispatch-boundary-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "path": path.as_posix(),
        "file": file_identity(path) if path.is_file() else None,
        "maxLines": max_lines,
        "actualLines": line_count,
        "requiredDelegates": REQUIRED_DELEGATES,
        "importedDelegates": imported_delegates,
        "routedDelegates": routed_delegates,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())

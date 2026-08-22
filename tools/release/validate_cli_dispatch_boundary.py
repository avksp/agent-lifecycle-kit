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
    "dispatch_research": "agent_lifecycle.cli.dispatch_research",
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
        role = _dispatch_role(path)
        required_delegates = REQUIRED_DELEGATES if role == "root" else {}
        body = _body(path, args.max_lines, None, role, required_delegates, [], [], blockers)
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
    role = _dispatch_role(path)
    required_delegates = REQUIRED_DELEGATES if role == "root" else {}
    registry_delegates = _registry_delegates(path, required_delegates)
    if registry_delegates is None:
        imported_delegates = _imported_delegates(tree, required_delegates)
        routed_delegates = _routed_delegates(tree, required_delegates)
    else:
        imported_delegates = registry_delegates
        routed_delegates = registry_delegates
    missing_imports = sorted(set(required_delegates).difference(imported_delegates))
    missing_routes = sorted(set(required_delegates).difference(routed_delegates))
    if missing_imports:
        blockers.append({"code": "cli-dispatch-delegate-import-missing", "delegates": missing_imports})
    if missing_routes:
        blockers.append({"code": "cli-dispatch-delegate-route-missing", "delegates": missing_routes})
    if role == "root" and any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("_dispatch_")
        for node in tree.body
    ):
        blockers.append({"code": "cli-dispatch-domain-handler-retained", "path": path.as_posix()})
    if role == "observability" and not _has_top_level_function(tree, "dispatch_observability"):
        blockers.append({"code": "cli-dispatch-entrypoint-missing", "path": path.as_posix(), "entrypoint": "dispatch_observability"})
    if role == "planning" and not _has_top_level_function(tree, "dispatch_planning"):
        blockers.append({"code": "cli-dispatch-entrypoint-missing", "path": path.as_posix(), "entrypoint": "dispatch_planning"})
    if role == "unknown":
        blockers.append({"code": "cli-dispatch-role-unknown", "path": path.as_posix()})

    body = _body(
        path,
        args.max_lines,
        line_count,
        role,
        required_delegates,
        sorted(imported_delegates),
        sorted(routed_delegates),
        blockers,
    )
    write_json(Path(args.evidence), {**body, "validationDigest": digest_value(body)})
    return 0 if not blockers else 1


def _dispatch_role(path: Path) -> str:
    if path.name == "dispatch.py":
        return "root"
    if path.name == "dispatch_observability.py":
        return "observability"
    if path.name == "dispatch_planning.py":
        return "planning"
    return "unknown"


def _has_top_level_function(tree: ast.AST, name: str) -> bool:
    return any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name for node in tree.body)


def _imported_delegates(tree: ast.AST, required_delegates: dict[str, str]) -> set[str]:
    imported: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        for name, module in required_delegates.items():
            if node.module == module and any(alias.name == name for alias in node.names):
                imported.add(name)
    return imported


def _routed_delegates(tree: ast.AST, required_delegates: dict[str, str]) -> set[str]:
    routed: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id in required_delegates:
            routed.add(node.func.id)
    return routed


def _registry_delegates(path: Path, required_delegates: dict[str, str]) -> set[str] | None:
    """Read lazy delegate bindings from a sibling command registry when present."""
    if not required_delegates:
        return None
    registry_path = path.with_name("command_registry.py")
    if not registry_path.is_file():
        return None
    try:
        tree = ast.parse(registry_path.read_text(encoding="utf-8"), filename=registry_path.as_posix())
    except (OSError, SyntaxError):
        return None
    delegates: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for value in node.values:
            if not isinstance(value, ast.Tuple) or len(value.elts) < 2:
                continue
            module, function = value.elts[0], value.elts[1]
            if not isinstance(module, ast.Constant) or not isinstance(module.value, str):
                continue
            if not isinstance(function, ast.Constant) or not isinstance(function.value, str):
                continue
            for name, required_module in required_delegates.items():
                if module.value == required_module and function.value == name:
                    delegates.add(name)
    return delegates


def _body(
    path: Path,
    max_lines: int,
    line_count: int | None,
    role: str,
    required_delegates: dict[str, str],
    imported_delegates: list[str],
    routed_delegates: list[str],
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schemaVersion": "agent-cli-dispatch-boundary-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "path": path.as_posix(),
        "file": file_identity(path) if path.is_file() else None,
        "role": role,
        "maxLines": max_lines,
        "actualLines": line_count,
        "requiredDelegates": required_delegates,
        "importedDelegates": imported_delegates,
        "routedDelegates": routed_delegates,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())

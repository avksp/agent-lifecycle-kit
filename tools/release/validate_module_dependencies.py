from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Any

from release_common import digest_value, file_identity, write_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--forbid-cycle", action="append", default=[])
    parser.add_argument("--max-lines", action="append", default=[])
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    package_root = Path(args.package_root)
    graph, identities = _build_graph(package_root)
    blockers: list[dict[str, Any]] = []
    forbidden_cycles = [_parse_cycle(value) for value in args.forbid_cycle]
    for cycle in forbidden_cycles:
        if _nodes_share_cycle(graph, cycle):
            blockers.append({"code": "module-import-cycle", "modules": cycle})
    line_checks = []
    for value in args.max_lines:
        path, maximum = _parse_line_check(value)
        count = len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else None
        line_checks.append({"path": path.as_posix(), "maxLines": maximum, "actualLines": count})
        if count is None:
            blockers.append({"code": "module-line-check-path-missing", "path": path.as_posix()})
        elif count > maximum:
            blockers.append({"code": "module-line-limit-exceeded", "path": path.as_posix(), "actualLines": count, "maxLines": maximum})
    body = {
        "schemaVersion": "agent-module-dependency-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "moduleCount": len(graph),
        "sourceFiles": identities,
        "forbiddenCycles": forbidden_cycles,
        "lineChecks": line_checks,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.evidence), {**body, "validationDigest": digest_value(body)})
    return 0 if not blockers else 1


def _build_graph(package_root: Path) -> tuple[dict[str, set[str]], list[dict[str, Any]]]:
    if not package_root.is_dir():
        return {}, []
    module_root = _module_root(package_root)
    graph: dict[str, set[str]] = {}
    identities: list[dict[str, Any]] = []
    for path in sorted(package_root.rglob("*.py")):
        module = _module_name(package_root, module_root, path)
        graph.setdefault(module, set())
        identities.append(file_identity(path))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        graph[module].update(_imports(tree, module))
    return graph, identities


def _module_root(package_root: Path) -> str:
    names = [package_root.name]
    parent = package_root.parent
    while (parent / "__init__.py").exists():
        names.insert(0, parent.name)
        parent = parent.parent
    return ".".join(names)


def _module_name(package_root: Path, module_root: str, path: Path) -> str:
    relative = path.relative_to(package_root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join([module_root, *parts]) if parts else module_root


def _imports(tree: ast.AST, module: str) -> set[str]:
    imports: set[str] = set()
    package = module.rsplit(".", 1)[0] if "." in module else module
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names if alias.name.startswith("agent_lifecycle"))
        elif isinstance(node, ast.ImportFrom):
            target = _resolve_from_import(module, package, node)
            if target and target.startswith("agent_lifecycle"):
                imports.add(target)
                imports.update(f"{target}.{alias.name}" for alias in node.names if alias.name != "*")
    return imports


def _resolve_from_import(module: str, package: str, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    base_parts = package.split(".")
    if node.level > len(base_parts):
        return None
    parent = base_parts[: len(base_parts) - node.level + 1]
    if node.module:
        parent.extend(node.module.split("."))
    return ".".join(parent)


def _parse_cycle(value: str) -> list[str]:
    modules = [item.strip() for item in value.split(",") if item.strip()]
    if len(modules) < 2:
        raise SystemExit("--forbid-cycle must contain at least two comma-separated modules")
    return modules


def _parse_line_check(value: str) -> tuple[Path, int]:
    path_text, separator, limit_text = value.rpartition("=")
    if not separator or not path_text or not limit_text.isdigit() or int(limit_text) < 1:
        raise SystemExit("--max-lines must use PATH=POSITIVE_INTEGER")
    return Path(path_text), int(limit_text)


def _nodes_share_cycle(graph: dict[str, set[str]], nodes: list[str]) -> bool:
    return all(_reachable(graph, source, target) for source in nodes for target in nodes if source != target)


def _reachable(graph: dict[str, set[str]], source: str, target: str) -> bool:
    pending = [source]
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current == target:
            return True
        if current in visited:
            continue
        visited.add(current)
        pending.extend(graph.get(current, set()).difference(visited))
    return False


if __name__ == "__main__":
    raise SystemExit(main())

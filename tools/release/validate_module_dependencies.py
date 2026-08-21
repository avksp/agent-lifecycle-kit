from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

from release_common import digest_value, file_identity, write_json


POLICY_SCHEMA = "agent-architecture-dependencies.v1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--policy")
    parser.add_argument("--require-acyclic-modules", action="store_true")
    parser.add_argument("--require-acyclic-packages", action="store_true")
    parser.add_argument("--forbid-cycle", action="append", default=[])
    parser.add_argument("--max-lines", action="append", default=[])
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    package_root = Path(args.package_root)
    blockers: list[dict[str, Any]] = []
    policy: dict[str, Any] = {}
    if args.policy:
        try:
            policy = _load_policy(Path(args.policy))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            blockers.append({"code": "architecture-policy-invalid", "path": args.policy, "message": str(exc)})

    graph, identities, module_paths = _build_graph(package_root)
    package_graph = _package_graph(graph, package_root)
    module_sccs = _strongly_connected_components(graph)
    package_sccs = _strongly_connected_components(package_graph)

    if args.require_acyclic_modules:
        blockers.extend({"code": "module-import-cycle", "modules": cycle} for cycle in module_sccs)
    if args.require_acyclic_packages:
        blockers.extend({"code": "package-import-cycle", "packages": cycle} for cycle in package_sccs)

    layer_policy = _layer_policy_result(graph, package_root, policy, module_paths)
    blockers.extend(layer_policy["blockers"])

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
            blockers.append(
                {"code": "module-line-limit-exceeded", "path": path.as_posix(), "actualLines": count, "maxLines": maximum}
            )

    body = {
        "schemaVersion": "agent-module-dependency-validation.v2",
        "status": "PASS" if not blockers else "FAIL",
        "moduleCount": len(graph),
        "packageCount": len(package_graph),
        "sourceFiles": identities,
        "moduleSccs": module_sccs,
        "packageSccs": package_sccs,
        "packageEdges": _edges(package_graph),
        "layerPolicy": layer_policy,
        "policy": policy,
        "forbiddenCycles": forbidden_cycles,
        "lineChecks": line_checks,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.evidence), {**body, "validationDigest": digest_value(body)})
    return 0 if not blockers else 1


def _load_policy(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schemaVersion") != POLICY_SCHEMA:
        raise ValueError(f"expected {POLICY_SCHEMA}")
    return value


def _build_graph(package_root: Path) -> tuple[dict[str, set[str]], list[dict[str, Any]], dict[str, Path]]:
    if not package_root.is_dir():
        return {}, [], {}
    module_root = _module_root(package_root)
    paths = sorted(package_root.rglob("*.py"))
    module_paths = {_module_name(package_root, module_root, path): path for path in paths}
    graph: dict[str, set[str]] = {module: set() for module in module_paths}
    identities: list[dict[str, Any]] = []
    for module, path in sorted(module_paths.items()):
        identities.append(file_identity(path))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        graph[module].update(_imports(tree, module, set(module_paths)))
    return graph, identities, module_paths


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
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join([module_root, *parts]) if parts else module_root


def _imports(tree: ast.AST, module: str, modules: set[str]) -> set[str]:
    imports: set[str] = set()
    package = module.rsplit(".", 1)[0] if "." in module else module
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = _normalize_target(alias.name, modules)
                if target:
                    imports.add(target)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from_import(module, package, node)
            if not base:
                continue
            target = _normalize_target(base, modules)
            if target:
                imports.add(target)
            for alias in node.names:
                if alias.name == "*":
                    continue
                candidate = _normalize_target(f"{base}.{alias.name}", modules)
                if candidate:
                    imports.add(candidate)
    return imports


def _normalize_target(target: str | None, modules: set[str]) -> str | None:
    if not target or not target.startswith("agent_lifecycle"):
        return None
    parts = target.split(".")
    while parts:
        candidate = ".".join(parts)
        if candidate in modules:
            return candidate
        parts.pop()
    return None


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


def _package_graph(graph: dict[str, set[str]], package_root: Path) -> dict[str, set[str]]:
    root = _module_root(package_root)
    result: dict[str, set[str]] = {}
    for module, imports in graph.items():
        source = _package_name(module, root)
        result.setdefault(source, set())
        for target in imports:
            result[source].add(_package_name(target, root))
    return result


def _package_name(module: str, root: str) -> str:
    if module == root:
        return root
    parts = module.split(".")
    if len(parts) == 2 and parts[1] in {"__main__", "_version"}:
        return parts[1]
    return parts[1] if len(parts) > 1 else module


def _edges(graph: dict[str, set[str]]) -> list[dict[str, str]]:
    return [{"from": source, "to": target} for source in sorted(graph) for target in sorted(graph[source])]


def _strongly_connected_components(graph: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in sorted(graph.get(node, set())):
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] != indices[node]:
            return
        component: list[str] = []
        while True:
            target = stack.pop()
            on_stack.remove(target)
            component.append(target)
            if target == node:
                break
        if len(component) > 1:
            components.append(sorted(component))

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return sorted(components)


def _layer_policy_result(
    graph: dict[str, set[str]],
    package_root: Path,
    policy: dict[str, Any],
    module_paths: dict[str, Path],
) -> dict[str, Any]:
    root = _module_root(package_root)
    package_levels = policy.get("packageLevels", {}) if isinstance(policy.get("packageLevels"), dict) else {}
    module_levels = policy.get("moduleLevels", {}) if isinstance(policy.get("moduleLevels"), dict) else {}
    violations: list[dict[str, Any]] = []
    unclassified: list[str] = []
    for source in sorted(graph):
        source_level = _level(source, root, package_levels, module_levels)
        if source_level is None:
            unclassified.append(source)
            continue
        for target in sorted(graph[source]):
            target_level = _level(target, root, package_levels, module_levels)
            if target_level is None:
                unclassified.append(target)
            elif source_level < target_level:
                violations.append(
                    {"from": source, "to": target, "fromLevel": source_level, "toLevel": target_level}
                )
    blockers = []
    if policy:
        if unclassified:
            blockers.append({"code": "architecture-layer-unclassified", "modules": sorted(set(unclassified))})
        if violations:
            blockers.append({"code": "architecture-layer-violation", "edges": violations})
    return {
        "schemaVersion": POLICY_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "packageLevels": package_levels,
        "moduleLevels": module_levels,
        "violations": violations,
        "unclassified": sorted(set(unclassified)),
        "blockers": blockers,
        "modulePathCount": len(module_paths),
    }


def _level(module: str, root: str, package_levels: dict[str, Any], module_levels: dict[str, Any]) -> int | None:
    value = module_levels.get(module)
    if value is None:
        value = package_levels.get(_package_name(module, root))
    return value if isinstance(value, int) and not isinstance(value, bool) else None


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

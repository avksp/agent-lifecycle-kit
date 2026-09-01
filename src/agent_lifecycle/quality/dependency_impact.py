"""Canonical Python module graph and conservative dependency impact helpers."""

from __future__ import annotations

import ast
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, sha256_hex
from agent_lifecycle.contracts.paths import normalize_repo_path

MODULE_DEPENDENCY_REPORT_SCHEMA = "agent-module-dependency-report.v1"


def build_module_dependency_report(package_root: Path, *, repository_root: Path | None = None) -> dict[str, Any]:
    """Build a digest-bound complete graph for one Python package tree."""

    graph, source_files, _ = build_dependency_graph(package_root, repository_root=repository_root)
    body = {
        "schemaVersion": MODULE_DEPENDENCY_REPORT_SCHEMA,
        "status": "PASS",
        "moduleRoot": module_root(package_root),
        "graphComplete": True,
        "moduleCount": len(graph),
        "sourceFiles": source_files,
        "moduleEdges": graph_edges(graph),
        "blockers": [],
        "productionPromotionClaimed": False,
    }
    return {**body, "reportDigest": canonical_digest(body)}


def validate_module_dependency_report(report: dict[str, Any]) -> dict[str, Any]:
    """Validate report shape, identities, graph closure, and self-digest."""

    blockers: list[dict[str, Any]] = []
    if report.get("schemaVersion") != MODULE_DEPENDENCY_REPORT_SCHEMA:
        blockers.append({"code": "dependency-report-schema-invalid"})
    if report.get("status") != "PASS" or report.get("graphComplete") is not True:
        blockers.append({"code": "dependency-report-incomplete"})
    source_files = report.get("sourceFiles")
    modules: set[str] = set()
    paths: set[str] = set()
    if not isinstance(source_files, list):
        blockers.append({"code": "dependency-report-sources-invalid"})
        source_files = []
    for item in source_files:
        if not _valid_source_identity(item):
            blockers.append({"code": "dependency-report-source-invalid"})
            continue
        if item["module"] in modules or item["path"] in paths:
            blockers.append({"code": "dependency-report-source-duplicate"})
        modules.add(item["module"])
        paths.add(item["path"])
    if report.get("moduleCount") != len(modules):
        blockers.append({"code": "dependency-report-module-count"})
    edges = report.get("moduleEdges")
    seen_edges: set[tuple[str, str]] = set()
    if not isinstance(edges, list):
        blockers.append({"code": "dependency-report-edges-invalid"})
        edges = []
    for item in edges:
        if (
            not isinstance(item, dict)
            or set(item) != {"from", "to"}
            or item.get("from") not in modules
            or item.get("to") not in modules
            or item.get("from") == item.get("to")
        ):
            blockers.append({"code": "dependency-report-edge-invalid"})
            continue
        edge = (item["from"], item["to"])
        if edge in seen_edges:
            blockers.append({"code": "dependency-report-edge-duplicate"})
        seen_edges.add(edge)
    body = {key: value for key, value in report.items() if key != "reportDigest"}
    if report.get("reportDigest") != canonical_digest(body):
        blockers.append({"code": "dependency-report-digest-mismatch"})
    if report.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "dependency-report-production-claim"})
    result = {
        "schemaVersion": "agent-module-dependency-report-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "moduleCount": len(modules),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**result, "validationDigest": canonical_digest(result)}


def build_dependency_graph(
    package_root: Path,
    *,
    repository_root: Path | None = None,
) -> tuple[dict[str, set[str]], list[dict[str, Any]], dict[str, Path]]:
    """Parse all Python sources under package_root into one closed graph."""

    package_root = package_root.resolve()
    if not package_root.is_dir():
        return {}, [], {}
    identity_root = repository_root.resolve() if repository_root is not None else package_root.parent
    if not package_root.is_relative_to(identity_root):
        raise LifecycleError("dependency-report-root-invalid", "package root must be inside repository root")
    root_name = module_root(package_root)
    paths = sorted(package_root.rglob("*.py"))
    module_paths = {module_name(package_root, root_name, path): path for path in paths}
    modules = set(module_paths)
    graph: dict[str, set[str]] = {module: set() for module in modules}
    source_files: list[dict[str, Any]] = []
    for module, path in sorted(module_paths.items()):
        data = path.read_bytes()
        display_path = path.relative_to(identity_root).as_posix()
        source_files.append(
            {
                "module": module,
                "path": display_path,
                "sha256": sha256_hex(data),
                "bytes": len(data),
            }
        )
        tree = ast.parse(data.decode("utf-8"), filename=path.as_posix())
        graph[module].update(target for target in imports_for_tree(tree, module, modules) if target != module)
    return graph, source_files, module_paths


def graph_from_report(report: dict[str, Any]) -> dict[str, set[str]]:
    """Return a graph only from a valid complete dependency report."""

    validation = validate_module_dependency_report(report)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "dependency-report-invalid",
            "module dependency report failed validation",
            {"validation": validation},
        )
    modules = {item["module"] for item in report["sourceFiles"]}
    graph: dict[str, set[str]] = {module: set() for module in modules}
    for edge in report["moduleEdges"]:
        graph[edge["from"]].add(edge["to"])
    return graph


def module_paths_from_report(report: dict[str, Any]) -> dict[str, str]:
    """Map canonical source paths to modules from a validated report."""

    graph_from_report(report)
    return {item["path"]: item["module"] for item in report["sourceFiles"]}


def transitive_dependents(graph: dict[str, set[str]], modules: set[str]) -> set[str]:
    """Expand changed modules to every module that can import them transitively."""

    reverse: dict[str, set[str]] = {module: set() for module in graph}
    for source, targets in graph.items():
        for target in targets:
            reverse.setdefault(target, set()).add(source)
    impacted = set(modules)
    pending = list(modules)
    while pending:
        current = pending.pop()
        for dependent in reverse.get(current, set()):
            if dependent not in impacted:
                impacted.add(dependent)
                pending.append(dependent)
    return impacted


def package_dependency_graph(graph: dict[str, set[str]], package_root: Path) -> dict[str, set[str]]:
    root_name = module_root(package_root)
    result: dict[str, set[str]] = {}
    for module, imports in graph.items():
        source = package_name(module, root_name)
        result.setdefault(source, set())
        for target in imports:
            target_package = package_name(target, root_name)
            if target_package != source:
                result[source].add(target_package)
    return result


def graph_edges(graph: dict[str, set[str]]) -> list[dict[str, str]]:
    return [{"from": source, "to": target} for source in sorted(graph) for target in sorted(graph[source])]


def strongly_connected_components(graph: dict[str, set[str]]) -> list[list[str]]:
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


def module_root(package_root: Path) -> str:
    names = [package_root.name]
    parent = package_root.parent
    while (parent / "__init__.py").exists():
        names.insert(0, parent.name)
        parent = parent.parent
    return ".".join(names)


def module_name(package_root: Path, root_name: str, path: Path) -> str:
    relative = path.relative_to(package_root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join([root_name, *parts]) if parts else root_name


def package_name(module: str, root_name: str) -> str:
    if module == root_name:
        return root_name
    parts = module.split(".")
    if len(parts) == 2 and parts[1] in {"__main__", "_version"}:
        return parts[1]
    return parts[1] if len(parts) > 1 else module


def imports_for_tree(tree: ast.AST, module: str, modules: set[str]) -> set[str]:
    imports: set[str] = set()
    package = module.rsplit(".", 1)[0] if "." in module else module
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = _normalize_target(alias.name, modules)
                if target:
                    imports.add(target)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from_import(package, node)
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
    if not target:
        return None
    parts = target.split(".")
    while parts:
        candidate = ".".join(parts)
        if candidate in modules:
            return candidate
        parts.pop()
    return None


def _resolve_from_import(package: str, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    base_parts = package.split(".")
    if node.level > len(base_parts):
        return None
    parent = base_parts[: len(base_parts) - node.level + 1]
    if node.module:
        parent.extend(node.module.split("."))
    return ".".join(parent)


def _valid_source_identity(value: Any) -> bool:
    if not (
        isinstance(value, dict)
        and set(value) == {"module", "path", "sha256", "bytes"}
        and isinstance(value.get("module"), str)
        and bool(value["module"])
        and isinstance(value.get("path"), str)
        and bool(value["path"])
        and _is_digest(value.get("sha256"))
        and isinstance(value.get("bytes"), int)
        and not isinstance(value.get("bytes"), bool)
        and value["bytes"] >= 0
    ):
        return False
    source_path = value["path"]
    if PurePosixPath(source_path).is_absolute() or PureWindowsPath(source_path).is_absolute():
        return False
    try:
        return normalize_repo_path(source_path, label="dependency source") == source_path
    except LifecycleError:
        return False


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


__all__ = [
    "MODULE_DEPENDENCY_REPORT_SCHEMA",
    "build_dependency_graph",
    "build_module_dependency_report",
    "graph_edges",
    "graph_from_report",
    "module_paths_from_report",
    "module_root",
    "package_dependency_graph",
    "package_name",
    "strongly_connected_components",
    "transitive_dependents",
    "validate_module_dependency_report",
]

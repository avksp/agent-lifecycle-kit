"""Canonical Python module graph and conservative dependency impact helpers."""

from __future__ import annotations

import ast
from itertools import product
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, sha256_hex
from agent_lifecycle.contracts.paths import normalize_repo_path

MODULE_DEPENDENCY_REPORT_SCHEMA = "agent-module-dependency-report.v1"


def build_module_dependency_report(package_root: Path, *, repository_root: Path | None = None) -> dict[str, Any]:
    """Build a digest-bound graph, reporting unresolved dynamic imports."""

    graph, source_files, _, blockers = _dependency_graph(package_root, repository_root=repository_root)
    body = {
        "schemaVersion": MODULE_DEPENDENCY_REPORT_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "moduleRoot": module_root(package_root),
        "graphComplete": not blockers,
        "moduleCount": len(graph),
        "sourceFiles": source_files,
        "moduleEdges": graph_edges(graph),
        "blockers": blockers,
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
    if not isinstance(report.get("blockers"), list) or report["blockers"]:
        blockers.append({"code": "dependency-report-blockers-present"})
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
    """Return the legacy graph tuple only when dynamic coverage is complete."""
    graph, sources, paths, blockers = _dependency_graph(package_root, repository_root=repository_root)
    if blockers:
        raise LifecycleError("dependency-graph-incomplete", "dynamic imports remain unresolved", {"blockers": blockers})
    return graph, sources, paths


def _dependency_graph(
    package_root: Path,
    *,
    repository_root: Path | None,
) -> tuple[dict[str, set[str]], list[dict[str, Any]], dict[str, Path], list[dict[str, Any]]]:

    package_root = package_root.resolve()
    if not package_root.is_dir():
        return {}, [], {}, [{"code": "dependency-report-package-missing"}]
    identity_root = repository_root.resolve() if repository_root is not None else package_root.parent
    if not package_root.is_relative_to(identity_root):
        raise LifecycleError("dependency-report-root-invalid", "package root must be inside repository root")
    root_name = module_root(package_root)
    paths = sorted(package_root.rglob("*.py"))
    module_paths = {module_name(package_root, root_name, path): path for path in paths}
    modules = set(module_paths)
    graph: dict[str, set[str]] = {module: set() for module in modules}
    source_files: list[dict[str, Any]] = []
    trees: dict[str, ast.AST] = {}
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
        trees[module] = ast.parse(data.decode("utf-8"), filename=path.as_posix())
        graph[module].update(
            target
            for target in imports_for_tree(trees[module], module, modules, is_package=path.name == "__init__.py")
            if target != module
        )
    blockers: list[dict[str, Any]] = []
    for module, tree in sorted(trees.items()):
        dynamic, missing = _dynamic_imports(tree, module, trees, module_paths)
        graph[module].update(dynamic - {module})
        blockers.extend(missing)
    return graph, source_files, module_paths, blockers


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


def imports_for_tree(tree: ast.AST, module: str, modules: set[str], *, is_package: bool = False) -> set[str]:
    imports: set[str] = set()
    package = module if is_package or "." not in module else module.rsplit(".", 1)[0]
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


def _dynamic_imports(
    tree: ast.AST,
    module: str,
    trees: dict[str, ast.AST],
    paths: dict[str, Path],
) -> tuple[set[str], list[dict[str, Any]]]:
    aliases = {"__import__": "builtin"}
    modules = {"importlib": "importlib", "builtins": "builtin"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"importlib", "builtins"}:
                    modules[alias.asname or alias.name] = "builtin" if alias.name == "builtins" else "importlib"
        if isinstance(node, ast.ImportFrom) and node.module in {"importlib", "builtins"}:
            builtin = node.module == "builtins"
            for alias in node.names:
                if alias.name == ("__import__" if builtin else "import_module"):
                    aliases[alias.asname or alias.name] = "builtin" if builtin else "importlib"
    # Assignment aliases must not hide a dynamic importer from completeness.
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and (kind := _dynamic_callee(node.value, aliases, modules)):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id not in aliases:
                        aliases[target.id] = kind
                        changed = True
    edges: set[str] = set()
    blockers: list[dict[str, Any]] = []
    package = module if paths[module].name == "__init__.py" else module.rsplit(".", 1)[0]
    root = module.split(".")[0]
    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        func = call.func
        kind = _dynamic_callee(func, aliases, modules)
        if kind is None:
            continue
        builtin = kind == "builtin"
        bindings = _registry_bindings(tree, module, call, trees)
        argument = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == "name"), None)
        names = _string_values(argument, bindings)
        package_arg = (
            call.args[1]
            if len(call.args) > 1 and not builtin
            else next(
                (k.value for k in call.keywords if k.arg == "package"),
                None,
            )
        )
        packages = _string_values(package_arg, {"__package__": {package}})
        unsupported = builtin and _unsupported_builtin_import(call)
        unresolved = not names or unsupported or kind == "unknown"
        for name in sorted(names or []):
            if not name:
                unresolved = True
                continue
            if name.startswith("."):
                if builtin or not packages or len(packages) != 1:
                    unresolved = True
                    continue
                level = len(name) - len(name.lstrip("."))
                parts = next(iter(packages)).split(".")
                if level > len(parts):
                    unresolved = True
                    continue
                name = ".".join(parts[: len(parts) - level + 1] + ([name[level:]] if name[level:] else []))
            if name in paths:
                edges.add(name)
            elif name == root or name.startswith(root + "."):
                unresolved = True
        if unresolved:
            blockers.append({"code": "dependency-dynamic-import-unresolved", "module": module, "line": call.lineno})
    return edges, blockers


def _unsupported_builtin_import(call: ast.Call) -> bool:
    if (
        len(call.args) > 4
        or any(isinstance(argument, ast.Starred) for argument in call.args)
        or any(keyword.arg in {None, "level"} for keyword in call.keywords)
    ):
        return True
    fromlist = (
        call.args[3]
        if len(call.args) > 3
        else next((keyword.value for keyword in call.keywords if keyword.arg == "fromlist"), None)
    )
    return fromlist is not None and not (isinstance(fromlist, (ast.List, ast.Tuple)) and not fromlist.elts)


def _dynamic_callee(node: ast.AST, aliases: dict[str, str], modules: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        kind = modules.get(node.value.id)
        if kind and node.attr == ("__import__" if kind == "builtin" else "import_module"):
            return kind
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id in modules
    ):
        kind = modules[node.args[0].id]
        attribute = node.args[1]
        if not isinstance(attribute, ast.Constant):
            return "unknown"
        if attribute.value == ("__import__" if kind == "builtin" else "import_module"):
            return kind
    return None


def _registry_bindings(
    tree: ast.AST,
    module: str,
    call: ast.Call,
    trees: dict[str, ast.AST],
) -> dict[str, set[str]]:
    """Read the two existing finite registries as data, without importing code."""
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and call in ast.walk(node)
    ]
    if not functions:
        return {}
    function = functions[-1]
    root = module.split(".")[0]
    bindings: dict[str, set[str]] = {}
    if module == root + ".cli.dispatch" and function.name == "_lazy_call":
        registry = _literal_assignment(trees.get(root + ".cli.command_registry"), "COMMAND_DISPATCH")
        if (
            not isinstance(registry, dict)
            or not registry
            or any(
                not isinstance(value, (tuple, list)) or len(value) != 3 or not isinstance(value[0], str)
                for value in registry.values()
            )
        ):
            return {}
        targets = {value[0] for value in registry.values()}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_lazy_call":
                values = _string_values(node.args[0] if node.args else None, {})
                if not values:
                    return {}
                targets.update(values)
        bindings["module_name"] = targets
    elif module == root + ".host_protocol.inspection" and function.name == "_load_inspection_handler":
        handlers = _literal_assignment(trees.get(root + ".host_protocol.inspection_profile"), "INSPECTION_HANDLER_IDS")
        if (
            not isinstance(handlers, (set, frozenset, list, tuple))
            or not handlers
            or any(not isinstance(value, str) for value in handlers)
        ):
            return {}
        bindings["handler_id"] = set(handlers)
    else:
        return {}
    for statement in function.body:
        if statement.lineno >= call.lineno:
            break
        if isinstance(statement, ast.Assign):
            values = _string_values(statement.value, bindings)
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    bindings.pop(target.id, None)
                    if values:
                        bindings[target.id] = values
    return bindings


def _literal_assignment(tree: ast.AST | None, name: str) -> Any:
    if not isinstance(tree, ast.Module):
        return None
    writes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
        and any(
            isinstance(part, ast.Name) and part.id == name
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
            for part in ast.walk(target)
        )
    ]
    if len(writes) != 1:
        return None
    if any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == name
        for node in ast.walk(tree)
    ):
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            value = node.value
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "frozenset":
                if len(value.args) != 1 or value.keywords:
                    return None
                value = value.args[0]
            try:
                return ast.literal_eval(value)
            except (ValueError, TypeError, SyntaxError):
                return None
    return None


def _string_values(node: ast.AST | None, bindings: dict[str, set[str]], depth: int = 0) -> set[str] | None:
    if depth > 10:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Name):
        return bindings.get(node.id)
    if isinstance(node, ast.JoinedStr):
        pieces = [
            _string_values(v.value if isinstance(v, ast.FormattedValue) else v, bindings, depth + 1)
            for v in node.values
            if not isinstance(v, ast.FormattedValue) or (v.conversion == -1 and v.format_spec is None)
        ]
        if len(pieces) != len(node.values) or any(piece is None for piece in pieces):
            return None
        count = 1
        for piece in pieces:
            count *= len(piece or [])
        if count > 1024:
            return None
        return {"".join(parts) for parts in product(*(piece or set() for piece in pieces))}
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "replace"
        and len(node.args) == 2
        and not node.keywords
    ):
        values = _string_values(node.func.value, bindings, depth + 1)
        old, new = (_string_values(arg, {}, depth + 1) for arg in node.args)
        if values is not None and old is not None and new is not None and len(old) == len(new) == 1:
            return {value.replace(next(iter(old)), next(iter(new))) for value in values}
    return None


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

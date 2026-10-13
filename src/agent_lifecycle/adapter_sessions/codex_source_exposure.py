"""Owned codex source exposure helpers."""
from __future__ import annotations
from typing import Any
from agent_lifecycle.contracts import LifecycleError
from pathlib import Path
from agent_lifecycle.adapter_sessions.private_input import _require
from agent_lifecycle.adapter_sessions.input_lifecycle import _sha
import ast
from agent_lifecycle.contracts import canonical_bytes
import json
from agent_lifecycle.contracts.authority_io import read_authority_bytes
from agent_lifecycle.contracts import read_json_object
import shlex
import unittest
from agent_lifecycle.adapter_sessions.codex_source_subject import _r69h_check_test_dependency_closure


_R69H_SOURCE_ORACLE_SHA256 = "5f7b3cee3f074ebfbf4129bd4058d38116ef8385be20e6fbcd965158bc07a4fe"

def _source_ast_ranges(raw: bytes, *, relative: str, mode: str,
                       symbols: list[str], helpers: list[str]) -> list[dict[str, Any]]:
    """Select complete AST spans from pinned names, independent of packet writing."""
    try:
        tree = ast.parse(raw, filename=relative)
    except (SyntaxError, ValueError) as exc:
        raise LifecycleError("codex-exact-source-exposure-invalid",
                             "reviewed source cannot be parsed") from exc
    lines = raw.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    def span(node: ast.AST) -> tuple[int, int]:
        start_node = min(getattr(node, "decorator_list", []) or [node],
                         key=lambda item: (item.lineno, item.col_offset))
        return (offsets[start_node.lineno - 1] + node.col_offset,
                offsets[node.end_lineno - 1] + node.end_col_offset)

    if mode == "FULL":
        return [{"symbol": "FULL", "start": 0, "end": len(raw), "role": "CONTENT"}]
    first = next((node for node in tree.body if isinstance(
        node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))), None)
    _require(first is not None, "codex-exact-source-exposure-invalid",
             "source has no named body")
    header_end = offsets[first.lineno - 1]
    ranges = [{"symbol": "MODULE_HEADER", "start": 0,
               "end": header_end, "role": "CONTENT"}]
    if mode == "NAMED_FUNCTIONS":
        candidates = {node.name: node for node in tree.body
                      if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        test_spans: dict[str, tuple[int, int]] = {}
        wanted = list(symbols)
    elif mode == "NAMED_TESTS_AND_CHANGED_FUNCTIONS":
        candidates = {}
        test_spans = {}
        seen_names: list[str] = []
        for group_index, group in enumerate(tree.body):
            if not isinstance(group, ast.ClassDef):
                continue
            following = tree.body[group_index + 1] if group_index + 1 < len(tree.body) else None
            class_end = offsets[following.lineno - 1] if following else len(raw)
            for index, node in enumerate(group.body):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    seen_names.append(node.name)
                    candidates[node.name] = node
                    first_decorator = min(node.decorator_list or [node],
                                          key=lambda item: (item.lineno, item.col_offset))
                    start = offsets[first_decorator.lineno - 1]
                    if index + 1 < len(group.body):
                        next_node = group.body[index + 1]
                        next_first = min(getattr(next_node, "decorator_list", []) or [next_node],
                                         key=lambda item: (item.lineno, item.col_offset))
                        end = offsets[next_first.lineno - 1]
                    else:
                        end = (class_end - 1 if raw[class_end - 1:class_end] == b"\n"
                               else class_end)
                    _require(start < end and offsets[node.end_lineno - 1]
                             + node.end_col_offset <= end,
                             "codex-exact-source-exposure-invalid",
                             "test method byte range overlaps another node")
                    test_spans[node.name] = (start, end)
        _require(len(seen_names) == len(set(seen_names)),
                 "codex-exact-source-exposure-invalid", "ambiguous test method name")
        wanted = list(dict.fromkeys(symbols + helpers + [
            name for name in candidates if name.startswith("test_r69h_")]))
    else:
        raise LifecycleError("codex-exact-source-exposure-invalid", "unknown source mode")
    _require(set(wanted) <= set(candidates),
             "codex-exact-source-exposure-invalid", "reviewed symbol is missing or ambiguous")
    for name in wanted:
        start, end = (test_spans[name] if mode == "NAMED_TESTS_AND_CHANGED_FUNCTIONS"
                      else span(candidates[name]))
        ranges.append({"symbol": name, "start": start, "end": end, "role": "CONTENT"})
    return sorted(ranges, key=lambda item: (item["start"], item["end"], item["symbol"]))

def _masked_noncontent(raw: bytes, ranges: list[dict[str, Any]]) -> bytes:
    """Keep every unselected byte and its relative order for baseline comparison."""
    cursor = 0
    chunks = []
    for row in ranges:
        start, end = row["start"], row["end"]
        _require(0 <= cursor <= start < end <= len(raw),
                 "codex-exact-source-exposure-invalid", "source ranges overlap or escape")
        chunks.append(raw[cursor:start])
        if not row["symbol"].startswith("test_r69h_"):
            chunks.append(("<" + row["symbol"] + ">").encode("ascii"))
        cursor = end
    chunks.append(raw[cursor:])
    return b"".join(chunks)

def _r69h_exposure_inventory(raw: bytes, invalid) -> tuple[list[tuple[str | None, int, int, ast.AST]], dict[str, dict[str, Any]]]:
    try:
        raw.decode('utf-8')
        tree = ast.parse(raw)
    except (UnicodeError, SyntaxError, ValueError) as exc:
        raise LifecycleError(invalid, 'Codex source is not parseable UTF-8') from exc
    offsets = [0]
    for line in raw.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    nodes: list[tuple[str | None, int, int, ast.AST]] = []
    starts: list[tuple[str | None, int, int, ast.AST]] = []
    prior_line = 0
    bindings: dict[str, dict[str, Any]] = {}
    for index, node in enumerate(tree.body):
        named = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        if isinstance(node, ast.Expr):
            _require(index == 0 and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str), invalid, 'unclassified executable top-level expression')
        elif not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign)):
            raise LifecycleError(invalid, 'unclassified top-level statement')
        first = min(getattr(node, 'decorator_list', []) or [node], key=lambda item: (item.lineno, item.col_offset))
        _require(first.lineno > prior_line and node.lineno > prior_line, invalid, 'same-line or out-of-order top-level nodes')
        prior_line = node.lineno
        start = offsets[first.lineno - 1] + node.col_offset
        ast_end = offsets[node.end_lineno - 1] + node.end_col_offset
        _require(0 <= start < ast_end <= len(raw), invalid, 'invalid AST byte offsets')
        _require(first is node or raw[start:start + 1] == b'@', invalid, 'decorator does not start at its top-level column')
        starts.append((node.name if named else None, start, ast_end, node))
        pairs: list[tuple[str, dict[str, Any]]] = []
        if named:
            pairs = [(node.name, {'kind': type(node).__name__, 'origin': None, 'member': None, 'alias': None})]
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            _require(len(targets) == 1 and isinstance(targets[0], ast.Name), invalid, 'chained or destructured top-level assignment')
            name = targets[0].id
            starts[-1] = (name, start, ast_end, node)
            pairs = [(name, {'kind': type(node).__name__, 'origin': None, 'member': None, 'alias': None})]
        elif isinstance(node, ast.Import):
            pairs = [(alias.asname or alias.name.split('.')[0], {'kind': 'Import', 'origin': alias.name, 'member': None, 'alias': alias.asname}) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            _require(node.level == 0 and node.module is not None and all((alias.name != '*' for alias in node.names)), invalid, 'relative or star import')
            pairs = [(alias.asname or alias.name, {'kind': 'ImportFrom', 'origin': node.module, 'member': alias.name, 'alias': alias.asname}) for alias in node.names]
        for name, identity in pairs:
            _require(name not in bindings, invalid, 'duplicate top-level binding')
            bindings[name] = identity
    for index, (name, start, ast_end, node) in enumerate(starts):
        end = starts[index + 1][1] if index + 1 < len(starts) else len(raw)
        _require(start < end and ast_end <= end, invalid, 'overlapping or ambiguous top-level byte range')
        nodes.append((name, start, end, node))
    return (nodes, bindings)

def _r69h_exposure_local_names(function: ast.AST) -> set[str]:
    names = set()
    globals_declared = set()
    if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        arguments = function.args
        names.update((arg.arg for arg in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)))
        names.update((arg.arg for arg in (arguments.vararg, arguments.kwarg) if arg))

    class Collect(ast.NodeVisitor):

        def visit_Name(self, item: ast.Name) -> None:
            if isinstance(item.ctx, ast.Store):
                names.add(item.id)

        def visit_Global(self, item: ast.Global) -> None:
            globals_declared.update(item.names)

        def visit_Nonlocal(self, item: ast.Nonlocal) -> None:
            globals_declared.update(item.names)

        def visit_FunctionDef(self, item: ast.FunctionDef) -> None:
            names.add(item.name)
        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, item: ast.ClassDef) -> None:
            names.add(item.name)

        def visit_Import(self, item: ast.Import) -> None:
            names.update((alias.asname or alias.name.split('.')[0] for alias in item.names))

        def visit_ImportFrom(self, item: ast.ImportFrom) -> None:
            names.update((alias.asname or alias.name for alias in item.names))

        def visit_ExceptHandler(self, item: ast.ExceptHandler) -> None:
            if item.name is not None:
                names.add(item.name)
            self.generic_visit(item)

        def visit_ListComp(self, item: ast.ListComp) -> None:
            pass
        visit_SetComp = visit_ListComp
        visit_DictComp = visit_ListComp
        visit_GeneratorExp = visit_ListComp
    collector = Collect()
    body = getattr(function, 'body', [])
    for item in body if isinstance(body, list) else []:
        collector.visit(item)
    return names - globals_declared

def _r69h_exposure_referenced(node: ast.AST, scope) -> set[str]:
    result = set()
    scopes: list[set[str]] = []

    class Loads(ast.NodeVisitor):

        def visit_Name(self, item: ast.Name) -> None:
            if isinstance(item.ctx, ast.Load) and (not any((item.id in scope for scope in scopes))):
                result.add(item.id)

        def visit_Call(self, item: ast.Call) -> None:
            if isinstance(item.func, ast.Name) and item.func.id in {'globals', 'locals', 'vars', 'eval', 'exec', '__import__'}:
                raise LifecycleError(scope, 'dynamic local symbol lookup is undecidable')
            self.generic_visit(item)

        def visit_NamedExpr(self, item: ast.NamedExpr) -> None:
            raise LifecycleError(scope, 'assignment expression scope is undecidable')

        def visit_FunctionDef(self, item: ast.FunctionDef) -> None:
            for decorator in item.decorator_list:
                self.visit(decorator)
            for default in (*item.args.defaults, *item.args.kw_defaults):
                if default is not None:
                    self.visit(default)
            for arg in (*item.args.posonlyargs, *item.args.args, *item.args.kwonlyargs):
                if arg.annotation is not None:
                    self.visit(arg.annotation)
            for arg in (item.args.vararg, item.args.kwarg):
                if arg is not None and arg.annotation is not None:
                    self.visit(arg.annotation)
            if item.returns is not None:
                self.visit(item.returns)
            scopes.append(_r69h_exposure_local_names(item))
            for child in item.body:
                self.visit(child)
            scopes.pop()
        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Lambda(self, item: ast.Lambda) -> None:
            for default in (*item.args.defaults, *item.args.kw_defaults):
                if default is not None:
                    self.visit(default)
            scopes.append(_r69h_exposure_local_names(item))
            self.visit(item.body)
            scopes.pop()

        def visit_ClassDef(self, item: ast.ClassDef) -> None:
            for child in (*item.decorator_list, *item.bases):
                self.visit(child)
            scopes.append(_r69h_exposure_local_names(item))
            for child in item.body:
                self.visit(child)
            scopes.pop()

        def _comprehension(self, item: ast.AST, values: list[ast.AST]) -> None:
            names = {name.id for part in item.generators for name in ast.walk(part.target) if isinstance(name, ast.Name)}
            if item.generators:
                self.visit(item.generators[0].iter)
            scopes.append(names)
            for index, part in enumerate(item.generators):
                if index:
                    self.visit(part.iter)
                for condition in part.ifs:
                    self.visit(condition)
            for value in values:
                self.visit(value)
            scopes.pop()

        def visit_ListComp(self, item: ast.ListComp) -> None:
            self._comprehension(item, [item.elt])
        visit_SetComp = visit_ListComp
        visit_GeneratorExp = visit_ListComp

        def visit_DictComp(self, item: ast.DictComp) -> None:
            self._comprehension(item, [item.key, item.value])
    Loads().visit(node)
    return result

def _r69h_exposure_masked(raw: bytes, rows: list[tuple[str | None, int, int, ast.AST]], first: int, selected: set[str], old_names, now_names) -> bytes:
    parts = [b'<MODULE_HEADER>']
    for name, start, end, _ in rows:
        if start < first:
            continue
        if name in selected:
            if name in old_names & now_names:
                parts.append(('<' + name + '>').encode('ascii'))
        else:
            parts.append(raw[start:end])
    return b''.join(parts)

def _r69h_codex_exposure(source: bytes, before: bytes, rule: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Independently select v7 Codex bytes before the packet writer sees them."""
    invalid = 'codex-exact-source-exposure-invalid'
    scope = 'codex-exact-source-exposure-scope'
    old_rows, old_bindings = _r69h_exposure_inventory(before, invalid)
    now_rows, now_bindings = _r69h_exposure_inventory(source, invalid)
    _require(_sha(canonical_bytes(old_bindings)) == rule['baselineTypedBindingInventorySha256'], invalid, 'pinned baseline binding inventory differs')
    old_names, now_names = (set(old_bindings), set(now_bindings))
    future = {name for name in now_names - old_names - set(rule['approvedNewTopLevelBindings']) if name.startswith(rule['permittedFutureFunctionPrefix']) and now_bindings[name]['kind'] == 'FunctionDef' or (name.startswith(rule['permittedFutureGlobalPrefix']) and now_bindings[name]['kind'] in {'Assign', 'AnnAssign'})}
    _require(now_names - old_names == set(rule['approvedNewTopLevelBindings']) | future and old_names - now_names == set(rule['approvedRemovedTopLevelBindings']), scope, 'unapproved top-level binding added or removed')
    for name in old_names & now_names:
        _require(old_bindings[name] == now_bindings[name], scope, 'continuing typed top-level binding changed: ' + name)
    original_now = {name: identity for name, identity in now_bindings.items() if name not in future}
    _require(_sha(canonical_bytes(original_now)) == rule['currentCandidateTypedBindingInventorySha256'], scope, 'original current binding inventory changed')
    old_by_name = {name: (start, end, node) for name, start, end, node in old_rows if name is not None}
    now_by_name = {name: (start, end, node) for name, start, end, node in now_rows if name is not None}
    for name, expected in rule['unchangedContextIdentityOnlySha256'].items():
        _require(name in old_by_name and name in now_by_name, scope, 'identity-only context function missing')
        old_start, old_end, _ = old_by_name[name]
        start, end, _ = now_by_name[name]
        _require(before[old_start:old_end] == source[start:end] and _sha(source[start:end]) == expected, scope, 'identity-only context function changed')
    first_old = next((start for _, start, _, node in old_rows if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))), None)
    first_now = next((start for _, start, _, node in now_rows if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))), None)
    _require(first_old is not None and first_now is not None and (first_old > 0) and (first_now > 0), invalid, 'module header boundary absent')
    required = set(rule['currentRequiredFunctionSymbols']) | set(rule['currentRequiredGlobalAssignments']) | future
    seeds = set(rule['changedFunctionClosureSeeds']) | set(rule['currentRequiredGlobalAssignments']) | future
    _require(required <= set(now_by_name) and seeds <= required, scope, 'required Codex source symbol missing')
    imported_used: dict[str, dict[str, Any]] = {}
    closure = set(seeds)
    while True:
        needed = set()
        for name in closure:
            for dependency in _r69h_exposure_referenced(now_by_name[name][2], scope):
                if dependency in now_by_name:
                    needed.add(dependency)
                elif dependency in now_bindings:
                    imported_used[dependency] = now_bindings[dependency]
        expanded = closure | needed
        if expanded == closure:
            break
        closure = expanded
    _require(set(rule['currentLocalDependencyClosure']) <= closure and required <= closure | set(rule['currentRequiredFunctionSymbols']), scope, 'local dependency closure is incomplete')
    _require(not closure.intersection(rule['unchangedContextIdentityOnlySha256']), scope, 'identity-only context became a required implementation')
    approved_imports = rule['currentImportedAliasIdentitiesUsedByClosure']
    for name, identity in imported_used.items():
        _require(name in approved_imports and identity['kind'] in {'Import', 'ImportFrom'} and (identity == approved_imports[name]), scope, 'unreviewed imported dependency: ' + name)
    required |= closure
    old_selected = required & old_names | set(rule['baselineDeletedFunctionTombstones'])
    current_masked = _r69h_exposure_masked(source, now_rows, first_now, required, old_names, now_names)
    _require(current_masked == _r69h_exposure_masked(before, old_rows, first_old, old_selected, old_names, now_names) and _sha(current_masked) == rule['maskedNonContentSha256'] and (len(current_masked) == rule['maskedNonContentBytes']), scope, 'Codex source changed outside selected CONTENT spans')
    ranges = [{'symbol': 'MODULE_HEADER', 'start': 0, 'end': first_now, 'role': 'CONTENT'}]
    ranges.extend(({'symbol': name, 'start': start, 'end': end, 'role': 'CONTENT'} for name, start, end, _ in now_rows if name in required and start >= first_now))
    _require({row['symbol'] for row in ranges} == required | {'MODULE_HEADER'}, scope, 'selected source span set is incomplete')
    identity_only = [{'symbol': name, 'start': now_by_name[name][0], 'end': now_by_name[name][1], 'role': 'IDENTITY_ONLY', 'sha256': expected} for name, expected in sorted(rule['unchangedContextIdentityOnlySha256'].items())]
    return (sorted(ranges, key=lambda row: row['start']), identity_only)

def _check_required_route_bridge(
    source_by_module: dict[str, bytes], oracle: dict[str, Any],
) -> None:
    """Resolve direct imported calls and the pinned process-runner handoff."""
    trees = {module: ast.parse(raw, filename=module + ".py")
             for module, raw in source_by_module.items()}
    imports: dict[str, dict[str, str]] = {}
    functions: dict[str, dict[str, ast.AST]] = {}
    for module, tree in trees.items():
        imported = {}
        local = {}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    if node.module.startswith("agent_lifecycle.adapter_sessions."):
                        imported[alias.asname or alias.name] = (
                            node.module.rsplit(".", 1)[-1] + "." + alias.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _require(node.name not in local, "codex-exact-source-exposure-bridge",
                         "ambiguous route function")
                local[node.name] = node
        imports[module], functions[module] = imported, local

    def direct_calls(module: str, function: str) -> set[str]:
        node = functions.get(module, {}).get(function)
        _require(node is not None, "codex-exact-source-exposure-bridge",
                 "mandatory route function missing")
        resolved = set()
        for item in ast.walk(node):
            if not isinstance(item, ast.Call):
                continue
            callee = item.func
            if isinstance(callee, ast.Name):
                if callee.id in functions[module]:
                    resolved.add(module + "." + callee.id)
                elif callee.id in imports[module]:
                    resolved.add(imports[module][callee.id])
            elif isinstance(callee, ast.Attribute) and isinstance(callee.value, ast.Name):
                alias = callee.value.id
                if alias in imports[module]:
                    resolved.add(imports[module][alias] + "." + callee.attr)
        return resolved

    for caller, callee in oracle["requiredCallEdges"]:
        module, function = caller.split(".", 1)
        _require(callee in direct_calls(module, function),
                 "codex-exact-source-exposure-bridge",
                 "mandatory direct route call is missing")
    for caller, callee in (("launch_preflight.launch_from_local_profile",
                            "launch_preflight._load_context"),):
        module, function = caller.split(".", 1)
        _require(callee in direct_calls(module, function),
                 "codex-exact-source-exposure-bridge", "runner context call is missing")

    launcher = functions["launcher"]["launch_from_local_profile"]
    injected = any(isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Subscript)
                           and isinstance(target.value, ast.Name) and target.value.id == "kwargs"
                           and isinstance(target.slice, ast.Constant)
                           and target.slice.value == "process_runner"
                           for target in node.targets)
                   and isinstance(node.value, ast.Name) and node.value.id == "run_process"
                   for node in ast.walk(launcher))
    loader = functions["launch_preflight"]["_load_context"]
    assigned = any(isinstance(node, ast.keyword) and node.arg == "runner"
                   and isinstance(node.value, ast.BoolOp) and isinstance(node.value.op, ast.Or)
                   and [term.id for term in node.value.values if isinstance(term, ast.Name)]
                   == ["process_runner", "run_process"]
                   for node in ast.walk(loader))
    managed = functions["launch_preflight"]["_managed_task"]
    guarded = any(isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                  and len(node.test.ops) == 1 and isinstance(node.test.ops[0], ast.IsNot)
                  and isinstance(node.test.left, ast.Attribute)
                  and isinstance(node.test.left.value, ast.Name)
                  and (node.test.left.value.id, node.test.left.attr) == ("context", "runner")
                  and isinstance(node.test.comparators[0], ast.Name)
                  and node.test.comparators[0].id == "run_process"
                  and any(isinstance(child, ast.Raise) for child in node.body)
                  for node in ast.walk(managed))
    runner = functions["launch_preflight"]["_run_exact_managed_process"]
    invoked = any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and isinstance(node.func.value, ast.Name)
                  and (node.func.value.id, node.func.attr) == ("context", "runner")
                  for node in ast.walk(runner))
    _require(injected and assigned and guarded and invoked
             and "launch_preflight._run_exact_managed_process"
             in direct_calls("launch_preflight", "_managed_task"),
             "codex-exact-source-exposure-bridge", "runner bridge is incomplete")

def _discover_bootstrap_test_ids(root: Path, oracle: dict[str, Any],
                                 contract: dict[str, Any]) -> dict[str, list[str]]:
    """Discover exact C34/C35 case membership without executing test methods."""
    result = {}
    commands = {row["id"]: row for row in contract["validation"]["commands"]}
    for command_id in ("C34", "C35"):
        command = commands[command_id]
        parts = shlex.split(command["command"])
        _require(parts[:5] == ["PYTHONDONTWRITEBYTECODE=1", "PYTHONPATH=src",
                                "python3", "-m", "unittest"] and parts[-1] == "-q",
                 "codex-exact-source-exposure-tests", "locked test command changed")
        modules = parts[5:-1]
        paths = {module: module.replace(".", "/") + ".py" for module in modules}
        before = {module: _sha(read_authority_bytes(root / relative, root=root,
                                                     max_bytes=262_144))
                  for module, relative in paths.items()}
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromNames(modules)
        _require(not loader.errors, "codex-exact-source-exposure-tests",
                 "test loader could not resolve locked modules")

        def flatten(group: unittest.TestSuite) -> list[str]:
            names = []
            for item in group:
                if isinstance(item, unittest.TestSuite):
                    names.extend(flatten(item))
                else:
                    names.append(item.id())
            return names

        discovered = flatten(suite)
        _require(bool(discovered) and len(discovered) == len(set(discovered)),
                 "codex-exact-source-exposure-tests", "test IDs are missing or repeated")
        after = {module: _sha(read_authority_bytes(root / relative, root=root,
                                                    max_bytes=262_144))
                 for module, relative in paths.items()}
        _require(before == after, "codex-exact-source-exposure-stale",
                 "test source changed during discovery")
        baseline = {module + "." + case
                    for row in oracle["caseRoster"][command_id]
                    for module, relative in paths.items()
                    if relative == row["modulePath"]
                    for case in row["caseIds"]}
        additions = set(discovered) - baseline
        _require(baseline <= set(discovered)
                 and all(name.split(".")[-1].startswith("test_r69h_")
                         and name.rsplit(".", 2)[0] in modules
                         and "test_host_launch_commands" not in name
                         for name in additions),
                 "codex-exact-source-exposure-tests", "test case roster differs")
        result[command_id] = sorted(discovered)
    return result

def _check_source_exposure(root: Path) -> dict[str, Any]:
    """Check the locked v7/v8 source membership and unchanged bytes."""
    plan = root / "tasks/release-2-16"
    contract = read_json_object(plan / "route-bootstrap-contract.json")
    delivery = contract["auditJoin"]["delivery"]
    oracle_path = delivery["oracles"][0]
    expected_sha = {
        "tasks/release-2-16/SOURCE-EXPOSURE-ORACLE-v7.json": _R69H_SOURCE_ORACLE_SHA256,
        "tasks/release-2-16/SOURCE-EXPOSURE-ORACLE-v8.json":
            "d19e5edb56f4908c949f4239763038915f27798f54e8cdbbc13db6a361f93834",
    }.get(oracle_path)
    _require(expected_sha is not None and delivery["sourceOracleSha256"] == expected_sha,
             "codex-exact-source-exposure-invalid", "installed source oracle route differs")
    oracle_raw = read_authority_bytes(root / oracle_path, root=root, max_bytes=131_072)
    _require(_sha(oracle_raw) == expected_sha,
             "codex-exact-source-exposure-invalid", "source oracle changed")
    oracle = json.loads(oracle_raw)
    _require(oracle.get("r8CodexSlice", {}).get("path") ==
             "src/agent_lifecycle/adapter_sessions/codex_exact_prompt.py",
             "codex-exact-source-exposure-invalid", "R8-R3 Codex slice missing")
    expected = set(contract["ownership"]["temporaryLeadWritePaths"])
    rows = oracle.get("requiredSourceSet")
    _require(isinstance(rows, list) and len(rows) == 6
             and {row.get("path") for row in rows if isinstance(row, dict)} == expected,
             "codex-exact-source-exposure-invalid", "six-source membership differs")
    checked = []
    module_sources = {}
    helpers = ["_workflow_state", "_snapshot"]
    for row in rows:
        relative = row["path"]
        path = Path(relative)
        baseline = Path(row["baselineSnapshotPath"])
        _require(not path.is_absolute() and ".." not in path.parts
                 and not baseline.is_absolute() and ".." not in baseline.parts,
                 "codex-exact-source-exposure-invalid", "source path escapes checkout")
        source = read_authority_bytes(root / path, root=root, max_bytes=262_144)
        before = read_authority_bytes(plan / baseline, root=root, max_bytes=262_144)
        _require(_sha(before) == row["baselineSha256"]
                 and len(before) == row["baselineBytes"],
                 "codex-exact-source-exposure-invalid", "pinned baseline differs")
        mode = row["exposureMode"]
        symbols = row["requiredSymbols"]
        identity_only: list[dict[str, Any]] = []
        if mode == "TOP_LEVEL_AST_SLICES_WITH_BASELINE_TOMBSTONES":
            _require(relative == oracle["r8CodexSlice"]["path"],
                     "codex-exact-source-exposure-invalid", "R8 slice attached to wrong source")
            current_ranges, identity_only = _r69h_codex_exposure(
                source, before, oracle["r8CodexSlice"])
        else:
            current_ranges = _source_ast_ranges(source, relative=relative,
                                                mode=mode, symbols=symbols, helpers=helpers)
            baseline_ranges = _source_ast_ranges(before, relative=relative,
                                                 mode=mode, symbols=symbols, helpers=helpers)
        if mode not in {"FULL", "TOP_LEVEL_AST_SLICES_WITH_BASELINE_TOMBSTONES"}:
            _require(_masked_noncontent(source, current_ranges)
                     == _masked_noncontent(before, baseline_ranges),
                     "codex-exact-source-exposure-scope",
                     f"{relative} changed outside reviewed AST spans")
        module_sources[path.stem] = source
        checked.append({"path": relative, "beforeExists": True,
                        "beforeSha256": row["baselineSha256"],
                        "currentFullSha256": _sha(source),
                        "currentFullBytes": len(source), "ranges": current_ranges,
                        "identityOnly": identity_only})
    read_only = oracle["requiredReadOnlySource"]
    relative = read_only["path"]
    launcher = read_authority_bytes(root / relative, root=root, max_bytes=262_144)
    pinned_launcher = read_authority_bytes(plan / read_only["baselineSnapshotPath"],
                                           root=root, max_bytes=262_144)
    _require(_sha(launcher) == read_only["sha256"] and launcher == pinned_launcher,
             "codex-exact-source-exposure-bridge", "read-only launcher facade changed")
    module_sources["launcher"] = launcher
    _check_required_route_bridge(module_sources, oracle)
    checked.append({"path": relative, "beforeExists": True,
                    "beforeSha256": read_only["sha256"],
                    "currentFullSha256": _sha(launcher),
                    "currentFullBytes": len(launcher),
                    "ranges": [{"symbol": "FULL_READ_ONLY_BRIDGE", "start": 0,
                                "end": len(launcher), "role": "CONTENT"}],
                    "identityOnly": []})
    test_closure = _r69h_check_test_dependency_closure(root, oracle, checked)
    cases = _discover_bootstrap_test_ids(root, oracle, contract)
    return {"oracleSha256": _sha(oracle_raw), "sources": checked,
            "discoveredCaseIds": cases, "testDependencyClosure": test_closure}

def _build_source_exposure_packet(root: Path, checked: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    """Reopen checked sources and emit exact delivered bytes and range identities."""
    _require(checked == _check_source_exposure(root),
             "codex-exact-source-exposure-stale", "checker selection changed before packet build")
    blocks = []
    text_blocks = []
    for source in checked["sources"]:
        relative = source["path"]
        raw = read_authority_bytes(root / relative, root=root, max_bytes=262_144)
        _require(_sha(raw) == source["currentFullSha256"]
                 and len(raw) == source["currentFullBytes"],
                 "codex-exact-source-exposure-stale", "source changed while building packet")
        for selected in source["ranges"]:
            part = raw[selected["start"]:selected["end"]]
            try:
                decoded = part.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise LifecycleError("codex-exact-source-exposure-invalid",
                                     "selected source is not UTF-8") from exc
            block = {"path": relative, "beforeExists": source["beforeExists"],
                     "beforeSha256": source["beforeSha256"],
                     "currentFullSha256": source["currentFullSha256"],
                     "currentFullBytes": source["currentFullBytes"],
                     "ranges": [[selected["start"], selected["end"]]],
                     "deliveredBytes": len(part), "deliveredSha256": _sha(part),
                     "caseOrReceiptId": selected["symbol"],
                     "generationRule": ("R69J_V8_AST_SLICE_OR_FULL"
                                        if checked["oracleSha256"] ==
                                        "d19e5edb56f4908c949f4239763038915f27798f54e8cdbbc13db6a361f93834"
                                        else "R69I_V7_AST_SLICE_OR_FULL"),
                     "reason": "required source CONTENT"}
            blocks.append(block)
            text_blocks.append("@@ " + relative + ":" + str(selected["start"])
                               + ":" + str(selected["end"]) + "\n" + decoded + "\n")
        for selected in source.get("identityOnly", []):
            part = raw[selected["start"]:selected["end"]]
            _require(_sha(part) == selected["sha256"],
                     "codex-exact-source-exposure-stale", "identity-only source changed")
            blocks.append({"path": relative, "beforeExists": source["beforeExists"],
                           "beforeSha256": source["beforeSha256"],
                           "currentFullSha256": source["currentFullSha256"],
                           "currentFullBytes": source["currentFullBytes"],
                           "ranges": [[selected["start"], selected["end"]]],
                           "deliveredBytes": 0, "deliveredSha256": _sha(b""),
                           "identitySha256": selected["sha256"],
                           "caseOrReceiptId": selected["symbol"],
                           "generationRule": ("R69J_V8_IDENTITY_ONLY"
                                              if checked["oracleSha256"] ==
                                              "d19e5edb56f4908c949f4239763038915f27798f54e8cdbbc13db6a361f93834"
                                              else "R69I_V7_IDENTITY_ONLY"),
                           "reason": "unchanged baseline bytes; semantics not delivered"})
            text_blocks.append("@@ IDENTITY_ONLY " + relative + ":"
                               + str(selected["start"]) + ":" + str(selected["end"])
                               + " sha256=" + selected["sha256"] + "\n")
        reopened = read_authority_bytes(root / relative, root=root, max_bytes=262_144)
        _require(_sha(reopened) == source["currentFullSha256"] and len(reopened) == len(raw),
                 "codex-exact-source-exposure-stale", "source changed after packet copy")
    manifest = {"schemaVersion": "alk-r69h-source-exposure-manifest.v1",
                "oracleSha256": checked["oracleSha256"], "blocks": blocks,
                "testDependencyClosure": checked["testDependencyClosure"]}
    packet = ("ALK_SOURCE_EXPOSURE_PACKET_V1\n" + "".join(text_blocks)).encode("utf-8")
    return manifest, packet

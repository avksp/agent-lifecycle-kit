"""Shared policy checks used by the existing architecture validator entrypoints.

Branch score counts if/for/while/except/if-expression nodes, one per
comprehension generator plus each filter, extra boolean operands, extra match
cases/OR patterns and match guards. Nested defs/classes have separate qualified
names. Defaults (including keyword-only defaults) and decorators belong to the
declared function's score, even when evaluated by its enclosing scope. Thus
headers and nested bodies are each measured once, never charged to both functions.
Lambdas' expressions remain part of their containing function's score.
Fingerprints exclude comments, docstrings and annotations, not executable code.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import EllipsisType
from typing import Any, TypeAlias

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.quality.dependency_impact import package_name


class _BranchCounter(ast.NodeVisitor):
    def __init__(self) -> None:
        self.score = 0

    def visit_FunctionDef(self, _node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, _node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, _node: ast.ClassDef) -> None:
        return

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp)):
            self.score += 1
        elif isinstance(node, ast.comprehension):
            self.score += 1 + len(node.ifs)
        elif isinstance(node, ast.BoolOp):
            self.score += len(node.values) - 1
        elif isinstance(node, ast.Match):
            self.score += max(0, len(node.cases) - 1)
            self.score += sum(case.guard is not None for case in node.cases)
        elif isinstance(node, ast.MatchOr):
            self.score += len(node.patterns) - 1
        super().generic_visit(node)


def branch_score(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    visitor = _BranchCounter()
    for expression in [*node.decorator_list, *node.args.defaults, *node.args.kw_defaults]:
        if expression is not None:
            visitor.visit(expression)
    for statement in node.body:
        visitor.visit(statement)
    return visitor.score


class _SemanticTree(ast.NodeTransformer):
    def generic_visit(self, node: ast.AST) -> ast.AST:
        super().generic_visit(node)
        body = getattr(node, "body", None)
        if (
            isinstance(body, list)
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body.pop(0)
        for field in ("annotation", "returns", "type_comment"):
            if hasattr(node, field):
                setattr(node, field, None)
        return node

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST | None:
        if node.value is None:
            return None
        return self.visit(ast.Assign(targets=[node.target], value=node.value))


_AstValue: TypeAlias = "ast.AST | list[_AstValue] | str | int | float | complex | bytes | EllipsisType | None"


def _canonical_ast_dump(value: _AstValue) -> str:
    """Keep the accepted Python 3.12 field representation on supported runtimes.

    Unlike newer ast.dump defaults, empty lists remain explicit. Python 3.11
    declarations acquire the empty type_params field introduced in 3.12.
    Optional None fields stay omitted. Python 3.15 eager imports omit only the
    known integer is_lazy=0 default; nonzero flags and future fields remain.
    This preserves the accepted representation without ignoring lazy semantics.
    """
    if isinstance(value, ast.AST):
        fields = [
            (name, child)
            for name, child in ast.iter_fields(value)
            if not (
                name == "is_lazy"
                and isinstance(value, (ast.Import, ast.ImportFrom))
                and type(child) is int
                and child == 0
            )
        ]
        if isinstance(value, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not any(
            name == "type_params" for name, _ in fields
        ):
            fields.append(("type_params", getattr(value, "type_params", [])))
        parts = [
            f"{name}={_canonical_ast_dump(child)}"
            for name, child in fields
            if not (child is None and getattr(type(value), name, ...) is None)
        ]
        return f"{type(value).__name__}({', '.join(parts)})"
    if isinstance(value, list):
        return f"[{', '.join(_canonical_ast_dump(child) for child in value)}]"
    return repr(value)


def semantic_fingerprint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    normalized = _SemanticTree().visit(copy.deepcopy(node))
    return hashlib.sha256(_canonical_ast_dump(normalized).encode()).hexdigest()


class _Functions(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.stack: list[str] = []
        self.records: list[dict[str, Any]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.stack.append(node.name)
        self.records.append(
            {
                "path": self.path,
                "name": ".".join(self.stack),
                "line": node.lineno,
                "score": branch_score(node),
                "fingerprint": semantic_fingerprint(node),
            }
        )
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef


def function_branch_records(tree: ast.AST, path: str) -> list[dict[str, Any]]:
    visitor = _Functions(path)
    visitor.visit(tree)
    return visitor.records


def _named_rows(rows: list[dict[str, Any]], fields: set[str], label: str) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for row in rows:
        if set(row) != fields or not all(isinstance(row.get(key), str) and row[key] for key in ("path", "name")):
            raise ValueError(f"Invalid {label} row")
        key = row["path"], row["name"]
        if key in result or any("*" in value for value in key):
            raise ValueError(f"Duplicate or wildcard {label}")
        result[key] = row
    return result


def validate_branch_policy(policy: dict[str, Any]) -> None:
    baseline = policy["branchBaseline"]
    if canonical_digest(baseline) != policy["branchBaselineDigest"]:
        raise ValueError("Branch baseline digest differs; automatic growth is forbidden")
    rows = _named_rows(baseline, {"path", "name", "score", "fingerprint"}, "branch baseline")
    for row in rows.values():
        if type(row["score"]) is not int or row["score"] <= policy["branchLimit"]:
            raise ValueError("Branch baseline must describe existing over-limit debt")
        if not isinstance(row["fingerprint"], str) or len(row["fingerprint"]) != 64:
            raise ValueError("Invalid branch fingerprint")
    exceptions = _named_rows(
        policy["branchExceptions"],
        {"path", "name", "maxScore", "reason", "owner", "tests", "review"},
        "branch exception",
    )
    for row in exceptions.values():
        if not all(isinstance(row[key], str) and row[key].strip() for key in ("reason", "owner", "review")):
            raise ValueError("Branch exception requires reason, owner and independent review")
        if (
            not isinstance(row["tests"], list)
            or not row["tests"]
            or not all(isinstance(test, str) and test for test in row["tests"])
        ):
            raise ValueError("Branch exception requires named tests")
        if type(row["maxScore"]) is not int or row["maxScore"] < 0:
            raise ValueError("Invalid branch exception ceiling")


def branch_findings(records: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    validate_branch_policy(policy)
    baseline = {(row["path"], row["name"]): row for row in policy["branchBaseline"]}
    exceptions = {(row["path"], row["name"]): row for row in policy["branchExceptions"]}
    findings = []
    for row in records:
        key = row["path"], row["name"]
        old, exception = baseline.get(key), exceptions.get(key)
        if row["score"] <= policy["branchLimit"]:
            continue
        if exception is not None and row["score"] <= exception["maxScore"]:
            continue
        if old is not None and row["fingerprint"] == old["fingerprint"] and row["score"] == old["score"]:
            continue
        if old is not None and row["score"] * 5 <= old["score"] * 4:
            continue
        findings.append(
            {
                "code": "architecture-branch-ratchet-violation",
                **row,
                "previousScore": None if old is None else old["score"],
            }
        )
    return findings


def load_architecture_limits(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schemaVersion") != "agent-architecture-limits.v1":
        raise ValueError("Unsupported architecture limits policy")
    names = (
        "targetFileLines",
        "hardFileLines",
        "targetFunctionLines",
        "hardFunctionLines",
        "hardSymbols",
        "cliTargetFunctionLines",
        "cliHardFunctionLines",
    )
    if set(value["limits"]) != set(names) or not all(
        type(value["limits"][key]) is int and value["limits"][key] > 0 for key in names
    ):
        raise ValueError("Invalid architecture limits")
    if type(value["branchLimit"]) is not int or value["branchLimit"] <= 0:
        raise ValueError("Invalid branch limit")
    validate_branch_policy(value)
    return value


def _import_base(node: ast.ImportFrom, consumer: str, is_package: bool) -> str:
    if not node.level:
        return node.module or ""
    package = consumer if is_package else consumer.rpartition(".")[0]
    return importlib.util.resolve_name("." * node.level + (node.module or ""), package)


def _cross_private(module: str, symbol: str, consumer: str, root: str) -> bool:
    return (
        module.startswith(root + ".")
        and symbol.startswith("_")
        and package_name(module, root) != package_name(consumer, root)
    )


def _private_row(module: str, symbol: str, alias: str, consumer: str, *, reexport: bool) -> dict[str, Any]:
    return {"module": module, "symbol": symbol, "alias": alias, "consumer": consumer, "explicitReexport": reexport}


def _direct_private_imports(
    tree: ast.AST, consumer: str, root: str, is_package: bool
) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    rows: list[dict[str, Any]] = []
    modules: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.setdefault(alias.asname or alias.name.split(".")[0], set()).add(
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom):
            base = _import_base(node, consumer, is_package)
            for alias in node.names:
                modules.setdefault(alias.asname or alias.name, set()).add(base + "." + alias.name)
                if _cross_private(base, alias.name, consumer, root):
                    rows.append(
                        _private_row(
                            base, alias.name, alias.asname or alias.name, consumer, reexport=alias.asname == alias.name
                        )
                    )
    return rows, modules


def _module_expression(node: ast.AST, aliases: dict[str, set[str]]) -> set[str]:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, set())
    if isinstance(node, ast.Attribute):
        base = _module_expression(node.value, aliases)
        return {module + "." + node.attr for module in base}
    return set()


def _module_alias_candidates(
    tree: ast.AST,
    aliases: dict[str, set[str]],
    known_modules: set[str] | None,
) -> set[str]:
    """Bound propagation to statically named modules and their package prefixes."""
    modules = set(known_modules) if known_modules is not None else set().union(*aliases.values())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return {
        ".".join(module.split(".")[:length]) for module in modules for length in range(1, len(module.split(".")) + 1)
    }


def _propagate_module_aliases(tree: ast.AST, aliases: dict[str, set[str]], candidates: set[str]) -> None:
    # The finite candidate set also terminates self-referential attribute chains.
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                names, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                names, value = [node.target], node.value
            else:
                continue
            targets = _module_expression(value, aliases) & candidates
            for name in names:
                if isinstance(name, ast.Name):
                    known = aliases.setdefault(name.id, set())
                    changed |= not targets.issubset(known)
                    known.update(targets)


def private_import_records(
    tree: ast.AST, consumer: str, root: str, *, is_package: bool = False, known_modules: set[str] | None = None
) -> list[dict[str, Any]]:
    rows, aliases = _direct_private_imports(tree, consumer, root, is_package)
    _propagate_module_aliases(tree, aliases, _module_alias_candidates(tree, aliases, known_modules))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            for module in _module_expression(node.value, aliases):
                if (known_modules is None or module in known_modules) and _cross_private(
                    module, node.attr, consumer, root
                ):
                    rows.append(_private_row(module, node.attr, ast.unparse(node), consumer, reexport=False))
    unique = {canonical_digest(row): row for row in rows}
    return sorted(unique.values(), key=lambda row: (row["consumer"], row["module"], row["symbol"], row["alias"]))


def private_import_findings(records: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    groups = {
        "ordinary": policy.get("privateImportBaseline", []),
        "reexports": policy.get("privateImportReexports", []),
    }
    if canonical_digest(groups) != policy.get("privateImportBaselineDigest"):
        raise ValueError("Private import baseline digest differs; automatic growth is forbidden")
    allowed: dict[tuple[str, ...], str] = {}
    for group, rows in groups.items():
        for row in rows:
            if set(row) != {"module", "symbol", "alias", "consumer", "reason"}:
                raise ValueError("Private import exception requires exact module, symbol, alias, consumer and reason")
            if not all(isinstance(value, str) and value.strip() and "*" not in value for value in row.values()):
                raise ValueError("Private import exceptions cannot be blank or wildcarded")
            key = tuple(row[name] for name in ("module", "symbol", "alias", "consumer"))
            if key in allowed:
                raise ValueError("Duplicate private import exception")
            allowed[key] = group
    blockers = []
    for row in records:
        key = tuple(row[name] for name in ("module", "symbol", "alias", "consumer"))
        category = "reexports" if row["explicitReexport"] else "ordinary"
        if allowed.get(key) != category:
            blockers.append({"code": "architecture-private-import-unapproved", **row})
    return {
        "records": records,
        "explicitReexportCount": sum(row["explicitReexport"] for row in records),
        "ordinaryCount": sum(not row["explicitReexport"] for row in records),
        "blockers": blockers,
    }

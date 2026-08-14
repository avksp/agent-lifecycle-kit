"""Reject host, network and provider execution from the offline path."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import canonical_digest, sha256_hex


BANNED_IMPORT_ROOTS = {
    "anthropic",
    "google.generativeai",
    "httpx",
    "mistralai",
    "openai",
    "pexpect",
    "requests",
    "socket",
    "subprocess",
    "urllib",
}
PROCESS_CALLS = {"Popen", "call", "check_call", "check_output", "run", "system"}
HOST_PROCESS_CALLS = PROCESS_CALLS | {
    "exec",
    "execl",
    "execle",
    "execlp",
    "execv",
    "execve",
    "execvp",
    "execvpe",
    "popen",
    "posix_spawn",
    "posix_spawnp",
    "run_process",
    "spawnl",
    "spawnle",
    "spawnlp",
    "spawnlpe",
    "spawnv",
    "spawnve",
    "spawnvp",
    "spawnvpe",
}
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LIVE_PROBE_MODULE = REPOSITORY_ROOT / "src/agent_lifecycle/host_protocol/agent_plugin_qualification.py"
LIVE_HOST_EXECUTION_FUNCTIONS = {"_default_probe_runner", "_run_probe_command"}


def validate_offline_boundary(paths: list[Path]) -> dict[str, Any]:
    checks = [_check_path(path) for path in paths]
    blockers = [item for check in checks for item in check["blockers"]]
    body = {
        "schemaVersion": "agent-plugin-offline-boundary-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "paths": [path.as_posix() for path in paths],
        "checks": checks,
        "blockers": blockers,
        "hostExecutionStarted": False,
        "modelCallsStarted": False,
        "networkCallsStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _check_path(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": path.as_posix(), "status": "FAIL", "blockers": [{"code": "offline-path-missing"}]}
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=path.as_posix())
    except (OSError, SyntaxError) as exc:
        return {
            "path": path.as_posix(),
            "status": "FAIL",
            "blockers": [{"code": "offline-parse-failed", "errorType": type(exc).__name__}],
        }
    blockers: list[dict[str, Any]] = []
    visitor = _BoundaryVisitor(path)
    visitor.visit(tree)
    blockers.extend(visitor.blockers)
    return {
        "path": path.as_posix(),
        "status": "PASS" if not blockers else "FAIL",
        "file": {"path": path.as_posix(), "sha256": sha256_hex(path.read_bytes()), "bytes": path.stat().st_size},
        "scope": {
            "liveHostExecutionFunctions": sorted(LIVE_HOST_EXECUTION_FUNCTIONS) if _is_live_probe_module(path) else [],
            "offlineFunctionsChecked": visitor.offline_functions_checked,
        },
        "blockers": blockers,
    }


class _BoundaryVisitor(ast.NodeVisitor):
    """Inspect offline code while permitting only the explicit live probe helpers."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.function_stack: list[str] = []
        self.host_process_aliases: set[str] = set()
        self.blockers: list[dict[str, Any]] = []
        self.offline_functions_checked: list[str] = []

    @property
    def _live_host_scope(self) -> bool:
        return _is_live_probe_module(self.path) and any(
            name in LIVE_HOST_EXECUTION_FUNCTIONS for name in self.function_stack
        )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append(node.name)
        if not self._live_host_scope:
            self.offline_functions_checked.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.function_stack.append(node.name)
        if not self._live_host_scope:
            self.offline_functions_checked.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = _import_root(alias.name)
            if root in BANNED_IMPORT_ROOTS:
                self.blockers.append({"code": "offline-import", "line": node.lineno, "import": root})
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        root = _import_root(node.module or "")
        if root in BANNED_IMPORT_ROOTS:
            self.blockers.append({"code": "offline-import", "line": node.lineno, "import": root})
        if (node.module or "").endswith(".process"):
            for alias in node.names:
                if alias.name == "run_process":
                    self.host_process_aliases.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        leaf = name.rsplit(".", 1)[-1]
        is_host_process_call = (
            name in HOST_PROCESS_CALLS
            or leaf in HOST_PROCESS_CALLS
            or name in self.host_process_aliases
            or leaf in self.host_process_aliases
            or name.endswith(".system")
        )
        live_process_call = self._live_host_scope and (
            name == "run_process" or leaf == "run_process" or name in self.host_process_aliases or leaf in self.host_process_aliases
        )
        if is_host_process_call and not live_process_call:
            self.blockers.append({"code": "offline-process-call", "line": node.lineno, "call": name})
        self.generic_visit(node)


def _is_live_probe_module(path: Path) -> bool:
    try:
        return path.resolve() == LIVE_PROBE_MODULE
    except OSError:
        return False


def _import_root(name: str) -> str:
    if name.startswith("google.generativeai"):
        return "google.generativeai"
    return name.split(".", 1)[0]


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Agent Plugins offline execution boundary.")
    parser.add_argument("--path", action="append", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    result = validate_offline_boundary([Path(item) for item in args.path])
    evidence = Path(args.evidence)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

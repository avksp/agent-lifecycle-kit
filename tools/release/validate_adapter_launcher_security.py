from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Any

from release_common import digest_value, file_identity, write_json

FORBIDDEN_SNIPPETS = (
    "shell=True",
    "os.system(",
    "pty.spawn(",
    "pexpect.",
    ".write_text(",
    ".write_bytes(",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", action="append", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    blockers: list[dict[str, Any]] = []
    scanned: list[dict[str, Any]] = []
    for raw in args.paths:
        path = Path(raw)
        files = sorted(path.rglob("*.py")) if path.is_dir() else [path]
        for file_path in files:
            text = file_path.read_text(encoding="utf-8")
            scanned.append(file_identity(file_path))
            for snippet in FORBIDDEN_SNIPPETS:
                if snippet in text and not _allowed_write(file_path, snippet):
                    blockers.append({"code": "adapter-launcher-forbidden-snippet", "path": file_path.as_posix(), "snippet": snippet})
            blockers.extend(_boundary_blockers(file_path, text))
    body = {
        "schemaVersion": "agent-adapter-launcher-security-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "scannedFiles": scanned,
        "blockers": blockers,
        "requiredInvariants": {
            "argvArrays": True,
            "shellFalse": True,
            "envAllowlist": True,
            "redactedReceipts": True,
            "nativeConfigWrites": False,
            "secretStorage": False,
            "genericDescriptorLaunch": False,
            "exactEnvironmentNames": True,
        },
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.evidence), {**body, "validationDigest": digest_value(body)})
    return 0 if not blockers else 1


def _allowed_write(path: Path, snippet: str) -> bool:
    if path.as_posix().endswith("session_store.py") and snippet in {".write_text(", ".write_bytes("}:
        return True
    return False


def _boundary_blockers(path: Path, text: str) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [{"code": "adapter-launcher-source-invalid", "path": path.as_posix()}]

    if path.name == "launcher.py":
        if "adapter-generic-launch-disabled" not in text:
            blockers.append({"code": "adapter-generic-launch-blocker-missing", "path": path.as_posix()})
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                if isinstance(child.func, ast.Name) and child.func.id == "run_process":
                    if node.name == "launch_from_local_profile":
                        continue
                    blockers.append(
                        {
                            "code": "adapter-generic-launch-process-route",
                            "path": path.as_posix(),
                            "function": node.name,
                        }
                    )
                elif _is_subprocess_call(child, "run") and not (
                    node.name == "_git_bytes" and _is_bounded_git_read(child)
                ):
                    blockers.append(
                        {
                            "code": "adapter-git-identity-process-route",
                            "path": path.as_posix(),
                            "function": node.name,
                        }
                    )
    blockers.extend(_popen_blockers(path, tree))
    if path.name == "env.py":
        if "import fnmatch" in text or "fnmatch." in text:
            blockers.append({"code": "adapter-env-wildcard-route", "path": path.as_posix()})
        if "adapter-env-wildcard-disallowed" not in text:
            blockers.append({"code": "adapter-env-wildcard-blocker-missing", "path": path.as_posix()})
    return blockers


def _popen_blockers(path: Path, tree: ast.AST) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for node in getattr(tree, "body", []):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = [
            child
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and _is_subprocess_call(child, "Popen")
        ]
        for call in calls:
            if path.name == "process.py" and node.name == "_run_bounded_process" and _is_bounded_popen(call, node):
                continue
            blockers.append(
                {
                    "code": "adapter-unbounded-process-route",
                    "path": path.as_posix(),
                    "function": node.name,
                }
            )
    return blockers


def _is_bounded_git_read(call: ast.Call) -> bool:
    if len(call.args) != 1 or not isinstance(call.args[0], ast.List):
        return False
    argv = call.args[0].elts
    if len(argv) != 2 or not isinstance(argv[0], ast.Constant) or argv[0].value != "git":
        return False
    if not isinstance(argv[1], ast.Starred) or not isinstance(argv[1].value, ast.Name) or argv[1].value.id != "args":
        return False
    keywords = _keywords(call)
    timeout = keywords.get("timeout")
    return (
        _is_name(keywords.get("cwd"), "root")
        and _is_false(keywords.get("shell"))
        and _is_subprocess_constant(keywords.get("stdin"), "DEVNULL")
        and _is_subprocess_constant(keywords.get("stdout"), "PIPE")
        and _is_subprocess_constant(keywords.get("stderr"), "PIPE")
        and isinstance(timeout, ast.Constant)
        and isinstance(timeout.value, (int, float))
        and 0 < timeout.value <= 10
        and _is_false(keywords.get("check"))
    )


def _is_bounded_popen(call: ast.Call, function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if len(call.args) != 1 or not _is_name(call.args[0], "argv"):
        return False
    keywords = _keywords(call)
    safe_call = (
        _is_false(keywords.get("shell"))
        and _is_name(keywords.get("env"), "env")
        and _is_subprocess_constant(keywords.get("stdin"), "PIPE")
        and _is_subprocess_constant(keywords.get("stdout"), "PIPE")
        and _is_subprocess_constant(keywords.get("stderr"), "PIPE")
    )
    referenced_names = {child.id for child in ast.walk(function) if isinstance(child, ast.Name)}
    process_methods = {
        child.func.attr
        for child in ast.walk(function)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and isinstance(child.func.value, ast.Name)
        and child.func.value.id == "process"
    }
    return (
        safe_call
        and {"max_input_bytes", "max_output_bytes", "timeout_seconds"} <= referenced_names
        and {"kill", "wait"} <= process_methods
    )


def _keywords(call: ast.Call) -> dict[str, ast.expr]:
    return {item.arg: item.value for item in call.keywords if item.arg is not None}


def _is_subprocess_call(call: ast.Call, name: str) -> bool:
    return (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "subprocess"
        and call.func.attr == name
    )


def _is_subprocess_constant(value: ast.expr | None, name: str) -> bool:
    return (
        isinstance(value, ast.Attribute)
        and isinstance(value.value, ast.Name)
        and value.value.id == "subprocess"
        and value.attr == name
    )


def _is_name(value: ast.expr | None, name: str) -> bool:
    return isinstance(value, ast.Name) and value.id == name


def _is_false(value: ast.expr | None) -> bool:
    return isinstance(value, ast.Constant) and value.value is False


if __name__ == "__main__":
    raise SystemExit(main())

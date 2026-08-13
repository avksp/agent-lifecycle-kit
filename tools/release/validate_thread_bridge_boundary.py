from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path
from typing import Any

try:
    from release_common import digest_value, file_identity, write_json
except ModuleNotFoundError:  # pragma: no cover - supports direct package imports in tests
    from tools.release.release_common import digest_value, file_identity, write_json


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
AUTHORITY_MARKERS = re.compile(
    r"\b(?:ignore\s+(?:all\s+)?previous|execute\s+(?:the\s+)?(?:tool|command)|"
    r"approve\s+(?:all\s+)?tools|system\s+instruction|developer\s+instruction|"
    r"bypass\s+(?:review|freeze)|freeze\s+(?:the\s+)?plan|accept\s+(?:the\s+)?task)\b",
    re.IGNORECASE,
)


def validate_thread_bridge_boundary(paths: list[Path]) -> dict[str, Any]:
    checks = [_check_path(path) for path in paths]
    blockers = [blocker for check in checks for blocker in check["blockers"]]
    body = {
        "schemaVersion": "agent-thread-bridge-boundary-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "paths": [path.as_posix() for path in paths],
        "checks": checks,
        "blockers": blockers,
        "modelCallsStarted": False,
        "networkCallsStarted": False,
        "hostExecutionStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def _check_path(path: Path) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not path.is_file():
        return {"path": path.as_posix(), "status": "FAIL", "blockers": [{"code": "thread-boundary-path-missing"}]}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    except SyntaxError as exc:
        return {
            "path": path.as_posix(),
            "status": "FAIL",
            "blockers": [{"code": "thread-boundary-parse-failed", "line": exc.lineno, "message": exc.msg}],
        }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _import_root(alias.name)
                if root in BANNED_IMPORT_ROOTS:
                    blockers.append({"code": "thread-boundary-import", "path": path.as_posix(), "line": node.lineno, "import": root})
        elif isinstance(node, ast.ImportFrom):
            root = _import_root(node.module or "")
            if root in BANNED_IMPORT_ROOTS:
                blockers.append({"code": "thread-boundary-import", "path": path.as_posix(), "line": node.lineno, "import": root})
        elif isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in PROCESS_CALLS or name.rsplit(".", 1)[-1] in PROCESS_CALLS or name.endswith(".system"):
                blockers.append({"code": "thread-boundary-process-call", "path": path.as_posix(), "line": node.lineno, "call": name})
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and AUTHORITY_MARKERS.search(node.value):
            blockers.append({"code": "thread-boundary-authority-marker", "path": path.as_posix(), "line": node.lineno})
    return {
        "path": path.as_posix(),
        "status": "PASS" if not blockers else "FAIL",
        "file": file_identity(path),
        "blockers": blockers,
    }


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", action="append", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    payload = validate_thread_bridge_boundary([Path(item) for item in args.path])
    write_json(Path(args.evidence), payload)
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

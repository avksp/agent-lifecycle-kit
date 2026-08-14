from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Any

try:
    from release_common import digest_value, write_json
except ModuleNotFoundError:  # pragma: no cover - supports direct package imports in tests
    from tools.release.release_common import digest_value, write_json


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
SOURCE_PATHS = (
    "src/agent_lifecycle/contracts/audit_optimization_schemas.py",
    "src/agent_lifecycle/metrics/audit_samples.py",
    "src/agent_lifecycle/metrics/audit_optimization.py",
    "src/agent_lifecycle/metrics/recommendations.py",
    "src/agent_lifecycle/metrics/outcome_index.py",
    "src/agent_lifecycle/metrics/regression_signals.py",
    "src/agent_lifecycle/review_mesh/results.py",
    "src/agent_lifecycle/policy/proposals.py",
    "src/agent_lifecycle/cli/metrics_parser.py",
    "src/agent_lifecycle/cli/dispatch_observability.py",
)
SENSITIVE_STORAGE_MARKERS = ("rawPromptStored = True", "rawOutputStored = True", "secretsStored = True", "providerModelNamesStored = True")


def validate_audit_optimization(root: Path, *, repository_root: Path | None = None) -> dict[str, Any]:
    """Validate that the optimizer remains local, bounded and advisory-only."""

    repo = repository_root or Path.cwd()
    checks = [_check_path(repo / relative) for relative in SOURCE_PATHS]
    blockers = [item for check in checks for item in check["blockers"]]
    body = {
        "schemaVersion": "agent-audit-optimization-boundary-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "evidenceRoot": root.as_posix(),
        "paths": [item.as_posix() for item in (repo / relative for relative in SOURCE_PATHS)],
        "checks": checks,
        "blockers": blockers,
        "modelCallsStarted": False,
        "networkCallsStarted": False,
        "hostExecutionStarted": False,
        "rawPromptStored": False,
        "rawOutputStored": False,
        "secretsStored": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def _check_path(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": path.as_posix(), "status": "FAIL", "blockers": [{"code": "optimizer-path-missing", "path": path.as_posix()}]}
    text = path.read_text(encoding="utf-8")
    blockers: list[dict[str, Any]] = []
    for marker in SENSITIVE_STORAGE_MARKERS:
        if marker in text:
            blockers.append({"code": "optimizer-sensitive-storage-marker", "path": path.as_posix(), "marker": marker})
    try:
        tree = ast.parse(text, filename=path.as_posix())
    except SyntaxError as exc:
        return {"path": path.as_posix(), "status": "FAIL", "blockers": [{"code": "optimizer-parse-failed", "line": exc.lineno, "message": exc.msg}]}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _import_root(alias.name)
                if root in BANNED_IMPORT_ROOTS:
                    blockers.append({"code": "optimizer-boundary-import", "path": path.as_posix(), "line": node.lineno, "import": root})
        elif isinstance(node, ast.ImportFrom):
            root = _import_root(node.module or "")
            if root in BANNED_IMPORT_ROOTS:
                blockers.append({"code": "optimizer-boundary-import", "path": path.as_posix(), "line": node.lineno, "import": root})
        elif isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in PROCESS_CALLS or name.rsplit(".", 1)[-1] in PROCESS_CALLS or name.endswith(".system"):
                blockers.append({"code": "optimizer-host-process-call", "path": path.as_posix(), "line": node.lineno, "call": name})
    return {"path": path.as_posix(), "status": "PASS" if not blockers else "FAIL", "blockers": blockers}


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
    parser.add_argument("--root", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    payload = validate_audit_optimization(Path(args.root))
    write_json(Path(args.evidence), payload)
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

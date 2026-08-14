"""Validate the shell-free process-group boundary and cleanup controls."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import canonical_digest, sha256_hex


def validate_process_boundary(paths: list[Path]) -> dict[str, Any]:
    checks = [_check_path(path) for path in paths]
    blockers = [blocker for check in checks for blocker in check["blockers"]]
    required = {"process.py", "process_groups.py"}
    present = {path.name for path in paths}
    for name in sorted(required - present):
        blockers.append({"code": "process-boundary-required-path-missing", "path": name})
    body = {
        "schemaVersion": "agent-process-boundary-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "paths": [path.as_posix() for path in paths],
        "checks": checks,
        "blockers": blockers,
        "shellExecutionAllowed": False,
        "backgroundCollectorAllowed": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _check_path(path: Path) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not path.is_file():
        return {"path": path.as_posix(), "status": "FAIL", "blockers": [{"code": "process-boundary-path-missing"}]}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    except (OSError, SyntaxError) as exc:
        return {"path": path.as_posix(), "status": "FAIL", "blockers": [{"code": "process-boundary-parse-failed", "errorType": type(exc).__name__}]}
    calls = {_call_name(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    strings = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    if path.name == "process.py":
        if "subprocess.Popen" not in calls:
            blockers.append({"code": "process-boundary-popen-missing"})
        if "popen_group_kwargs" not in calls:
            blockers.append({"code": "process-boundary-group-route-missing"})
        if "ProcessGroupOwner" not in calls:
            blockers.append({"code": "process-boundary-owner-missing"})
        if "cleanup_grace_seconds" not in names:
            blockers.append({"code": "process-boundary-grace-period-missing"})
    if path.name == "process_groups.py":
        if "os.killpg" not in calls:
            blockers.append({"code": "process-boundary-posix-kill-missing"})
        if "CreateJobObjectW" not in strings and "CreateJobObjectW" not in attributes:
            blockers.append({"code": "process-boundary-windows-job-missing"})
        if "TerminateJobObject" not in strings and "TerminateJobObject" not in attributes:
            blockers.append({"code": "process-boundary-windows-terminate-missing"})
    for node in ast.walk(tree):
        if not isinstance(node, ast.keyword) or node.arg != "shell":
            continue
        if isinstance(node.value, ast.Constant) and node.value.value is True:
            blockers.append({"code": "process-boundary-shell-enabled", "line": node.lineno})
    return {
        "path": path.as_posix(),
        "status": "PASS" if not blockers else "FAIL",
        "file": {"sha256": sha256_hex(path.read_bytes()), "bytes": path.stat().st_size},
        "calls": sorted(call for call in calls if call),
        "blockers": blockers,
    }


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate managed process cleanup and shell-free launch boundaries.")
    parser.add_argument("--path", action="append", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    result = validate_process_boundary([Path(item) for item in args.path])
    evidence = Path(args.evidence)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

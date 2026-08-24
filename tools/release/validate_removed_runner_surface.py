"""Validate the Release 2.0 workflow-only execution surface."""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path
from typing import Any

from release_common import digest_value, write_json


REMOVED_COMMANDS = ("start", "status", "transition", "stop", "resume")
ACTIVE_CODE_FILES = (
    "cli/command_registry.py",
    "cli/parsers.py",
    "cli/lifecycle_parsers.py",
    "cli/dispatch_lifecycle.py",
    "workflow/transition_contract.py",
)
REQUIRED_DOC_MARKERS = (
    "workflow run",
    "migrate-runner-artifact",
    "read-only",
    "non-authoritative",
)
REMOVED_COMMAND_PATTERN = re.compile(
    r"agent-lifecycle\s+runner\s+(?:start|status|transition|stop|resume)\b"
)


def validate_removed_runner_surface(*, package_root: Path, docs_root: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []

    for relative in ACTIVE_CODE_FILES:
        path = package_root / relative
        check = _check_active_code_file(path, relative)
        checks.append(check)
        if check["status"] != "PASS":
            blockers.extend(check["blockers"])

    boundary = _check_import_boundary(package_root)
    checks.append(boundary)
    if boundary["status"] != "PASS":
        blockers.extend(boundary["blockers"])

    docs = _check_documentation(docs_root)
    checks.append(docs)
    if docs["status"] != "PASS":
        blockers.extend(docs["blockers"])

    workflow = _check_workflow_route(package_root)
    checks.append(workflow)
    if workflow["status"] != "PASS":
        blockers.extend(workflow["blockers"])

    body = {
        "schemaVersion": "agent-removed-runner-surface-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "removedCommands": [f"runner {command}" for command in REMOVED_COMMANDS],
        "checks": checks,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def _check_active_code_file(path: Path, relative: str) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not path.is_file():
        blockers.append({"code": "removed-runner-surface-file-missing", "path": relative})
        return {"name": "active-code", "path": relative, "status": "FAIL", "blockers": blockers}
    text = path.read_text(encoding="utf-8")
    forbidden = [
        "_add_runner_parser",
        "_dispatch_runner",
        'add_parser("runner"',
        "args.command == \"runner\"",
        "args.command == 'runner'",
    ]
    matches = [marker for marker in forbidden if marker in text]
    if matches:
        blockers.append({"code": "removed-runner-surface-active-reference", "path": relative, "matches": matches})
    return {
        "name": "active-code",
        "path": relative,
        "status": "PASS" if not blockers else "FAIL",
        "matches": matches,
        "blockers": blockers,
    }


def _check_import_boundary(package_root: Path) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    scanned = 0
    for path in sorted(package_root.rglob("*.py")):
        relative = path.relative_to(package_root).as_posix()
        if relative.startswith("runner/") or relative in {
            "contracts/legacy_runner_schemas.py",
            "contracts/runner_schemas.py",
            "contracts/runner_worktree_schemas.py",
        }:
            continue
        scanned += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            blockers.append({"code": "removed-runner-surface-parse-failed", "path": relative, "error": type(exc).__name__})
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
                if any(name == "agent_lifecycle.runner" or name.startswith("agent_lifecycle.runner.") for name in names):
                    blockers.append({"code": "removed-runner-import", "path": relative, "line": node.lineno})
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "agent_lifecycle.runner" or module.startswith("agent_lifecycle.runner."):
                    blockers.append({"code": "removed-runner-import", "path": relative, "line": node.lineno})
    return {
        "name": "active-import-boundary",
        "status": "PASS" if not blockers else "FAIL",
        "scannedFiles": scanned,
        "blockers": blockers,
    }


def _check_documentation(docs_root: Path) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    files = sorted(path for path in docs_root.rglob("*.md") if path.is_file())
    legacy_command_matches: list[str] = []
    marker_files: dict[str, list[str]] = {}
    for path in files:
        relative = path.relative_to(docs_root).as_posix()
        text = path.read_text(encoding="utf-8")
        if REMOVED_COMMAND_PATTERN.search(text):
            legacy_command_matches.append(relative)
        marker_files[relative] = [marker for marker in REQUIRED_DOC_MARKERS if marker in text]
    if legacy_command_matches:
        blockers.append(
            {
                "code": "removed-runner-command-documented-as-active",
                "paths": legacy_command_matches,
            }
        )
    required_paths = ("reference/cli.md", "reference/runner.md", "guides/runner-migration-2.md")
    missing_markers = {
        relative: [marker for marker in REQUIRED_DOC_MARKERS if marker not in marker_files.get(relative, [])]
        for relative in required_paths
        if not all(marker in marker_files.get(relative, []) for marker in REQUIRED_DOC_MARKERS)
    }
    if missing_markers:
        blockers.append({"code": "removed-runner-documentation-incomplete", "paths": missing_markers})
    return {
        "name": "documentation-boundary",
        "status": "PASS" if not blockers else "FAIL",
        "scannedFiles": len(files),
        "requiredPaths": list(required_paths),
        "legacyCommandMatches": legacy_command_matches,
        "blockers": blockers,
    }


def _check_workflow_route(package_root: Path) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    workflow_run = package_root / "workflow/run.py"
    migration = package_root / "migration/legacy_runner.py"
    if not workflow_run.is_file():
        blockers.append({"code": "workflow-route-missing", "path": "workflow/run.py"})
    elif "def run_workflow_step" not in workflow_run.read_text(encoding="utf-8"):
        blockers.append({"code": "workflow-route-missing", "path": "workflow/run.py", "symbol": "run_workflow_step"})
    if not migration.is_file():
        blockers.append({"code": "legacy-migration-missing", "path": "migration/legacy_runner.py"})
    return {
        "name": "workflow-route",
        "status": "PASS" if not blockers else "FAIL",
        "workflowRoute": "workflow/run.py",
        "migrationRoute": "migration/legacy_runner.py",
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--docs-root", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    evidence = validate_removed_runner_surface(
        package_root=Path(args.package_root),
        docs_root=Path(args.docs_root),
    )
    write_json(Path(args.evidence), evidence)
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

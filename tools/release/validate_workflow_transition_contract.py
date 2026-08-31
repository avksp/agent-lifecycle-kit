"""Validate the closed workflow action catalog and its consumers."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts.lifecycle_action_catalog import (
    ACTION_TYPES,
    OPERATION_ACTION_TYPES,
    REMOVED_RUNNER_COMMANDS,
    WORKFLOW_PHASE_ACTION_TYPES,
    validate_action_catalog,
)

try:
    from release_common import digest_value, write_json
except ModuleNotFoundError:
    from tools.release.release_common import digest_value, write_json


CONSUMERS = {
    "src/agent_lifecycle/workflow/query.py": "transition_contract",
    "src/agent_lifecycle/workflow/next_action.py": "transition_contract",
    "src/agent_lifecycle/workflow/run.py": "transition_contract",
    "src/agent_lifecycle/workflow/continuation.py": "transition_contract",
    "src/agent_lifecycle/workflow/continuation_batch.py": "transition_contract",
    "src/agent_lifecycle/host_protocol/lifecycle_gate.py": "lifecycle_action_catalog",
    "src/agent_lifecycle/adapter_sessions/workflow_bridge.py": "transition_contract",
}


def validate_transition_contract(package_root: Path) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    catalog = validate_action_catalog()
    blockers.extend(catalog["blockers"])
    for phase, actions in WORKFLOW_PHASE_ACTION_TYPES.items():
        if not actions:
            blockers.append({"code": "transition-phase-has-no-action", "phase": phase})
    for operation, actions in OPERATION_ACTION_TYPES.items():
        if not actions:
            blockers.append({"code": "transition-operation-has-no-action", "operation": operation})
    source_checks: list[dict[str, Any]] = []
    for relative, marker in sorted(CONSUMERS.items()):
        if package_root.name == "agent_lifecycle" and relative.startswith("src/agent_lifecycle/"):
            path = package_root / relative.removeprefix("src/agent_lifecycle/")
        else:
            path = package_root / relative
        if not path.is_file():
            blockers.append({"code": "transition-consumer-missing", "path": relative})
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        except (OSError, SyntaxError) as exc:
            blockers.append({"code": "transition-consumer-unreadable", "path": relative, "message": str(exc)})
            continue
        imported_names = _imported_names(tree)
        present = marker in imported_names or marker in path.read_text(encoding="utf-8")
        source_checks.append({"path": relative, "marker": marker, "status": "PASS" if present else "FAIL"})
        if not present:
            blockers.append({"code": "transition-consumer-bypasses-catalog", "path": relative, "marker": marker})
    body = {
        "schemaVersion": "agent-workflow-transition-contract-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "catalogDigest": catalog["catalogDigest"],
        "actionTypes": sorted(ACTION_TYPES),
        "phaseCount": len(WORKFLOW_PHASE_ACTION_TYPES),
        "operationCount": len(OPERATION_ACTION_TYPES),
        "removedRunnerCommandCount": len(REMOVED_RUNNER_COMMANDS),
        "sourceChecks": source_checks,
        "catalog": catalog,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def _imported_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[-1] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[-1])
            names.update(alias.name for alias in node.names)
    return names


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    root = Path(args.package_root)
    result = validate_transition_contract(root)
    result["packageRoot"] = root.as_posix()
    result["packageRootExists"] = root.is_dir()
    write_json(
        Path(args.evidence),
        {
            **result,
            "validationDigest": digest_value(
                {key: value for key, value in result.items() if key != "validationDigest"}
            ),
        },
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

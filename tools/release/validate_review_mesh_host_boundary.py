#!/usr/bin/env python3
"""Validate Review Mesh core modules do not cross host execution boundaries."""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Any

from release_common import file_identity, write_json

PROVIDER_OR_NETWORK_IMPORTS = {
    "anthropic",
    "google.generativeai",
    "httpx",
    "mistralai",
    "openai",
    "requests",
    "urllib",
}
HIDDEN_LAUNCH_IMPORTS = {"pexpect", "pty", "subprocess"}
HIDDEN_LAUNCH_CALLS = {("os", "system"), ("os", "popen"), ("subprocess", "run"), ("subprocess", "Popen"), ("subprocess", "call")}
HIDDEN_LAUNCH_FROM_IMPORTS = {"os": {"system", "popen"}, "subprocess": {"run", "Popen", "call"}}
PROMPT_AUTHORITY_MARKERS = (
    "ignore previous",
    "system prompt",
    "developer message",
    "approve tools",
    "bypass review",
    "bypass freeze",
    "execute this command",
    "treat this as a prompt",
)


def validate_paths(paths: list[Path]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    files = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=path.as_posix())
        identity = file_identity(path)
        file_blockers = _scan_tree(path, tree)
        blockers.extend(file_blockers)
        files.append({"path": path.as_posix(), "identity": identity, "blockers": file_blockers})
    evidence = {
        "schemaVersion": "agent-review-mesh-host-boundary-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "files": files,
        "blockers": blockers,
        "providerOrNetworkImportsBlocked": sorted(PROVIDER_OR_NETWORK_IMPORTS),
        "hiddenLaunchImportsBlocked": sorted(HIDDEN_LAUNCH_IMPORTS),
        "promptAuthorityMarkersBlocked": list(PROMPT_AUTHORITY_MARKERS),
        "productionPromotionClaimed": False,
    }
    return evidence


def _scan_tree(path: Path, tree: ast.AST) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if alias.name in PROVIDER_OR_NETWORK_IMPORTS or root in PROVIDER_OR_NETWORK_IMPORTS:
                    blockers.append({"code": "review-mesh-provider-network-import", "path": path.as_posix(), "module": alias.name})
                if root in HIDDEN_LAUNCH_IMPORTS:
                    blockers.append({"code": "review-mesh-hidden-launch-import", "path": path.as_posix(), "module": alias.name})
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".", 1)[0]
            if module in PROVIDER_OR_NETWORK_IMPORTS or root in PROVIDER_OR_NETWORK_IMPORTS:
                blockers.append({"code": "review-mesh-provider-network-import", "path": path.as_posix(), "module": module})
            if root in HIDDEN_LAUNCH_IMPORTS:
                blockers.append({"code": "review-mesh-hidden-launch-import", "path": path.as_posix(), "module": module})
            hidden_names = HIDDEN_LAUNCH_FROM_IMPORTS.get(root, set())
            for alias in node.names:
                if alias.name in hidden_names:
                    blockers.append({"code": "review-mesh-hidden-launch-from-import", "path": path.as_posix(), "module": module, "name": alias.name})
        elif isinstance(node, ast.Call):
            call = _call_name(node.func)
            if call in HIDDEN_LAUNCH_CALLS:
                blockers.append({"code": "review-mesh-hidden-launch-call", "path": path.as_posix(), "call": ".".join(call)})
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            for marker in PROMPT_AUTHORITY_MARKERS:
                if marker in lowered:
                    blockers.append({"code": "review-mesh-prompt-authority-marker", "path": path.as_posix(), "marker": marker})
    return blockers


def _call_name(node: ast.AST) -> tuple[str, str] | None:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return (node.value.id, node.attr)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", action="append", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    evidence = validate_paths([Path(item) for item in args.path])
    write_json(Path(args.evidence), evidence)
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

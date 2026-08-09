#!/usr/bin/env python3
"""Verify that risk execution composes existing policy authorities."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any


def validate_boundary(path: Path, quality_floor: Path, adaptive_policy: Path) -> dict[str, Any]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = _imports(tree)
    blockers: list[dict[str, Any]] = []
    if "agent_lifecycle.policy.quality_floor.resolve_quality_floor" not in imports:
        blockers.append({"code": "risk-policy-quality-floor-reuse-missing"})
    if "agent_lifecycle.model_routing.resolve_model_route" not in imports:
        blockers.append({"code": "risk-policy-model-routing-reuse-missing"})
    if any(name.startswith("agent_lifecycle.policy.adaptive_lifecycle") for name in imports):
        blockers.append({"code": "risk-policy-adaptive-authority-imported"})
    forbidden = ("openai", "anthropic", "requests", "httpx", "subprocess", "urllib")
    for name in sorted(imports):
        if any(name == item or name.startswith(item + ".") for item in forbidden):
            blockers.append({"code": "risk-policy-host-or-provider-import", "import": name})
    body = {
        "schemaVersion": "agent-risk-policy-boundary-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "path": path.as_posix(),
        "qualityFloorPath": quality_floor.as_posix(),
        "qualityFloorDigest": _digest(quality_floor),
        "adaptivePolicyPath": adaptive_policy.as_posix(),
        "adaptivePolicyDigest": _digest(adaptive_policy),
        "checks": {
            "qualityFloorReused": not any(item["code"] == "risk-policy-quality-floor-reuse-missing" for item in blockers),
            "modelRoutingReused": not any(item["code"] == "risk-policy-model-routing-reuse-missing" for item in blockers),
            "adaptivePolicyRemainsSeparate": not any(item["code"] == "risk-policy-adaptive-authority-imported" for item in blockers),
        },
        "blockers": blockers,
    }
    return body


def _imports(tree: ast.AST) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            result.update(f"{module}.{alias.name}" for alias in node.names)
    return result


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--quality-floor", type=Path, required=True)
    parser.add_argument("--adaptive-policy", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    result = validate_boundary(args.path, args.quality_floor, args.adaptive_policy)
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

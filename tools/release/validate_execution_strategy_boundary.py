#!/usr/bin/env python3
"""Verify that execution strategy composes policy without becoming an engine."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any

_REQUIRED_IMPORTS = {
    "agent_lifecycle.policy.risk_execution.derive_risk_execution_profile",
    "agent_lifecycle.policy.adaptive_lifecycle.build_adaptive_lifecycle_decision",
    "agent_lifecycle.policy.adaptive_lifecycle.small_model_packet_eligibility",
    "agent_lifecycle.policy.quality_floor.mode_index",
    "agent_lifecycle.review_mesh.recommendation.recommend_review_mesh_for_plan_manifest",
}
_FORBIDDEN_ROOTS = {
    "anthropic",
    "google.generativeai",
    "httpx",
    "mistralai",
    "openai",
    "requests",
    "subprocess",
    "urllib",
}


def validate_boundary(
    strategy: Path,
    risk: Path,
    adaptive: Path,
    quality_floor: Path,
    review_mesh: Path,
    small_packets: Path,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    strategy_imports = _imports(strategy)
    missing = sorted(_REQUIRED_IMPORTS - strategy_imports)
    blockers.extend({"code": "execution-strategy-authority-reuse-missing", "import": item} for item in missing)
    for name in sorted(strategy_imports):
        if any(name == root or name.startswith(root + ".") for root in _FORBIDDEN_ROOTS):
            blockers.append({"code": "execution-strategy-host-or-provider-import", "import": name})

    authorities = {
        "risk": risk,
        "adaptive": adaptive,
        "qualityFloor": quality_floor,
        "reviewMesh": review_mesh,
    }
    for label, path in authorities.items():
        inverse = sorted(
            name for name in _imports(path) if name.startswith("agent_lifecycle.policy.execution_strategy")
        )
        blockers.extend(
            {"code": "execution-strategy-inverse-authority-import", "authority": label, "import": item}
            for item in inverse
        )

    packet_source = small_packets.read_text(encoding="utf-8")
    for marker in ("executionStrategy", "execution-strategy-compact-blocked"):
        if marker not in packet_source:
            blockers.append({"code": "execution-strategy-small-packet-guard-missing", "marker": marker})

    paths = {"strategy": strategy, **authorities, "smallPackets": small_packets}
    body = {
        "schemaVersion": "agent-execution-strategy-boundary-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "paths": {
            label: {"path": path.as_posix(), "sha256": _digest(path)}
            for label, path in paths.items()
        },
        "checks": {
            "existingAuthoritiesReused": not missing,
            "hostAndProviderImportsAbsent": not any(
                item["code"] == "execution-strategy-host-or-provider-import" for item in blockers
            ),
            "authorityDirectionPreserved": not any(
                item["code"] == "execution-strategy-inverse-authority-import" for item in blockers
            ),
            "smallPacketGuardPresent": not any(
                item["code"] == "execution-strategy-small-packet-guard-missing" for item in blockers
            ),
        },
        "blockers": blockers,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    return body


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
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
    parser.add_argument("--strategy", type=Path, required=True)
    parser.add_argument("--risk", type=Path, required=True)
    parser.add_argument("--adaptive", type=Path, required=True)
    parser.add_argument("--quality-floor", type=Path, required=True)
    parser.add_argument("--review-mesh", type=Path, required=True)
    parser.add_argument("--small-packets", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    result = validate_boundary(
        args.strategy,
        args.risk,
        args.adaptive,
        args.quality_floor,
        args.review_mesh,
        args.small_packets,
    )
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

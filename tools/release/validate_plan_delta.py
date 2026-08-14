#!/usr/bin/env python3
"""Validate plan-delta lineage and authority semantics offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.planning.deltas import build_plan_delta, validate_plan_delta


def _manifest(revision: int = 1, description: str = "same") -> dict:
    return {
        "package": {"id": "release-fixture"},
        "planRevision": revision,
        "status": "FROZEN",
        "baseRevision": {"ref": "main", "sha": "0" * 40},
        "specification": {"requirements": [{"id": "R1", "description": description}], "tier": "S1"},
        "workstreams": [{"id": "WS1", "writes": ["src/example.py"], "evidenceIds": ["EV1"]}],
        "acceptance": {"criteria": [{"id": "AC1"}]},
        "validation": {"extraEvidence": ["EV1"]},
        "budgetPolicy": {"modelTokenBudget": 0},
        "securityGates": ["offline"],
        "finalAuditGates": ["review"],
        "planFiles": ["README.md"],
        "developerOverview": "overview.md",
    }


def validate(root: Path) -> dict:
    before = _manifest()
    after = _manifest(2, "changed")
    delta = build_plan_delta(before, after)
    delta_validation = validate_plan_delta(delta)
    unchanged = build_plan_delta(before, _manifest(2, "same"))
    mismatch = build_plan_delta(before, _manifest(1, "changed"))
    blockers = []
    if delta["status"] != "PASS" or not delta["reviewRequired"] or not delta["newLockRequired"]:
        blockers.append({"code": "authority-change-not-detected"})
    if delta_validation["status"] != "PASS":
        blockers.append({"code": "valid-delta-rejected", "details": delta_validation})
    if unchanged["reviewRequired"]:
        blockers.append({"code": "unchanged-delta-requires-review"})
    if mismatch["status"] != "BLOCKED":
        blockers.append({"code": "lineage-mismatch-accepted"})
    body = {
        "schemaVersion": "agent-plan-delta-release-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "checks": {
            "authorityChange": delta,
            "authorityChangeValidation": delta_validation,
            "documentationOnlyChange": unchanged,
            "invalidLineageBlocked": mismatch["status"] == "BLOCKED",
        },
        "blockers": blockers,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    result = validate(args.root.resolve())
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

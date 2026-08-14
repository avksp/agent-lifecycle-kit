#!/usr/bin/env python3
"""Validate the bounded project-principles contract without model or host calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.project.principles import validate_project_principles


def _valid() -> dict:
    body = {
        "schemaVersion": "agent-project-principles.v1",
        "principlesId": "example-project",
        "revision": 1,
        "entries": [
            {"id": "bounded-changes", "category": "delivery", "statement": "Keep changes small and reviewable."},
        ],
        "authority": {
            "principlesRole": "defaults-and-constraints",
            "sourceOfTruth": "frozen-plan-and-lock",
            "semanticReview": "independent-review",
        },
        "source": {"kind": "project-local", "path": "docs/project-principles.json"},
        "productionPromotionClaimed": False,
    }
    return {**body, "principlesDigest": canonical_digest(body)}


def validate(root: Path) -> dict:
    valid = _valid()
    valid_result = validate_project_principles(valid, project_root=root)
    sensitive = dict(valid)
    sensitive["entries"] = [{"id": "bad", "category": "security", "statement": "Use the command python script.py"}]
    sensitive_result = validate_project_principles(sensitive, project_root=root)
    escaped = dict(valid)
    escaped["source"] = {"kind": "project-local", "path": "../outside.json"}
    escaped["principlesDigest"] = canonical_digest({key: value for key, value in escaped.items() if key != "principlesDigest"})
    escaped_result = validate_project_principles(escaped, project_root=root)
    blockers = []
    if valid_result["status"] != "PASS":
        blockers.append({"code": "valid-fixture-rejected", "details": valid_result})
    if sensitive_result["status"] != "FAIL":
        blockers.append({"code": "sensitive-fixture-accepted"})
    if escaped_result["status"] != "FAIL":
        blockers.append({"code": "escaped-fixture-accepted"})
    body = {
        "schemaVersion": "agent-project-principles-release-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "checks": {
            "validArtifact": valid_result,
            "sensitiveArtifactRejected": sensitive_result["status"] == "FAIL",
            "escapedSourceRejected": escaped_result["status"] == "FAIL",
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

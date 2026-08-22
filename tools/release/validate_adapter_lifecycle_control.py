"""Validate the provider-neutral lifecycle-control candidate declarations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from release_common import digest_value, file_identity, load_json, write_json
except ModuleNotFoundError:  # pragma: no cover - package-style test imports
    from tools.release.release_common import digest_value, file_identity, load_json, write_json

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.live_hosts.claude_lifecycle_control_harness import validate_candidate_template  # noqa: E402

from agent_lifecycle.contracts.lifecycle_control_schemas import validate_lifecycle_control_policy  # noqa: E402
from agent_lifecycle.host_protocol.lifecycle_control_qualification import (  # noqa: E402
    build_fixture_evidence,
    build_qualification_receipt,
    validate_qualification_receipt,
)

VALIDATION_SCHEMA = "agent-adapter-lifecycle-control-validation.v1"
EXPECTED_OPERATIONS = {"file-edit", "shell-command", "task-accept", "run-finalize"}


def validate_adapter_lifecycle_control(
    *,
    adapter_root: Path,
    policy_path: Path,
) -> dict[str, Any]:
    """Validate Claude's copy-preview declaration without launching a host."""

    template_path = adapter_root / "claude" / "lifecycle-control.template.json"
    blockers = validate_candidate_template(template_path)
    checks: list[dict[str, Any]] = []
    try:
        template = load_json(template_path)
    except (OSError, ValueError, TypeError, SystemExit) as exc:
        template = {}
        blockers.append({"code": "candidate-template-read-failed", "type": type(exc).__name__})
    try:
        policy = load_json(policy_path)
    except (OSError, ValueError, TypeError, SystemExit) as exc:
        policy = {}
        blockers.append({"code": "control-policy-read-failed", "type": type(exc).__name__})

    policy_validation = validate_lifecycle_control_policy(policy) if policy else {"status": "FAIL", "blockers": []}
    if policy_validation.get("status") != "PASS":
        blockers.extend(policy_validation.get("blockers", []))
    checks.append(
        {"id": "candidate-template", "status": "PASS" if not validate_candidate_template(template_path) else "FAIL"}
    )
    checks.append({"id": "control-policy", "status": policy_validation.get("status", "FAIL")})

    operations = template.get("operations") if isinstance(template, dict) else None
    if isinstance(operations, dict):
        if set(operations) != EXPECTED_OPERATIONS:
            blockers.append({"code": "candidate-operation-set"})
        for operation, entry in operations.items():
            if not isinstance(entry, dict):
                continue
            declared = entry.get("declaredLevel")
            supported = entry.get("supportedLevel")
            qualified = entry.get("qualifiedLevel")
            if declared != "GUIDANCE_ONLY" or supported != "GUIDANCE_ONLY" or qualified != "GUIDANCE_ONLY":
                blockers.append({"code": "candidate-level-overclaim", "operation": operation})
            if entry.get("qualificationStatus") != "NO_RECOMMENDATION":
                blockers.append({"code": "candidate-qualification-status", "operation": operation})

    host_version = template.get("hostVersion", "") if isinstance(template, dict) else ""
    positive, negative = build_fixture_evidence(
        host="claude-code",
        host_version=host_version if isinstance(host_version, str) else "",
        operation="file-edit",
    )
    fixture_receipt = build_qualification_receipt(
        adapter_id="claude",
        host="claude-code",
        host_version=host_version if isinstance(host_version, str) else "",
        expected_host_version=host_version if isinstance(host_version, str) else "",
        operation="file-edit",
        declared_level="GUIDANCE_ONLY",
        supported_level="GUIDANCE_ONLY",
        positive_evidence=positive,
        negative_evidence=negative,
        evidence_refs=["fixture:claude-lifecycle-control"],
        live_evidence=False,
    )
    fixture_validation = validate_qualification_receipt(fixture_receipt, expected_host_version=host_version)
    if fixture_validation.get("status") != "PASS" or fixture_receipt.get("status") != "NO_RECOMMENDATION":
        blockers.extend(fixture_validation.get("blockers", []))
        blockers.append({"code": "candidate-fixture-validation"})
    checks.append(
        {
            "id": "fixture-nonpromotion",
            "status": "PASS"
            if fixture_validation.get("status") == "PASS" and fixture_receipt.get("status") == "NO_RECOMMENDATION"
            else "FAIL",
        }
    )

    body = {
        "schemaVersion": VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "adapterId": "claude",
        "host": "claude-code",
        "template": file_identity(template_path) if template_path.is_file() else None,
        "policy": file_identity(policy_path) if policy_path.is_file() else None,
        "checks": checks,
        "fixtureQualificationStatus": fixture_receipt.get("status"),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Claude lifecycle-control candidate.")
    parser.add_argument("--adapter-root", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    result = validate_adapter_lifecycle_control(adapter_root=Path(args.adapter_root), policy_path=Path(args.policy))
    write_json(Path(args.evidence), result)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

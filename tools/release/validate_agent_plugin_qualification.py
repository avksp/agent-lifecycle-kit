"""Validate a portable Agent Plugins package against one client profile."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from agent_plugin_package import validate_package
except ModuleNotFoundError:  # pragma: no cover - package import when used as a test module
    from tools.release.agent_plugin_package import validate_package
from agent_lifecycle.contracts import read_json_object
from agent_lifecycle.host_protocol.agent_plugin_qualification import (
    build_offline_qualification_receipt,
    validate_offline_receipt,
)
from agent_lifecycle.contracts.agent_plugin_qualification_schemas import validate_qualification_profile


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a portable Agent Plugins package offline.")
    parser.add_argument("--package", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    package = Path(args.package)
    profile = read_json_object(Path(args.profile), label="Agent Plugins qualification profile")
    profile_validation = validate_qualification_profile(profile)
    package_result = validate_package(package, expected_version=args.version)
    receipt = build_offline_qualification_receipt(
        package_root=package,
        profile=profile,
        package_result=package_result,
    )
    receipt_validation = validate_offline_receipt(receipt)
    blockers = list(profile_validation.get("blockers", []))
    blockers.extend(package_result.get("blockers", []))
    blockers.extend(receipt_validation.get("blockers", []))
    result = {
        "schemaVersion": "agent-plugin-qualification-evidence.v1",
        "status": "PASS" if not blockers and receipt["status"] == "OFFLINE_VALIDATED" else "FAIL",
        "receipt": receipt,
        "receiptValidation": receipt_validation,
        "blockers": blockers,
        "modelCallsStarted": False,
        "networkCallsStarted": False,
        "hostProcessesStarted": 0,
        "productionPromotionClaimed": False,
    }
    evidence = Path(args.evidence)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

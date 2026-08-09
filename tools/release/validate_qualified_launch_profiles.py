from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_lifecycle.adapter_sessions.local_launch_profile import validate_local_launch_profile  # noqa: E402
from agent_lifecycle.adapter_sessions.qualification import load_shipped_launch_profile  # noqa: E402
from release_common import digest_value, file_identity, write_json  # noqa: E402

QUALIFIED_ADAPTERS = ("claude", "codex", "opencode")


def validate_qualified_launch_profiles(adapter_root: Path) -> dict[str, Any]:
    repository_root = adapter_root.resolve().parent
    checks: list[dict[str, Any]] = []
    for adapter_id in QUALIFIED_ADAPTERS:
        blockers: list[dict[str, Any]] = []
        descriptor_path = adapter_root / adapter_id / "adapter.descriptor.json"
        try:
            descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
            profile = load_shipped_launch_profile(adapter_id, repository_root=repository_root)
            validation = validate_local_launch_profile(profile)
        except Exception as error:
            blockers.append({"code": "qualified-launch-profile-load", "adapterId": adapter_id, "error": type(error).__name__})
            checks.append({"adapterId": adapter_id, "status": "FAIL", "blockers": blockers})
            continue
        declared = descriptor.get("qualifiedLaunch")
        if descriptor.get("managedLaunch", {}).get("status") != "WRAPPER_ONLY":
            blockers.append({"code": "qualified-launch-wrapper-boundary", "adapterId": adapter_id})
        if not isinstance(declared, dict) or declared.get("status") != "VERSION_BOUND_LOCAL":
            blockers.append({"code": "qualified-launch-declaration", "adapterId": adapter_id})
        elif declared.get("profilePath") != f"adapters/{adapter_id}/launch_profile.py":
            blockers.append({"code": "qualified-launch-profile-path", "adapterId": adapter_id})
        expected = profile.get("qualification", {}).get("expectedVersion")
        if not isinstance(declared, dict) or declared.get("expectedHostVersion") != expected:
            blockers.append({"code": "qualified-launch-version-binding", "adapterId": adapter_id})
        if validation["status"] != "PASS":
            blockers.extend(validation["blockers"])
        checks.append(
            {
                "adapterId": adapter_id,
                "status": "PASS" if not blockers else "FAIL",
                "descriptor": file_identity(descriptor_path),
                "profile": file_identity(adapter_root / adapter_id / "launch_profile.py"),
                "profileDigest": validation["profileDigest"],
                "blockers": blockers,
            }
        )
    blockers = [item for check in checks for item in check["blockers"]]
    body = {
        "schemaVersion": "agent-qualified-launch-profile-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "checks": checks,
        "blockers": blockers,
        "modelCallsStarted": False,
        "hostProcessesStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter-root", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    payload = validate_qualified_launch_profiles(Path(args.adapter_root))
    write_json(Path(args.evidence), payload)
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

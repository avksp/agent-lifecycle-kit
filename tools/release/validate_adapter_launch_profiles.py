from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from release_common import digest_value, file_identity, load_json, write_json
from agent_lifecycle.host_protocol import validate_adapter_descriptor
from agent_lifecycle.host_protocol.validation import validate_managed_launch_profile


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter-root", default="adapters")
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    adapter_root = Path(args.adapter_root)
    descriptors = sorted(adapter_root.glob("*/adapter.descriptor.json"))
    blockers: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for path in descriptors:
        descriptor = load_json(path)
        descriptor_validation = validate_adapter_descriptor(descriptor)
        profile_validation = validate_managed_launch_profile(descriptor.get("managedLaunch", {}))
        if descriptor_validation["status"] != "PASS":
            blockers.append({"code": "adapter-descriptor-invalid", "path": path.as_posix(), "blockers": descriptor_validation["blockers"]})
        if profile_validation["status"] != "PASS":
            blockers.append({"code": "adapter-launch-profile-invalid", "path": path.as_posix(), "blockers": profile_validation["blockers"]})
        profile = descriptor.get("managedLaunch", {}) if isinstance(descriptor.get("managedLaunch"), dict) else {}
        rows.append(
            {
                "adapterId": descriptor.get("adapterId"),
                "path": path.as_posix(),
                "profileStatus": profile.get("status"),
                "shell": profile.get("shell"),
                "writesNativeConfig": profile.get("writesNativeConfig"),
                "promptInjectionDefault": profile.get("promptInjectionDefault"),
                "identity": file_identity(path),
            }
        )
    if not descriptors:
        blockers.append({"code": "adapter-descriptors-missing", "message": "no adapter descriptors found"})
    body = {
        "schemaVersion": "agent-adapter-launch-profile-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "adapterCount": len(descriptors),
        "profiles": rows,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.evidence), {**body, "validationDigest": digest_value(body)})
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())

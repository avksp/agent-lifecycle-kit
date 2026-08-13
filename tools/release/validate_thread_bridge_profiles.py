from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from release_common import digest_value, file_identity, load_json, write_json

from agent_lifecycle.contracts.thread_bridge_schemas import (
    THREAD_ADAPTER_STATUS_VALUES,
    validate_thread_bridge_profile,
)
from agent_lifecycle.host_protocol import validate_adapter_descriptor, validate_capability_manifest
from agent_lifecycle.host_protocol.capabilities import (
    build_thread_bridge_profile_from_descriptor,
    capability_manifest_identity,
)
from agent_lifecycle.contracts import canonical_digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter-root", default="adapters")
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    adapter_root = Path(args.adapter_root)
    descriptors = sorted(adapter_root.glob("*/adapter.descriptor.json"))
    blockers: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for descriptor_path in descriptors:
        manifest_path = descriptor_path.parent / "capabilities.manifest.json"
        descriptor = load_json(descriptor_path)
        descriptor_validation = validate_adapter_descriptor(descriptor)
        if descriptor_validation["status"] != "PASS":
            blockers.append(
                {
                    "code": "adapter-descriptor-invalid",
                    "path": descriptor_path.as_posix(),
                    "blockers": descriptor_validation["blockers"],
                }
            )
        if not manifest_path.is_file():
            blockers.append({"code": "capability-manifest-missing", "path": manifest_path.as_posix()})
            continue
        manifest = load_json(manifest_path)
        manifest_validation = validate_capability_manifest(manifest, descriptor=descriptor)
        if manifest_validation["status"] != "PASS":
            blockers.append(
                {
                    "code": "capability-manifest-invalid",
                    "path": manifest_path.as_posix(),
                    "blockers": manifest_validation["blockers"],
                }
            )
        profile = descriptor.get("threadBridge")
        projected = manifest.get("threadBridge")
        if not isinstance(profile, dict) or not isinstance(projected, dict):
            blockers.append({"code": "thread-bridge-profile-missing", "path": descriptor_path.as_posix()})
            continue
        profile_validation = validate_thread_bridge_profile(profile)
        if profile_validation["status"] != "PASS":
            blockers.append(
                {
                    "code": "thread-bridge-profile-invalid",
                    "path": descriptor_path.as_posix(),
                    "blockers": profile_validation["blockers"],
                }
            )
        expected = build_thread_bridge_profile_from_descriptor(
            descriptor,
            capability_manifest_digest=capability_manifest_identity(manifest),
        )
        if projected != expected:
            blockers.append({"code": "thread-bridge-profile-drift", "path": manifest_path.as_posix()})
        operations = projected.get("operations") if isinstance(projected.get("operations"), list) else []
        positive = [
            item
            for item in operations
            if isinstance(item, dict) and item.get("declaredStatus") in {"SUPPORTED", "WRAPPER_ONLY"}
        ]
        for item in positive:
            if item.get("declaredStatus") == "SUPPORTED":
                blockers.append(
                    {
                        "code": "thread-bridge-positive-claim-without-receipt",
                        "adapterId": descriptor.get("adapterId"),
                        "operation": item.get("name"),
                    }
                )
        declared_statuses = {
            item.get("declaredStatus")
            for item in operations
            if isinstance(item, dict)
        }
        invalid_statuses = sorted(declared_statuses.difference(THREAD_ADAPTER_STATUS_VALUES))
        if invalid_statuses:
            blockers.append(
                {
                    "code": "thread-bridge-status-invalid",
                    "adapterId": descriptor.get("adapterId"),
                    "statuses": invalid_statuses,
                }
            )
        rows.append(
            {
                "adapterId": descriptor.get("adapterId"),
                "host": descriptor.get("host"),
                "descriptor": file_identity(descriptor_path),
                "capabilityManifest": file_identity(manifest_path),
                "descriptorDigest": canonical_digest(descriptor),
                "capabilityManifestIdentity": capability_manifest_identity(manifest),
                "operationCount": len(operations),
                "declaredStatuses": sorted(declared_statuses),
                "qualificationRequired": projected.get("qualificationRequired"),
            }
        )
    if len(descriptors) != 12:
        blockers.append({"code": "thread-bridge-adapter-count", "expected": 12, "actual": len(descriptors)})
    body = {
        "schemaVersion": "agent-thread-bridge-profile-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "adapterCount": len(descriptors),
        "adapters": rows,
        "blockers": blockers,
        "hostExecutionStarted": False,
        "modelCallsStarted": False,
        "networkCallsStarted": False,
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.evidence), {**body, "validationDigest": digest_value(body)})
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())

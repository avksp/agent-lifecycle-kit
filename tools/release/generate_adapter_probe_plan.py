from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from release_common import canonical_bytes, file_identity, load_json, sha256_hex, write_json


PROFILE_SCHEMA = "agent-adapter-probe-profile.v1"
PLAN_SCHEMA = "agent-adapter-probe-plan.v1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--adapter-root", default="adapters")
    parser.add_argument("--host", action="append", default=[])
    parser.add_argument("--manifest", action="append", default=[])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    profile_path = Path(args.profile)
    profile = load_json(profile_path)
    adapter_root = Path(args.adapter_root)
    blockers: list[dict[str, Any]] = []
    _validate_profile(profile, blockers)
    manifest_paths = _selected_manifest_paths(adapter_root, args.manifest, args.host, blockers)
    max_hosts = _positive_int(profile.get("maxHostsPerPlan"))
    if max_hosts is not None and len(manifest_paths) > max_hosts:
        blockers.append({"code": "adapter-probe-host-cap-exceeded", "hostCount": len(manifest_paths), "maxHostsPerPlan": max_hosts})
    hosts = [_host_plan(path, load_json(path), profile, blockers) for path in manifest_paths]

    body = {
        "schemaVersion": PLAN_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "profile": file_identity(profile_path),
        "profileId": profile.get("profileId"),
        "adapterRoot": adapter_root.as_posix(),
        "manifestCount": len(manifest_paths),
        "hostCount": len(hosts),
        "hosts": hosts,
        "blockers": blockers,
        "liveCallsStarted": False,
        "promotionDecision": "NOT_EVALUATED",
        "maturityChangeClaimed": False,
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.out), {**body, "planDigest": sha256_hex(canonical_bytes(body))})
    return 0 if not blockers else 1


def _validate_profile(profile: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    if profile.get("schemaVersion") != PROFILE_SCHEMA:
        blockers.append({"code": "adapter-probe-profile-schema-invalid"})
    if profile.get("status") != "OPTIONAL":
        blockers.append({"code": "adapter-probe-profile-status-invalid"})
    if profile.get("liveCallsStarted") is not False:
        blockers.append({"code": "adapter-probe-profile-live-calls-started"})
    if profile.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "adapter-probe-profile-production-claim"})
    if profile.get("maturityChangeClaimed") is not False:
        blockers.append({"code": "adapter-probe-profile-maturity-claim"})
    if _positive_int(profile.get("maxHostsPerPlan")) is None:
        blockers.append({"code": "adapter-probe-profile-host-cap-invalid"})
    if _positive_int(profile.get("maxLiveOperationsPerHost")) is None:
        blockers.append({"code": "adapter-probe-profile-operation-cap-invalid"})
    if _positive_int(profile.get("defaultTimeoutSeconds")) is None:
        blockers.append({"code": "adapter-probe-profile-timeout-invalid"})
    _check_string_list(profile.get("deterministicSmokeOperations"), "adapter-probe-profile-smoke-operations-invalid", blockers)
    _check_string_list(profile.get("requiredReceiptSchemas"), "adapter-probe-profile-receipt-schemas-invalid", blockers)


def _selected_manifest_paths(
    adapter_root: Path,
    requested_manifests: list[str],
    requested_hosts: list[str],
    blockers: list[dict[str, Any]],
) -> list[Path]:
    if requested_manifests:
        paths = [Path(value) for value in requested_manifests]
    else:
        if not adapter_root.is_dir():
            blockers.append({"code": "adapter-root-missing", "path": adapter_root.as_posix()})
            return []
        selected = set(requested_hosts)
        paths = [
            path / "capabilities.manifest.json"
            for path in sorted(adapter_root.iterdir(), key=lambda item: item.name)
            if path.is_dir() and (not selected or path.name in selected)
        ]
    missing = [path.as_posix() for path in paths if not path.is_file()]
    for path in missing:
        blockers.append({"code": "adapter-probe-manifest-missing", "path": path})
    return [path for path in paths if path.is_file()]


def _host_plan(path: Path, manifest: dict[str, Any], profile: dict[str, Any], blockers: list[dict[str, Any]]) -> dict[str, Any]:
    before = len(blockers)
    if manifest.get("schemaVersion") != "agent-adapter-capability-manifest.v1":
        blockers.append({"code": "adapter-probe-manifest-schema-invalid", "path": path.as_posix()})
    if manifest.get("promotion", {}).get("productionPromotionClaimed") is not False:
        blockers.append({"code": "adapter-probe-manifest-production-claim", "adapterId": manifest.get("adapterId")})
    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, list):
        blockers.append({"code": "adapter-probe-manifest-capabilities-invalid", "adapterId": manifest.get("adapterId")})
        capabilities = []
    probes = _planned_probes(capabilities, profile)
    max_live = _positive_int(profile.get("maxLiveOperationsPerHost")) or len(probes)
    live_probes = [item for item in probes if item["liveEvidenceRequired"]]
    if len(live_probes) > max_live:
        blockers.append({"code": "adapter-probe-live-operation-cap-exceeded", "adapterId": manifest.get("adapterId")})
    return {
        "adapterId": manifest.get("adapterId"),
        "host": manifest.get("host"),
        "maturity": manifest.get("maturity"),
        "manifest": file_identity(path),
        "manifestDigest": sha256_hex(canonical_bytes(manifest)),
        "descriptorDigest": manifest.get("descriptorDigest"),
        "probeCount": len(probes),
        "requiredLiveOperationCount": len(live_probes),
        "deterministicSmokeOperationCount": len(probes) - len(live_probes),
        "probes": probes,
        "status": "PASS" if len(blockers) == before else "FAIL",
        "promotionDecision": "NOT_EVALUATED",
        "maturityChangeClaimed": False,
        "productionPromotionClaimed": False,
    }


def _planned_probes(capabilities: list[Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    smoke_operations = set(_strings(profile.get("deterministicSmokeOperations")))
    timeout = _positive_int(profile.get("defaultTimeoutSeconds")) or 120
    probes: list[dict[str, Any]] = []
    for item in capabilities:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        live_required = item.get("liveEvidenceRequiredForVerified") is True
        if not live_required and name not in smoke_operations:
            continue
        probes.append(
            {
                "name": name,
                "mapping": item.get("mapping"),
                "category": "live-required" if live_required else "deterministic-smoke",
                "liveEvidenceRequired": live_required,
                "syntheticReplayAccepted": False,
                "hostOperationRequestSchema": "agent-host-operation-request.v1",
                "hostOperationReceiptSchema": "agent-host-operation-receipt.v1",
                "maxAttempts": 1,
                "timeoutSeconds": timeout,
            }
        )
    return probes


def _check_string_list(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        blockers.append({"code": code})


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _positive_int(value: Any) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return None
    return value


if __name__ == "__main__":
    raise SystemExit(main())

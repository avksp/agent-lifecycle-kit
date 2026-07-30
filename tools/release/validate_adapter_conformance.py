from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from release_common import file_identity, load_json, write_json

from agent_lifecycle.host_protocol import validate_adapter_descriptor, validate_capability_manifest, validate_event_capture_conformance


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--adapter-root", default="adapters")
    parser.add_argument("--conformance-root", default="conformance/adapters")
    parser.add_argument("--host", action="append", default=[])
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    baseline_path = Path(args.baseline)
    adapter_root = Path(args.adapter_root)
    conformance_root = Path(args.conformance_root)
    baseline = load_json(baseline_path)
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    hosts = _selected_hosts(adapter_root, args.host)

    if baseline.get("schemaVersion") != "agent-lifecycle-adapter-baseline.v1":
        blockers.append({"code": "invalid-adapter-baseline", "message": "unsupported adapter baseline schemaVersion"})
    if not hosts:
        blockers.append({"code": "missing-adapter-hosts", "message": "no adapter hosts were selected"})

    for adapter_id in hosts:
        checks.append(_check_adapter(adapter_id, adapter_root, conformance_root, baseline, blockers))

    evidence = {
        "schemaVersion": "agent-adapter-conformance-verification.v1",
        "status": "PASS" if not blockers else "FAIL",
        "baseline": file_identity(baseline_path),
        "adapterRoot": adapter_root.as_posix(),
        "conformanceRoot": conformance_root.as_posix(),
        "hosts": hosts,
        "checks": checks,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.evidence), evidence)
    return 0 if not blockers else 1


def _check_adapter(
    adapter_id: str,
    adapter_root: Path,
    conformance_root: Path,
    baseline: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    adapter_dir = adapter_root / adapter_id
    conformance_path = conformance_root / adapter_id / "offline-baseline.json"
    descriptor_path = adapter_dir / "adapter.descriptor.json"
    capability_path = adapter_dir / "capabilities.manifest.json"
    projection_path = adapter_dir / "projection.manifest.json"
    event_stream_path = conformance_root / adapter_id / "event-stream.json"
    event_receipt_path = conformance_root / adapter_id / "event-stream-receipt.json"
    check: dict[str, Any] = {
        "adapterId": adapter_id,
        "status": "PASS",
        "descriptor": _identity_if_file(descriptor_path),
        "capabilityManifest": _identity_if_file(capability_path),
        "projection": _identity_if_file(projection_path),
        "offlineBaseline": _identity_if_file(conformance_path),
        "eventStream": _identity_if_file(event_stream_path),
        "eventStreamReceipt": _identity_if_file(event_receipt_path),
        "validations": {},
    }
    before = len(blockers)
    if not descriptor_path.is_file():
        blockers.append({"code": "missing-adapter-descriptor", "adapterId": adapter_id})
    if not capability_path.is_file():
        blockers.append({"code": "missing-capability-manifest", "adapterId": adapter_id})
    if not conformance_path.is_file():
        blockers.append({"code": "missing-offline-conformance-baseline", "adapterId": adapter_id})
    if len(blockers) != before:
        check["status"] = "FAIL"
        return check

    descriptor = load_json(descriptor_path)
    manifest = load_json(capability_path)
    conformance = load_json(conformance_path)
    projection = load_json(projection_path) if projection_path.is_file() else None
    events = _load_json_array(event_stream_path) if event_stream_path.is_file() else None
    event_receipt = load_json(event_receipt_path) if event_receipt_path.is_file() else None
    descriptor_validation = validate_adapter_descriptor(descriptor, baseline=baseline)
    capability_validation = validate_capability_manifest(manifest, descriptor=descriptor)
    event_capture_validation = validate_event_capture_conformance(
        descriptor=descriptor,
        projection=projection,
        capability_manifest=manifest,
        events=events,
        receipt=event_receipt,
    )
    check["host"] = descriptor.get("host")
    check["maturity"] = descriptor.get("maturity")
    check["validations"] = {
        "descriptor": descriptor_validation["status"],
        "capabilityManifest": capability_validation["status"],
        "eventCapture": event_capture_validation["status"],
    }
    _collect_validation_blockers(adapter_id, descriptor_validation, blockers)
    _collect_validation_blockers(adapter_id, capability_validation, blockers)
    _collect_validation_blockers(adapter_id, event_capture_validation, blockers)
    _validate_offline_baseline(adapter_id, conformance, descriptor, manifest, baseline, blockers)
    _validate_native_manifest(adapter_id, conformance, blockers)
    check["status"] = "PASS" if len(blockers) == before else "FAIL"
    return check


def _validate_offline_baseline(
    adapter_id: str,
    conformance: dict[str, Any],
    descriptor: dict[str, Any],
    manifest: dict[str, Any],
    baseline: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> None:
    expected_descriptor = f"adapters/{adapter_id}/adapter.descriptor.json"
    expected_manifest = f"adapters/{adapter_id}/capabilities.manifest.json"
    if conformance.get("schemaVersion") != "agent-lifecycle-adapter-conformance.v1":
        blockers.append({"code": "invalid-offline-conformance-schema", "adapterId": adapter_id})
    if conformance.get("adapterId") != adapter_id:
        blockers.append({"code": "offline-conformance-adapter-mismatch", "adapterId": adapter_id})
    if conformance.get("host") != descriptor.get("host"):
        blockers.append({"code": "offline-conformance-host-mismatch", "adapterId": adapter_id})
    if conformance.get("adapterDescriptor") != expected_descriptor:
        blockers.append({"code": "offline-conformance-descriptor-path", "adapterId": adapter_id})
    if conformance.get("capabilityManifest") != expected_manifest:
        blockers.append({"code": "offline-conformance-capability-path", "adapterId": adapter_id})
    if descriptor.get("capabilityManifest") != expected_manifest:
        blockers.append({"code": "descriptor-capability-path", "adapterId": adapter_id})
    if manifest.get("adapterId") != adapter_id:
        blockers.append({"code": "capability-manifest-adapter-mismatch", "adapterId": adapter_id})
    if manifest.get("host") != descriptor.get("host"):
        blockers.append({"code": "capability-manifest-host-mismatch", "adapterId": adapter_id})
    if conformance.get("sharedBaseline") != "conformance/core/adapter-baseline.v1.json":
        blockers.append({"code": "offline-conformance-shared-baseline", "adapterId": adapter_id})
    if conformance.get("requiredMaturity") != baseline.get("maturityRules", {}).get("requiredReleaseMaturity"):
        blockers.append({"code": "offline-conformance-maturity-rule", "adapterId": adapter_id})
    if conformance.get("liveRuntimeRequired") is not False:
        blockers.append({"code": "offline-conformance-live-runtime-required", "adapterId": adapter_id})
    if conformance.get("expectedResult") != "PASS":
        blockers.append({"code": "offline-conformance-expected-result", "adapterId": adapter_id})


def _validate_native_manifest(adapter_id: str, conformance: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    native_manifest = conformance.get("nativeManifest")
    if native_manifest is None:
        return
    if not isinstance(native_manifest, str) or not native_manifest:
        blockers.append({"code": "invalid-native-manifest-path", "adapterId": adapter_id})
        return
    if not Path(native_manifest).is_file():
        blockers.append({"code": "missing-native-manifest", "adapterId": adapter_id, "path": native_manifest})


def _collect_validation_blockers(adapter_id: str, validation: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    for blocker in validation.get("blockers", []):
        if isinstance(blocker, dict):
            item = dict(blocker)
            item["adapterId"] = adapter_id
            blockers.append(item)


def _load_json_array(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise SystemExit(f"expected JSON array of objects: {path}")
    return value


def _selected_hosts(adapter_root: Path, requested: list[str]) -> list[str]:
    if requested:
        return sorted(set(requested))
    if not adapter_root.is_dir():
        return []
    return sorted(path.name for path in adapter_root.iterdir() if (path / "adapter.descriptor.json").is_file())


def _identity_if_file(path: Path) -> dict[str, Any] | None:
    return file_identity(path) if path.is_file() else None


if __name__ == "__main__":
    raise SystemExit(main())

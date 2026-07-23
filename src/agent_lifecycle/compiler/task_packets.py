"""Deterministic task packet compilation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_bytes,
    canonical_digest,
    read_json_object,
)


def compile_task_packets(
    manifest_path: Path,
    *,
    out_dir: Path | None = None,
    write: bool = False,
) -> dict[str, Any]:
    root = Path.cwd()
    manifest = read_json_object(manifest_path, label="plan manifest")
    plan_digest = _verify_manifest(root, manifest)
    output_dir = out_dir or _default_output_dir(root, manifest)
    packets = [_packet(manifest, plan_digest, workstream) for workstream in _workstreams(manifest)]
    packet_records = [_packet_record(output_dir, packet) for packet in packets]
    index = _index(manifest, plan_digest, output_dir, packet_records)
    if write:
        _write_packets(output_dir, packets, index)
    return {"index": index, "packets": packets}


def _verify_manifest(root: Path, manifest: dict[str, Any]) -> str:
    if manifest.get("status") != "FROZEN":
        raise LifecycleError("plan-not-frozen", "only FROZEN plans can be compiled")
    package = manifest.get("package", {})
    plan_root = package.get("planArtifactRoot")
    if not isinstance(plan_root, str) or not plan_root:
        raise LifecycleError("invalid-plan-manifest", "package.planArtifactRoot is required")
    digest = canonical_digest(manifest)
    lock = read_json_object(root / plan_root / "plan.lock.json", label="plan lock")
    if lock.get("manifestHash") != digest:
        raise LifecycleError("plan-lock-mismatch", "plan lock does not bind manifest")
    return digest


def _default_output_dir(root: Path, manifest: dict[str, Any]) -> Path:
    artifact_root = manifest.get("package", {}).get("artifactRoot")
    if not isinstance(artifact_root, str) or not artifact_root:
        raise LifecycleError("invalid-plan-manifest", "package.artifactRoot is required")
    return root / artifact_root / "workflow/task-packets"


def _workstreams(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    workstreams = manifest.get("workstreams")
    if not isinstance(workstreams, list) or not workstreams:
        raise LifecycleError("invalid-plan-manifest", "workstreams are required")
    return [item for item in workstreams if isinstance(item, dict)]


def _packet(
    manifest: dict[str, Any],
    plan_digest: str,
    workstream: dict[str, Any],
) -> dict[str, Any]:
    task = _task_projection(workstream)
    specification = _specification_projection(manifest, task)
    packet = {
        "schemaVersion": "agent-task-packet.v1",
        "plan": _plan_projection(manifest, plan_digest),
        "task": task,
        "ownership": _ownership_projection(manifest, workstream),
        "specification": specification,
        "context": {"refs": list(workstream.get("contextRefs", []))},
        "validation": _validation_projection(workstream),
        "acceptance": _acceptance_projection(manifest, workstream),
    }
    model_route = _model_route_projection(workstream)
    if model_route is not None:
        packet["modelRoute"] = model_route
    return packet


def _task_projection(workstream: dict[str, Any]) -> dict[str, Any]:
    task_id = workstream.get("id")
    if not isinstance(task_id, str) or not task_id:
        raise LifecycleError("invalid-plan-manifest", "workstream id is required")
    return {
        "id": task_id,
        "title": workstream.get("title"),
        "goal": workstream.get("title"),
        "owner": workstream.get("owner"),
        "reviewer": workstream.get("reviewer"),
        "dependsOn": list(workstream.get("dependsOn", [])),
        "required": workstream.get("required", True),
        "plannedItems": list(workstream.get("plannedItems", [])),
        "acceptanceIds": list(workstream.get("acceptanceIds", [])),
        "evidenceIds": list(workstream.get("evidenceIds", [])),
        "artifactPaths": dict(workstream.get("artifactPaths", {})),
        "launchGate": workstream.get("launchGate"),
        "capabilityHints": list(workstream.get("capabilityHints", [])),
        "requiredTools": list(workstream.get("requiredTools", [])),
        "executionPolicy": dict(workstream.get("executionPolicy", {})),
        "controllerGates": [],
    }


def _plan_projection(manifest: dict[str, Any], plan_digest: str) -> dict[str, Any]:
    package = manifest.get("package", {})
    return {
        "packageId": package.get("id"),
        "planRevision": manifest.get("planRevision"),
        "planDigest": plan_digest,
        "manifestPath": manifest.get("manifestPath"),
        "developerOverview": manifest.get("developerOverview"),
    }


def _ownership_projection(
    manifest: dict[str, Any],
    workstream: dict[str, Any],
) -> dict[str, Any]:
    return {
        "writes": list(workstream.get("writes", [])),
        "readOnly": list(manifest.get("readOnly", [])),
        "forbiddenWrites": list(manifest.get("forbiddenWrites", [])),
        "leadOwned": list(manifest.get("leadOwned", [])),
    }


def _specification_projection(manifest: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    requirements = list(task.get("plannedItems", []))
    source = manifest.get("specification", {})
    payload = {"taskId": task["id"], "requirements": requirements, "source": source}
    return {
        "tier": source.get("tier"),
        "revision": source.get("revision"),
        "source": source.get("artifact"),
        "requirements": requirements,
        "traceDigest": canonical_digest(payload),
    }


def _validation_projection(workstream: dict[str, Any]) -> dict[str, Any]:
    return {
        "acceptanceIds": list(workstream.get("acceptanceIds", [])),
        "evidenceIds": list(workstream.get("evidenceIds", [])),
    }


def _model_route_projection(workstream: dict[str, Any]) -> dict[str, Any] | None:
    model_route = workstream.get("modelRoute")
    if model_route is None:
        return None
    if not isinstance(model_route, dict):
        raise LifecycleError("invalid-plan-manifest", "workstream.modelRoute must be an object")
    return dict(model_route)


def _acceptance_projection(
    manifest: dict[str, Any],
    workstream: dict[str, Any],
) -> list[dict[str, Any]]:
    wanted = set(workstream.get("acceptanceIds", []))
    checks = manifest.get("acceptanceCriteria", manifest.get("acceptance", []))
    if not isinstance(checks, list):
        return []
    return [item for item in checks if isinstance(item, dict) and item.get("id") in wanted]


def _packet_record(output_dir: Path, packet: dict[str, Any]) -> dict[str, Any]:
    task_id = packet["task"]["id"]
    data = canonical_bytes(packet) + b"\n"
    return {
        "taskId": task_id,
        "path": (output_dir / f"{task_id}.task-packet.json").as_posix(),
        "sha256": canonical_digest(packet),
        "bytes": len(data),
        "dependsOn": packet["task"]["dependsOn"],
    }


def _index(
    manifest: dict[str, Any],
    plan_digest: str,
    output_dir: Path,
    packet_records: list[dict[str, Any]],
) -> dict[str, Any]:
    package = manifest.get("package", {})
    packet_hashes = {item["taskId"]: item["sha256"] for item in packet_records}
    return {
        "packageId": package.get("id"),
        "manifestDigest": plan_digest,
        "outputDirectory": output_dir.as_posix(),
        "packetCount": len(packet_records),
        "packets": packet_records,
        "packetSetHash": canonical_digest({"packets": packet_hashes}),
    }


def _write_packets(
    output_dir: Path,
    packets: list[dict[str, Any]],
    index: dict[str, Any],
) -> None:
    for packet in packets:
        _write_idempotent(output_dir / f"{packet['task']['id']}.task-packet.json", packet)
    _write_idempotent(output_dir / "index.json", index)


def _write_idempotent(path: Path, payload: dict[str, Any]) -> None:
    data = canonical_bytes(payload) + b"\n"
    if path.exists():
        if path.read_bytes() != data:
            raise LifecycleError("output-conflict", f"output exists with different content: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)

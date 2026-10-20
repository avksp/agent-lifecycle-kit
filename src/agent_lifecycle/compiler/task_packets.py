"""Deterministic task packet compilation."""

from __future__ import annotations

import hashlib
import os
import threading
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_bytes,
    canonical_digest,
    read_json_object,
)
from agent_lifecycle.contracts.authority_io import create_authority_bytes, read_authority_bytes
from agent_lifecycle.contracts.authority_text import require_manifest_text
from agent_lifecycle.contracts.execution_target import discard_created_output
from agent_lifecycle.contracts.ownership_paths import (
    compiler_output_paths,
    repository_authority_name,
    require_manifest_authority_paths,
    require_output_footprint,
)
from agent_lifecycle.contracts.process_lock import exclusive_process_lock
from agent_lifecycle.freeze import verify_plan_package_integrity
from agent_lifecycle.planning.validation import validate_plan_manifest
from agent_lifecycle.policy.execution_strategy import validate_execution_strategy

_PUBLICATION_ACTIVE: ContextVar[frozenset[tuple[int, int, str]]] = ContextVar(
    "alk_packet_publications", default=frozenset()
)


@contextmanager
def packet_publication_lock(output_dir: Path) -> Iterator[None]:
    """Serialize the existing publication/adoption boundary, including nested composition."""
    identity = unicodedata.normalize("NFC", output_dir.resolve().as_posix()).casefold()
    key = (os.getpid(), threading.get_ident(), identity)
    active = _PUBLICATION_ACTIVE.get()
    if key in active:
        yield
        return
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    path = Path.home().resolve() / ".agent-lifecycle-kit" / "workflow-locks" / f"packets-{digest}.lock"
    with exclusive_process_lock(path):
        token = _PUBLICATION_ACTIVE.set(active | {key})
        try:
            yield
        finally:
            _PUBLICATION_ACTIVE.reset(token)


def compile_task_packets(
    manifest_path: Path,
    *,
    out_dir: Path | None = None,
    write: bool = False,
    execution_strategy: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    publication_guard: Callable[[], None] | None = None,
) -> dict[str, Any]:
    root = repository_root if repository_root is not None else Path.cwd()
    manifest_path = root / repository_authority_name(root / manifest_path, root)
    manifest = read_json_object(manifest_path, label="plan manifest")
    require_manifest_text(manifest)
    require_manifest_authority_paths(manifest, operation_root=root)
    plan_digest = _verify_manifest(root, manifest)
    _verify_execution_strategy(execution_strategy, plan_digest=plan_digest)
    output_dir = out_dir or _default_output_dir(manifest)
    require_output_footprint(
        manifest,
        compiler_output_paths(manifest, output_dir=output_dir),
        repository_root=root,
        manifest_path=manifest_path,
    )
    packets = [
        _packet(manifest, plan_digest, workstream, execution_strategy=execution_strategy)
        for workstream in _workstreams(manifest)
    ]
    packet_records = [_packet_record(output_dir, packet) for packet in packets]
    index = _index(manifest, plan_digest, output_dir, packet_records)
    if write:
        _write_packets(output_dir, packets, index, repository_root=root, publication_guard=publication_guard)
    return {"index": index, "packets": packets}


def _verify_manifest(root: Path, manifest: dict[str, Any]) -> str:
    if manifest.get("status") != "FROZEN":
        raise LifecycleError("plan-not-frozen", "only FROZEN plans can be compiled")
    validate_plan_manifest(manifest, require_completeness=True)
    package = manifest.get("package", {})
    plan_root = package.get("planArtifactRoot")
    if not isinstance(plan_root, str) or not plan_root:
        raise LifecycleError("invalid-plan-manifest", "package.planArtifactRoot is required")
    digest = canonical_digest(manifest)
    lock = read_json_object(root / plan_root / "plan.lock.json", label="plan lock")
    verify_plan_package_integrity(manifest, lock, repository_root=root)
    return digest


def _default_output_dir(manifest: dict[str, Any]) -> Path:
    artifact_root = manifest.get("package", {}).get("artifactRoot")
    if not isinstance(artifact_root, str) or not artifact_root:
        raise LifecycleError("invalid-plan-manifest", "package.artifactRoot is required")
    return Path(artifact_root) / "workflow/task-packets"


def _workstreams(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    workstreams = manifest.get("workstreams")
    if not isinstance(workstreams, list) or not workstreams:
        raise LifecycleError("invalid-plan-manifest", "workstreams are required")
    return [item for item in workstreams if isinstance(item, dict)]


def _packet(
    manifest: dict[str, Any],
    plan_digest: str,
    workstream: dict[str, Any],
    *,
    execution_strategy: dict[str, Any] | None = None,
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
    strategy = _strategy_projection(execution_strategy, task_id=task["id"])
    if strategy is not None:
        packet["executionStrategy"] = strategy
    return packet


def _verify_execution_strategy(strategy: dict[str, Any] | None, *, plan_digest: str) -> None:
    if strategy is None:
        return
    validation = validate_execution_strategy(strategy)
    if validation["status"] != "PASS":
        raise LifecycleError("task-strategy-invalid", "execution strategy is invalid", {"validation": validation})
    lineage_value = strategy.get("lineage")
    lineage = lineage_value if isinstance(lineage_value, dict) else {}
    if lineage.get("planDigest") != plan_digest:
        raise LifecycleError("task-strategy-plan-mismatch", "execution strategy plan digest mismatch")


def _strategy_projection(strategy: dict[str, Any] | None, *, task_id: str) -> dict[str, Any] | None:
    if strategy is None:
        return None
    lineage_value = strategy.get("lineage")
    lineage = lineage_value if isinstance(lineage_value, dict) else {}
    if lineage.get("taskId") != task_id:
        return None
    implementation = next(
        (
            item
            for item in strategy.get("phaseRoutes", [])
            if isinstance(item, dict) and item.get("phase") == "task-implementation"
        ),
        {},
    )
    packet_value = strategy.get("packet")
    packet = packet_value if isinstance(packet_value, dict) else {}
    quality_value = strategy.get("quality")
    quality = quality_value if isinstance(quality_value, dict) else {}
    projection = {
        "schemaVersion": strategy.get("schemaVersion"),
        "strategyDigest": strategy.get("strategyDigest"),
        "operationId": lineage.get("operationId"),
        "resolvedRiskTier": quality.get("resolvedRiskTier"),
        "qualityFloor": quality.get("qualityFloor"),
        "modelClass": implementation.get("modelClass"),
        "packetMode": packet.get("mode"),
        "sourceDecisionDigests": dict(strategy.get("sourceDecisionDigests", {})),
        "authorityPreserved": packet.get("authorityPreserved") is True,
        "advisoryOnly": True,
    }
    if strategy.get("projectProfileDigest") is not None:
        projection["projectProfileDigest"] = strategy["projectProfileDigest"]
    return projection


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
    checks = _acceptance_criteria(manifest)
    if not isinstance(checks, list):
        return []
    return [item for item in checks if isinstance(item, dict) and item.get("id") in wanted]


def _acceptance_criteria(manifest: dict[str, Any]) -> Any:
    legacy_checks = manifest.get("acceptanceCriteria")
    if legacy_checks is not None:
        return legacy_checks
    acceptance = manifest.get("acceptance")
    if isinstance(acceptance, dict):
        return acceptance.get("criteria")
    return acceptance


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
    *,
    repository_root: Path,
    publication_guard: Callable[[], None] | None = None,
) -> None:
    prepared = [(output_dir / f"{packet['task']['id']}.task-packet.json", packet) for packet in packets]
    prepared.append((output_dir / "index.json", index))
    prepared = [
        (Path(repository_authority_name(repository_root / path, repository_root)), payload)
        for path, payload in prepared
    ]
    with packet_publication_lock(repository_root / output_dir):
        expected = {path: canonical_bytes(payload) + b"\n" for path, payload in prepared}
        for path, data in expected.items():
            try:
                actual = read_authority_bytes(repository_root / path, root=repository_root, max_bytes=len(data))
            except FileNotFoundError:
                continue
            if actual != data:
                raise LifecycleError("output-conflict", "output exists with different content")
        created: list[tuple[Path, bytes, tuple[int, ...]]] = []
        pending: Path | None = None
        try:
            for path, payload in prepared:
                if publication_guard is not None:
                    publication_guard()
                pending = path
                if _write_idempotent(path, payload, repository_root=repository_root):
                    info = (repository_root / path).lstat()
                    identity = (
                        info.st_dev,
                        info.st_ino,
                        info.st_mode,
                        info.st_size,
                        info.st_mtime_ns,
                        info.st_ctime_ns,
                    )
                    created.append((path, expected[path], identity))
                pending = None
        except BaseException as exc:
            conflicts: list[str] = []
            if (
                pending is not None
                and isinstance(exc, LifecycleError)
                and exc.code == "authority-output-unavailable"
                and not discard_created_output(repository_root, str(pending), [expected[pending]], allow_partial=True)
            ):
                conflicts.append(str(pending))
            for path, data, created_identity in reversed(created):
                if not discard_created_output(repository_root, str(path), [data], expected_identity=created_identity):
                    conflicts.append(str(path))
            if conflicts:
                raise LifecycleError(
                    "packet-publication-rollback-conflict",
                    "Changed writer data was retained during rollback",
                    {"paths": conflicts},
                ) from exc
            raise


def _write_idempotent(path: Path, payload: dict[str, Any], *, repository_root: Path | None = None) -> bool:
    data = canonical_bytes(payload) + b"\n"
    root = repository_root if repository_root is not None else Path.cwd()
    path = root / repository_authority_name(root / path, root)
    try:
        create_authority_bytes(path, data, root=root)
    except FileExistsError:
        if read_authority_bytes(path, root=root, max_bytes=len(data)) != data:
            raise LifecycleError("output-conflict", "output exists with different content") from None
        return False
    return True

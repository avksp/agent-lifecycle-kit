from __future__ import annotations

import argparse
import json
from pathlib import Path

from release_common import digest_value, file_identity, load_json, write_json
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.schemas import get_schema
from agent_lifecycle.workflow import check_lineage


REQUIRED_RELEASE_EVIDENCE = (
    "release-assembly.json",
    "release-verification.json",
    "support-matrix-contract.json",
    "deferred-promotion-contract.json",
    "release-neutrality-report.json",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--release-evidence-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--operation-request")
    args = parser.parse_args()

    manifest = load_json(Path(args.manifest))
    state = load_json(Path(args.state))
    evidence_dir = Path(args.release_evidence_dir)
    evidence_payloads, evidence_files, blockers = _load_required_evidence(evidence_dir)
    task_statuses = {task.get("id"): task.get("status") for task in state.get("tasks", [])}
    required_tasks = _required_tasks(manifest, state)
    not_accepted = [task_id for task_id in required_tasks if task_statuses.get(task_id) != "ACCEPTED"]
    lineage = _lineage(manifest, state, evidence_payloads)
    if lineage["status"] != "PASS":
        blockers.append({"code": "lineage-check-failed", "message": "lineage checks failed"})
    status = "PASS" if not blockers and not not_accepted else "FAIL"
    output = {
        "schemaVersion": "agent-final-candidate-audit.v1",
        "semanticStatus": "READY_FOR_FINALIZATION" if status == "PASS" else "CHANGES_REQUIRED",
        "status": status,
        "planRevision": manifest.get("planRevision"),
        "planDigest": digest_value(manifest),
        "stateRevision": state.get("stateRevision"),
        "lineageChecks": lineage["lineageChecks"],
        "missingReleaseEvidence": [item["name"] for item in blockers if item["code"] == "missing-release-evidence"],
        "notAcceptedTasks": not_accepted,
        "blockers": blockers,
        "productionPromotionClaimed": False,
        "operationRequest": args.operation_request,
    }
    if status == "PASS":
        output["releaseEvidence"] = evidence_files
    write_json(Path(args.output), output)
    return 0 if status == "PASS" else 1


def _load_required_evidence(evidence_dir: Path) -> tuple[dict[str, dict], list[dict], list[dict]]:
    payloads: dict[str, dict] = {}
    identities: list[dict] = []
    blockers: list[dict] = []
    for name in REQUIRED_RELEASE_EVIDENCE:
        path = evidence_dir / name
        if not path.is_file():
            blockers.append({"code": "missing-release-evidence", "name": name, "message": "required evidence is missing"})
            continue
        payload = _load_evidence_json(path, name, blockers)
        if payload is None:
            continue
        payloads[name] = payload
        identities.append(file_identity(path))
        blockers.extend(_evidence_blockers(name, payload))
    return payloads, identities, blockers


def _load_evidence_json(path: Path, name: str, blockers: list[dict]) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        blockers.append(
            {
                "code": "malformed-release-evidence",
                "name": name,
                "message": "required evidence must be a JSON object",
                "error": exc.__class__.__name__,
            }
        )
        return None
    if not isinstance(value, dict):
        blockers.append({"code": "malformed-release-evidence", "name": name, "message": "required evidence must be a JSON object"})
        return None
    return value


def _evidence_blockers(name: str, payload: dict) -> list[dict]:
    blockers: list[dict] = []
    schema_version = payload.get("schemaVersion")
    if not isinstance(schema_version, str) or not schema_version:
        blockers.append({"code": "missing-evidence-schema", "name": name, "message": "evidence schemaVersion is missing"})
    else:
        try:
            get_schema(schema_version)
        except LifecycleError:
            blockers.append({"code": "unknown-evidence-schema", "name": name, "schemaVersion": schema_version})
    if "status" in payload and payload.get("status") != "PASS":
        blockers.append({"code": "evidence-status-not-pass", "name": name, "status": payload.get("status")})
    counters = payload.get("counters")
    if isinstance(counters, dict):
        non_zero = {
            key: value
            for key, value in counters.items()
            if not isinstance(value, int) or isinstance(value, bool) or value != 0
        }
        if non_zero:
            blockers.append({"code": "evidence-counters-non-zero", "name": name, "counters": counters})
    if payload.get("productionPromotionClaimed") is True:
        blockers.append({"code": "production-promotion-claim", "name": name})
    if payload.get("mismatches"):
        blockers.append({"code": "release-inventory-mismatch", "name": name, "mismatches": payload.get("mismatches")})
    return blockers


def _required_tasks(manifest: dict, state: dict) -> list[str]:
    manifest_tasks = [
        str(item.get("id"))
        for item in manifest.get("workstreams", [])
        if isinstance(item, dict) and item.get("required", True)
    ]
    if manifest_tasks:
        return sorted(manifest_tasks)
    return sorted(
        str(item.get("id"))
        for item in state.get("tasks", [])
        if isinstance(item, dict) and item.get("required", True)
    )


def _lineage(manifest: dict, state: dict, evidence_payloads: dict[str, dict]) -> dict:
    package = manifest.get("package", {})
    artifact_root = package.get("artifactRoot")
    plan_root = package.get("planArtifactRoot")
    task_index = _load_optional(Path(str(artifact_root)) / "workflow/task-packets/index.json") if isinstance(artifact_root, str) else None
    lock = _load_optional(Path(str(plan_root)) / "plan.lock.json") if isinstance(plan_root, str) else None
    final_audit = _state_artifact(state, "finalAudit")
    final_proof = _state_artifact(state, "finalProof")
    release_inventory = _release_inventory(evidence_payloads)
    return check_lineage(
        manifest,
        state=state,
        task_packet_index=task_index,
        final_audit=final_audit,
        final_proof=final_proof,
        release_inventory=release_inventory,
        lock=lock,
    )


def _load_optional(path: Path) -> dict | None:
    return load_json(path) if path.is_file() else None


def _state_artifact(state: dict, key: str) -> dict | None:
    identity = state.get(key)
    path = identity.get("path") if isinstance(identity, dict) else None
    if not isinstance(path, str):
        return None
    return _load_optional(Path(path))


def _release_inventory(evidence_payloads: dict[str, dict]) -> dict | None:
    assembly = evidence_payloads.get("release-assembly.json")
    inventory = assembly.get("inventory") if isinstance(assembly, dict) else None
    path = inventory.get("path") if isinstance(inventory, dict) else None
    if not isinstance(path, str):
        return None
    return _load_optional(Path(path))


if __name__ == "__main__":
    raise SystemExit(main())

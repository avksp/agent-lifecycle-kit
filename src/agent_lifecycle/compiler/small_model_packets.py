"""Small-model task packet compilation and output validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.compiler.task_packets import compile_task_packets
from agent_lifecycle.context import render_context
from agent_lifecycle.context.profiles import small_model_windows
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest, is_under_repo_path, read_json_object
from agent_lifecycle.policy.adaptive_lifecycle import small_model_packet_eligibility

SMALL_MODEL_PACKET_SCHEMA = "agent-small-model-task-packet.v1"
SMALL_MODEL_INDEX_SCHEMA = "agent-small-model-task-packet-index.v1"
SMALL_MODEL_OUTPUT_CONTRACT_SCHEMA = "agent-small-model-output-contract.v1"
SMALL_MODEL_TASK_RESULT_SCHEMA = "agent-small-model-task-result.v1"
SMALL_MODEL_OUTPUT_VALIDATION_SCHEMA = "agent-small-model-output-validation.v1"
SMALL_MODEL_COMPILE_RESULT_SCHEMA = "agent-small-model-packet-compile-result.v1"

REQUIRED_OUTPUT_FIELDS = (
    "schemaVersion",
    "status",
    "taskId",
    "changedFiles",
    "validation",
    "summary",
    "blockers",
    "writeScopeDigest",
    "outputContractDigest",
    "productionPromotionClaimed",
)


def compile_small_model_packets(
    manifest_path: Path,
    *,
    context_profile_path: Path,
    out_dir: Path | None = None,
    target_window: str = "4k-strict",
    latest_user: str = "Execute this small-model task packet exactly.",
    adaptive_decision: dict[str, Any] | None = None,
    write: bool = False,
) -> dict[str, Any]:
    """Compile frozen task packets into bounded small-model packets."""

    manifest = read_json_object(manifest_path, label="plan manifest")
    profile = read_json_object(context_profile_path, label="context profile")
    if target_window not in small_model_windows(profile):
        raise LifecycleError("small-model-window-unsupported", "target window is not allowed for small-model packets", {"targetWindow": target_window})
    compiled = compile_task_packets(manifest_path, write=False)
    output_dir = out_dir or _default_output_dir(manifest)
    eligibility = small_model_packet_eligibility(adaptive_decision) if adaptive_decision is not None else _default_eligibility()
    blockers = list(eligibility.get("blockers", []))
    packets: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for source_packet in compiled["packets"]:
        summary = build_small_model_state_summary(source_packet)
        rendered = render_context(profile, source_packet, summary, latest_user=latest_user, window=target_window)
        if rendered["status"] != "PASS":
            blockers.append(
                {
                    "code": "small-model-context-overflow",
                    "taskId": source_packet["task"]["id"],
                    "receipt": rendered["receipt"],
                }
            )
        packet = build_small_model_packet(
            source_packet,
            context_receipt=rendered["receipt"],
            adaptive_policy=eligibility,
        )
        packets.append(packet)
        records.append(_packet_record(output_dir, packet))
    index_body = {
        "schemaVersion": SMALL_MODEL_INDEX_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "packageId": compiled["index"]["packageId"],
        "manifestDigest": compiled["index"]["manifestDigest"],
        "sourcePacketSetHash": compiled["index"]["packetSetHash"],
        "outputDirectory": output_dir.as_posix(),
        "targetWindow": target_window,
        "packetCount": len(records),
        "packets": records,
        "adaptivePolicy": eligibility,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    index = {**index_body, "indexDigest": canonical_digest(index_body)}
    if write:
        _write_packets(output_dir, packets, index)
    body = {
        "schemaVersion": SMALL_MODEL_COMPILE_RESULT_SCHEMA,
        "status": index["status"],
        "index": index,
        "packets": packets,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "resultDigest": canonical_digest(body)}


def build_small_model_packet(
    source_packet: dict[str, Any],
    *,
    context_receipt: dict[str, Any],
    adaptive_policy: dict[str, Any],
) -> dict[str, Any]:
    if source_packet.get("schemaVersion") != "agent-task-packet.v1":
        raise LifecycleError("invalid-task-packet", "small-model packets require agent-task-packet.v1 input")
    write_scope = _write_scope(source_packet)
    output_contract = build_small_model_output_contract(source_packet, write_scope=write_scope)
    task = source_packet["task"]
    body = {
        "schemaVersion": SMALL_MODEL_PACKET_SCHEMA,
        "plan": dict(source_packet.get("plan", {})),
        "task": {
            "id": task.get("id"),
            "title": task.get("title"),
            "goal": task.get("goal") or task.get("title"),
            "owner": task.get("owner"),
            "dependsOn": list(task.get("dependsOn", [])),
        },
        "executionSurface": "small-model",
        "sourceTaskPacketDigest": canonical_digest(source_packet),
        "writeScope": write_scope,
        "requiredOutputContract": output_contract,
        "validation": _validation(source_packet),
        "context": {
            "window": context_receipt.get("window"),
            "profileDigest": context_receipt.get("profileDigest"),
            "renderReceiptDigest": canonical_digest(context_receipt),
            "envelopeDigest": context_receipt.get("envelopeDigest"),
            "estimatedTokens": context_receipt.get("estimatedTokens", {}),
            "overflowPolicy": context_receipt.get("overflowPolicy", {}),
        },
        "adaptivePolicy": adaptive_policy,
        "forbiddenActions": [
            "expand-write-scope",
            "change-contracts-without-review",
            "claim-critical-review-calibration",
            "store-provider-or-secret-values",
            "skip-required-output-contract",
        ],
        "compactInstructions": {
            "requiredOutcome": "Return only the required output contract.",
            "doNotDo": [
                "Do not edit outside writeScope.writes.",
                "Do not treat this packet as final audit or production promotion.",
                "Do not invent missing context; block instead.",
            ],
        },
        "productionPromotionClaimed": False,
    }
    return {**body, "packetDigest": canonical_digest(body)}


def build_small_model_output_contract(source_packet: dict[str, Any], *, write_scope: dict[str, Any]) -> dict[str, Any]:
    task = source_packet.get("task", {})
    body = {
        "schemaVersion": SMALL_MODEL_OUTPUT_CONTRACT_SCHEMA,
        "taskId": task.get("id"),
        "requiredSchemaVersion": SMALL_MODEL_TASK_RESULT_SCHEMA,
        "allowedStatuses": ["PASS", "FAIL", "BLOCKED"],
        "requiredFields": list(REQUIRED_OUTPUT_FIELDS),
        "writeScope": write_scope,
        "writeScopeDigest": canonical_digest(write_scope),
        "validation": _validation(source_packet),
        "productionPromotionClaimed": False,
    }
    return {**body, "contractDigest": canonical_digest(body)}


def validate_small_model_output(output: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if contract.get("schemaVersion") != SMALL_MODEL_OUTPUT_CONTRACT_SCHEMA:
        blockers.append({"code": "small-model-output-contract-schema"})
    if output.get("schemaVersion") != SMALL_MODEL_TASK_RESULT_SCHEMA:
        blockers.append({"code": "small-model-output-schema"})
    for field in contract.get("requiredFields", REQUIRED_OUTPUT_FIELDS):
        if field not in output:
            blockers.append({"code": "small-model-output-field-missing", "field": field})
    if output.get("taskId") != contract.get("taskId"):
        blockers.append({"code": "small-model-output-task-mismatch", "taskId": output.get("taskId")})
    if output.get("status") not in contract.get("allowedStatuses", []):
        blockers.append({"code": "small-model-output-status", "status": output.get("status")})
    if output.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "small-model-output-production-claim"})
    if output.get("writeScopeDigest") != contract.get("writeScopeDigest"):
        blockers.append({"code": "small-model-output-write-scope-digest"})
    if output.get("outputContractDigest") != contract.get("contractDigest"):
        blockers.append({"code": "small-model-output-contract-digest"})
    if not isinstance(output.get("summary"), str) or not output.get("summary"):
        blockers.append({"code": "small-model-output-summary"})
    if not isinstance(output.get("validation"), list):
        blockers.append({"code": "small-model-output-validation"})
    if not isinstance(output.get("blockers"), list):
        blockers.append({"code": "small-model-output-blockers"})
    changed_files = output.get("changedFiles")
    if not isinstance(changed_files, list) or not all(isinstance(item, str) and item for item in changed_files):
        blockers.append({"code": "small-model-output-changed-files"})
        changed_files = []
    _check_changed_files(changed_files, contract.get("writeScope", {}), blockers)
    body = {
        "schemaVersion": SMALL_MODEL_OUTPUT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "taskId": contract.get("taskId"),
        "changedFiles": changed_files,
        "blockers": blockers,
        "outputDigest": canonical_digest(output),
        "contractDigest": contract.get("contractDigest"),
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def build_small_model_state_summary(source_packet: dict[str, Any]) -> dict[str, Any]:
    task = source_packet.get("task", {})
    ownership = source_packet.get("ownership", {})
    return {
        "latestUserIntent": f"Complete task {task.get('id')} without expanding scope.",
        "activeDecisions": [
            f"taskId={task.get('id')}",
            "executionSurface=small-model",
            "outputContract=required",
        ],
        "openBlockers": [],
        "acceptedEvidence": [{"id": item, "status": "required"} for item in task.get("evidenceIds", [])],
        "changedFiles": list(ownership.get("writes", [])),
        "nextRequiredAction": "execute the micro-packet or return BLOCKED with a concrete reason",
        "doNotDo": [
            "Do not expand write scope.",
            "Do not skip validation commands.",
            "Do not claim final audit or production promotion.",
        ],
    }


def _validation(source_packet: dict[str, Any]) -> dict[str, Any]:
    validation = dict(source_packet.get("validation", {}))
    commands = source_packet.get("task", {}).get("validationCommands")
    if isinstance(commands, list):
        validation["commands"] = list(commands)
    else:
        validation["commands"] = list(source_packet.get("validation", {}).get("commands", []))
    return validation


def _write_scope(source_packet: dict[str, Any]) -> dict[str, Any]:
    ownership = source_packet.get("ownership", {})
    writes = _string_list(ownership.get("writes", []))
    return {
        "writes": writes,
        "readOnly": _string_list(ownership.get("readOnly", [])),
        "forbiddenWrites": _string_list(ownership.get("forbiddenWrites", [])),
        "leadOwned": list(ownership.get("leadOwned", [])) if isinstance(ownership.get("leadOwned", []), list) else [],
        "exact": True,
        "cannotExpand": True,
        "writeScopeDigest": canonical_digest({"writes": writes}),
    }


def _check_changed_files(changed_files: list[str], write_scope: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    writes = _string_list(write_scope.get("writes", []))
    read_only = _string_list(write_scope.get("readOnly", []))
    forbidden = _string_list(write_scope.get("forbiddenWrites", []))
    for path in changed_files:
        if writes and not any(is_under_repo_path(path, root) for root in writes):
            blockers.append({"code": "small-model-output-outside-write-scope", "path": path})
        if any(is_under_repo_path(path, root) for root in [*read_only, *forbidden]):
            blockers.append({"code": "small-model-output-forbidden-path", "path": path})


def _packet_record(output_dir: Path, packet: dict[str, Any]) -> dict[str, Any]:
    task_id = packet["task"]["id"]
    data = canonical_bytes(packet) + b"\n"
    return {
        "taskId": task_id,
        "path": (output_dir / f"{task_id}.small-model-packet.json").as_posix(),
        "sha256": packet["packetDigest"],
        "bytes": len(data),
        "sourceTaskPacketDigest": packet["sourceTaskPacketDigest"],
    }


def _default_output_dir(manifest: dict[str, Any]) -> Path:
    artifact_root = manifest.get("package", {}).get("artifactRoot")
    if not isinstance(artifact_root, str) or not artifact_root:
        raise LifecycleError("invalid-plan-manifest", "package.artifactRoot is required")
    return Path(artifact_root) / "workflow/small-model-packets"


def _write_packets(output_dir: Path, packets: list[dict[str, Any]], index: dict[str, Any]) -> None:
    for packet in packets:
        _write_idempotent(output_dir / f"{packet['task']['id']}.small-model-packet.json", packet)
    _write_idempotent(output_dir / "index.json", index)


def _write_idempotent(path: Path, payload: dict[str, Any]) -> None:
    data = canonical_bytes(payload) + b"\n"
    if path.exists():
        if path.read_bytes() != data:
            raise LifecycleError("output-conflict", f"output exists with different content: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str) and item] if isinstance(value, list) else []


def _default_eligibility() -> dict[str, Any]:
    return {
        "status": "PASS",
        "decisionDigest": None,
        "qualityFloor": None,
        "recommendedMode": None,
        "smallModelPacketEligible": True,
        "advisoryOnly": True,
        "blockers": [],
    }

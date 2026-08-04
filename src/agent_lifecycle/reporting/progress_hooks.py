"""Opt-in workflow progress hooks built on the read-only progress bridge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object, write_json_create
from agent_lifecycle.reporting.progress_bridge import (
    SUPPORT_LEVELS,
    build_progress_bridge_receipt,
    render_progress_bridge_terminal,
)

PROGRESS_HOOK_POLICY_SCHEMA = "agent-progress-hook-policy.v1"
PROGRESS_HOOK_RECEIPT_SCHEMA = "agent-progress-hook-receipt.v1"

HOOK_MODES = {"off", "stderr", "receipt"}
HOOK_COMMANDS = {
    "workflow run": "after-workflow-run",
    "workflow task-result": "after-task-result",
    "workflow task-accept": "after-task-accept",
    "workflow finalize": "after-finalize",
}
HOOK_POINTS = set(HOOK_COMMANDS.values())
PROGRESS_HOOK_ENV = "ALK_PROGRESS_HOOK"


def build_progress_hook_policy(*, hook_mode: str = "off") -> dict[str, Any]:
    """Return the safe operating policy for workflow progress hooks."""

    mode = _enum("hookMode", hook_mode, HOOK_MODES)
    body = {
        "schemaVersion": PROGRESS_HOOK_POLICY_SCHEMA,
        "status": "PASS",
        "hookMode": mode,
        "allowedHookModes": sorted(HOOK_MODES),
        "allowedCommands": sorted(HOOK_COMMANDS),
        "allowedHookPoints": [HOOK_COMMANDS[key] for key in sorted(HOOK_COMMANDS)],
        "envVar": PROGRESS_HOOK_ENV,
        "defaultEnabled": False,
        "stdoutJsonPreserved": True,
        "stderrOnly": mode == "stderr",
        "receiptPathAllowed": mode == "receipt",
        "readOnly": True,
        "modelCallsStarted": False,
        "stateWritten": False,
        "tokenSpendForProgress": False,
        "pluginInstalledIsLifecycleProof": False,
        "autoClaimRequiresManagedWorkflowProof": True,
        "productionPromotionClaimed": False,
    }
    return {**body, "policyDigest": canonical_digest(body)}


def build_progress_hook_receipt(
    *,
    adapter_id: str,
    support_level: str,
    command: str,
    hook_point: str,
    hook_mode: str,
    state_path: Path,
    managed_workflow_proof: dict[str, Any],
    usage_receipt_paths: list[Path] | None = None,
    change_summary_path: Path | None = None,
) -> dict[str, Any]:
    """Build an attested workflow progress hook receipt."""

    mode = _enum("hookMode", hook_mode, {"stderr", "receipt"})
    level = _enum("supportLevel", support_level, SUPPORT_LEVELS)
    normalized_command = _enum("command", command, set(HOOK_COMMANDS))
    expected_hook = HOOK_COMMANDS[normalized_command]
    hook = _enum("hookPoint", hook_point, HOOK_POINTS)
    if hook != expected_hook:
        raise LifecycleError(
            "progress-hook-command-mismatch",
            "progress hook point does not match workflow command",
            {"command": normalized_command, "hookPoint": hook, "expectedHookPoint": expected_hook},
        )
    proof = _managed_workflow_proof(managed_workflow_proof, normalized_command)
    bridge = build_progress_bridge_receipt(
        adapter_id=adapter_id,
        support_level=level,
        hook_point=hook,
        state_path=state_path,
        usage_receipt_paths=usage_receipt_paths or [],
        change_summary_path=change_summary_path,
        display_mode="terminal",
    )
    state_payload = read_json_object(state_path, label="workflow state")
    state_identity = {
        "schemaVersion": state_payload.get("schemaVersion"),
        "statePath": state_path.as_posix(),
        "stateRevision": state_payload.get("stateRevision"),
        "phase": state_payload.get("phase"),
        "runId": state_payload.get("runId"),
        "packageId": state_payload.get("packageId"),
        "planDigest": state_payload.get("planDigest"),
    }
    auto_claim_allowed = level == "AUTO" and proof["status"] == "PASS"
    body = {
        "schemaVersion": PROGRESS_HOOK_RECEIPT_SCHEMA,
        "status": "EMITTED" if mode == "stderr" else "RECORDED",
        "adapterId": bridge["adapterId"],
        "supportLevel": level,
        "command": normalized_command,
        "hookPoint": hook,
        "hookMode": mode,
        "displayMode": "terminal",
        "managedWorkflow": True,
        "managedWorkflowProof": proof,
        "autoClaimAllowed": auto_claim_allowed,
        "pluginInstalledIsLifecycleProof": False,
        "stdoutJsonPreserved": True,
        "readOnly": True,
        "modelCallsStarted": False,
        "stateWritten": False,
        "tokenSpendForProgress": False,
        "tokenCountsInferred": False,
        "hostTelemetryParsedInCore": False,
        "stateIdentity": state_identity,
        "progressIdentity": bridge["progressIdentity"],
        "bridgeDigest": bridge["bridgeDigest"],
        "terminalText": render_progress_bridge_terminal(bridge),
        "renderedLines": bridge["renderedLines"],
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def write_progress_hook_receipt(path: Path, receipt: dict[str, Any]) -> None:
    """Write a hook receipt without overwriting prior evidence."""

    write_json_create(path, receipt)


def _managed_workflow_proof(value: dict[str, Any], command: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError("progress-hook-proof-invalid", "managed workflow proof must be an object")
    proof = dict(value)
    proof.setdefault("kind", "alk-managed-workflow-command")
    proof.setdefault("command", command)
    proof.setdefault("status", "PASS")
    if proof.get("status") != "PASS":
        raise LifecycleError("progress-hook-proof-not-pass", "managed workflow proof must be PASS", {"proof": proof})
    if proof.get("kind") != "alk-managed-workflow-command":
        raise LifecycleError("progress-hook-proof-kind", "managed workflow proof kind is unsupported", {"proof": proof})
    if proof.get("command") != command:
        raise LifecycleError(
            "progress-hook-proof-command",
            "managed workflow proof command does not match hook command",
            {"proofCommand": proof.get("command"), "command": command},
        )
    return proof


def _enum(field: str, value: str, allowed: set[str]) -> str:
    if value not in allowed:
        raise LifecycleError("progress-hook-invalid-enum", f"invalid {field}: {value}", {"field": field, "allowed": sorted(allowed)})
    return value

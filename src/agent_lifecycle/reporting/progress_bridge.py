"""Adapter-facing progress bridge receipts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.reporting.progress_terminal import render_progress_terminal
from agent_lifecycle.reporting.progress_view import build_lifecycle_progress_view, build_lifecycle_progress_watch

PROGRESS_BRIDGE_RECEIPT_SCHEMA = "agent-progress-bridge-receipt.v1"
PROGRESS_BRIDGE_CONFIG_SCHEMA = "agent-progress-bridge-config.v1"

SUPPORT_LEVELS = {"AUTO", "WATCH", "MANUAL", "UNSUPPORTED"}
HOOK_POINTS = {
    "after-workflow-run",
    "after-task-result",
    "after-task-accept",
    "after-finalize",
    "side-terminal-watch",
    "manual",
}
DISPLAY_MODES = {"terminal", "json"}


def build_progress_bridge_config(
    *,
    adapter_id: str,
    support_level: str,
    hook_points: list[str],
    display_mode: str = "terminal",
) -> dict[str, Any]:
    """Build a static adapter progress bridge support declaration."""

    adapter = _adapter_id(adapter_id)
    level = _enum("supportLevel", support_level, SUPPORT_LEVELS)
    hooks = [_enum("hookPoint", item, HOOK_POINTS) for item in hook_points]
    if not hooks:
        raise LifecycleError("progress-bridge-hook-points-missing", "progress bridge config needs at least one hook point")
    mode = _enum("displayMode", display_mode, DISPLAY_MODES)
    body = {
        "schemaVersion": PROGRESS_BRIDGE_CONFIG_SCHEMA,
        "status": "PASS",
        "adapterId": adapter,
        "supportLevel": level,
        "hookPoints": hooks,
        "displayMode": mode,
        "sourceOfTruth": False,
        "readOnly": True,
        "modelCallsStarted": False,
        "stateWritten": False,
        "tokenSpendForProgress": False,
        "hostTelemetryParsedInCore": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "configDigest": canonical_digest(body)}


def build_progress_bridge_receipt(
    *,
    adapter_id: str,
    support_level: str,
    hook_point: str,
    state_path: Path,
    usage_receipt_paths: list[Path] | None = None,
    change_summary_path: Path | None = None,
    display_mode: str = "terminal",
    watch: bool = False,
    iterations: int = 1,
    interval_seconds: float = 0.0,
) -> dict[str, Any]:
    """Build a read-only progress bridge receipt for host adapter wrappers."""

    adapter = _adapter_id(adapter_id)
    level = _enum("supportLevel", support_level, SUPPORT_LEVELS)
    hook = _enum("hookPoint", hook_point, HOOK_POINTS)
    mode = _enum("displayMode", display_mode, DISPLAY_MODES)
    usage_paths = usage_receipt_paths or []
    if watch:
        progress = build_lifecycle_progress_watch(
            state_path=state_path,
            usage_receipt_paths=usage_paths,
            change_summary_path=change_summary_path,
            iterations=iterations,
            interval_seconds=interval_seconds,
        )
        progress_identity = {"schemaVersion": progress["schemaVersion"], "digest": progress["watchDigest"]}
    else:
        progress = build_lifecycle_progress_view(
            state_path=state_path,
            usage_receipt_paths=usage_paths,
            change_summary_path=change_summary_path,
        )
        progress_identity = {"schemaVersion": progress["schemaVersion"], "digest": progress["progressDigest"]}
    rendered = render_progress_terminal(progress)
    body = {
        "schemaVersion": PROGRESS_BRIDGE_RECEIPT_SCHEMA,
        "status": "PASS",
        "adapterId": adapter,
        "supportLevel": level,
        "hookPoint": hook,
        "displayMode": mode,
        "sourceOfTruth": False,
        "readOnly": True,
        "modelCallsStarted": False,
        "stateWritten": False,
        "tokenSpendForProgress": False,
        "tokenCountsInferred": False,
        "hostTelemetryParsedInCore": False,
        "terminal": bool(progress.get("terminal")),
        "watch": watch,
        "inputCounts": {
            "usageReceiptCount": len(usage_paths),
            "changeSummaryProvided": change_summary_path is not None,
        },
        "progressIdentity": progress_identity,
        "renderedLines": rendered.splitlines(),
        "terminalText": rendered,
        "productionPromotionClaimed": False,
    }
    return {**body, "bridgeDigest": canonical_digest(body)}


def render_progress_bridge_terminal(receipt: dict[str, Any]) -> str:
    """Return terminal text from a progress bridge receipt."""

    if receipt.get("schemaVersion") != PROGRESS_BRIDGE_RECEIPT_SCHEMA:
        raise LifecycleError(
            "progress-bridge-unsupported-schema",
            "unsupported progress bridge receipt schema",
            {"schemaVersion": receipt.get("schemaVersion")},
        )
    terminal_text = receipt.get("terminalText")
    if not isinstance(terminal_text, str) or not terminal_text:
        raise LifecycleError("progress-bridge-terminal-missing", "progress bridge receipt has no terminal text")
    return terminal_text


def _adapter_id(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleError("progress-bridge-adapter-missing", "adapter id is required")
    return value.strip()


def _enum(field: str, value: str, allowed: set[str]) -> str:
    if value not in allowed:
        raise LifecycleError(
            "progress-bridge-invalid-enum",
            f"invalid {field}: {value}",
            {"field": field, "allowed": sorted(allowed)},
        )
    return value

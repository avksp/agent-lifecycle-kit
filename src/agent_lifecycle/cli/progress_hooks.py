"""CLI plumbing for opt-in workflow progress hooks."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.reporting.progress_hooks import (
    HOOK_COMMANDS,
    PROGRESS_HOOK_ENV,
    build_progress_hook_receipt,
    write_progress_hook_receipt,
)

PROGRESS_HOOK_MODES = ("off", "stderr", "receipt")
PROGRESS_HOOK_SUPPORT_LEVELS = ("AUTO", "WATCH", "MANUAL", "UNSUPPORTED")


def add_progress_hook_args(parser: argparse.ArgumentParser) -> None:
    """Add common opt-in progress hook flags to supported workflow commands."""

    parser.add_argument("--progress-hook", choices=PROGRESS_HOOK_MODES)
    parser.add_argument("--progress-receipt")
    parser.add_argument("--progress-adapter", default="alk-workflow")
    parser.add_argument("--progress-support-level", choices=PROGRESS_HOOK_SUPPORT_LEVELS, default="AUTO")
    parser.add_argument("--progress-usage-receipt", action="append", default=[])
    parser.add_argument("--progress-change-summary")
    parser.add_argument("--progress-managed-proof")


def validate_workflow_progress_hook_request(args: argparse.Namespace, *, command: str) -> None:
    """Validate hook flags before a workflow command can mutate state."""

    mode = _resolve_hook_mode(args)
    if mode == "off":
        return
    if command not in HOOK_COMMANDS:
        raise LifecycleError("progress-hook-command-unsupported", "workflow command does not support progress hooks", {"command": command})
    if mode == "receipt" and not getattr(args, "progress_receipt", None):
        raise LifecycleError("progress-hook-receipt-path-missing", "--progress-hook receipt requires --progress-receipt")


def maybe_emit_workflow_progress_hook(
    args: argparse.Namespace,
    *,
    command: str,
    state_path: Path,
) -> dict[str, Any] | None:
    """Emit progress for a completed workflow command without touching stdout."""

    mode = _resolve_hook_mode(args)
    if mode == "off":
        return None
    receipt_path = Path(args.progress_receipt) if getattr(args, "progress_receipt", None) else None
    proof = _managed_workflow_proof(args, command)
    receipt = build_progress_hook_receipt(
        adapter_id=args.progress_adapter,
        support_level=args.progress_support_level,
        command=command,
        hook_point=HOOK_COMMANDS[command],
        hook_mode=mode,
        state_path=state_path,
        managed_workflow_proof=proof,
        usage_receipt_paths=[Path(item) for item in args.progress_usage_receipt],
        change_summary_path=Path(args.progress_change_summary) if args.progress_change_summary else None,
    )
    if mode == "receipt":
        write_progress_hook_receipt(receipt_path, receipt)
    else:
        sys.stderr.write(receipt["terminalText"].rstrip("\n") + "\n")
    return receipt


def _resolve_hook_mode(args: argparse.Namespace) -> str:
    flag_value = getattr(args, "progress_hook", None)
    if flag_value:
        return flag_value
    env_value = os.environ.get(PROGRESS_HOOK_ENV, "").strip().lower()
    if not env_value:
        return "off"
    if env_value != "stderr":
        raise LifecycleError(
            "progress-hook-env-unsupported",
            f"{PROGRESS_HOOK_ENV} only supports stderr",
            {"envVar": PROGRESS_HOOK_ENV, "value": env_value, "allowed": ["stderr"]},
        )
    return env_value


def _managed_workflow_proof(args: argparse.Namespace, command: str) -> dict[str, Any]:
    if getattr(args, "progress_managed_proof", None):
        return {
            "kind": "alk-managed-workflow-command",
            "status": "PASS",
            "command": command,
            "proof": args.progress_managed_proof,
        }
    proof: dict[str, Any] = {
        "kind": "alk-managed-workflow-command",
        "status": "PASS",
        "command": command,
        "statePath": str(args.state),
    }
    for attr, key in (
        ("operation_id", "operationId"),
        ("expected_revision", "expectedRevision"),
        ("source_revision", "sourceRevision"),
        ("task", "taskId"),
    ):
        value = getattr(args, attr, None)
        if value is not None:
            proof[key] = value
    return proof

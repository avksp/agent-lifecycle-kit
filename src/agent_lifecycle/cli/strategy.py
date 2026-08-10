"""CLI integration for read-only execution strategy resolution."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.launcher import load_adapter_descriptor
from agent_lifecycle.contracts import LifecycleError, read_json_object, write_json_create
from agent_lifecycle.policy.execution_strategy import resolve_execution_strategy


def dispatch_strategy(args: argparse.Namespace) -> dict[str, Any]:
    if args.strategy_command != "resolve":
        raise LifecycleError("command-not-implemented", "strategy command is not implemented")
    _descriptor_path, descriptor = load_adapter_descriptor(
        args.adapter,
        Path(args.descriptor) if args.descriptor else None,
    )
    payload = resolve_execution_strategy(
        manifest=read_json_object(Path(args.manifest), label="frozen plan manifest"),
        lock=read_json_object(Path(args.lock), label="plan lock"),
        state=read_json_object(Path(args.state), label="workflow state"),
        task_id=args.task,
        adapter_id=args.adapter,
        adapter_host=str(descriptor.get("host", "")),
        operation_id=args.operation_id,
        expected_revision=args.expected_revision,
        source_revision=args.source_revision,
        requested_risk=args.risk,
        risk_policy=read_json_object(Path(args.risk_policy), label="risk execution policy"),
        routing_profile=read_json_object(Path(args.routing_profile), label="model routing profile"),
        baseline_profile=read_json_object(Path(args.baseline_profile), label="lifecycle baseline profile"),
        host_profile=(
            read_json_object(Path(args.host_model_profile), label="host model profile")
            if args.host_model_profile
            else None
        ),
    )
    try:
        write_json_create(Path(args.out), payload)
    except FileExistsError as exc:
        raise LifecycleError("output-already-exists", "execution strategy output already exists") from exc
    return payload

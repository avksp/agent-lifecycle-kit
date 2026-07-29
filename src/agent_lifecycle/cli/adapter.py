"""Adapter CLI parser and dispatch."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, read_json_object
from agent_lifecycle.host_protocol import (
    inspect_adapter_descriptor,
    require_adapter_event_stream_pass,
    require_adapter_inspection_pass,
    require_adapter_validation_pass,
    scaffold_adapter,
    validate_adapter_descriptor,
    validate_adapter_event_stream,
)


def add_adapter_parser(subparsers: argparse._SubParsersAction) -> None:
    adapter = subparsers.add_parser("adapter", help="adapter commands")
    adapter_sub = adapter.add_subparsers(dest="adapter_command")
    adapter_validate = adapter_sub.add_parser("validate")
    adapter_validate.add_argument("--descriptor", required=True)
    adapter_validate.add_argument("--baseline")
    adapter_validate.add_argument("--request", action="append", default=[])
    adapter_validate.add_argument("--receipt", action="append", default=[])
    adapter_inspect = adapter_sub.add_parser("inspect")
    adapter_inspect.add_argument("--descriptor", required=True)
    adapter_inspect.add_argument("--host-bin")
    adapter_inspect.add_argument("--project-root", default=".")
    adapter_inspect.add_argument("--skip-host-commands", action="store_true")
    adapter_inspect.add_argument("--timeout-seconds", type=float, default=10.0)
    adapter_event = adapter_sub.add_parser("event-check")
    adapter_event.add_argument("--event", action="append", required=True)
    adapter_scaffold = adapter_sub.add_parser("scaffold")
    adapter_scaffold.add_argument("--host", required=True)
    adapter_scaffold.add_argument("--target", required=True)
    adapter_scaffold.add_argument("--maturity", default="EXPERIMENTAL")
    adapter_scaffold.add_argument("--dry-run", action="store_true")


def dispatch_adapter(args: argparse.Namespace) -> dict[str, Any]:
    if args.adapter_command == "validate":
        descriptor = read_json_object(Path(args.descriptor), label="adapter descriptor")
        baseline = read_json_object(Path(args.baseline), label="adapter baseline") if args.baseline else None
        requests = [read_json_object(Path(path), label="host operation request") for path in args.request]
        receipts = [read_json_object(Path(path), label="host operation receipt") for path in args.receipt]
        return require_adapter_validation_pass(
            validate_adapter_descriptor(
                descriptor,
                baseline=baseline,
                requests=requests,
                receipts=receipts,
            )
        )
    if args.adapter_command == "inspect":
        descriptor_path = Path(args.descriptor)
        descriptor = read_json_object(descriptor_path, label="adapter descriptor")
        return require_adapter_inspection_pass(
            inspect_adapter_descriptor(
                descriptor,
                descriptor_path=descriptor_path,
                host_bin=args.host_bin,
                project_root=Path(args.project_root),
                skip_host_commands=args.skip_host_commands,
                timeout_seconds=args.timeout_seconds,
            )
        )
    if args.adapter_command == "event-check":
        events = [read_json_object(Path(path), label="adapter event") for path in args.event]
        return require_adapter_event_stream_pass(validate_adapter_event_stream(events))
    if args.adapter_command == "scaffold":
        return scaffold_adapter(
            host=args.host,
            target=Path(args.target),
            maturity=args.maturity,
            dry_run=args.dry_run,
        )
    raise LifecycleError("command-not-implemented", "adapter command is not implemented")

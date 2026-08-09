"""Adapter and readiness CLI dispatch handlers."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.cli.adapter import dispatch_adapter
from agent_lifecycle.contracts import LifecycleError, write_json_create
from agent_lifecycle.diagnostics import build_diagnostic_bundle, build_readiness_report


def dispatch_adapters(args: argparse.Namespace) -> dict[str, Any]:
    """Dispatch adapter-facing and readiness command groups."""
    if args.command == "diagnose":
        return build_readiness_report(
            project_root=Path(args.project_root),
            adapter_paths=[Path(item) for item in args.adapter] if args.adapter else None,
            include_install_plans=not args.no_install_plans,
            include_host_probes=args.include_host_probes,
            timeout_seconds=args.timeout_seconds,
            max_host_probes=args.max_host_probes,
            context_profile=Path(args.context_profile) if args.context_profile else None,
            model_profile=Path(args.model_profile) if args.model_profile else None,
            adapter_baseline=Path(args.adapter_baseline) if args.adapter_baseline else None,
        )
    if args.command == "diagnostics":
        return _dispatch_diagnostics(args)
    if args.command == "adapter":
        return dispatch_adapter(args)
    raise LifecycleError("command-not-implemented", "adapter command is not implemented")


def _dispatch_diagnostics(args: argparse.Namespace) -> dict[str, Any]:
    if args.diagnostics_command == "bundle":
        payload = build_diagnostic_bundle(
            project_root=Path(args.project_root),
            artifact_paths=[Path(item) for item in args.artifact],
            max_artifacts=args.max_artifacts,
            max_input_bytes=args.max_input_bytes,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    raise LifecycleError("command-not-implemented", "diagnostics command is not implemented")

"""Adapter and readiness CLI dispatch handlers."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from agent_lifecycle.cli.adapter import dispatch_adapter
from agent_lifecycle.contracts import LifecycleError, read_json_object, write_json_create
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
        if args.adapter_command == "external-job":
            return _dispatch_external_job(args)
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


def _dispatch_external_job(args: argparse.Namespace) -> dict[str, Any]:
    from agent_lifecycle.adapter_sessions.external_jobs import (
        load_external_job_attempt,
        request_external_job_cancel,
        run_external_job,
    )

    request = _read_external_job_request(args.request)
    job_root = Path(args.job_root) if args.job_root else None
    if args.external_job_command == "run":
        argv = list(args.argv)
        if argv[:1] == ["--"]:
            argv = argv[1:]
        child_requests = [_read_external_job_request(path) for path in args.child_request]
        payload = run_external_job(
            request,
            argv,
            env=dict(os.environ),
            cwd=Path(args.cwd),
            job_root=job_root,
            verdict=args.verdict,
            complete=not args.incomplete,
            cost_micros=args.cost_micros,
            reported_tokens=args.reported_tokens,
            child_requests=child_requests,
        )
    elif args.external_job_command == "status":
        payload = load_external_job_attempt(request, job_root=job_root)
    elif args.external_job_command == "cancel":
        payload = request_external_job_cancel(request, job_root=job_root)
    else:
        raise LifecycleError("command-not-implemented", "external job command is not implemented")
    if args.out:
        write_json_create(Path(args.out), payload)
    return payload


def _read_external_job_request(path: str) -> dict[str, Any]:
    from agent_lifecycle.contracts.external_job_schemas import (
        require_external_job_pass,
        validate_external_job_request,
    )

    request = read_json_object(Path(path), label="external job request")
    require_external_job_pass(validate_external_job_request(request), "request")
    return request

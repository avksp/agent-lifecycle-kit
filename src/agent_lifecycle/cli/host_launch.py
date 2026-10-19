"""Operator-local host launch profile commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.accounting.host_bridge import (
    CAPABILITY_UNAVAILABLE,
    read_accounting_input,
    resolve_accounting_capability,
)
from agent_lifecycle.adapter_sessions.launch_execution import resolve_qualified_accounting_capability
from agent_lifecycle.adapter_sessions.launcher import inspect_local_launch_profile, launch_from_local_profile
from agent_lifecycle.contracts import LifecycleError, write_json_create


def dispatch_host_launch(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "accounting_request", None) is not None:
        # A version probe is an ALK-owned process too. Refuse the requested
        # guarantee before profile loading or any probe/model launch.
        read_accounting_input(Path(args.accounting_request))
        raise LifecycleError(CAPABILITY_UNAVAILABLE, "Accounting profile qualification is unavailable")
    if args.host_launch_command == "inspect":
        payload = inspect_local_launch_profile(Path(args.profile))
    elif args.host_launch_command == "preflight":
        payload = launch_from_local_profile(profile_path=Path(args.profile), operation="preflight")
    elif args.host_launch_command == "accounting-check":
        payload = resolve_accounting_capability(
            read_accounting_input(Path(args.profile)),
            read_accounting_input(Path(args.request)),
            expectation_digest=args.expectation_digest,
            plan_digest=args.plan_digest,
            candidate_digest=args.candidate_digest,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        raise LifecycleError(CAPABILITY_UNAVAILABLE, "Accounting capability was refused", payload)
    elif args.host_launch_command == "qualification-check":
        payload = resolve_qualified_accounting_capability(
            project_root=Path.cwd(),
            profiles_root=Path(args.profiles_root),
            adapter_id=args.adapter,
            request=read_accounting_input(Path(args.request)),
        )
        if payload["outcome"] == "DENY":
            if args.out:
                write_json_create(Path(args.out), payload)
            raise LifecycleError(CAPABILITY_UNAVAILABLE, "Source qualification is unavailable", payload)
    else:
        raise LifecycleError("command-not-implemented", "host launch command is not implemented")
    if args.out:
        write_json_create(Path(args.out), payload)
    return payload

"""Operator-local host launch profile commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.launcher import inspect_local_launch_profile, launch_from_local_profile
from agent_lifecycle.contracts import LifecycleError, write_json_create


def dispatch_host_launch(args: argparse.Namespace) -> dict[str, Any]:
    if args.host_launch_command == "inspect":
        payload = inspect_local_launch_profile(Path(args.profile))
    elif args.host_launch_command == "preflight":
        payload = launch_from_local_profile(profile_path=Path(args.profile), operation="preflight")
    else:
        raise LifecycleError("command-not-implemented", "host launch command is not implemented")
    if args.out:
        write_json_create(Path(args.out), payload)
    return payload

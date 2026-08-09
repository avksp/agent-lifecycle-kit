"""Root unified lifecycle start command."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions import start_lifecycle
from agent_lifecycle.contracts import LifecycleError, write_json_create


def dispatch_start(args: argparse.Namespace, remainder: list[str]) -> dict[str, Any]:
    """Delegate the public start command to adapter-session composition."""

    if remainder:
        raise LifecycleError("start-argument-unknown", f"unknown start arguments: {' '.join(remainder)}")
    payload = start_lifecycle(
        adapter_id=args.adapter,
        mode=args.mode,
        task_file=Path(args.task_file) if args.task_file else None,
        task_text=args.task_text,
        resume_session_id=args.resume_session_id,
        candidate_out=Path(args.candidate_out) if args.candidate_out else None,
        descriptor_path=Path(args.descriptor) if args.descriptor else None,
        session_root=Path(args.session_root) if args.session_root else None,
        state_path=Path(args.state) if args.state else None,
        lock_path=Path(args.lock) if args.lock else None,
        task_id=args.task,
        operation_id=args.operation_id,
        expected_revision=args.expected_revision,
        source_revision=args.source_revision,
        max_input_bytes=args.max_input_bytes,
        target_tokens=args.target_tokens,
        package_id=args.package_id,
    )
    if args.out:
        write_json_create(Path(args.out), payload)
    return payload

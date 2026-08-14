"""CLI dispatch for deterministic research evidence validation."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, read_json_object, write_json_create
from agent_lifecycle.research import (
    build_evidence_summary,
    load_evidence_package,
    read_source_snapshot,
    validate_evidence_package,
)


def dispatch_research(args: argparse.Namespace) -> dict[str, Any]:
    package_path = Path(args.package)
    package = load_evidence_package(package_path, max_bytes=args.max_bytes)
    snapshots = _load_snapshots(args.snapshot)
    if args.research_command == "validate":
        payload = validate_evidence_package(package, snapshots=snapshots, max_bytes=args.max_bytes)
    elif args.research_command == "summary":
        validation = (
            read_json_object(Path(args.validation), label="research evidence validation")
            if args.validation
            else validate_evidence_package(package, snapshots=snapshots, max_bytes=args.max_bytes)
        )
        payload = build_evidence_summary(package, validation)
    else:
        raise LifecycleError("command-not-implemented", "research command is not implemented")
    if args.out:
        try:
            write_json_create(Path(args.out), payload)
        except FileExistsError as exc:
            raise LifecycleError("output-already-exists", "research output already exists") from exc
    return payload


def _load_snapshots(values: list[str]) -> dict[str, bytes]:
    snapshots: dict[str, bytes] = {}
    for value in values:
        if "=" not in value:
            raise LifecycleError("research-snapshot-binding-invalid", "snapshot must use SOURCE_ID=PATH")
        source_id, raw_path = value.split("=", 1)
        if not source_id or not raw_path or source_id in snapshots:
            raise LifecycleError("research-snapshot-binding-invalid", "snapshot source binding is invalid")
        snapshots[source_id] = read_source_snapshot(Path(raw_path))
    return snapshots

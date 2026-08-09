"""CLI integration for deterministic reference-task evaluation."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.benchmarks import evaluate_reference_task
from agent_lifecycle.contracts import LifecycleError, write_json_create


def dispatch_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    if args.benchmark_command != "evaluate":
        raise LifecycleError("command-not-implemented", "benchmark command is not implemented")
    payload = evaluate_reference_task(suite_path=Path(args.suite), artifact_path=Path(args.artifact))
    if args.out:
        try:
            write_json_create(Path(args.out), payload)
        except FileExistsError as exc:
            raise LifecycleError("output-already-exists", "benchmark output already exists") from exc
    return payload

"""CLI integration for deterministic reference-task evaluation."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.benchmarks import compare_reference_task_evaluations, evaluate_reference_task
from agent_lifecycle.contracts import LifecycleError, read_json_object, write_json_create


def dispatch_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    if args.benchmark_command == "evaluate":
        payload = evaluate_reference_task(suite_path=Path(args.suite), artifact_path=Path(args.artifact))
    elif args.benchmark_command == "compare":
        payload = compare_reference_task_evaluations(
            read_json_object(Path(args.baseline), label="baseline reference-task evaluation"),
            read_json_object(Path(args.candidate), label="candidate reference-task evaluation"),
        )
    else:
        raise LifecycleError("command-not-implemented", "benchmark command is not implemented")
    if args.out:
        try:
            write_json_create(Path(args.out), payload)
        except FileExistsError as exc:
            raise LifecycleError("output-already-exists", "benchmark output already exists") from exc
    return payload

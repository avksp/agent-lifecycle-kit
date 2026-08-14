"""CLI integration for deterministic reference-task evaluation."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.benchmarks import (
    compare_qualified_routes,
    compare_reference_task_evaluations,
    evaluate_reference_task,
    qualify_benchmark_runs,
    select_stratified_tasks,
    validate_benchmark_run_receipt,
)
from agent_lifecycle.benchmarks.contracts import load_suite
from agent_lifecycle.contracts import LifecycleError, read_json_object, write_json_create


def dispatch_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    if args.benchmark_command == "evaluate":
        payload = evaluate_reference_task(suite_path=Path(args.suite), artifact_path=Path(args.artifact))
    elif args.benchmark_command == "compare":
        payload = compare_reference_task_evaluations(
            read_json_object(Path(args.baseline), label="baseline reference-task evaluation"),
            read_json_object(Path(args.candidate), label="candidate reference-task evaluation"),
        )
    elif args.benchmark_command in {"sample", "select"}:
        payload = select_stratified_tasks(
            Path(args.suite),
            seed=args.seed,
            max_tasks=args.max_tasks,
            max_strata=args.max_strata,
        )
    elif args.benchmark_command in {"receipt-check", "validate-receipt"}:
        suite = load_suite(Path(args.suite)) if args.suite else None
        payload = validate_benchmark_run_receipt(
            read_json_object(Path(args.receipt), label="benchmark run receipt"),
            suite=suite,
        )
    elif args.benchmark_command in {"qualify", "qualification"}:
        suite = load_suite(Path(args.suite)) if args.suite else None
        sample = read_json_object(Path(args.sample), label="benchmark sample") if args.sample else None
        payload = qualify_benchmark_runs(
            [read_json_object(Path(path), label="benchmark run receipt") for path in args.receipt],
            sample=sample,
            suite=suite,
        )
    elif args.benchmark_command == "compare-routes":
        suite = load_suite(Path(args.suite)) if args.suite else None
        sample = read_json_object(Path(args.sample), label="benchmark sample") if args.sample else None
        payload = compare_qualified_routes(
            [read_json_object(Path(path), label="baseline benchmark run receipt") for path in args.baseline],
            [read_json_object(Path(path), label="candidate benchmark run receipt") for path in args.candidate],
            sample=sample,
            suite=suite,
        )
    else:
        raise LifecycleError("command-not-implemented", "benchmark command is not implemented")
    if args.out:
        try:
            write_json_create(Path(args.out), payload)
        except FileExistsError as exc:
            raise LifecycleError("output-already-exists", "benchmark output already exists") from exc
    return payload

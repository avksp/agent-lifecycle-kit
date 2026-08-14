"""Deterministic, read-only reference-task evaluation and qualification."""

from agent_lifecycle.benchmarks.contracts import (
    build_benchmark_run_receipt,
    load_benchmark_run_receipt,
    validate_benchmark_run_receipt,
)
from agent_lifecycle.benchmarks.evaluator import evaluate_reference_task
from agent_lifecycle.benchmarks.comparison import (
    compare_reference_task_evaluations,
    compare_qualified_routes,
    validate_qualified_route_comparison,
    validate_reference_task_comparison,
)
from agent_lifecycle.benchmarks.qualification import qualify_benchmark_runs, validate_qualification_report
from agent_lifecycle.benchmarks.stratification import (
    build_stratified_sample,
    select_stratified_tasks,
    validate_stratified_sample,
)

__all__ = [
    "build_benchmark_run_receipt",
    "load_benchmark_run_receipt",
    "validate_benchmark_run_receipt",
    "compare_reference_task_evaluations",
    "compare_qualified_routes",
    "evaluate_reference_task",
    "qualify_benchmark_runs",
    "build_stratified_sample",
    "select_stratified_tasks",
    "validate_qualified_route_comparison",
    "validate_qualification_report",
    "validate_reference_task_comparison",
    "validate_stratified_sample",
]

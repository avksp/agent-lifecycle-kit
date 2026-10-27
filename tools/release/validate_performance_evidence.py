"""Validate bounded performance evidence without turning timing into authority."""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
from pathlib import Path
from statistics import median
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.canonical import write_json_replace_private
from agent_lifecycle.contracts.performance_limits import validate_performance_policy


VALIDATION_SCHEMA = "agent-performance-validation.v1"
BASELINE_SCHEMA = "agent-performance-baseline.v1"


def validate_performance_evidence(*, policy_path: Path, input_path: Path, repository_root: Path) -> dict[str, Any]:
    """Check evidence structure, bounds, lineage and comparability."""

    blockers: list[dict[str, Any]] = []
    policy: dict[str, Any] = {}
    baseline: dict[str, Any] = {}
    try:
        policy = read_json_object(policy_path, label="performance policy")
        limits = validate_performance_policy(policy)
        baseline = read_json_object(input_path, label="performance baseline")
        _validate_baseline(policy, baseline, limits, repository_root, blockers)
    except LifecycleError as exc:
        blockers.append({"code": exc.code, "message": exc.message})
    body = {
        "schemaVersion": VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "policy": {
            "path": _relative(policy_path, repository_root),
            "digest": canonical_digest(policy) if policy else None,
        },
        "input": {
            "path": _relative(input_path, repository_root),
            "digest": canonical_digest(baseline) if baseline else None,
        },
        "checks": {
            "policy": not any(item["code"].startswith("performance-policy") for item in blockers),
            "lineage": not any(item["code"].startswith("performance-lineage") for item in blockers),
            "samples": not any(item["code"].startswith("performance-sample") for item in blockers),
            "bounds": not any(item["code"].startswith("performance-bound") for item in blockers),
            "comparability": not any(item["code"].startswith("performance-comparability") for item in blockers),
        },
        "operations": [
            {
                "id": item.get("id"),
                "status": item.get("status"),
                "sampleCount": len(item.get("samples", [])) if isinstance(item.get("samples"), list) else 0,
            }
            for item in baseline.get("operations", [])
            if isinstance(item, dict)
        ],
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _validate_baseline(
    policy: dict[str, Any], baseline: dict[str, Any], limits: Any, root: Path, blockers: list[dict[str, Any]]
) -> None:
    _validate_input_bindings(policy, baseline, root, blockers)
    if baseline.get("schemaVersion") != BASELINE_SCHEMA:
        blockers.append({"code": "performance-lineage-schema-invalid"})
    if baseline.get("status") != "PASS":
        blockers.append({"code": "performance-lineage-baseline-failed"})
    source = baseline.get("sourceRevision")
    if not isinstance(source, str) or len(source) != 40 or any(char not in "0123456789abcdef" for char in source):
        blockers.append({"code": "performance-lineage-source-invalid"})
    else:
        current = _current_revision(root)
        if current is not None and source != current:
            blockers.append({"code": "performance-lineage-source-stale", "expected": current, "actual": source})
    environment = baseline.get("environment")
    if not isinstance(environment, dict) or not all(
        environment.get(key) for key in ("platform", "python", "implementation")
    ):
        blockers.append({"code": "performance-lineage-environment-invalid"})
    if baseline.get("comparability", {}).get("status") != "COMPARABLE":
        blockers.append({"code": "performance-comparability-no-recommendation"})
    operations = baseline.get("operations")
    requested = policy.get("operations")
    if (
        not isinstance(operations, list)
        or [item.get("id") for item in operations if isinstance(item, dict)] != requested
    ):
        blockers.append({"code": "performance-sample-operation-set-invalid"})
        return
    benchmark = policy["benchmark"]
    for operation in operations:
        if not isinstance(operation, dict):
            blockers.append({"code": "performance-sample-entry-invalid"})
            continue
        operation_id = operation.get("id")
        samples = operation.get("samples")
        if (
            operation.get("status") != "PASS"
            or not isinstance(samples, list)
            or len(samples) != benchmark["samplesPerCase"]
        ):
            blockers.append({"code": "performance-sample-incomplete", "operation": operation_id})
            continue
        if not isinstance(operation.get("commandArgvDigest"), str) or len(operation["commandArgvDigest"]) != 64:
            blockers.append({"code": "performance-sample-command-digest-invalid", "operation": operation_id})
        for sample in samples:
            _validate_sample(sample, operation_id, benchmark["maxOutputBytes"], blockers)
        _validate_operation_metrics(operation, benchmark, blockers)
        summary = operation.get("summary")
        if not isinstance(summary, dict) or summary.get("sampleCount") != len(samples):
            blockers.append({"code": "performance-sample-summary-invalid", "operation": operation_id})
        counts = operation.get("operationCounts")
        if not isinstance(counts, dict) or counts.get("invocations") != len(samples):
            blockers.append({"code": "performance-bound-operation-count-invalid", "operation": operation_id})
    if baseline.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "performance-bound-promotion-claimed"})
    if limits.max_evidence_bytes_per_run < 1:
        blockers.append({"code": "performance-bound-evidence-invalid"})


def _validate_sample(sample: Any, operation_id: Any, max_output: int, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(sample, dict):
        blockers.append({"code": "performance-sample-entry-invalid", "operation": operation_id})
        return
    if sample.get("status") != "PASS" or sample.get("returncode") != 0:
        blockers.append({"code": "performance-sample-failed", "operation": operation_id})
    for key in ("wallSeconds", "maxRssBytes", "stdoutBytes", "stderrBytes"):
        value = sample.get(key)
        if key == "maxRssBytes" and value is None:
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
            blockers.append({"code": "performance-bound-sample-value-invalid", "operation": operation_id, "field": key})
    for key in ("stdoutBytes", "stderrBytes"):
        value = sample.get(key)
        if isinstance(value, int) and value > max_output:
            blockers.append({"code": "performance-bound-output-exceeded", "operation": operation_id, "stream": key})
    for key in ("stdoutSha256", "stderrSha256"):
        value = sample.get(key)
        if not isinstance(value, str) or len(value) != 64:
            blockers.append({"code": "performance-sample-digest-invalid", "operation": operation_id, "field": key})


def _validate_input_bindings(
    policy: dict[str, Any],
    baseline: dict[str, Any],
    root: Path,
    blockers: list[dict[str, Any]],
) -> None:
    from tools.performance.run_performance_baseline import METRIC_DEFINITIONS, source_identity

    body = {key: value for key, value in baseline.items() if key != "baselineDigest"}
    try:
        valid_digest = baseline.get("baselineDigest") == canonical_digest(body)
    except (TypeError, ValueError):
        valid_digest = False
    if not valid_digest:
        blockers.append({"code": "performance-lineage-baseline-digest-invalid"})
    binding = baseline.get("policy")
    if not isinstance(binding, dict) or binding.get("digest") != canonical_digest(policy):
        blockers.append({"code": "performance-lineage-policy-mismatch"})
    if baseline.get("sourceInputs") != source_identity(root):
        blockers.append({"code": "performance-lineage-inputs-stale"})
    if baseline.get("metricDefinitions") != METRIC_DEFINITIONS:
        blockers.append({"code": "performance-comparability-metric-definitions"})
    wall = baseline.get("totalWallSeconds")
    if (
        type(wall) not in (int, float)
        or not math.isfinite(wall)
        or not 0 <= wall <= policy["benchmark"]["maxTotalWallSeconds"]
    ):
        blockers.append({"code": "performance-bound-total-wall-invalid"})


def _percentile95(values: list[float]) -> float | None:
    return sorted(values)[math.ceil(len(values) * 0.95) - 1] if values else None


def _validate_operation_metrics(
    operation: dict[str, Any],
    benchmark: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> None:
    from tools.performance.run_performance_baseline import LIFECYCLE_OPERATIONS

    samples = operation["samples"]
    name = operation.get("id")
    walls = [item.get("wallSeconds") for item in samples if isinstance(item, dict)]
    if len(walls) != len(samples) or any(
        type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in walls
    ):
        return
    summary = operation.get("summary")
    if not isinstance(summary, dict):
        return
    if summary.get("medianWallSeconds") != median(walls) or summary.get("p95WallSeconds") != _percentile95(walls):
        blockers.append({"code": "performance-sample-metric-summary", "operation": name})
    warmups = operation.get("warmupSamples")
    if not isinstance(warmups, list) or len(warmups) != benchmark["warmupSamples"]:
        blockers.append({"code": "performance-sample-warmup-incomplete", "operation": name})
    else:
        for value in warmups:
            _validate_sample(value, name, benchmark["maxOutputBytes"], blockers)
    counts = operation.get("operationCounts", {})
    actual_warmups = len(warmups) if isinstance(warmups, list) else 0
    processes = len(samples) + actual_warmups if operation.get("kind") != "in-process" else 0
    if counts.get("warmups") != actual_warmups or counts.get("subprocesses") != processes:
        blockers.append({"code": "performance-bound-operation-count-invalid", "operation": name})
    if any(
        isinstance(sample, dict)
        and type(sample.get("wallSeconds")) in (int, float)
        and sample["wallSeconds"] > benchmark["maxCommandWallSeconds"]
        for sample in samples + (warmups if isinstance(warmups, list) else [])
    ):
        blockers.append({"code": "performance-bound-command-wall-invalid", "operation": name})
    if name not in LIFECYCLE_OPERATIONS:
        return
    size = 100 if name.endswith("growing") else 1
    workload = operation.get("workload")
    if not isinstance(workload, dict) or workload.get("size") != size:
        blockers.append({"code": "performance-comparability-workload-invalid", "operation": name})
        return
    for sample in samples + (warmups if isinstance(warmups, list) else []):
        if not isinstance(sample, dict):
            continue
        data = sample.get("lifecycle")
        if not isinstance(data, dict):
            blockers.append({"code": "performance-comparability-worker-contract", "operation": name})
            continue
        if (
            data.get("workload") != workload
            or data.get("operation") != name
            or data.get("fixtureArtifactsUnchanged") is not True
            or data.get("productionPromotionClaimed") is not False
        ):
            blockers.append({"code": "performance-comparability-worker-contract", "operation": name})
            continue
        for key in (
            "setupWallSeconds",
            "operationWallSeconds",
            "validationWallSeconds",
            "workerWallSeconds",
            "subprocessOverheadSeconds",
        ):
            value = data.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                blockers.append({"code": "performance-bound-worker-time", "operation": name, "field": key})
        if name.startswith("accounting-") and (
            workload.get("reservations") != size or workload.get("events") != size + 1
        ):
            blockers.append({"code": "performance-comparability-workload-invalid", "operation": name})
        if name.startswith("workflow-") and (
            workload.get("tasks") != size or workload.get("phase") != "AWAITING_AUTHORIZATION"
        ):
            blockers.append({"code": "performance-comparability-workload-invalid", "operation": name})
    details = summary.get("lifecycleMetrics")
    if not isinstance(details, dict):
        blockers.append({"code": "performance-sample-worker-summary", "operation": name})
        return
    for key in ("operationWallSeconds", "setupWallSeconds", "subprocessOverheadSeconds"):
        values = [
            item["lifecycle"].get(key)
            for item in samples
            if isinstance(item, dict) and isinstance(item.get("lifecycle"), dict)
        ]
        if len(values) != len(samples):
            continue
        if all(type(value) in (int, float) and math.isfinite(value) for value in values):
            if details.get(key) != {"median": median(values), "p95": _percentile95(values)}:
                blockers.append({"code": "performance-sample-worker-summary", "operation": name, "field": key})


def compare_performance_baselines(
    *,
    policy_path: Path,
    baseline_path: Path,
    candidate_path: Path,
    repository_root: Path,
) -> dict[str, Any]:
    """Refuse source/environment/workload/metric drift; compare validated data."""
    validations = [
        validate_performance_evidence(
            policy_path=policy_path,
            input_path=path,
            repository_root=repository_root,
        )
        for path in (baseline_path, candidate_path)
    ]
    blockers = [item for check in validations for item in check["blockers"]]
    rows = []
    if not blockers:
        baseline = read_json_object(baseline_path, label="performance baseline")
        candidate = read_json_object(candidate_path, label="performance candidate")
        for key in ("sourceRevision", "sourceInputs", "environment", "policy", "metricDefinitions"):
            if baseline[key] != candidate[key]:
                blockers.append({"code": "performance-comparability-drift", "field": key})
        for left, right in zip(baseline["operations"], candidate["operations"], strict=True):
            for key in ("id", "kind", "commandArgvDigest", "workload"):
                if left.get(key) != right.get(key):
                    blockers.append({"code": "performance-comparability-drift", "field": key})
            reference = left["summary"]["medianWallSeconds"]
            if reference <= 0:
                blockers.append({"code": "performance-comparability-zero-reference"})
            else:
                rows.append({"id": left["id"], "wallMedianRatio": right["summary"]["medianWallSeconds"] / reference})
    body = {
        "schemaVersion": "agent-performance-comparison.v1",
        "status": "COMPARABLE" if not blockers else "NO_RECOMMENDATION",
        "selfComparison": baseline_path.resolve() == candidate_path.resolve(),
        "operations": rows if not blockers else [],
        "blockers": blockers,
        "performanceAcceptanceClaimed": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "comparisonDigest": canonical_digest(body)}


def _current_revision(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            shell=False,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.decode("ascii", errors="ignore").strip()
    return value if result.returncode == 0 and len(value) == 40 else None


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return "<outside-repository>"


def main() -> int:
    # Direct script entry and module entry must resolve the same local tools.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--compare-input")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    if args.compare_input:
        result = compare_performance_baselines(
            policy_path=Path(args.policy),
            baseline_path=Path(args.input),
            candidate_path=Path(args.compare_input),
            repository_root=root,
        )
    else:
        result = validate_performance_evidence(
            policy_path=Path(args.policy), input_path=Path(args.input), repository_root=root
        )
    write_json_replace_private(Path(args.evidence), result)
    return 0 if result["status"] in {"PASS", "COMPARABLE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

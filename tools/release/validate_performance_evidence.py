"""Validate bounded performance evidence without turning timing into authority."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
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
        "policy": {"path": _relative(policy_path, repository_root), "digest": canonical_digest(policy) if policy else None},
        "input": {"path": _relative(input_path, repository_root), "digest": canonical_digest(baseline) if baseline else None},
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


def _validate_baseline(policy: dict[str, Any], baseline: dict[str, Any], limits: Any, root: Path, blockers: list[dict[str, Any]]) -> None:
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
    if not isinstance(environment, dict) or not all(environment.get(key) for key in ("platform", "python", "implementation")):
        blockers.append({"code": "performance-lineage-environment-invalid"})
    if baseline.get("comparability", {}).get("status") != "COMPARABLE":
        blockers.append({"code": "performance-comparability-no-recommendation"})
    operations = baseline.get("operations")
    requested = policy.get("operations")
    if not isinstance(operations, list) or [item.get("id") for item in operations if isinstance(item, dict)] != requested:
        blockers.append({"code": "performance-sample-operation-set-invalid"})
        return
    benchmark = policy["benchmark"]
    for operation in operations:
        if not isinstance(operation, dict):
            blockers.append({"code": "performance-sample-entry-invalid"})
            continue
        operation_id = operation.get("id")
        samples = operation.get("samples")
        if operation.get("status") != "PASS" or not isinstance(samples, list) or len(samples) != benchmark["samplesPerCase"]:
            blockers.append({"code": "performance-sample-incomplete", "operation": operation_id})
            continue
        if not isinstance(operation.get("commandArgvDigest"), str) or len(operation["commandArgvDigest"]) != 64:
            blockers.append({"code": "performance-sample-command-digest-invalid", "operation": operation_id})
        for sample in samples:
            _validate_sample(sample, operation_id, benchmark["maxOutputBytes"], blockers)
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
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            blockers.append({"code": "performance-bound-sample-value-invalid", "operation": operation_id, "field": key})
    for key in ("stdoutBytes", "stderrBytes"):
        value = sample.get(key)
        if isinstance(value, int) and value > max_output:
            blockers.append({"code": "performance-bound-output-exceeded", "operation": operation_id, "stream": key})
    for key in ("stdoutSha256", "stderrSha256"):
        value = sample.get(key)
        if not isinstance(value, str) or len(value) != 64:
            blockers.append({"code": "performance-sample-digest-invalid", "operation": operation_id, "field": key})


def _current_revision(root: Path) -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=False, check=False, timeout=10)
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    result = validate_performance_evidence(policy_path=Path(args.policy), input_path=Path(args.input), repository_root=root)
    write_json_replace_private(Path(args.evidence), result)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

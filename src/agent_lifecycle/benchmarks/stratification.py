"""Deterministic bounded selection of reference-task strata."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.benchmarks.contracts import LoadedSuite, load_suite
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.benchmark_schemas import STRATIFIED_SAMPLE_SCHEMA


def select_stratified_tasks(
    suite: LoadedSuite | Path,
    *,
    seed: str = "default",
    max_tasks: int = 24,
    max_strata: int = 16,
) -> dict[str, Any]:
    """Select a stable task sample from explicit family/tier/shape fields.

    The selector chooses one task from each selected stratum first, then fills
    remaining capacity from the same deterministic ordering. It never reads
    task text and never starts an external runner.
    """

    loaded = load_suite(suite) if isinstance(suite, Path) else suite
    if not isinstance(loaded, LoadedSuite):
        raise LifecycleError("benchmark-suite-invalid", "suite must be a loaded reference-task suite or path")
    if not isinstance(seed, str) or not seed.strip():
        raise LifecycleError("benchmark-sample-seed", "sample seed must be a non-empty string")
    if not isinstance(max_tasks, int) or isinstance(max_tasks, bool) or max_tasks < 1:
        raise LifecycleError("benchmark-sample-task-limit", "max_tasks must be a positive integer")
    if not isinstance(max_strata, int) or isinstance(max_strata, bool) or max_strata < 1:
        raise LifecycleError("benchmark-sample-strata-limit", "max_strata must be a positive integer")

    rows = [dict(item) for item in loaded.payload["tasks"]]
    ordered = sorted(rows, key=lambda row: _ordering_digest(seed, row["id"]))
    by_stratum: dict[str, list[dict[str, Any]]] = {}
    for row in ordered:
        by_stratum.setdefault(_stratum_key(row), []).append(row)
    stratum_keys = sorted(by_stratum, key=lambda key: _ordering_digest(seed, key))
    selected_strata = stratum_keys[:max_strata]

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for key in selected_strata:
        row = by_stratum[key][0]
        if len(selected) >= max_tasks:
            break
        selected.append(row)
        selected_ids.add(row["id"])
    for row in ordered:
        if len(selected) >= max_tasks:
            break
        if row["id"] not in selected_ids:
            selected.append(row)
            selected_ids.add(row["id"])

    strata = []
    for key in selected_strata:
        candidates = by_stratum[key]
        strata.append(
            {
                "key": key,
                "family": candidates[0]["family"],
                "tier": candidates[0]["tier"],
                "shape": _shape(candidates[0]),
                "candidateTaskIds": [row["id"] for row in candidates],
                "selectedTaskIds": [row["id"] for row in candidates if row["id"] in selected_ids],
            }
        )
    body = {
        "schemaVersion": STRATIFIED_SAMPLE_SCHEMA,
        "status": "PASS",
        "suite": {
            "id": loaded.payload["suiteId"],
            "version": loaded.payload["suiteVersion"],
            "digest": loaded.digest,
        },
        "seed": seed,
        "bounds": {"maxTasks": max_tasks, "maxStrata": max_strata},
        "strata": strata,
        "selectedTaskIds": [row["id"] for row in selected],
        "omittedTaskIds": [row["id"] for row in rows if row["id"] not in selected_ids],
        "productionPromotionClaimed": False,
    }
    return {**body, "sampleDigest": canonical_digest(body)}


def build_stratified_sample(
    suite: LoadedSuite | Path,
    *,
    seed: str = "default",
    max_tasks: int = 24,
    max_strata: int = 16,
) -> dict[str, Any]:
    """Compatibility name for callers that use the report terminology."""

    return select_stratified_tasks(suite, seed=seed, max_tasks=max_tasks, max_strata=max_strata)


def validate_stratified_sample(sample: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if sample.get("schemaVersion") != STRATIFIED_SAMPLE_SCHEMA:
        blockers.append({"code": "benchmark-sample-schema"})
    if sample.get("status") != "PASS":
        blockers.append({"code": "benchmark-sample-status"})
    selected = sample.get("selectedTaskIds")
    omitted = sample.get("omittedTaskIds")
    if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected):
        blockers.append({"code": "benchmark-sample-selected-tasks"})
        selected = []
    if not isinstance(omitted, list) or not all(isinstance(item, str) for item in omitted):
        blockers.append({"code": "benchmark-sample-omitted-tasks"})
    if len(set(selected)) != len(selected):
        blockers.append({"code": "benchmark-sample-duplicate-task"})
    if sample.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "benchmark-sample-production-claim"})
    expected = canonical_digest({key: value for key, value in sample.items() if key != "sampleDigest"})
    if sample.get("sampleDigest") != expected:
        blockers.append({"code": "benchmark-sample-digest"})
    return {
        "schemaVersion": "agent-benchmark-stratified-sample-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "blockers": blockers,
        "sampleDigest": sample.get("sampleDigest"),
        "productionPromotionClaimed": False,
        "validationDigest": canonical_digest(
            {
                "schemaVersion": "agent-benchmark-stratified-sample-validation.v1",
                "status": "PASS" if not blockers else "FAIL",
                "blockers": blockers,
                "sampleDigest": sample.get("sampleDigest"),
                "productionPromotionClaimed": False,
            }
        ),
    }


def _stratum_key(row: dict[str, Any]) -> str:
    return f"{row['family']}|{row['tier']}|{_shape(row)}"


def _ordering_digest(seed: str, value: str) -> str:
    return canonical_digest({"seed": seed, "value": value})


def _shape(row: dict[str, Any]) -> str:
    return row.get("shape") or {
        "planning": "planning",
        "architecture-review": "review",
        "bug-forensics": "investigation",
        "s1-managed-task": "implementation",
        "s2-evidence-task": "evidence",
    }[row["family"]]

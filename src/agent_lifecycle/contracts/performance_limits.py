"""Typed ceilings shared by performance evidence and optimized domains."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any

from agent_lifecycle.contracts.errors import LifecycleError

PERFORMANCE_POLICY_SCHEMA = "agent-performance-budgets.v1"


@dataclass(frozen=True)
class PerformanceLimits:
    """Closed resource ceilings that performance workstreams must not exceed."""

    max_git_processes_per_full_scan: int = 4
    max_git_objects: int = 1_000_000
    max_git_inventory_bytes: int = 128 * 1024 * 1024
    max_git_object_bytes: int = 16 * 1024 * 1024
    max_git_expanded_bytes: int = 4 * 1024 * 1024 * 1024
    max_git_batch_framing_bytes: int = 128 * 1024 * 1024
    max_full_scan_wall_seconds: int = 600
    max_untracked_files: int = 100_000
    max_untracked_bytes: int = 4 * 1024 * 1024 * 1024
    max_hash_chunk_bytes: int = 256 * 1024
    max_worktree_identity_wall_seconds_per_capture: int = 120
    max_deny_rules: int = 1_024
    max_deny_rule_bytes: int = 4_096
    max_deny_rule_aggregate_bytes: int = 1 * 1024 * 1024
    max_simple_literal_rules: int = 64
    max_linux_group_samples_per_second: int = 4
    max_ed25519_optimized_to_reference_median_ratio_bps: int = 2_000
    max_benchmark_samples_per_case: int = 31
    max_benchmark_output_bytes: int = 16 * 1024 * 1024
    max_evidence_bytes_per_run: int = 96 * 1024 * 1024


DEFAULT_PERFORMANCE_LIMITS = PerformanceLimits()

_FIELD_TO_JSON = {
    field.name: "".join(
        part if index == 0 else part[:1].upper() + part[1:] for index, part in enumerate(field.name.split("_"))
    )
    for field in fields(PerformanceLimits)
}
_JSON_TO_FIELD = {value: key for key, value in _FIELD_TO_JSON.items()}


def performance_limits_to_json(limits: PerformanceLimits = DEFAULT_PERFORMANCE_LIMITS) -> dict[str, int]:
    """Return the stable JSON spelling of a typed limit set."""

    return {_FIELD_TO_JSON[field.name]: int(getattr(limits, field.name)) for field in fields(limits)}


def performance_limits_from_json(value: Mapping[str, Any]) -> PerformanceLimits:
    """Parse a closed limit object and reject unsafe or unknown values."""

    if not isinstance(value, Mapping):
        raise LifecycleError("performance-limits-invalid", "performance limits must be an object")
    expected = set(_JSON_TO_FIELD)
    unknown = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if unknown or missing:
        raise LifecycleError(
            "performance-limits-fields-invalid",
            "performance limits must contain the closed field set",
            {"unknown": unknown, "missing": missing},
        )
    parsed: dict[str, int] = {}
    for json_name, field_name in _JSON_TO_FIELD.items():
        raw = value[json_name]
        if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
            raise LifecycleError(
                "performance-limit-value-invalid",
                f"performance limit {json_name} must be a positive integer",
            )
        parsed[field_name] = raw
    limits = PerformanceLimits(**parsed)
    if limits.max_ed25519_optimized_to_reference_median_ratio_bps > 10_000:
        raise LifecycleError(
            "performance-limit-ratio-invalid",
            "Ed25519 ratio cannot exceed 100 percent",
        )
    if limits.max_hash_chunk_bytes > limits.max_untracked_bytes:
        raise LifecycleError(
            "performance-limit-chunk-invalid",
            "hash chunk cannot exceed the aggregate untracked-byte limit",
        )
    return limits


def validate_performance_policy(policy: Mapping[str, Any]) -> PerformanceLimits:
    """Validate the versioned policy and return its typed resource ceilings."""

    if not isinstance(policy, Mapping):
        raise LifecycleError("performance-policy-invalid", "performance policy must be an object")
    allowed = {
        "schemaVersion",
        "revision",
        "sourceRevision",
        "limits",
        "benchmark",
        "operations",
        "productionPromotionClaimed",
    }
    unknown = sorted(set(policy) - allowed)
    if unknown:
        raise LifecycleError(
            "performance-policy-unknown-field", "performance policy contains an unknown field", {"fields": unknown}
        )
    if policy.get("schemaVersion") != PERFORMANCE_POLICY_SCHEMA:
        raise LifecycleError("performance-policy-schema-invalid", "performance policy schemaVersion is unsupported")
    revision = policy.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise LifecycleError("performance-policy-revision-invalid", "performance policy revision must be positive")
    source_revision = policy.get("sourceRevision")
    if (
        not isinstance(source_revision, str)
        or len(source_revision) != 40
        or any(char not in "0123456789abcdef" for char in source_revision)
    ):
        raise LifecycleError("performance-policy-source-invalid", "performance policy sourceRevision must be a Git SHA")
    raw_limits = policy.get("limits")
    if not isinstance(raw_limits, Mapping):
        raise LifecycleError("performance-policy-limits-invalid", "performance policy limits must be an object")
    limits = performance_limits_from_json(raw_limits)
    benchmark = policy.get("benchmark")
    if not isinstance(benchmark, Mapping):
        raise LifecycleError("performance-policy-benchmark-invalid", "performance policy benchmark must be an object")
    benchmark_allowed = {
        "warmupSamples",
        "samplesPerCase",
        "maxCommandWallSeconds",
        "maxTotalWallSeconds",
        "maxOutputBytes",
    }
    benchmark_unknown = sorted(set(benchmark) - benchmark_allowed)
    if benchmark_unknown:
        raise LifecycleError(
            "performance-policy-unknown-field", "benchmark contains an unknown field", {"fields": benchmark_unknown}
        )
    for name in benchmark_allowed:
        raw = benchmark.get(name)
        minimum = 0 if name == "warmupSamples" else 1
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < minimum:
            qualifier = "non-negative" if name == "warmupSamples" else "positive"
            raise LifecycleError(
                "performance-policy-benchmark-invalid", f"benchmark {name} must be a {qualifier} integer"
            )
    if benchmark["samplesPerCase"] > limits.max_benchmark_samples_per_case:
        raise LifecycleError("performance-policy-benchmark-exceeds-limit", "samplesPerCase exceeds the typed ceiling")
    if benchmark["maxOutputBytes"] > limits.max_benchmark_output_bytes:
        raise LifecycleError("performance-policy-benchmark-exceeds-limit", "maxOutputBytes exceeds the typed ceiling")
    operations = policy.get("operations")
    if (
        not isinstance(operations, list)
        or not operations
        or not all(isinstance(item, str) and item for item in operations)
    ):
        raise LifecycleError(
            "performance-policy-operations-invalid", "performance policy operations must be non-empty strings"
        )
    if len(set(operations)) != len(operations):
        raise LifecycleError("performance-policy-operations-invalid", "performance policy operations must be unique")
    if policy.get("productionPromotionClaimed") is not False:
        raise LifecycleError(
            "performance-policy-promotion-invalid", "performance policy cannot claim production promotion"
        )
    return limits


__all__ = [
    "DEFAULT_PERFORMANCE_LIMITS",
    "PERFORMANCE_POLICY_SCHEMA",
    "PerformanceLimits",
    "performance_limits_from_json",
    "performance_limits_to_json",
    "validate_performance_policy",
]

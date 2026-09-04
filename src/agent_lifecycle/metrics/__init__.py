"""Lifecycle resource and process-cost metrics."""

from agent_lifecycle.metrics.cost_collection import (
    build_lifecycle_cost_summary,
    generate_lifecycle_cost_report,
)
from agent_lifecycle.metrics.costs import (
    COST_CATEGORIES,
    DEFAULT_MODE_LIMITS,
    require_lifecycle_cost_pass,
    validate_lifecycle_cost_report,
)
from agent_lifecycle.metrics.outcome_index import (
    build_quality_cost_signal_summary,
    build_quality_cost_signals,
    build_task_outcome_index,
)
from agent_lifecycle.metrics.phase_resources import (
    MAX_PHASE_RESOURCE_ENTRIES,
    build_phase_resource_measurement,
    require_phase_resource_measurement_pass,
    validate_phase_resource_measurement,
)
from agent_lifecycle.metrics.recommendations import (
    build_lifecycle_recommendation_summary,
    recommend_from_quality_cost_signals,
    recommend_lifecycle_mode,
    require_lifecycle_recommendation_pass,
    summarize_lifecycle_overhead,
    validate_lifecycle_baselines,
)
from agent_lifecycle.metrics.regression_signals import summarize_regression_signals
from agent_lifecycle.metrics.release_accounting import (
    ACCOUNTING_VIEWS,
    MAX_RELEASE_ACCOUNTING_ARTIFACTS,
    MAX_RELEASE_ACCOUNTING_ENTRIES,
    PROVENANCE_FIELDS,
    build_release_accounting,
    build_release_accounting_source,
    require_release_accounting_pass,
    validate_release_accounting,
    validate_release_accounting_source,
)
from agent_lifecycle.metrics.usage_export import (
    build_usage_export,
    require_usage_export_pass,
    usage_export_totals,
    validate_usage_export,
)
from agent_lifecycle.metrics.workflow_economics import (
    DERIVED_AGGREGATE_STATUSES,
    SOURCE_AVAILABILITY_STATUSES,
    WORKFLOW_METRIC_KEYS,
    build_workflow_metric_set,
    build_workflow_resource_summary,
    validate_workflow_resource_summary,
)

__all__ = [
    "ACCOUNTING_VIEWS",
    "COST_CATEGORIES",
    "DEFAULT_MODE_LIMITS",
    "DERIVED_AGGREGATE_STATUSES",
    "MAX_PHASE_RESOURCE_ENTRIES",
    "MAX_RELEASE_ACCOUNTING_ARTIFACTS",
    "MAX_RELEASE_ACCOUNTING_ENTRIES",
    "PROVENANCE_FIELDS",
    "SOURCE_AVAILABILITY_STATUSES",
    "WORKFLOW_METRIC_KEYS",
    "build_lifecycle_cost_summary",
    "build_lifecycle_recommendation_summary",
    "build_phase_resource_measurement",
    "build_quality_cost_signal_summary",
    "build_quality_cost_signals",
    "build_release_accounting",
    "build_release_accounting_source",
    "build_task_outcome_index",
    "build_usage_export",
    "build_workflow_metric_set",
    "build_workflow_resource_summary",
    "generate_lifecycle_cost_report",
    "recommend_from_quality_cost_signals",
    "recommend_lifecycle_mode",
    "require_lifecycle_cost_pass",
    "require_lifecycle_recommendation_pass",
    "require_phase_resource_measurement_pass",
    "require_release_accounting_pass",
    "require_usage_export_pass",
    "summarize_lifecycle_overhead",
    "summarize_regression_signals",
    "usage_export_totals",
    "validate_lifecycle_baselines",
    "validate_lifecycle_cost_report",
    "validate_phase_resource_measurement",
    "validate_release_accounting",
    "validate_release_accounting_source",
    "validate_usage_export",
    "validate_workflow_resource_summary",
]

_LAZY_AUDIT_OPTIMIZATION_EXPORTS = {
    "build_audit_efficiency_input",
    "build_audit_efficiency_report",
    "build_audit_optimization_report",
    "build_audit_sample",
    "build_audit_samples",
    "build_audit_statistics",
    "evaluate_candidate_profiles",
    "recommend_audit_optimization",
    "require_audit_sample_pass",
    "validate_audit_optimization_report",
    "validate_audit_efficiency_input",
    "validate_audit_efficiency_report",
    "validate_audit_sample",
}

__all__.extend(sorted(_LAZY_AUDIT_OPTIMIZATION_EXPORTS))


def __getattr__(name: str):
    if name in _LAZY_AUDIT_OPTIMIZATION_EXPORTS:
        if name in {
            "build_audit_efficiency_input",
            "build_audit_efficiency_report",
            "validate_audit_efficiency_input",
            "validate_audit_efficiency_report",
        }:
            from agent_lifecycle.metrics import audit_efficiency

            return getattr(audit_efficiency, name)
        if name in {"build_audit_sample", "build_audit_samples", "require_audit_sample_pass", "validate_audit_sample"}:
            from agent_lifecycle.metrics import audit_samples

            return getattr(audit_samples, name)
        from agent_lifecycle.metrics import audit_optimization

        return getattr(audit_optimization, name)
    raise AttributeError(name)

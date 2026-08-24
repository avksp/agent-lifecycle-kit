"""Lifecycle policy proposal helpers."""

from agent_lifecycle.policy.apply import apply_policy_proposal, build_tuned_policy
from agent_lifecycle.policy.adaptive_lifecycle import (
    build_adaptive_lifecycle_decision,
    require_adaptive_lifecycle_decision_pass,
    small_model_packet_eligibility,
    validate_adaptive_lifecycle_decision,
)
from agent_lifecycle.policy.proposals import (
    accept_finding_check_proposal,
    build_finding_check_proposal,
    build_policy_proposal,
    build_policy_summary,
    require_policy_proposal_pass,
)
from agent_lifecycle.policy.quality_floor import quality_floor_mode, resolve_quality_floor
from agent_lifecycle.policy.runtime_receipts import (
    build_runtime_policy_receipt,
    require_runtime_policy_receipt_pass,
    validate_runtime_policy_receipt,
)
__all__ = [
    "apply_policy_proposal",
    "accept_finding_check_proposal",
    "build_adaptive_lifecycle_decision",
    "build_policy_proposal",
    "build_finding_check_proposal",
    "build_policy_summary",
    "build_runtime_policy_receipt",
    "build_tuned_policy",
    "deferred_execution_strategy_summary",
    "execution_strategy_summary",
    "quality_floor_mode",
    "require_adaptive_lifecycle_decision_pass",
    "require_policy_proposal_pass",
    "require_runtime_policy_receipt_pass",
    "resolve_quality_floor",
    "resolve_execution_strategy",
    "small_model_packet_eligibility",
    "validate_adaptive_lifecycle_decision",
    "validate_runtime_policy_receipt",
    "validate_execution_strategy",
]

_LAZY_EXECUTION_STRATEGY_EXPORTS = {
    "deferred_execution_strategy_summary",
    "execution_strategy_summary",
    "resolve_execution_strategy",
    "validate_execution_strategy",
}


def __getattr__(name: str):
    if name in _LAZY_EXECUTION_STRATEGY_EXPORTS:
        from agent_lifecycle.policy import execution_strategy

        return getattr(execution_strategy, name)
    raise AttributeError(name)

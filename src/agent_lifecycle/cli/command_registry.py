"""Provider-neutral lazy CLI dispatch registry."""

from __future__ import annotations

COMMAND_DISPATCH = {
    "start": ("agent_lifecycle.cli.start", "dispatch_start", True),
    "host-launch": ("agent_lifecycle.cli.host_launch", "dispatch_host_launch", False),
    "strategy": ("agent_lifecycle.cli.strategy", "dispatch_strategy", False),
    "project": ("agent_lifecycle.cli.project", "dispatch_project", False),
    "diagnose": ("agent_lifecycle.cli.dispatch_adapters", "dispatch_adapters", False),
    "diagnostics": ("agent_lifecycle.cli.dispatch_adapters", "dispatch_adapters", False),
    "adapter": ("agent_lifecycle.cli.dispatch_adapters", "dispatch_adapters", False),
    "research": ("agent_lifecycle.cli.dispatch_research", "dispatch_research", False),
    "version": ("agent_lifecycle.cli.dispatch_contracts", "dispatch_contracts", False),
    "schema": ("agent_lifecycle.cli.dispatch_contracts", "dispatch_contracts", False),
    "contract": ("agent_lifecycle.cli.dispatch_contracts", "dispatch_contracts", False),
    "evidence": ("agent_lifecycle.cli.dispatch_contracts", "dispatch_contracts", False),
    "import": ("agent_lifecycle.cli.dispatch_contracts", "dispatch_contracts", False),
    "quality": ("agent_lifecycle.cli.dispatch_contracts", "dispatch_contracts", False),
    "review-mesh": ("agent_lifecycle.cli.dispatch_contracts", "dispatch_contracts", False),
    "workflow": ("agent_lifecycle.cli.dispatch_lifecycle", "dispatch_lifecycle", False),
    "audit": ("agent_lifecycle.cli.dispatch_lifecycle", "dispatch_lifecycle", False),
    "report": ("agent_lifecycle.cli.dispatch_observability", "dispatch_observability", False),
    "context": ("agent_lifecycle.cli.dispatch_observability", "dispatch_observability", False),
    "goal": ("agent_lifecycle.cli.dispatch_observability", "dispatch_observability", False),
    "model": ("agent_lifecycle.cli.dispatch_observability", "dispatch_observability", False),
    "metrics": ("agent_lifecycle.cli.dispatch_observability", "dispatch_observability", False),
    "thread": ("agent_lifecycle.cli.dispatch_observability", "dispatch_observability", False),
    "tier": ("agent_lifecycle.cli.dispatch_planning", "dispatch_planning", False),
    "specification": ("agent_lifecycle.cli.dispatch_planning", "dispatch_planning", False),
    "plan": ("agent_lifecycle.cli.dispatch_planning", "dispatch_planning", False),
    "task": ("agent_lifecycle.cli.dispatch_planning", "dispatch_planning", False),
    "policy": ("agent_lifecycle.cli.policy", "dispatch_policy", False),
    "followup": ("agent_lifecycle.cli.followup", "dispatch_followup", False),
    "worktree": ("agent_lifecycle.cli.worktree", "dispatch_worktree", False),
    "benchmark": ("agent_lifecycle.cli.benchmarks", "dispatch_benchmark", False),
}


__all__ = ["COMMAND_DISPATCH"]

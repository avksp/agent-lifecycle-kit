"""Compact context rendering for small-context hosts."""

from agent_lifecycle.context.profiles import load_context_profile, validate_context_profile
from agent_lifecycle.context.rendering import check_context, render_context
from agent_lifecycle.context.checkpoints import (
    build_context_checkpoint,
    require_context_checkpoint_pass,
    validate_context_checkpoint,
)
from agent_lifecycle.context.checkpoint_store import (
    list_context_checkpoints,
    load_context_checkpoint,
    restore_context_checkpoint,
    write_context_checkpoint,
)

__all__ = [
    "build_episode_context",
    "check_context",
    "build_context_checkpoint",
    "load_context_profile",
    "list_context_checkpoints",
    "load_context_checkpoint",
    "render_context",
    "restore_context_checkpoint",
    "require_context_checkpoint_pass",
    "validate_context_checkpoint",
    "validate_context_profile",
    "write_context_checkpoint",
]


def __getattr__(name: str):
    if name == "build_episode_context":
        from agent_lifecycle.context.episode_retrieval import build_episode_context

        return build_episode_context
    raise AttributeError(name)

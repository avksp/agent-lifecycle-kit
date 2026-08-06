"""Compact context rendering for small-context hosts."""

from agent_lifecycle.context.profiles import load_context_profile, validate_context_profile
from agent_lifecycle.context.rendering import check_context, render_context

__all__ = [
    "build_episode_context",
    "check_context",
    "load_context_profile",
    "render_context",
    "validate_context_profile",
]


def __getattr__(name: str):
    if name == "build_episode_context":
        from agent_lifecycle.context.episode_retrieval import build_episode_context

        return build_episode_context
    raise AttributeError(name)

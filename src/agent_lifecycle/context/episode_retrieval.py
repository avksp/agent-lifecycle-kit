"""Context-oriented episode retrieval helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.evidence_index.episode_index import build_episode_index, retrieve_episodes


def build_episode_context(
    project_root: Path,
    artifact_paths: list[str],
    *,
    query: str = "",
    hash_chain: dict[str, Any] | None = None,
    external_context_hints: list[dict[str, Any]] | None = None,
    max_results: int = 8,
    target_tokens: int = 2048,
) -> dict[str, Any]:
    """Build and query a bounded episode context from explicit artifacts."""

    index = build_episode_index(project_root, artifact_paths, hash_chain=hash_chain, target_tokens=target_tokens)
    return retrieve_episodes(
        index,
        query=query,
        max_results=max_results,
        external_context_hints=external_context_hints,
        target_tokens=target_tokens,
    )

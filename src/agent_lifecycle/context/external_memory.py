"""Local external memory/context helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import read_json_object
from agent_lifecycle.evidence_index.episode_index import (
    build_episode_index,
    require_episode_retrieval_pass,
    retrieve_episodes,
)
from agent_lifecycle.evidence_index.external_context import (
    build_external_context_import_receipt,
    external_context_hints_from_receipts,
    require_external_context_import_pass,
    validate_external_context_import_receipt,
)


def import_external_memory_context(
    source_path: Path,
    *,
    citation: str | None = None,
    source_id: str | None = None,
    max_input_bytes: int = 32768,
    target_tokens: int = 2048,
) -> dict[str, Any]:
    """Import a local external memory export as an optional context receipt."""

    receipt = build_external_context_import_receipt(
        source_path,
        citation=citation,
        source_id=source_id,
        max_input_bytes=max_input_bytes,
        target_tokens=target_tokens,
    )
    require_external_context_import_pass(validate_external_context_import_receipt(receipt))
    return receipt


def load_external_context_hints(receipt_paths: list[Path]) -> list[dict[str, Any]]:
    """Load external context import receipts and return retrieval hints."""

    receipts = [read_json_object(path, label="external context receipt") for path in receipt_paths]
    return external_context_hints_from_receipts(receipts)


def build_episode_retrieval_with_external_context(
    project_root: Path,
    artifact_paths: list[str],
    *,
    external_context_paths: list[Path] | None = None,
    query: str = "",
    max_results: int = 8,
    max_external_context_hints: int = 4,
    target_tokens: int = 2048,
) -> dict[str, Any]:
    """Build episode retrieval with optional, non-proof external context hints."""

    index = build_episode_index(project_root, artifact_paths, target_tokens=target_tokens)
    retrieval = retrieve_episodes(
        index,
        query=query,
        max_results=max_results,
        external_context_hints=load_external_context_hints(external_context_paths or []),
        max_external_context_hints=max_external_context_hints,
        target_tokens=target_tokens,
    )
    return require_episode_retrieval_pass(retrieval)

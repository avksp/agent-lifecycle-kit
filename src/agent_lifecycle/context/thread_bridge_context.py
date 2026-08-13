"""Composition helpers for treating host-thread data as untrusted context."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.context.episode_retrieval import build_episode_context
from agent_lifecycle.context.external_memory import load_external_context_hints
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.thread_bridge_schemas import (
    build_thread_context_import,
    validate_thread_context_import,
)


def import_thread_context(
    receipt: dict[str, Any],
    *,
    operation_id: str | None = None,
    source_id: str | None = None,
    citation: str | None = None,
    max_imported_bytes: int = 32768,
    max_imported_tokens: int = 2048,
) -> dict[str, Any]:
    """Project an adapter receipt into bounded, non-authoritative context."""

    if not isinstance(receipt, dict):
        raise LifecycleError("thread-receipt-invalid", "thread receipt must be an object")
    if receipt.get("status") not in {"PASS", "FAIL", "BLOCKED", "UNAVAILABLE"}:
        raise LifecycleError("thread-receipt-invalid", "thread receipt status is unsupported")
    imported = build_thread_context_import(
        operation_id=operation_id or str(receipt.get("operationId") or "thread-context-import"),
        source_receipt_digest=str(receipt.get("receiptDigest") or ""),
        content=receipt.get("result", {}),
        source={
            "kind": "host-thread",
            "sourceId": source_id or "redacted",
            "citation": citation or "operator-provided",
            "operation": receipt.get("operation"),
            "status": receipt.get("status"),
        },
        max_imported_bytes=max_imported_bytes,
        max_imported_tokens=max_imported_tokens,
    )
    validation = validate_thread_context_import(imported)
    if validation["status"] != "PASS":
        raise LifecycleError("thread-context-invalid", "thread context import validation failed", {"validation": validation})
    return imported


def build_thread_episode_context(
    project_root: Path,
    artifact_paths: list[str],
    imported_context: dict[str, Any],
    *,
    external_context_paths: list[Path] | None = None,
    query: str = "",
    max_results: int = 8,
    target_tokens: int = 2048,
) -> dict[str, Any]:
    """Compose thread context with existing external-memory and episode retrieval."""

    validation = validate_thread_context_import(imported_context)
    if validation["status"] != "PASS":
        raise LifecycleError("thread-context-invalid", "thread context import validation failed", {"validation": validation})
    hints = load_external_context_hints(external_context_paths or [])
    hints.append(
        {
            "hintId": f"thread-context-{imported_context['importDigest'][:16]}",
            "contextRole": "optional-thread-context",
            "sourceOfTruth": False,
            "proof": False,
            "citation": imported_context.get("source", {}).get("citation", "operator-provided"),
            "sourceDigest": imported_context["importDigest"],
            "redactionStatus": imported_context.get("redactionStatus", {}).get("status", "PASS"),
            "text": _context_text(imported_context.get("content", {})),
        }
    )
    return build_episode_context(
        project_root,
        artifact_paths,
        query=query,
        external_context_hints=hints,
        max_results=max_results,
        target_tokens=target_tokens,
    )


def _context_text(content: Any) -> str:
    if isinstance(content, dict):
        return " ".join(f"{key}: {value}" for key, value in content.items())[:5600]
    return str(content)[:5600]

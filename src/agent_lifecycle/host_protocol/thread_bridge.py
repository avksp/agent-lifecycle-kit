"""Host-boundary helpers for optional thread operations.

This module only prepares and validates portable envelopes. Native thread APIs
remain owned by adapters and are intentionally outside the core package.
"""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.thread_bridge_schemas import (
    build_thread_context_import,
    build_thread_operation_receipt,
    build_thread_operation_request,
    build_thread_operation_validation,
    validate_thread_context_import,
    validate_thread_operation_receipt,
    validate_thread_operation_request,
)


def prepare_thread_request(**kwargs: Any) -> dict[str, Any]:
    """Prepare a host-neutral request without executing an operation."""

    return build_thread_operation_request(**kwargs)


def prepare_thread_context_import(**kwargs: Any) -> dict[str, Any]:
    """Prepare bounded external context from an adapter-owned receipt."""

    return build_thread_context_import(**kwargs)


def validate_thread_request(request: dict[str, Any]) -> dict[str, Any]:
    return validate_thread_operation_request(request)


def validate_thread_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    return validate_thread_operation_receipt(receipt)


def validate_thread_context(imported: dict[str, Any]) -> dict[str, Any]:
    return validate_thread_context_import(imported)


def validate_thread_exchange(request: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    """Validate request/receipt lineage without invoking a host."""

    return build_thread_operation_validation(request, receipt)


__all__ = [
    "build_thread_operation_receipt",
    "prepare_thread_context_import",
    "prepare_thread_request",
    "validate_thread_context",
    "validate_thread_exchange",
    "validate_thread_receipt",
    "validate_thread_request",
]

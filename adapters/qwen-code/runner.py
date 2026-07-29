"""Fail-closed runner skeleton for the adapter projection."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError


def run_operation(request: dict[str, Any]) -> dict[str, Any]:
    capability = request.get("capability")
    raise LifecycleError(
        "adapter-operation-not-implemented",
        "qwen-code adapter runner is not implemented for live execution",
        {"host": "qwen-code", "capability": capability},
    )

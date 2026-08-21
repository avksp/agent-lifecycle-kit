"""Verify immutable plan lock bindings."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.freeze.package_integrity import verify_plan_lock_envelope


def verify_plan_lock(manifest: dict[str, Any], lock: dict[str, Any]) -> dict[str, Any]:
    return verify_plan_lock_envelope(manifest, lock)

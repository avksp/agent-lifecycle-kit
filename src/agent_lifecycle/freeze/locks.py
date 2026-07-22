"""Verify immutable plan lock bindings."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest


def verify_plan_lock(manifest: dict[str, Any], lock: dict[str, Any]) -> dict[str, Any]:
    if lock.get("schemaVersion") != "agent-plan-lock.v1":
        raise LifecycleError("invalid-plan-lock", "plan lock schemaVersion is unsupported")
    digest = canonical_digest(manifest)
    if lock.get("manifestHash") != digest:
        raise LifecycleError("plan-lock-mismatch", "plan lock manifestHash mismatch")
    if lock.get("planRevision") != manifest.get("planRevision"):
        raise LifecycleError("plan-lock-mismatch", "plan lock revision mismatch")
    return {
        "schemaVersion": "agent-plan-lock-verification.v1",
        "packageId": lock.get("packageId") or manifest.get("package", {}).get("id"),
        "planRevision": lock.get("planRevision"),
        "manifestHash": digest,
    }

"""Shared workflow and release lineage checks."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import canonical_digest


def check_lineage(
    manifest: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
    task_packet_index: dict[str, Any] | None = None,
    final_audit: dict[str, Any] | None = None,
    final_proof: dict[str, Any] | None = None,
    release_inventory: dict[str, Any] | None = None,
    lock: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare frozen-plan identity across workflow and release artifacts."""

    package = manifest.get("package", {})
    expected = {
        "packageId": package.get("id"),
        "planRevision": manifest.get("planRevision"),
        "planDigest": canonical_digest(manifest),
    }
    checks: list[dict[str, Any]] = []
    _compare(checks, "manifest.packageId", expected["packageId"], package.get("id"))
    _compare(checks, "manifest.planRevision", expected["planRevision"], manifest.get("planRevision"))
    _compare(checks, "manifest.planDigest", expected["planDigest"], expected["planDigest"])
    if lock is not None:
        _compare(checks, "lock.packageId", expected["packageId"], lock.get("packageId"), optional_actual=True)
        _compare(checks, "lock.planRevision", expected["planRevision"], lock.get("planRevision"))
        _compare(checks, "lock.manifestHash", expected["planDigest"], lock.get("manifestHash"))
    if state is not None:
        _compare_artifact(checks, "state", expected, state)
        _compare_required_tasks(checks, manifest, state)
    if task_packet_index is not None:
        _compare(checks, "taskPacketIndex.packageId", expected["packageId"], task_packet_index.get("packageId"), optional_actual=True)
        _compare(checks, "taskPacketIndex.manifestDigest", expected["planDigest"], task_packet_index.get("manifestDigest"))
    if final_audit is not None:
        _compare_artifact(checks, "finalAudit", expected, final_audit, package_optional=True)
    if final_proof is not None:
        _compare_artifact(checks, "finalProof", expected, final_proof, package_optional=True)
    if release_inventory is not None:
        _compare_artifact(checks, "releaseInventory", expected, release_inventory, package_optional=True)
    status = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    return {
        "schemaVersion": "agent-workflow-lineage-check.v1",
        "status": status,
        "packageId": expected["packageId"],
        "planRevision": expected["planRevision"],
        "planDigest": expected["planDigest"],
        "lineageChecks": checks,
    }


def _compare_artifact(
    checks: list[dict[str, Any]],
    prefix: str,
    expected: dict[str, Any],
    artifact: dict[str, Any],
    *,
    package_optional: bool = False,
) -> None:
    _compare(
        checks,
        f"{prefix}.packageId",
        expected["packageId"],
        artifact.get("packageId"),
        optional_actual=package_optional,
    )
    _compare(checks, f"{prefix}.planRevision", expected["planRevision"], artifact.get("planRevision"))
    _compare(checks, f"{prefix}.planDigest", expected["planDigest"], artifact.get("planDigest"))


def _compare_required_tasks(
    checks: list[dict[str, Any]],
    manifest: dict[str, Any],
    state: dict[str, Any],
) -> None:
    expected = sorted(
        str(item.get("id"))
        for item in manifest.get("workstreams", [])
        if isinstance(item, dict) and item.get("required", True)
    )
    actual = sorted(
        str(item.get("id"))
        for item in state.get("tasks", [])
        if isinstance(item, dict) and item.get("required", True)
    )
    _compare(checks, "requiredTaskSet", expected, actual)


def _compare(
    checks: list[dict[str, Any]],
    check_id: str,
    expected: Any,
    actual: Any,
    *,
    optional_actual: bool = False,
) -> None:
    if optional_actual and actual is None:
        checks.append({"id": check_id, "status": "PASS", "expected": expected, "actual": actual, "skipped": True})
        return
    status = "PASS" if actual == expected else "FAIL"
    checks.append({"id": check_id, "status": status, "expected": expected, "actual": actual})

"""Canonical compatibility proof for accepted tasks preserved across plan revisions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent_lifecycle.contracts import canonical_digest

TASK_PLAN_COMPATIBILITY_SCHEMA = "agent-task-plan-compatibility-receipt.v1"
TASK_PLAN_COMPATIBILITY_VALIDATION_SCHEMA = "agent-task-plan-compatibility-receipt-validation.v1"

TASK_CONTRACT_KEYS = (
    "id",
    "title",
    "owner",
    "dependsOn",
    "writes",
    "reviewer",
    "launchGate",
    "capabilityHints",
    "requiredTools",
    "contextRefs",
    "acceptanceIds",
    "evidenceIds",
    "executionPolicy",
    "modelRoute",
    "reviewMesh",
    "artifactPaths",
    "controllerGates",
    "required",
)

EMPTY_LIST_CONTRACT_KEYS = frozenset({"acceptanceIds", "controllerGates"})

ACCEPTED_ARTIFACT_KEYS = (
    "result",
    "review",
    "implementationAuditReport",
)


def canonical_task_contract(task: dict[str, Any]) -> dict[str, Any]:
    """Return the exact task fields whose equality permits preservation."""

    return {
        key: deepcopy(task.get(key, []) if key in EMPTY_LIST_CONTRACT_KEYS else task.get(key))
        for key in TASK_CONTRACT_KEYS
    }


def task_contract_digest(task: dict[str, Any]) -> str:
    return canonical_digest(canonical_task_contract(task))


def task_contracts_compatible(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    return canonical_task_contract(previous) == canonical_task_contract(current)


def build_task_plan_compatibility_receipt(
    *,
    previous_state: dict[str, Any],
    current_plan: dict[str, Any],
    previous_task: dict[str, Any],
    current_task: dict[str, Any],
) -> dict[str, Any]:
    """Build a controller-owned proof for one unchanged accepted task."""

    previous_digest = task_contract_digest(previous_task)
    current_digest = task_contract_digest(current_task)
    if previous_digest != current_digest:
        raise ValueError("task contracts are not compatible")
    artifacts = {
        key: deepcopy(previous_task[key]) for key in ACCEPTED_ARTIFACT_KEYS if isinstance(previous_task.get(key), dict)
    }
    body: dict[str, Any] = {
        "schemaVersion": TASK_PLAN_COMPATIBILITY_SCHEMA,
        "status": "PASS",
        "taskId": current_task.get("id"),
        "attempt": previous_task.get("attempt"),
        "previousPlan": _plan_identity(previous_state),
        "currentPlan": deepcopy(current_plan),
        "taskContract": {
            "previousDigest": previous_digest,
            "currentDigest": current_digest,
            "compatible": True,
        },
        "acceptedArtifacts": artifacts,
        "decision": "PRESERVE_ACCEPTED_COMPATIBLE",
        "producer": {
            "boundary": "workflow-controller",
            "operation": "adopt-plan",
        },
        "blockers": [],
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def validate_task_plan_compatibility_receipt(
    receipt: dict[str, Any] | None,
    *,
    state: dict[str, Any],
    task: dict[str, Any],
    report: dict[str, Any] | None = None,
    report_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate preserved lineage and, when supplied, one prior audit report."""

    blockers: list[dict[str, Any]] = []
    payload = receipt if isinstance(receipt, dict) else {}
    if payload.get("schemaVersion") != TASK_PLAN_COMPATIBILITY_SCHEMA:
        blockers.append({"code": "task-plan-compatibility-schema"})
    if payload.get("status") != "PASS" or payload.get("blockers") != []:
        blockers.append({"code": "task-plan-compatibility-status"})
    if payload.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "task-plan-compatibility-production-claim"})
    producer = payload.get("producer")
    if producer != {"boundary": "workflow-controller", "operation": "adopt-plan"}:
        blockers.append({"code": "task-plan-compatibility-producer"})
    body = {key: value for key, value in payload.items() if key != "receiptDigest"}
    if payload.get("receiptDigest") != canonical_digest(body):
        blockers.append({"code": "task-plan-compatibility-digest"})

    if payload.get("taskId") != task.get("id"):
        blockers.append({"code": "task-plan-compatibility-task"})
    if payload.get("attempt") != task.get("attempt"):
        blockers.append({"code": "task-plan-compatibility-attempt"})
    current_plan = payload.get("currentPlan")
    expected_current = _plan_identity(state)
    if current_plan != expected_current:
        blockers.append({"code": "task-plan-compatibility-current-plan"})

    contract = payload.get("taskContract")
    current_digest = task_contract_digest(task)
    if (
        not isinstance(contract, dict)
        or contract.get("compatible") is not True
        or contract.get("previousDigest") != contract.get("currentDigest")
        or contract.get("currentDigest") != current_digest
    ):
        blockers.append({"code": "task-plan-compatibility-contract"})

    artifacts = payload.get("acceptedArtifacts")
    if not isinstance(artifacts, dict):
        blockers.append({"code": "task-plan-compatibility-artifacts"})
        artifacts = {}
    for key, expected in artifacts.items():
        if key not in ACCEPTED_ARTIFACT_KEYS or task.get(key) != expected:
            blockers.append({"code": "task-plan-compatibility-artifact-mismatch", "artifact": key})
    for key in ACCEPTED_ARTIFACT_KEYS:
        if isinstance(task.get(key), dict) and key not in artifacts:
            blockers.append({"code": "task-plan-compatibility-artifact-missing", "artifact": key})

    if report is not None:
        _validate_prior_report(
            report,
            report_identity=report_identity,
            previous_plan=payload.get("previousPlan"),
            task=task,
            artifacts=artifacts,
            blockers=blockers,
        )

    result = {
        "schemaVersion": TASK_PLAN_COMPATIBILITY_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "taskId": task.get("id"),
        "receiptDigest": payload.get("receiptDigest"),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**result, "validationDigest": canonical_digest(result)}


def _validate_prior_report(
    report: dict[str, Any],
    *,
    report_identity: dict[str, Any] | None,
    previous_plan: Any,
    task: dict[str, Any],
    artifacts: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> None:
    if not isinstance(previous_plan, dict):
        blockers.append({"code": "task-plan-compatibility-previous-plan"})
        return
    for key in ("runId", "packageId", "sourceRevision"):
        if report.get(key) != previous_plan.get(key):
            blockers.append({"code": "task-plan-compatibility-report-lineage", "field": key})
    if not _report_plan_lineage_is_compatible(report, previous_plan):
        for key in ("planRevision", "planDigest"):
            blockers.append({"code": "task-plan-compatibility-report-lineage", "field": key})
    if report.get("taskId") != task.get("id") or report.get("attempt") != task.get("attempt"):
        blockers.append({"code": "task-plan-compatibility-report-task"})
    expected_identity = artifacts.get("implementationAuditReport")
    if not isinstance(expected_identity, dict) or not isinstance(report_identity, dict):
        blockers.append({"code": "task-plan-compatibility-report-identity-missing"})
        return
    for key in ("path", "sha256", "bytes"):
        if report_identity.get(key) != expected_identity.get(key):
            blockers.append({"code": "task-plan-compatibility-report-identity", "field": key})
    if report.get("reportDigest") != expected_identity.get("reportDigest"):
        blockers.append({"code": "task-plan-compatibility-report-digest"})


def _report_plan_lineage_is_compatible(report: dict[str, Any], previous_plan: dict[str, Any]) -> bool:
    """Allow an accepted report from any earlier compatible plan revision.

    A run may adopt several compatible frozen plans before its final audit. The
    accepted artifact remains bound to the revision that produced it, so the
    immediate predecessor in a later compatibility receipt is not necessarily
    the report's original revision.
    """

    if report.get("planRevision") == previous_plan.get("planRevision") and report.get(
        "planDigest"
    ) == previous_plan.get("planDigest"):
        return True
    report_revision = report.get("planRevision")
    previous_revision = previous_plan.get("planRevision")
    report_digest = report.get("planDigest")
    return (
        isinstance(report_revision, int)
        and not isinstance(report_revision, bool)
        and isinstance(previous_revision, int)
        and not isinstance(previous_revision, bool)
        and 1 <= report_revision < previous_revision
        and isinstance(report_digest, str)
        and len(report_digest) == 64
        and all(character in "0123456789abcdef" for character in report_digest)
    )


def _plan_identity(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "runId": source.get("runId"),
        "packageId": source.get("packageId"),
        "planRevision": source.get("planRevision"),
        "planDigest": source.get("planDigest"),
        "sourceRevision": source.get("sourceRevision"),
    }

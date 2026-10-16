"""Pure task-start classification from an independently verified frozen plan."""

from __future__ import annotations

from typing import Any
from typing import cast as _validated_cast

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.immutable_input_schemas import (
    validate_a5_adoption_binding,
    validate_a5_boundary_registry,
    validate_a5_decision,
    validate_a5_decision_binding,
    validate_a5_invocation_request,
    validate_a5_plan_policy,
    validate_a5_policy,
)
from agent_lifecycle.planning.task_compatibility import validate_task_plan_compatibility_receipt


def evaluate_task_admission(
    manifest: dict[str, Any],
    state: dict[str, Any],
    task: dict[str, Any],
    subject: dict[str, Any],
    request: Any = None,
    *,
    registry: Any = None,
) -> dict[str, Any] | None:
    """Caller must verify manifest/lock/source first. No mutation or dispatch."""
    invocation = validate_a5_invocation_request(
        {"schemaVersion": "agent-a5-invocation-request.v1", "requestedProtection": "NONE"}
        if request is None
        else request
    )
    selected = [item for item in manifest.get("workstreams", []) if item.get("id") == task["id"]]
    if len(selected) != 1:
        raise LifecycleError("a5-context-invalid", "Frozen selected task is missing or ambiguous")
    frozen_task = selected[0]
    if "immutableInput" not in manifest:
        if (
            "immutableInput" in state
            or any("immutableInput" in item for item in manifest.get("workstreams", []))
            or "immutableInput" in task
        ):
            raise LifecycleError("a5-context-invalid", "Legacy classification contradicts marked inputs")
        if invocation["requestedProtection"] == "STRONG_A5":
            raise LifecycleError("a5-strong-unproven", "Strong protection is unproven for a legacy route")
        return None
    plan = validate_a5_plan_policy(manifest["immutableInput"])
    if state.get("immutableInput") != plan or task.get("immutableInput") != frozen_task.get("immutableInput"):
        raise LifecycleError("a5-context-invalid", "Native policies differ from the verified frozen manifest")
    policy = validate_a5_policy(frozen_task.get("immutableInput"))
    if plan["defaultRequirement"] == "STRONG_A5" and policy["frozenTaskRequirement"] != "STRONG_A5":
        raise LifecycleError("a5-context-invalid", "Task policy lowers the frozen default")
    boundaries = validate_a5_boundary_registry(registry)
    matched = [item for item in boundaries["records"] if item["adapterId"] == policy["adapterId"]]
    if len(matched) != 1:
        raise LifecycleError("a5-context-invalid", "Selected adapter boundary is unresolved")
    boundary = matched[0]
    if (
        any(policy[field] != boundary[field] for field in ("expectationId", "targetVersion", "boundaryRecordDigest"))
        or policy["entrySurface"] != "ALK_TASK_START"
    ):
        raise LifecycleError("a5-context-invalid", "Task policy differs from the selected route boundary")
    if "STRONG_A5" in (plan["defaultRequirement"], policy["frozenTaskRequirement"], invocation["requestedProtection"]):
        raise LifecycleError("a5-strong-unproven", "Strong A5 protection has not been proven")
    bound_request = {
        "schemaVersion": "agent-a5-limited-request.v1",
        "subject": subject,
        "requestedProtection": invocation["requestedProtection"],
        "expectedPolicyDigest": policy["policyDigest"],
        "expectedBoundaryRecordDigest": policy["boundaryRecordDigest"],
    }
    decision = {
        "schemaVersion": "agent-a5-limited-decision.v1",
        "subject": dict(subject),
        "policyDigest": policy["policyDigest"],
        "boundaryRecordDigest": policy["boundaryRecordDigest"],
        "requestDigest": canonical_digest(bound_request),
        "effectiveRequirement": "NONE",
        "disposition": "ORDINARY_NO_A5",
        "reason": "NO_STRONG_REQUIREMENT",
        "strongProtectionGranted": False,
        "scope": "ALK_ADMISSION_CLASSIFICATION_ONLY",
    }
    decision["decisionDigest"] = canonical_digest(decision)
    return validate_a5_decision_binding(decision, policy, bound_request)


def is_unadopted_ordinary_context(
    state: dict[str, Any],
    task: dict[str, Any],
    request: Any = None,
) -> bool:
    """Preserve existing unadopted calls; never downgrade partial adopted authority."""
    invocation = validate_a5_invocation_request(
        {"schemaVersion": "agent-a5-invocation-request.v1", "requestedProtection": "NONE"}
        if request is None
        else request
    )
    if state.get("manifestPath"):
        return False
    slots = {"immutableInput", "immutableInputAdmission", "immutableInputAdoption"}
    if "manifestPath" in state or "packetSet" in state or "immutableInput" in state or slots.intersection(task):
        raise LifecycleError("a5-context-invalid", "Partial adopted A5 context lacks its frozen manifest")
    if invocation["requestedProtection"] == "STRONG_A5":
        raise LifecycleError("a5-strong-unproven", "Unadopted ordinary calls cannot grant strong A5")
    return True


def policies_compatible_for_adoption(
    previous_task: dict[str, Any],
    current_task: dict[str, Any],
    *,
    previous_plan_policy: Any,
    current_plan_policy: Any,
) -> bool:
    """Additional compatibility condition; it never replaces the existing contract check."""
    for plan, task in ((previous_plan_policy, previous_task), (current_plan_policy, current_task)):
        policy = task.get("immutableInput")
        if plan is None:
            if policy is not None:
                raise LifecycleError("a5-context-invalid", "Adopted task policy lacks its plan policy")
        else:
            validate_a5_plan_policy(plan)
            validate_a5_policy(policy)
            if "STRONG_A5" in (
                plan["defaultRequirement"],
                _validated_cast(dict[str, Any], policy)["frozenTaskRequirement"],
            ):
                return False
    previous = previous_task.get("immutableInput")
    current = current_task.get("immutableInput")
    if previous is None:
        return current is None or current["frozenTaskRequirement"] == "NONE"
    return current == previous


def require_task_consumer_admission(
    manifest: dict[str, Any],
    state: dict[str, Any],
    task: dict[str, Any],
    consumer_subject: dict[str, Any],
    *,
    registry: Any = None,
    trusted_original_admission: dict[str, Any] | None = None,
) -> None:
    """Check verified current policy without replacing the original start decision."""
    original = task.get("immutableInputAdmission")
    binding = task.get("immutableInputAdoption")
    if original is not None:
        original = validate_a5_decision(original)
        if original != trusted_original_admission:
            raise LifecycleError("a5-context-invalid", "Original A5 admission is not joined to its native start")
        subject = original["subject"]
        if (
            subject["runId"] != state["runId"]
            or subject["packageId"] != state["packageId"]
            or subject["taskId"] != task["id"]
            or subject["targetAttempt"] != task["attempt"]
            or subject["stateRevision"] >= consumer_subject["stateRevision"]
        ):
            raise LifecycleError("a5-context-invalid", "Original A5 admission differs from the actual attempt")
        if binding is None and (
            subject["planDigest"] != state["planDigest"] or subject["sourceRevision"] != state["sourceRevision"]
        ):
            raise LifecycleError("a5-context-invalid", "Original A5 admission lacks current applicability")
        checked = evaluate_task_admission(manifest, state, task, subject, registry=registry)
        if checked != original:
            raise LifecycleError("a5-context-invalid", "Original A5 admission differs from verified policy")
    else:
        checked = evaluate_task_admission(manifest, state, task, consumer_subject, registry=registry)
        if checked is not None and (binding is None or binding.get("classification") != "PRESERVED_LEGACY_NO_A5"):
            raise LifecycleError("a5-context-invalid", "Executed marked task lacks its original A5 admission")
    if binding is not None:
        binding = validate_a5_adoption_binding(binding)
        compatibility = require_compatibility_receipt(state, task)
        if (
            binding["compatibilityReceiptDigest"] != compatibility.get("receiptDigest")
            or binding["runId"] != state["runId"]
            or binding["taskId"] != task["id"]
            or binding["actualAttempt"] != task["attempt"]
            or binding["currentPlanDigest"] != state["planDigest"]
            or binding["currentPolicyDigest"] != task.get("immutableInput", {}).get("policyDigest")
        ):
            raise LifecycleError("a5-context-invalid", "A5 adoption lacks current compatibility")
        if original is not None and (
            binding["classification"] != "PRESERVED_ORDINARY_NO_A5"
            or binding["originalPlanDigest"] != original["subject"]["planDigest"]
            or binding["originalPolicyDigest"] != original["policyDigest"]
            or binding["originalDecisionDigest"] != original["decisionDigest"]
        ):
            raise LifecycleError("a5-context-invalid", "A5 adoption lost its original admission")


def require_compatibility_receipt(state: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    receipt = task.get("planCompatibilityReceipt")
    result = validate_task_plan_compatibility_receipt(receipt, state=state, task=task)
    if result["status"] != "PASS":
        raise LifecycleError("a5-context-invalid", "A5 compatibility receipt is invalid", {"validation": result})
    return _validated_cast(dict[str, Any], receipt)


def original_legacy_plan_from_history(
    state: dict[str, Any],
    task: dict[str, Any],
    events: list[dict[str, Any]],
) -> str:
    """Follow verified native compatible adoptions back to the execution plan."""
    from agent_lifecycle.planning.task_compatibility import task_contracts_compatible

    current, current_task = state, task
    seen = set()
    while current_task.get("planCompatibilityReceipt") is not None:
        if current["planDigest"] in seen:
            raise LifecycleError("a5-context-invalid", "Legacy compatibility lineage contains a cycle")
        seen.add(current["planDigest"])
        receipt = require_compatibility_receipt(current, current_task)
        native = [
            event
            for event in events
            if event.get("eventType") == "plan-adopted"
            and event.get("runId") == state["runId"]
            and event.get("packageId") == state["packageId"]
            and event.get("payload", {}).get("planDigest") == current["planDigest"]
            and {"taskId": task["id"], "receiptDigest": receipt["receiptDigest"]}
            in event.get("payload", {}).get("taskCompatibilityReceipts", [])
        ]
        if len(native) != 1:
            raise LifecycleError("a5-context-invalid", "Legacy compatibility lacks its native adoption")
        event = native[0]
        operation = state.get("operationLedger", {}).get(event.get("operationId"))
        if (
            not isinstance(operation, dict)
            or operation.get("eventType") != "plan-adopted"
            or operation.get("stateRevision") != event.get("stateRevision")
        ):
            raise LifecycleError("a5-context-invalid", "Legacy compatibility lacks its native operation")
        snapshots = [
            snapshot
            for snapshot in state.get("priorSnapshots", [])
            if {
                key: snapshot.get(key) for key in ("runId", "packageId", "planRevision", "planDigest", "sourceRevision")
            }
            == receipt.get("previousPlan")
        ]
        candidates = [
            (snapshot, item)
            for snapshot in snapshots
            for item in snapshot.get("tasks", [])
            if item.get("id") == task["id"]
            and item.get("attempt") == task["attempt"]
            and item.get("status") == "ACCEPTED"
            and task_contracts_compatible(item, current_task)
            and all(
                item.get(role) == receipt["acceptedArtifacts"].get(role)
                for role in ("result", "review", "implementationAuditReport")
            )
        ]
        if len(candidates) != 1:
            raise LifecycleError("a5-context-invalid", "Legacy accepted task lineage is missing or ambiguous")
        current, current_task = candidates[0]
    return current["planDigest"]


def original_admission_from_events(
    state: dict[str, Any],
    task: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    require_legacy_start: bool = False,
) -> dict[str, Any] | None:
    """Join the retained decision to a separate controller start and operation record."""
    original = task.get("immutableInputAdmission")
    starts = [
        event
        for event in events
        if event.get("eventType") == "task-started"
        and event.get("runId") == state["runId"]
        and event.get("packageId") == state["packageId"]
        and isinstance(event.get("payload"), dict)
        and event["payload"].get("taskId") == task["id"]
        and event["payload"].get("attempt") == task["attempt"]
    ]
    if original is None:
        if any(event["payload"].get("immutableInputAdmission") is not None for event in starts):
            raise LifecycleError("a5-context-invalid", "Marked native start cannot lose its original admission")
        binding = task.get("immutableInputAdoption")
        if binding is not None or require_legacy_start:
            original_plan = original_legacy_plan_from_history(state, task, events)
            if binding is not None and binding["originalPlanDigest"] != original_plan:
                raise LifecycleError("a5-context-invalid", "Legacy binding differs from its original history")
            legacy = [event for event in starts if event["payload"].get("planDigest", original_plan) == original_plan]
            if len(legacy) != 1:
                raise LifecycleError("a5-context-invalid", "Original legacy native start is missing or ambiguous")
            event = legacy[0]
            operation = state.get("operationLedger", {}).get(event.get("operationId"))
            if (
                not isinstance(operation, dict)
                or operation.get("eventType") != "task-started"
                or operation.get("stateRevision") != event.get("stateRevision")
            ):
                raise LifecycleError("a5-context-invalid", "Original legacy start lacks its native operation")
        return None
    original = validate_a5_decision(original)
    subject = original["subject"]
    matching = [
        event
        for event in events
        if event.get("eventType") == "task-started" and event.get("operationId") == subject["operationId"]
    ]
    ledger = state.get("operationLedger", {}).get(subject["operationId"])
    if len(matching) != 1 or not isinstance(ledger, dict):
        raise LifecycleError("a5-context-invalid", "Original A5 native start is missing or ambiguous")
    event = matching[0]
    payload = event.get("payload", {})
    if (
        event.get("runId") != state["runId"]
        or event.get("packageId") != state["packageId"]
        or event.get("stateRevision") != subject["stateRevision"] + 1
        or ledger.get("stateRevision") != event.get("stateRevision")
        or ledger.get("eventType") != "task-started"
        or payload.get("taskId") != task["id"]
        or payload.get("attempt") != task["attempt"]
        or payload.get("planDigest") != subject["planDigest"]
        or payload.get("sourceRevision") != subject["sourceRevision"]
        or payload.get("immutableInputAdmission") != original
    ):
        raise LifecycleError("a5-context-invalid", "Original A5 decision differs from its native start")
    return validate_a5_decision(payload["immutableInputAdmission"])


def adoption_binding(
    previous_state: dict[str, Any],
    previous_task: dict[str, Any],
    current_task: dict[str, Any],
    current_plan: dict[str, Any],
    compatibility_receipt: dict[str, Any],
    *,
    trusted_original_admission: dict[str, Any] | None = None,
    trusted_legacy_plan_digest: str | None = None,
) -> dict[str, Any] | None:
    """Keep first execution lineage through successive compatible adoptions."""
    prior_policy = previous_task.get("immutableInput")
    current_policy = current_task.get("immutableInput")
    original = previous_task.get("immutableInputAdmission")
    prior = previous_task.get("immutableInputAdoption")
    if prior_policy is None and current_policy is None and original is None and prior is None:
        return None  # Preserve the pre-existing verified legacy compatibility route.
    receipt_task = {**current_task, "attempt": previous_task["attempt"]}
    for role in ("result", "review", "implementationAuditReport"):
        if isinstance(previous_task.get(role), dict):
            receipt_task[role] = previous_task[role]
    validation = validate_task_plan_compatibility_receipt(compatibility_receipt, state=current_plan, task=receipt_task)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "a5-context-invalid", "New A5 compatibility receipt is invalid", {"validation": validation}
        )
    if original is not None:
        validate_a5_decision(original)
        if original != trusted_original_admission:
            raise LifecycleError("a5-context-invalid", "Preserved A5 admission lacks its original native start")
        subject = original["subject"]
        if (
            original["disposition"] != "ORDINARY_NO_A5"
            or subject["runId"] != previous_state["runId"]
            or subject["taskId"] != previous_task["id"]
            or subject["targetAttempt"] != previous_task["attempt"]
        ):
            raise LifecycleError("a5-context-invalid", "Original admission differs from the accepted attempt")
        original_plan = subject["planDigest"]
        original_policy = original["policyDigest"]
        original_decision = original["decisionDigest"]
        classification = "PRESERVED_ORDINARY_NO_A5"
    else:
        if prior_policy is not None and prior is None:
            raise LifecycleError("a5-context-invalid", "Marked accepted task lacks its original admission")
        original_plan = trusted_legacy_plan_digest or previous_state["planDigest"]
        original_policy = original_decision = None
        classification = "PRESERVED_LEGACY_NO_A5"
    if prior is not None:
        validate_a5_adoption_binding(prior)
        previous_compatibility = require_compatibility_receipt(previous_state, previous_task)
        if prior["compatibilityReceiptDigest"] != previous_compatibility["receiptDigest"]:
            raise LifecycleError("a5-context-invalid", "Prior A5 adoption differs from its compatibility receipt")
        if (
            prior["runId"] != previous_state["runId"]
            or prior["taskId"] != previous_task["id"]
            or prior["actualAttempt"] != previous_task["attempt"]
            or prior["currentPlanDigest"] != previous_state["planDigest"]
            or prior["currentPolicyDigest"] != (prior_policy["policyDigest"] if prior_policy else None)
            or prior["originalPolicyDigest"] != original_policy
            or prior["originalDecisionDigest"] != original_decision
            or (original is not None and prior["originalPlanDigest"] != original_plan)
        ):
            raise LifecycleError("a5-context-invalid", "Prior adoption no longer binds the first attempt")
        original_plan = prior["originalPlanDigest"]
    elif original is not None and (
        prior_policy is None
        or original_policy != prior_policy["policyDigest"]
        or original["boundaryRecordDigest"] != prior_policy["boundaryRecordDigest"]
        or original_plan != previous_state["planDigest"]
    ):
        raise LifecycleError("a5-context-invalid", "Original admission no longer binds the frozen policy")
    body = {
        "schemaVersion": "agent-a5-adoption-binding.v1",
        "runId": previous_state["runId"],
        "taskId": previous_task["id"],
        "actualAttempt": previous_task["attempt"],
        "originalPlanDigest": original_plan,
        "currentPlanDigest": current_plan["planDigest"],
        "originalPolicyDigest": original_policy,
        "currentPolicyDigest": current_policy["policyDigest"] if current_policy else None,
        "originalDecisionDigest": original_decision,
        "compatibilityReceiptDigest": compatibility_receipt["receiptDigest"],
        "classification": classification,
        "strongProtectionGranted": False,
    }
    return validate_a5_adoption_binding({**body, "bindingDigest": canonical_digest(body)})

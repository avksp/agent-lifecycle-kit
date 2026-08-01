"""Deterministic completion gate decisions."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.followup import validate_followup_register

COMPLETION_GATE_RECEIPT_SCHEMA = "agent-completion-gate-receipt.v1"
COMPLETION_GATE_VALIDATION_SCHEMA = "agent-completion-gate-validation.v1"

COMPLETION_GATE_DECISIONS = {"STOP", "CONTINUE", "ESCALATE", "SPLIT", "FOLLOW_UP"}
FINALIZATION_DECISIONS = {"STOP", "FOLLOW_UP"}


def build_completion_gate_receipt(
    *,
    state: dict[str, Any],
    final_audit: dict[str, Any] | None = None,
    validation_results: list[dict[str, Any]] | None = None,
    required_validation_ids: list[str] | None = None,
    follow_up_register: dict[str, Any] | None = None,
    follow_up_candidates: list[dict[str, Any]] | None = None,
    regression_signals: list[dict[str, Any]] | None = None,
    risk_flags: list[dict[str, Any]] | None = None,
    split_candidates: list[dict[str, Any]] | None = None,
    verifier_id: str = "completion-gate",
) -> dict[str, Any]:
    """Build a receipt deciding whether the current work should stop or continue."""

    _require_state_lineage(state)
    verifier = _required_string(verifier_id, label="verifierId", error_code="invalid-completion-gate-input")
    validations = _validation_summary(validation_results or [], required_validation_ids or [])
    acceptance = _acceptance_summary(state)
    blocker = _blocker_summary(state)
    final_proof = _final_proof_summary(final_audit)
    follow_up = _follow_up_summary(follow_up_register, follow_up_candidates or [])
    regression = _signal_summary(regression_signals or [], blocker_statuses={"FAIL", "BLOCKING"})
    risk = _signal_summary(risk_flags or [], blocker_statuses={"HIGH", "CRITICAL", "SECURITY", "RELEASE"})
    split = _split_summary(split_candidates or [])
    decision, reason_codes, blockers = _decide(
        acceptance=acceptance,
        blocker=blocker,
        validations=validations,
        final_proof=final_proof,
        follow_up=follow_up,
        regression=regression,
        risk=risk,
        split=split,
    )
    input_digests = {
        "stateDigest": canonical_digest(_state_binding(state)),
        "finalAuditDigest": canonical_digest(final_audit) if final_audit is not None else None,
        "followUpRegisterDigest": canonical_digest(follow_up_register) if follow_up_register is not None else None,
        "validationResultsDigest": canonical_digest(validation_results or []),
        "followUpCandidatesDigest": canonical_digest(follow_up_candidates or []),
        "regressionSignalsDigest": canonical_digest(regression_signals or []),
        "riskFlagsDigest": canonical_digest(risk_flags or []),
        "splitCandidatesDigest": canonical_digest(split_candidates or []),
    }
    body = {
        "schemaVersion": COMPLETION_GATE_RECEIPT_SCHEMA,
        "status": "PASS",
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
        "stateRevision": state.get("stateRevision"),
        "decision": decision,
        "reasonCodes": reason_codes,
        "blockers": blockers,
        "acceptance": acceptance,
        "validation": validations,
        "finalProof": final_proof,
        "followUp": follow_up,
        "regression": regression,
        "risk": risk,
        "split": split,
        "inputDigests": input_digests,
        "verifier": {"id": verifier},
        "productionPromotionClaimed": False,
    }
    return {**body, "gateDigest": canonical_digest(body)}


def validate_completion_gate_receipt(
    receipt: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
    final_audit: dict[str, Any] | None = None,
    follow_up_register: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a completion gate receipt and optional current input bindings."""

    if not isinstance(receipt, dict):
        raise LifecycleError("invalid-completion-gate-receipt", "completion gate receipt must be an object")
    if receipt.get("schemaVersion") != COMPLETION_GATE_RECEIPT_SCHEMA:
        raise LifecycleError("invalid-completion-gate-receipt", "completion gate receipt schemaVersion is unsupported")
    if receipt.get("status") != "PASS":
        raise LifecycleError("invalid-completion-gate-receipt", "completion gate receipt status must be PASS")
    if receipt.get("productionPromotionClaimed") is not False:
        raise LifecycleError("completion-gate-production-claim", "completion gate must not claim production promotion")
    decision = receipt.get("decision")
    if decision not in COMPLETION_GATE_DECISIONS:
        raise LifecycleError("invalid-completion-gate-receipt", "completion gate decision is unsupported")
    reason_codes = _string_list(receipt.get("reasonCodes"), label="reasonCodes", error_code="invalid-completion-gate-receipt")
    if not reason_codes:
        raise LifecycleError("invalid-completion-gate-receipt", "completion gate reasonCodes are required")
    _require_verifier(receipt.get("verifier"))
    _validate_gate_digest(receipt)
    input_checks = _validate_input_bindings(receipt, state=state, final_audit=final_audit, follow_up_register=follow_up_register)
    finalization_allowed = decision in FINALIZATION_DECISIONS
    final_proof = receipt.get("finalProof")
    if decision in FINALIZATION_DECISIONS and not _receipt_final_proof_ready(final_proof):
        raise LifecycleError("completion-gate-final-proof-missing", "stop/follow-up decisions require ready final proof evidence")
    if decision in FINALIZATION_DECISIONS:
        _require_no_finalization_blockers(receipt, state=state, final_audit=final_audit, follow_up_register=follow_up_register)
    validation = {
        "schemaVersion": COMPLETION_GATE_VALIDATION_SCHEMA,
        "status": "PASS",
        "decision": decision,
        "reasonCodes": reason_codes,
        "finalizationAllowed": finalization_allowed,
        "inputChecks": input_checks,
        "receiptDigest": canonical_digest(receipt),
    }
    return {**validation, "validationDigest": canonical_digest(validation)}


def require_completion_gate_finalization(
    receipt: dict[str, Any],
    *,
    state: dict[str, Any],
    final_audit: dict[str, Any],
    follow_up_register: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Require a completion gate receipt that allows finalization."""

    validation = validate_completion_gate_receipt(
        receipt,
        state=state,
        final_audit=final_audit,
        follow_up_register=follow_up_register,
    )
    if validation["decision"] not in FINALIZATION_DECISIONS:
        raise LifecycleError(
            "completion-gate-not-ready",
            "completion gate does not allow finalization",
            {"decision": validation["decision"], "reasonCodes": validation["reasonCodes"]},
        )
    return validation


def _decide(
    *,
    acceptance: dict[str, Any],
    blocker: dict[str, Any],
    validations: dict[str, Any],
    final_proof: dict[str, Any],
    follow_up: dict[str, Any],
    regression: dict[str, Any],
    risk: dict[str, Any],
    split: dict[str, Any],
) -> tuple[str, list[str], list[dict[str, Any]]]:
    blockers: list[dict[str, Any]] = []
    reason_codes: list[str] = []
    if acceptance["missingTaskIds"]:
        blockers.append({"code": "required-acceptance-missing", "taskIds": acceptance["missingTaskIds"]})
        reason_codes.append("required-acceptance-missing")
    if blocker["open"]:
        blockers.append({"code": "open-workflow-blocker", "blocker": blocker["blocker"]})
        reason_codes.append("open-workflow-blocker")
    if validations["missingIds"]:
        blockers.append({"code": "validation-missing", "validationIds": validations["missingIds"]})
        reason_codes.append("validation-missing")
    if validations["failedIds"]:
        blockers.append({"code": "validation-failed", "validationIds": validations["failedIds"]})
        reason_codes.append("validation-failed")
    if follow_up["finalizationBlockerIds"]:
        blockers.append({"code": "follow-up-blocks-finalization", "itemIds": follow_up["finalizationBlockerIds"]})
        reason_codes.append("follow-up-blocks-finalization")
    if regression["blockingIds"]:
        blockers.append({"code": "regression-signal-blocking", "signalIds": regression["blockingIds"]})
        reason_codes.append("regression-signal-blocking")
    if risk["blockingIds"]:
        blockers.append({"code": "risk-escalation-required", "flagIds": risk["blockingIds"]})
        reason_codes.append("risk-escalation-required")
    if split["candidateIds"]:
        blockers.append({"code": "split-required", "candidateIds": split["candidateIds"]})
        reason_codes.append("split-required")
    if not final_proof["ready"]:
        blockers.append({"code": "final-proof-not-ready", "status": final_proof["status"]})
        reason_codes.append("final-proof-not-ready")

    if split["candidateIds"]:
        return "SPLIT", _dedupe(reason_codes), blockers
    if blocker["open"] or risk["blockingIds"] or follow_up["finalizationBlockerIds"]:
        return "ESCALATE", _dedupe(reason_codes), blockers
    if blockers:
        return "CONTINUE", _dedupe(reason_codes), blockers
    if follow_up["nonBlockingItemIds"] or follow_up["candidateIds"]:
        return "FOLLOW_UP", ["non-blocking-follow-up"], []
    return "STOP", ["all-required-evidence-passed"], []


def _acceptance_summary(state: dict[str, Any]) -> dict[str, Any]:
    required = []
    missing = []
    for task in state.get("tasks", []):
        if not isinstance(task, dict) or not task.get("required", True):
            continue
        task_id = str(task.get("id", ""))
        required.append(task_id)
        if task.get("status") != "ACCEPTED":
            missing.append(task_id)
    return {
        "requiredTaskIds": required,
        "missingTaskIds": missing,
        "accepted": not missing,
    }


def _blocker_summary(state: dict[str, Any]) -> dict[str, Any]:
    blocker = state.get("blocker")
    return {"open": isinstance(blocker, dict) and bool(blocker), "blocker": blocker if isinstance(blocker, dict) else None}


def _validation_summary(results: list[dict[str, Any]], required_ids: list[str]) -> dict[str, Any]:
    seen: dict[str, str] = {}
    for index, item in enumerate(results):
        if not isinstance(item, dict):
            raise LifecycleError("invalid-completion-gate-input", "validationResults items must be objects", {"index": index})
        result_id = _required_string(item.get("id"), label="validationResults.id", error_code="invalid-completion-gate-input")
        status = _required_string(item.get("status"), label="validationResults.status", error_code="invalid-completion-gate-input")
        seen[result_id] = status
    required = _string_list(required_ids, label="requiredValidationIds", error_code="invalid-completion-gate-input", allow_empty=True)
    failed = sorted(result_id for result_id, status in seen.items() if status not in {"PASS", "WAIVED"})
    missing = sorted(set(required).difference(seen))
    return {
        "requiredIds": required,
        "providedIds": sorted(seen),
        "missingIds": missing,
        "failedIds": failed,
    }


def _final_proof_summary(final_audit: dict[str, Any] | None) -> dict[str, Any]:
    if final_audit is None:
        return {"required": True, "ready": False, "status": "missing", "finalAuditDigest": None}
    status = final_audit.get("status")
    semantic = final_audit.get("semanticStatus")
    ready = (
        status == "PASS"
        and semantic == "READY_FOR_FINALIZATION"
        and final_audit.get("productionPromotionClaimed") is False
        and not final_audit.get("notAcceptedTasks")
        and not final_audit.get("missingReleaseEvidence")
        and not _open_blocking_findings(final_audit)
    )
    return {
        "required": True,
        "ready": ready,
        "status": status or "unknown",
        "semanticStatus": semantic,
        "finalAuditDigest": canonical_digest(final_audit),
    }


def _follow_up_summary(register: dict[str, Any] | None, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    finalization_blockers: list[str] = []
    non_blocking_items: list[str] = []
    if register is not None:
        validation = validate_followup_register(register)
        finalization_blockers = [str(item["id"]) for item in validation["finalizationBlockers"]]
        blocking = set(finalization_blockers)
        non_blocking_items = [
            str(item.get("id"))
            for item in register.get("items", [])
            if isinstance(item, dict) and item.get("status") in {"OPEN", "BLOCKED", "SCHEDULED"} and item.get("id") not in blocking
        ]
    candidate_ids = []
    for index, item in enumerate(candidates):
        if not isinstance(item, dict):
            raise LifecycleError("invalid-completion-gate-input", "followUpCandidates items must be objects", {"index": index})
        candidate_ids.append(_required_string(item.get("id"), label="followUpCandidates.id", error_code="invalid-completion-gate-input"))
    return {
        "candidateIds": sorted(candidate_ids),
        "nonBlockingItemIds": sorted(non_blocking_items),
        "finalizationBlockerIds": sorted(finalization_blockers),
    }


def _signal_summary(items: list[dict[str, Any]], *, blocker_statuses: set[str]) -> dict[str, Any]:
    blocking = []
    observed = []
    normalized_blockers = {item.lower() for item in blocker_statuses}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise LifecycleError("invalid-completion-gate-input", "signal items must be objects", {"index": index})
        item_id = _required_string(item.get("id"), label="signal.id", error_code="invalid-completion-gate-input")
        observed.append(item_id)
        status = str(item.get("status") or item.get("severity") or "").lower()
        if item.get("blocking") is True or status in normalized_blockers:
            blocking.append(item_id)
    return {"observedIds": sorted(observed), "blockingIds": sorted(blocking)}


def _split_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_ids = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise LifecycleError("invalid-completion-gate-input", "splitCandidates items must be objects", {"index": index})
        item_id = _required_string(item.get("id"), label="splitCandidates.id", error_code="invalid-completion-gate-input")
        if item.get("required", True):
            candidate_ids.append(item_id)
    return {"candidateIds": sorted(candidate_ids)}


def _validate_input_bindings(
    receipt: dict[str, Any],
    *,
    state: dict[str, Any] | None,
    final_audit: dict[str, Any] | None,
    follow_up_register: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    digests = receipt.get("inputDigests")
    if not isinstance(digests, dict):
        raise LifecycleError("invalid-completion-gate-receipt", "completion gate inputDigests are required")
    for name, source in (
        ("stateDigest", state),
        ("finalAuditDigest", final_audit),
        ("followUpRegisterDigest", follow_up_register),
    ):
        if source is None:
            checks.append({"name": name, "status": "NOT_CHECKED"})
            continue
        expected = canonical_digest(_state_binding(source)) if name == "stateDigest" else canonical_digest(source)
        if digests.get(name) != expected:
            raise LifecycleError("completion-gate-input-mismatch", f"completion gate {name} mismatch")
        checks.append({"name": name, "status": "PASS"})
    return checks


def _validate_gate_digest(receipt: dict[str, Any]) -> None:
    gate_digest = receipt.get("gateDigest")
    if not isinstance(gate_digest, str) or len(gate_digest) != 64:
        raise LifecycleError("invalid-completion-gate-receipt", "completion gate gateDigest is required")
    body = {key: value for key, value in receipt.items() if key != "gateDigest"}
    if canonical_digest(body) != gate_digest:
        raise LifecycleError("completion-gate-digest-mismatch", "completion gate digest mismatch")


def _state_binding(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
        "stateRevision": state.get("stateRevision"),
        "phase": state.get("phase"),
        "blocker": state.get("blocker"),
        "tasks": [
            {
                "id": task.get("id"),
                "required": task.get("required", True),
                "status": task.get("status"),
                "attempt": task.get("attempt"),
                "review": task.get("review"),
            }
            for task in state.get("tasks", [])
            if isinstance(task, dict)
        ],
    }


def _receipt_final_proof_ready(final_proof: Any) -> bool:
    return isinstance(final_proof, dict) and final_proof.get("required") is True and final_proof.get("ready") is True


def _require_no_finalization_blockers(
    receipt: dict[str, Any],
    *,
    state: dict[str, Any] | None,
    final_audit: dict[str, Any] | None,
    follow_up_register: dict[str, Any] | None,
) -> None:
    blockers = _receipt_finalization_blockers(receipt)
    if state is not None:
        acceptance = _acceptance_summary(state)
        if acceptance["missingTaskIds"]:
            blockers.append({"code": "required-acceptance-missing", "taskIds": acceptance["missingTaskIds"]})
        state_blocker = _blocker_summary(state)
        if state_blocker["open"]:
            blockers.append({"code": "open-workflow-blocker", "blocker": state_blocker["blocker"]})
    if final_audit is not None and not _final_proof_summary(final_audit)["ready"]:
        blockers.append({"code": "final-proof-not-ready"})
    if follow_up_register is not None:
        finalization_blockers = validate_followup_register(follow_up_register)["finalizationBlockers"]
        if finalization_blockers:
            blockers.append({"code": "follow-up-blocks-finalization", "items": finalization_blockers})
    if blockers:
        raise LifecycleError(
            "completion-gate-blocked",
            "stop/follow-up decisions cannot carry blocking evidence",
            {"blockers": blockers},
        )


def _receipt_finalization_blockers(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    receipt_blockers = receipt.get("blockers")
    if isinstance(receipt_blockers, list) and receipt_blockers:
        blockers.append({"code": "receipt-blockers-present", "blockers": receipt_blockers})
    acceptance = receipt.get("acceptance")
    if isinstance(acceptance, dict) and acceptance.get("missingTaskIds"):
        blockers.append({"code": "required-acceptance-missing", "taskIds": acceptance.get("missingTaskIds")})
    validation = receipt.get("validation")
    if isinstance(validation, dict):
        if validation.get("missingIds"):
            blockers.append({"code": "validation-missing", "validationIds": validation.get("missingIds")})
        if validation.get("failedIds"):
            blockers.append({"code": "validation-failed", "validationIds": validation.get("failedIds")})
    follow_up = receipt.get("followUp")
    if isinstance(follow_up, dict) and follow_up.get("finalizationBlockerIds"):
        blockers.append({"code": "follow-up-blocks-finalization", "itemIds": follow_up.get("finalizationBlockerIds")})
    for key, code, id_key in (
        ("regression", "regression-signal-blocking", "signalIds"),
        ("risk", "risk-escalation-required", "flagIds"),
        ("split", "split-required", "candidateIds"),
    ):
        summary = receipt.get(key)
        ids = summary.get("candidateIds" if key == "split" else "blockingIds") if isinstance(summary, dict) else None
        if ids:
            blockers.append({"code": code, id_key: ids})
    return blockers


def _open_blocking_findings(final_audit: dict[str, Any]) -> list[str]:
    findings = final_audit.get("findings", [])
    if not isinstance(findings, list):
        return ["invalid-findings"]
    return [
        str(item.get("id"))
        for item in findings
        if isinstance(item, dict)
        and item.get("status") == "open"
        and item.get("severity") in {"BLOCKER", "HIGH", "MEDIUM"}
    ]


def _require_state_lineage(state: dict[str, Any]) -> None:
    if not isinstance(state, dict):
        raise LifecycleError("invalid-completion-gate-input", "state must be an object")
    for key in ("runId", "packageId", "planDigest", "sourceRevision"):
        _required_string(state.get(key), label=f"state.{key}", error_code="invalid-completion-gate-input")
    revision = state.get("planRevision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise LifecycleError("invalid-completion-gate-input", "state.planRevision must be a positive integer")
    state_revision = state.get("stateRevision")
    if not isinstance(state_revision, int) or isinstance(state_revision, bool) or state_revision < 1:
        raise LifecycleError("invalid-completion-gate-input", "state.stateRevision must be a positive integer")


def _require_verifier(value: Any) -> None:
    if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not value["id"]:
        raise LifecycleError("invalid-completion-gate-receipt", "completion gate verifier.id is required")


def _string_list(
    value: Any,
    *,
    label: str,
    error_code: str,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise LifecycleError(error_code, f"{label} must be a list of non-empty strings")
    if not value and not allow_empty:
        raise LifecycleError(error_code, f"{label} must not be empty")
    return list(value)


def _required_string(value: Any, *, label: str, error_code: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError(error_code, f"{label} is required")
    return value


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result

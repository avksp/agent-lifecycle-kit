"""Closing preparation data only: retain outcomes and cost, invalidate affected checks.

These local assessment records are not signed closing-window requests.
No filesystem I/O, journal admission, operator qualification or dispatch occurs.
The current signed-request schema remains the authority for protected closing.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, NoReturn

from agent_lifecycle.contracts.errors import LifecycleError

ORDINARY_OPERATOR_CLAIM = "ORDINARY_LIMITED"
PROTECTED_OPERATOR_CLAIM = "PROTECTED_ADOPTION_OR_CLOSING"


def operator_claim_refusal(requested_claim: str | None) -> dict[str, str] | None:
    """Refuse the unavailable native operator route without granting ordinary work.

    Ordinary requests still require their existing independent execution gates.
    This pure classifier neither qualifies bootstrap inputs nor touches storage.
    """
    if requested_claim is None or requested_claim == ORDINARY_OPERATOR_CLAIM:
        return None
    if requested_claim != PROTECTED_OPERATOR_CLAIM:
        raise LifecycleError("closing-request-claim-unsupported", "Unknown operator claim")
    return {"status": "DENY", "reason": "UNSUPPORTED_OPERATOR_ROUTE", "writeOutcome": "NOT_STARTED"}


RETAINED_EVIDENCE_ASSESSMENT = "agent-retained-evidence-assessment.v1"

MAX_RESOURCE = (1 << 63) - 1

BINDINGS = ("source", "harness", "oracle", "fixture", "environment", "contract")

RESOURCE_FIELDS = (
    "oldCap",
    "spentAtActivation",
    "approvedAdditional",
    "cumulativeSpent",
    "windowSpent",
    "activeReservations",
    "windowReservations",
    "protectedCloseout",
    "windowProtectedCloseout",
    "operationUpperBound",
)

RESOURCE_REFS = (
    "unitDefinition",
    "operationUnitDefinition",
    "sourceQualificationRef",
    "openingRef",
    "pendingRef",
    "protectionRef",
    "reservationRef",
)


def _invalid(message: str) -> NoReturn:
    raise LifecycleError("invalid-closing-window-data", message)


def _record(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _invalid(f"{label} must be an object")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        _invalid(f"{label} must be a nonempty bounded string")
    return value


def _integer(value: Any, label: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_RESOURCE:
        _invalid(f"{label} must be a nonnegative bounded integer")
    return value


def _timestamp(value: Any, label: str) -> datetime:
    _text(value, label)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LifecycleError("invalid-closing-window-data", f"{label} is invalid") from exc
    return _trusted_time(parsed)


def _trusted_time(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _invalid("time must be explicitly supplied and timezone aware")
    return value.astimezone(UTC)


def _strings(value: Any, label: str, *, empty: bool = False) -> list[str]:
    if not isinstance(value, list) or len(value) > 1024 or (not value and not empty):
        _invalid(f"{label} must be a list")
    for item in value:
        _text(item, label)
    if len(set(value)) != len(value):
        _invalid(f"{label} contains duplicate identities")
    return value


def _validate_resource_scopes(value: Any) -> list[dict[str, Any]]:
    """Validate shape; null quantities/qualification remain unknown, never zero."""
    if not isinstance(value, list) or not value or len(value) > 1024:
        _invalid("resourceScopes must be nonempty")
    seen = set()
    for scope in value:
        _record(scope, "scope")
        _text(scope.get("scopeId"), "scopeId")
        if scope.get("scopeKind") not in ("RUN", "TASK"):
            _invalid("scopeKind must be RUN or TASK")
        for key in ("unit", "operationUnit", *RESOURCE_REFS):
            if key not in scope:
                _invalid(f"missing resource field {key}")
            if scope[key] is not None:
                _text(scope[key], key)
        identity = (scope["scopeId"], scope["unit"])
        if identity in seen:
            _invalid("duplicate scope/unit")
        seen.add(identity)
        for key in RESOURCE_FIELDS:
            if key not in scope:
                _invalid(f"missing resource field {key}")
            if scope[key] is not None:
                _integer(scope[key], key)
        completeness = scope.get("capInventoryComplete")
        if completeness is not None and type(completeness) is not bool:
            _invalid("capInventoryComplete must be boolean or unknown")
        caps = scope.get("effectiveCaps")
        if caps is None:
            continue
        if not isinstance(caps, list):
            _invalid("effectiveCaps must be a list or unknown")
        cap_ids = set()
        for cap in caps:
            _record(cap, "effective cap")
            cap_id = _text(cap.get("capId"), "capId")
            if cap_id in cap_ids:
                _invalid("duplicate effective cap identity")
            cap_ids.add(cap_id)
            if cap.get("disposition") not in (None, "UNKNOWN", "BINDING", "SUPERSEDED_BY_WINDOW"):
                _invalid("unsupported effective cap disposition")
            if cap.get("limit") is not None:
                _integer(cap["limit"], "effective cap limit")
            if cap.get("policyRef") is not None:
                _text(cap["policyRef"], "effective cap policyRef")
    return value


def _validate_evidence_assessment(assessment: dict[str, Any]) -> None:
    """Validate structure; semantic unknowns are assessed separately."""
    _record(assessment, "assessment")
    if assessment.get("schemaVersion") != RETAINED_EVIDENCE_ASSESSMENT:
        _invalid("unsupported evidence schema")
    if type(assessment.get("inventoryComplete")) is not bool:
        _invalid("inventoryComplete must be boolean")
    _strings(assessment.get("requiredCheckIds"), "requiredCheckIds")
    checks = assessment.get("checks")
    if not isinstance(checks, list) or len(checks) > 1024:
        _invalid("checks must be a list")
    ids = []
    for check in checks:
        _record(check, "check")
        ids.append(_text(check.get("checkId"), "checkId"))
        if check.get("executionState") not in ("NEVER_STARTED", "TERMINAL", "RUNNING", "UNKNOWN"):
            _invalid("unsupported executionState")
        if check.get("dependencies") is not None:
            _strings(check["dependencies"], "dependencies", empty=True)
        if check.get("plannedUpperBound") is not None:
            _integer(check["plannedUpperBound"], "plannedUpperBound")
        if check.get("receipt") is not None:
            receipt = _record(check["receipt"], "receipt")
            if type(receipt.get("completed")) is not bool:
                _invalid("receipt completion must be boolean")
            if receipt.get("outcome") not in (None, "PASS", "FAIL"):
                _invalid("unsupported evidence outcome")
            if check["executionState"] == "NEVER_STARTED":
                _invalid("never-started check cannot have a receipt")
    if len(set(ids)) != len(ids):
        _invalid("duplicate check identities")


def evaluate_closing_resources(scopes: list[dict[str, Any]], *, inventory_complete: bool) -> dict[str, Any]:
    """Two limits on one charge, for every supplied qualified task/run scope."""
    result: dict[str, Any] = {
        "status": "UNAVAILABLE",
        "authority": "NOT_EVALUATED",
        "acceptance": "NOT_EVALUATED",
        "scopes": [],
    }
    try:
        _validate_resource_scopes(scopes)
        if inventory_complete is not True or not any(s["scopeKind"] == "RUN" for s in scopes):
            return {**result, "reason": "complete run/task scope inventory required"}
        for scope in scopes:
            row = {
                "scopeId": scope["scopeId"],
                "scopeKind": scope["scopeKind"],
                "unit": scope["unit"],
                "original": deepcopy(scope),
                "status": "UNAVAILABLE",
            }
            result["scopes"].append(row)
            if any(scope[k] is None for k in (*RESOURCE_FIELDS, *RESOURCE_REFS, "unit", "operationUnit")):
                row["reason"] = "unknown required resource quantity or qualification"
                continue
            if scope["unit"] != scope["operationUnit"] or scope["unitDefinition"] != scope["operationUnitDefinition"]:
                row["reason"] = "unit mismatch; conversion is not permitted"
                continue
            # Limits use this scope's cumulative unit/horizon. A qualified policy
            # input must distinguish still binding caps from historical ones;
            # oldCap alone is neither a current limit nor permission to replace it.
            caps = scope.get("effectiveCaps")
            if (
                scope.get("capInventoryComplete") is not True
                or not caps
                or any(
                    cap.get("disposition") not in ("BINDING", "SUPERSEDED_BY_WINDOW")
                    or cap.get("limit") is None
                    or cap.get("policyRef") is None
                    for cap in caps
                )
            ):
                row["reason"] = "unknown applicable cap inventory, disposition or policy binding"
                continue
            ceiling = _integer(scope["spentAtActivation"] + scope["approvedAdditional"], "cumulative ceiling")
            minimum_spent = _integer(scope["spentAtActivation"] + scope["windowSpent"], "minimum cumulative spent")
            if (
                scope["cumulativeSpent"] < minimum_spent
                or scope["windowReservations"] > scope["activeReservations"]
                or scope["windowProtectedCloseout"] > scope["protectedCloseout"]
            ):
                row.update(status="DENY", reason="inconsistent cumulative/window projections")
                continue
            cumulative = _integer(
                sum(
                    scope[k]
                    for k in ("cumulativeSpent", "activeReservations", "operationUpperBound", "protectedCloseout")
                ),
                "cumulative required",
            )
            window = _integer(
                sum(
                    scope[k]
                    for k in ("windowSpent", "windowReservations", "operationUpperBound", "windowProtectedCloseout")
                ),
                "window required",
            )
            violated_caps = [
                cap["capId"] for cap in caps if cap["disposition"] == "BINDING" and cumulative > cap["limit"]
            ]
            fits = cumulative <= ceiling and window <= scope["approvedAdditional"] and not violated_caps
            row.update(
                status="VALIDATED_DATA" if fits else "DENY",
                fits=fits,
                proposedCumulativeCeiling=ceiling,
                windowAllowance=scope["approvedAdditional"],
                oldExcess=max(0, scope["spentAtActivation"] - scope["oldCap"]),
                cumulativeRequired=cumulative,
                windowRequired=window,
                violatedEffectiveCaps=violated_caps,
                reason="within proposed and applicable limits" if fits else "proposed or applicable cap exhausted",
            )
        statuses = {r["status"] for r in result["scopes"]}
        result["status"] = (
            "DENY" if "DENY" in statuses else "UNAVAILABLE" if "UNAVAILABLE" in statuses else "VALIDATED_DATA"
        )
    except LifecycleError as exc:
        result.update(status="DENY", reason=str(exc), errorCode=exc.code)
    return result


def _known_bindings(value: Any) -> bool:
    return isinstance(value, dict) and all(isinstance(value.get(k), str) and value[k].strip() for k in BINDINGS)


def _base_classification(check: dict[str, Any], now: datetime) -> tuple[str, str]:
    if (
        not isinstance(check.get("subject"), str)
        or not check["subject"].strip()
        or not _known_bindings(check.get("bindings"))
    ):
        return "UNAVAILABLE", "unknown check definition, subject or current bindings"
    if check["executionState"] in ("RUNNING", "UNKNOWN"):
        return "UNAVAILABLE", "execution unfinished or uncertain; duplicate work forbidden"
    receipt = check.get("receipt")
    if receipt is None:
        return "RERUN_REQUIRED", "known required check without usable result"
    if not receipt["completed"]:
        return "UNAVAILABLE", "receipt has no final completion"
    identities = ("receiptId", "digest", "producer", "attemptId", "operationId", "subject")
    if any(not isinstance(receipt.get(k), str) or not receipt[k].strip() for k in identities):
        return "UNAVAILABLE", "unknown original receipt identity or provenance"
    if receipt.get("authenticity") != "QUALIFIED" or not _known_bindings(receipt.get("bindings")):
        return "UNAVAILABLE", "unknown authenticity or mandatory original binding"
    if receipt.get("outcome") is None or receipt.get("validUntil") is None:
        return "UNAVAILABLE", "unknown final outcome or semantic TTL"
    if _timestamp(receipt["validUntil"], "semantic TTL") <= now:
        return "RERUN_REQUIRED", "semantic TTL expired"
    if receipt["subject"] != check["subject"] or any(receipt["bindings"][k] != check["bindings"][k] for k in BINDINGS):
        return "RERUN_REQUIRED", "subject or mandatory technical binding changed"
    return "REUSE", "completed applicable evidence; original outcome retained"


def assess_retained_evidence(
    assessment: dict[str, Any],
    *,
    now: datetime,
    observer_qualification: str | None,
) -> dict[str, Any]:
    """Classify qualified input facts; the caller must prove its observer trust boundary."""
    result: dict[str, Any] = {
        "status": "UNAVAILABLE",
        "authority": "NOT_EVALUATED",
        "acceptance": "NOT_EVALUATED",
        "dispatch": False,
        "retainedInput": deepcopy(assessment),
        "checks": [],
        "futureAdmissionRequired": True,
    }
    try:
        _validate_evidence_assessment(assessment)
        current = _trusted_time(now)
        if not isinstance(observer_qualification, str) or not observer_qualification.strip():
            return {**result, "reason": "qualified independent observer required"}
        checks = {c["checkId"]: c for c in assessment["checks"]}
        if not assessment["inventoryComplete"] or not set(assessment["requiredCheckIds"]).issubset(checks):
            return {**result, "reason": "unknown required inventory or check definition"}
        if any(c.get("dependencies") is None or not set(c["dependencies"]).issubset(checks) for c in checks.values()):
            return {**result, "reason": "unknown dependency metadata"}
        # Kahn order avoids recursive traversal of untrusted DAG depth.
        order: list[str] = []
        pending = set(checks)
        while pending:
            ready = sorted(k for k in pending if not pending.intersection(checks[k]["dependencies"]))
            if not ready:
                return {**result, "reason": "dependency cycle"}
            order.extend(ready)
            pending.difference_update(ready)
        rows: dict[str, dict[str, Any]] = {}
        for key in order:
            check = checks[key]
            status, reason = _base_classification(check, current)
            dependencies = [rows[k]["status"] for k in check["dependencies"]]
            if "UNAVAILABLE" in dependencies:
                status, reason = "UNAVAILABLE", "dependency applicability unavailable"
            elif status != "UNAVAILABLE" and "RERUN_REQUIRED" in dependencies:
                status, reason = "RERUN_REQUIRED", "required dependency invalidated or missing result"
            receipt = check.get("receipt") or {}
            row = {
                "checkId": key,
                "subject": check.get("subject"),
                "status": status,
                "reason": reason,
                "originalOutcome": receipt.get("outcome"),
                "evidenceGateSatisfied": status == "REUSE" and receipt.get("outcome") == "PASS",
                "proposedUpperBound": check.get("plannedUpperBound"),
                "admissionStatus": "NOT_ADMITTED",
            }
            rows[key] = row
            result["checks"].append(row)
        statuses = {rows[k]["status"] for k in assessment["requiredCheckIds"]}
        result["status"] = (
            "UNAVAILABLE"
            if "UNAVAILABLE" in statuses
            else "RERUN_REQUIRED"
            if "RERUN_REQUIRED" in statuses
            else "REUSE"
        )
        result["evidenceGateSatisfied"] = all(rows[k]["evidenceGateSatisfied"] for k in assessment["requiredCheckIds"])
    except LifecycleError as exc:
        result.update(status="DENY", reason=str(exc), errorCode=exc.code)
    return result

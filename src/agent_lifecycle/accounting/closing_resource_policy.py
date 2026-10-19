"""Pure closing-policy candidate arithmetic; journal and authority checks stay separate."""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any, NoReturn
from typing import cast as _validated_cast

from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest
from agent_lifecycle.contracts.closing_resource_schemas import (
    evaluate_nested_claim_headroom,
    validate_closing_operation_binding,
    validate_limit_proposal,
)
from agent_lifecycle.contracts.closing_window_schemas import validate_window_request
from agent_lifecycle.contracts.errors import LifecycleError

from .contracts import MAX_INTEGER, BudgetPolicy, EvidenceRef, JournalUnavailable, Operation, digest, uint

_PROPOSAL_FIELDS = frozenset(
    {
        "schemaVersion",
        "bindingId",
        "runId",
        "budgetScopeId",
        "journalIdentity",
        "closingWindowId",
        "predecessorWindowId",
        "inventoryDigest",
        "unit",
        "expectedJournalRevision",
        "expectedPolicy",
        "nextPolicy",
        "openingCoverageDigest",
        "activeReservationSetDigest",
        "protectionSetDigest",
        "priorViolationSetDigest",
        "requiredGuards",
        "limits",
        "protectionAllocations",
    }
)
_ANCHOR_FIELDS = frozenset(
    {
        "journalRevision",
        "openingCoverageDigest",
        "activeReservationSetDigest",
        "protectionSetDigest",
        "priorViolationSetDigest",
        "spent",
        "reservations",
        "protected",
        "violationsByOwner",
    }
)
_INVENTORY_FIELDS = frozenset(
    {
        "schemaVersion",
        "bindingId",
        "runId",
        "journalIdentity",
        "budgetScopeId",
        "unit",
        "taskIds",
        "requiredGuardBindings",
        "operationRoutePolicyDigest",
        "configurationDigest",
        "inventoryProducerQualificationRef",
    }
)
_GUARD_FIELDS = frozenset(
    {
        "guardId",
        "scope",
        "metric",
        "unitDefinitionDigest",
        "policyDigest",
        "limit",
        "consumerId",
        "consumerContractDigest",
        "disposition",
    }
)


def _claim_owner_key(owner: dict) -> str:
    if type(owner) is not dict or set(owner) != {"scopeKind", "taskId"}:
        _invalid("Claim owner is malformed")
    if owner == {"scopeKind": "RUN", "taskId": None}:
        return ""
    if owner["scopeKind"] == "TASK" and type(owner["taskId"]) is str and owner["taskId"]:
        return owner["taskId"]
    _invalid("Claim owner is malformed")


def _claim_frame(row: dict) -> dict:
    return {
        "cumulativeSpent": row["currentCumulativeSpent"],
        "activeReservations": row["allActiveReservations"],
        "protectedCloseout": row["globalProtected"],
        "windowSpent": row["windowSpent"],
        "windowReservations": row["windowActiveReservations"],
        "windowProtectedCloseout": row["windowProtected"],
    }


def classify_current_claim_data(selected: dict, sidecar: dict) -> dict:
    """Classify verified SQL replay data; never authorize the financial claim."""
    validate_closing_operation_binding(sidecar)
    if (
        type(selected) is not dict
        or type(selected.get("proposal")) is not dict
        or (type(selected.get("balances")) is not list or type(selected.get("storedOperation")) is not dict)
    ):
        _invalid("Current claim data is incomplete")
    proposal, balances, stored = selected["proposal"], selected["balances"], selected["storedOperation"]
    operation = _validated_cast(Operation, selected.get("operation"))
    try:
        original_binding = asdict(operation)
        if (
            proposal["bindingId"] != sidecar["bindingId"]
            or proposal["runId"] != sidecar["runId"]
            or proposal["budgetScopeId"] != sidecar["budgetScopeId"]
            or proposal["closingWindowId"] != sidecar["closingWindowId"]
            or proposal["unit"] != sidecar["unit"]
            or operation.operation_id != sidecar["operationId"]
            or operation.binding_digest != sidecar["nativeOperationDigest"]
            or operation.upper_bound_tokens != sidecar["upperBound"]
            or _claim_owner_key(sidecar["owner"]) != (operation.task_id or "")
            or stored["digest"] != operation.binding_digest
            or stored["binding"] != original_binding
        ):
            _invalid("Claim operation differs from immutable membership")
        limits = {_claim_owner_key(row["scope"]): validate_limit_proposal(row) for row in proposal["limits"]}
        rows = {_claim_owner_key(row["scope"]): row for row in balances}
        if (
            len(limits) != len(proposal["limits"])
            or len(rows) != len(balances)
            or (set(limits) != set(rows) or "" not in rows)
        ):
            _invalid("Claim proposal and balance owner inventories differ")
        for owner, row in rows.items():
            limit = limits[owner]
            if (
                row["schemaVersion"] != "agent-closing-resource-balance.v1"
                or row["runId"] != sidecar["runId"]
                or row["budgetScopeId"] != sidecar["budgetScopeId"]
                or row["closingWindowId"] != sidecar["closingWindowId"]
                or row["unit"] != sidecar["unit"]
                or row["journalRevision"] != selected["journalRevision"]
                or row["spentAtActivation"] != limit["knownSpentAtAnchor"]
                or row["cumulativeCeiling"] != limit["prospectiveCumulativeCeiling"]
                or row["windowAllowance"] != limit["approvedAdditional"]
                or row["priorViolationsDigest"] != limit["priorViolationSetDigest"]
            ):
                _invalid("Claim balance differs from persisted proposal")
        if (
            stored["state"] != "RESERVED"
            or stored["claim_id"] is not None
            or (stored["reservation"] != sidecar["upperBound"])
        ):
            return {
                "schemaVersion": "agent-closing-current-claim-data.v1",
                "disposition": "REFUSED",
                "reason": "OPERATION_NOT_UNCLAIMED_RESERVED",
                "operationReservationDataMatched": False,
                "financialAdmission": False,
                "nativePermissionGranted": False,
            }
        if any(row["qualification"] != "QUALIFIED" for row in rows.values()):
            return {
                "schemaVersion": "agent-closing-current-claim-data.v1",
                "disposition": "REFUSED",
                "reason": "BALANCES_NOT_QUALIFIED",
                "operationReservationDataMatched": True,
                "financialAdmission": False,
                "nativePermissionGranted": False,
            }
        task_id = operation.task_id
        headroom = evaluate_nested_claim_headroom(
            limits[""],
            _claim_frame(rows[""]),
            task_id,
            limits[task_id] if task_id is not None else None,
            _claim_frame(rows[task_id]) if task_id is not None else None,
            sidecar["upperBound"],
        )
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise LifecycleError("closing-resource-invalid", "Current claim data is malformed") from exc
    return {
        "schemaVersion": "agent-closing-current-claim-data.v1",
        "disposition": headroom["disposition"],
        "operationReservationDataMatched": True,
        "proposalBalanceDataMatched": True,
        "headroom": headroom,
        "financialAdmission": False,
        "nativePermissionGranted": False,
    }


def _invalid(detail: str) -> NoReturn:
    raise LifecycleError("closing-resource-invalid", detail)


def _bounded(value: Any, label: str) -> int:
    try:
        return uint(value)
    except ValueError as exc:
        raise LifecycleError("closing-resource-invalid", f"{label} is not a known bounded integer") from exc


def _owner_key(owner: Any) -> str:
    if type(owner) is not dict or set(owner) != {"scopeKind", "taskId"}:
        _invalid("Owner is malformed")
    if owner == {"scopeKind": "RUN", "taskId": None}:
        return ""
    if owner["scopeKind"] == "TASK" and type(owner["taskId"]) is str and 1 <= len(owner["taskId"]) <= 256:
        return owner["taskId"]
    _invalid("Owner kind or task attribution is invalid")


def _digest(value: Any, label: str) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        _invalid(f"{label} is not a digest")
    return value


def _checked_anchor(anchor: Any, proposal: dict, owners: set[str]) -> dict:
    if type(anchor) is not dict or set(anchor) != _ANCHOR_FIELDS:
        _invalid("Complete immutable source anchor is required")
    if type(anchor["journalRevision"]) is not int or not 0 <= anchor["journalRevision"] <= (1 << 53) - 1:
        _invalid("Anchor revision is invalid")
    if anchor["journalRevision"] != proposal["expectedJournalRevision"]:
        _invalid("Proposal journal revision differs from source anchor")
    for field in (
        "openingCoverageDigest",
        "activeReservationSetDigest",
        "protectionSetDigest",
        "priorViolationSetDigest",
    ):
        if _digest(anchor[field], field) != proposal[field]:
            _invalid(f"{field} differs from source anchor")
    for field in ("spent", "reservations", "protected", "violationsByOwner"):
        values = anchor[field]
        if type(values) is not dict or set(values) != owners:
            _invalid(f"{field} does not cover the exact owner inventory")
        for value in values.values():
            if field == "violationsByOwner":
                _digest(value, field)
            else:
                _bounded(value, field)
    if anchor["spent"][""] < sum(anchor["spent"][key] for key in owners - {""}):
        _invalid("Run cumulative spend is smaller than its task projections")
    if anchor["reservations"][""] < sum(anchor["reservations"][key] for key in owners - {""}):
        _invalid("Run reservations are smaller than their task projections")
    return anchor


def _protection_effects(proposal: dict, anchor: dict, limits: dict[str, dict]) -> tuple[list[dict], dict[str, int]]:
    rows = proposal["protectionAllocations"]
    if type(rows) is not list or len(rows) != len(limits):
        _invalid("Every owner needs exactly one protection row")
    effects, global_pool = [], {}
    for row in rows:
        if type(row) is not dict or set(row) != {
            "owner",
            "priorUnspent",
            "retainedAssignedToWindow",
            "addedForWindow",
            "retainedOutsideWindow",
        }:
            _invalid("Protection proposal is malformed")
        owner = _owner_key(row["owner"])
        if owner not in limits or owner in global_pool:
            _invalid("Protection owner is unknown or repeated")
        prior, retained, added, outside = (
            _bounded(row[name], name)
            for name in ("priorUnspent", "retainedAssignedToWindow", "addedForWindow", "retainedOutsideWindow")
        )
        if prior != anchor["protected"][owner] or retained > prior or outside != prior - retained:
            _invalid("Protection allocation differs from the immutable owner pool")
        if prior + added > MAX_INTEGER or retained + added > MAX_INTEGER:
            _invalid("Protection allocation overflows")
        limit = limits[owner]
        if limit["participation"] == "RETAIN_ONLY" and (retained or added):
            _invalid("Retained task cannot gain window protection")
        if limit["participation"] == "CLOSING_ENABLED" and retained + added > limit["approvedAdditional"]:
            _invalid("Window protection exceeds signed addition")
        global_pool[owner] = prior + added
        effects.append(
            {
                "owner": row["owner"],
                "priorUnspent": prior,
                "newGlobalUnspent": prior + added,
                "newWindowUnspent": retained + added,
                "retainedOutsideWindow": outside,
            }
        )
    return effects, global_pool


def _limit_effects(
    proposal: dict, anchor: dict, before: BudgetPolicy, owners: set[str]
) -> tuple[list[dict], dict[str, dict]]:
    rows = proposal["limits"]
    if type(rows) is not list or len(rows) != len(owners):
        _invalid("Every owner needs exactly one limit row")
    effects, selected = [], {}
    for row in rows:
        validate_limit_proposal(row)
        owner = _owner_key(row["scope"])
        if owner not in owners or owner in selected:
            _invalid("Limit owner is unknown or repeated")
        old = (
            {"kind": "FINITE", "value": before.run_cap}
            if owner == ""
            else (
                {"kind": "FINITE", "value": before.task_caps[owner]}
                if owner in before.task_caps
                else {"kind": "ABSENT"}
            )
        )
        if row["oldCap"] != old or row["knownSpentAtAnchor"] != anchor["spent"][owner]:
            _invalid("Signed old cap or spend differs from native source anchor")
        if row["priorViolationSetDigest"] != anchor["violationsByOwner"][owner]:
            _invalid("Owner violation history differs from source anchor")
        if owner == "" and row["participation"] != "CLOSING_ENABLED":
            _invalid("Run owner must be enabled")
        if row["participation"] == "RETAIN_ONLY":
            resulting, old_excess = (
                old,
                None if old["kind"] == "ABSENT" else max(0, anchor["spent"][owner] - old["value"]),
            )
        else:
            value = (
                row["prospectiveCumulativeCeiling"]
                if row["capDisposition"] == "SUPERSEDE_BY_CLOSING_POLICY"
                else old["value"]
            )
            resulting, old_excess = {"kind": "FINITE", "value": value}, max(0, anchor["spent"][owner] - old["value"])
        effects.append(
            {
                "scope": row["scope"],
                "participation": row["participation"],
                "oldCap": old,
                "spentAtActivation": anchor["spent"][owner],
                "approvedAdditional": row["approvedAdditional"],
                "cumulativeCeiling": row["prospectiveCumulativeCeiling"],
                "resultingCoreCap": resulting,
                "oldExcess": old_excess,
                "capDisposition": row["capDisposition"],
            }
        )
        selected[owner] = row
    return effects, selected


def _validated_resource_inventory_owners(inventory: dict, proposal: dict) -> set[str]:
    if (
        type(inventory) is not dict
        or set(inventory) != _INVENTORY_FIELDS
        or type(proposal) is not dict
        or set(proposal) != _PROPOSAL_FIELDS
    ):
        _invalid("Inventory or proposal is incomplete")
    if len(canonical_bytes(inventory)) > 1_048_576 or len(canonical_bytes(proposal)) > 1_048_576:
        _invalid("Resource wire document exceeds one MiB")
    if proposal["schemaVersion"] != "agent-closing-resource-proposal.v1":
        _invalid("Unsupported resource proposal")
    tasks = inventory.get("taskIds")
    if (
        type(tasks) is not list
        or len(tasks) > 4096
        or any(type(t) is not str or not 1 <= len(t) <= 256 for t in tasks)
        or len(set(tasks)) != len(tasks)
    ):
        _invalid("Inventory task IDs are incomplete or repeated")
    owners = {"", *tasks}
    if not 1 <= len(owners) <= 4097:
        _invalid("Unsupported owner count")
    for field in ("bindingId", "runId", "budgetScopeId", "journalIdentity"):
        if (
            type(inventory.get(field)) is not str
            or not 1 <= len(inventory[field]) <= 256
            or proposal[field] != inventory[field]
        ):
            _invalid(f"{field} differs from pinned inventory")
    if (
        type(proposal["closingWindowId"]) is not str
        or not 1 <= len(proposal["closingWindowId"]) <= 256
        or (
            proposal["predecessorWindowId"] is not None
            and (
                type(proposal["predecessorWindowId"]) is not str or not 1 <= len(proposal["predecessorWindowId"]) <= 256
            )
        )
    ):
        _invalid("Window identity is malformed")
    if inventory.get("schemaVersion") != "agent-closing-resource-inventory.v1" or proposal[
        "inventoryDigest"
    ] != canonical_digest(inventory):
        _invalid("Inventory identity differs")
    unit = inventory.get("unit")
    if (
        type(unit) is not dict
        or set(unit) != {"metric", "unitDefinitionId", "definitionDigest", "sourceQualificationDigest"}
        or unit["metric"] != "reportedTokens"
        or proposal["unit"] != unit
    ):
        _invalid("Unsupported or mismatched financial unit")
    if type(unit["unitDefinitionId"]) is not str or not 1 <= len(unit["unitDefinitionId"]) <= 256:
        _invalid("Unit definition identity is malformed")
    _digest(unit["definitionDigest"], "unit definition")
    _digest(unit["sourceQualificationDigest"], "source qualification")
    for field in ("operationRoutePolicyDigest", "configurationDigest"):
        _digest(inventory[field], field)
    qualification = inventory["inventoryProducerQualificationRef"]
    if (
        type(qualification) is not dict
        or set(qualification) != {"path", "sha256", "bytes"}
        or type(qualification["path"]) is not str
        or not qualification["path"]
    ):
        _invalid("Inventory producer qualification reference is malformed")
    _digest(qualification["sha256"], "inventory producer qualification")
    _bounded(qualification["bytes"], "inventory producer qualification bytes")
    guards = inventory["requiredGuardBindings"]
    if type(guards) is not list or len(guards) > 256 or proposal["requiredGuards"] != guards:
        _invalid("Required guard inventory differs")
    guard_ids = set()
    for guard in guards:
        if type(guard) is not dict or set(guard) != _GUARD_FIELDS or guard["disposition"] != "RETAIN_UNCHANGED":
            _invalid("Required guard is malformed")
        guard_id = guard["guardId"]
        if type(guard_id) is not str or not 1 <= len(guard_id) <= 256 or guard_id in guard_ids:
            _invalid("Required guard identity is missing or repeated")
        guard_ids.add(guard_id)
        if _owner_key(guard["scope"]) not in owners:
            _invalid("Required guard owner is unknown")
        for field in ("unitDefinitionDigest", "policyDigest", "consumerContractDigest"):
            _digest(guard[field], field)
        _bounded(guard["limit"], "guard limit")
        for field in ("metric", "consumerId"):
            if type(guard[field]) is not str or not 1 <= len(guard[field]) <= 256:
                _invalid(f"Guard {field} is malformed")
    return owners


def derive_policy_candidate_data(
    inventory: dict,
    proposal: dict,
    before_policy: BudgetPolicy,
    anchor: dict,
) -> dict:
    """Derive reviewable candidate bytes; source qualification and atomic apply remain mandatory."""
    owners = _validated_resource_inventory_owners(inventory, proposal)
    if type(proposal["nextPolicy"]) is not dict or set(proposal["nextPolicy"]) != {"policyId", "revision"}:
        _invalid("Next policy identity is malformed")
    before_policy.__post_init__()
    before_identity = {
        "policyId": before_policy.policy_id,
        "revision": before_policy.revision,
        "policyDigest": digest(asdict(before_policy)),
    }
    next_policy = proposal["nextPolicy"]
    if type(next_policy["revision"]) is not int or not 0 <= next_policy["revision"] <= (1 << 53) - 1:
        _invalid("Next policy revision is invalid")
    if proposal["expectedPolicy"] != before_identity or next_policy != {
        "policyId": before_policy.policy_id,
        "revision": before_policy.revision + 1,
    }:
        _invalid("Policy predecessor or successor differs")
    selected_anchor = _checked_anchor(anchor, proposal, owners)
    effects, limits = _limit_effects(proposal, selected_anchor, before_policy, owners)
    protection_effects, global_pool = _protection_effects(proposal, selected_anchor, limits)
    run = limits[""]
    after_global = sum(global_pool.values())
    window_protected = sum(row["newWindowUnspent"] for row in protection_effects)
    if window_protected > run["approvedAdditional"]:
        _invalid("Run window protection exceeds signed addition")
    if (
        after_global > MAX_INTEGER
        or selected_anchor["spent"][""] + selected_anchor["reservations"][""] + after_global
        > run["prospectiveCumulativeCeiling"]
    ):
        _invalid("Run cumulative headroom cannot hold existing commitments")
    for owner, row in limits.items():
        if row["participation"] != "CLOSING_ENABLED":
            continue
        total = (
            selected_anchor["spent"][owner]
            + selected_anchor["reservations"][owner]
            + (after_global if owner == "" else global_pool[owner])
        )
        if total > row["prospectiveCumulativeCeiling"] or (
            row["capDisposition"] == "RETAIN_BINDING" and total > row["oldCap"]["value"]
        ):
            _invalid("Enabled owner has insufficient cumulative headroom")
    proposal_digest = canonical_digest(proposal)
    task_caps = dict(before_policy.task_caps)
    for owner, row in limits.items():
        if owner and row["participation"] == "CLOSING_ENABLED":
            task_caps[owner] = next(
                effect["resultingCoreCap"]["value"] for effect in effects if _owner_key(effect["scope"]) == owner
            )
    protected = dict(before_policy.protected_closeout)
    for owner, amount in global_pool.items():
        if amount or owner in protected:
            protected[owner] = amount
        else:
            protected.pop(owner, None)
    run_effect = next(effect for effect in effects if _owner_key(effect["scope"]) == "")
    try:
        after = BudgetPolicy(
            before_policy.policy_id,
            next_policy["revision"],
            run_effect["resultingCoreCap"]["value"],
            task_caps,
            protected,
            EvidenceRef("urn:alk:closing-resource-proposal:" + proposal_digest, proposal_digest),
        )
    except ValueError as exc:
        raise LifecycleError("closing-resource-invalid", "Native after-policy is not representable") from exc
    candidate = {
        "schemaVersion": "agent-closing-resource-candidate.v1",
        "proposalDigest": proposal_digest,
        "inventoryDigest": proposal["inventoryDigest"],
        **{
            field: proposal[field]
            for field in (
                "bindingId",
                "runId",
                "budgetScopeId",
                "journalIdentity",
                "closingWindowId",
                "expectedJournalRevision",
            )
        },
        "beforePolicy": before_identity,
        "afterPolicy": {"policyId": after.policy_id, "revision": after.revision, "policyDigest": digest(asdict(after))},
        "limits": effects,
        "protectionAllocations": protection_effects,
        "preservedReservationSetDigest": proposal["activeReservationSetDigest"],
        "preservedViolationSetDigest": proposal["priorViolationSetDigest"],
        "retainedGuardSetDigest": canonical_digest(proposal["requiredGuards"]),
    }
    if len(canonical_bytes(candidate)) > 1_048_576:
        _invalid("Derived resource candidate exceeds one MiB")
    return {
        "status": "DATA_CANDIDATE",
        "candidate": candidate,
        "candidateDigest": canonical_digest(candidate),
        "nativeAfterPolicy": asdict(after),
        "sourceAnchorQualified": False,
        "nativePolicyPersisted": False,
        "financialAdmission": False,
        "requiresQualifiedSourceAndAtomicApply": True,
    }


def _activation_frames(frames: Any, proposal: dict, candidate: dict, anchor: dict) -> None:
    """Compare separately selected local frame data, without claiming SQL qualification."""
    fields = {
        "scope",
        "unit",
        "closingWindowId",
        "beforePolicy",
        "journalRevision",
        "cumulativeSpent",
        "activeReservations",
        "oldCap",
        "currentProtection",
        "reservationSetDigest",
        "violationSetDigest",
        "guardSetDigest",
        "cumulativeCeiling",
        "approvedAdditional",
        "newGlobalUnspent",
        "newWindowUnspent",
        "retainedOutsideWindow",
        "windowSpent",
        "windowReservations",
        "operationUpperBound",
    }
    limits = {_owner_key(row["scope"]): row for row in candidate["limits"]}
    protection = {_owner_key(row["owner"]): row for row in candidate["protectionAllocations"]}
    if type(frames) is not list or len(frames) != len(limits):
        _invalid("Activation requires the complete original owner frame set")
    seen = set()
    for frame in frames:
        if type(frame) is not dict or set(frame) != fields:
            _invalid("Activation frame is not the closed local data projection")
        owner = _owner_key(frame["scope"])
        if owner not in limits or owner in seen:
            _invalid("Activation frame owner is missing, unknown or duplicated")
        seen.add(owner)
        limit, pool = limits[owner], protection[owner]
        expected = {
            "scope": limit["scope"],
            "unit": proposal["unit"],
            "closingWindowId": proposal["closingWindowId"],
            "beforePolicy": candidate["beforePolicy"],
            "journalRevision": anchor["journalRevision"],
            "cumulativeSpent": anchor["spent"][owner],
            "activeReservations": anchor["reservations"][owner],
            "oldCap": limit["oldCap"],
            "currentProtection": anchor["protected"][owner],
            "reservationSetDigest": candidate["preservedReservationSetDigest"],
            "violationSetDigest": candidate["preservedViolationSetDigest"],
            "guardSetDigest": candidate["retainedGuardSetDigest"],
            **{key: limit[key] for key in ("cumulativeCeiling", "approvedAdditional")},
            **{key: pool[key] for key in ("newGlobalUnspent", "newWindowUnspent", "retainedOutsideWindow")},
            "windowSpent": 0,
            "windowReservations": 0,
            "operationUpperBound": 0,
        }
        if canonical_bytes(frame) != canonical_bytes(expected):
            _invalid("Activation current or projected frame differs from the original anchor/candidate")


def evaluate_activation_resource_binding(
    request: dict,
    inventory: dict,
    proposal: dict,
    candidate: dict,
    before_policy: BudgetPolicy,
    anchor: dict,
    current_frames: list,
) -> dict:
    """Join validated request and recomputed candidate with independent local frame data."""
    try:
        validate_window_request(request)
        if type(before_policy) is not BudgetPolicy or type(candidate) is not dict:
            _invalid("Activation policy or candidate type is invalid")
        derived = derive_policy_candidate_data(inventory, proposal, before_policy, anchor)
        if canonical_bytes(candidate) != canonical_bytes(derived["candidate"]):
            _invalid("Activation candidate differs from full recomputation")
        if (
            request["resourceApprovalDigest"] != canonical_digest(proposal)
            or request["policyEffectCandidateDigest"] != derived["candidateDigest"]
        ):
            _invalid("Activation request proposal/candidate digest differs")
        for key in ("bindingId", "runId", "budgetScopeId", "journalIdentity"):
            if request["scope"][key] != inventory[key]:
                _invalid(f"Activation request {key} differs from original inventory")
        for key in ("closingWindowId", "predecessorWindowId"):
            if request[key] != proposal[key]:
                _invalid(f"Activation request {key} differs from proposal")
        if request["expectedAccountingRevision"] != proposal["expectedJournalRevision"]:
            _invalid("Activation request journal revision differs")
        _activation_frames(current_frames, proposal, candidate, anchor)
    except (LifecycleError, TypeError, ValueError, KeyError) as exc:
        raise LifecycleError("activation-resource-binding-invalid", str(exc)) from exc
    return {
        "disposition": "DATA_CANDIDATE",
        "candidateDigest": derived["candidateDigest"],
        "dataBindingMatched": True,
        "sourceAnchorQualified": False,
        "nativePolicyPersisted": False,
        "nativeActivationGranted": False,
        "nativePermissionGranted": False,
        "financialAdmission": False,
        "nonceConsumed": False,
        "dispatchAuthorized": False,
    }


def _native_policy(data: object) -> BudgetPolicy:
    """Decode exact replay bytes, without treating a digest as a policy."""
    if not isinstance(data, dict) or set(data) != {
        "policy_id",
        "revision",
        "run_cap",
        "task_caps",
        "protected_closeout",
        "authorization",
    }:
        raise JournalUnavailable("Malformed closing native policy")
    authorization = data["authorization"]
    if not isinstance(authorization, dict) or set(authorization) != {"ref", "digest"}:
        raise JournalUnavailable("Malformed closing policy authorization reference")
    if not isinstance(data["task_caps"], dict) or not isinstance(data["protected_closeout"], dict):
        raise JournalUnavailable("Malformed closing policy owner caps")
    try:
        policy = BudgetPolicy(
            data["policy_id"],
            data["revision"],
            data["run_cap"],
            data["task_caps"],
            data["protected_closeout"],
            EvidenceRef(**authorization),
        )
        if asdict(policy) != data:
            raise ValueError("Native policy bytes changed during decoding")
    except (AttributeError, TypeError, ValueError, UnicodeError) as exc:
        raise JournalUnavailable("Invalid closing native policy") from exc
    return policy


def _apply_closing_policy(state: dict, payload: dict, revision: int | None) -> dict:
    """Replay an already admitted immutable policy event; this grants no authority."""
    if not isinstance(payload, dict) or set(payload) != {
        "effect",
        "candidate",
        "proposal",
        "nativeBeforePolicy",
        "nativeAfterPolicy",
    }:
        raise JournalUnavailable("Closing policy event is incomplete")
    effect, candidate, proposal = (payload[key] for key in ("effect", "candidate", "proposal"))
    if not all(isinstance(value, dict) for value in (effect, candidate, proposal)):
        raise JournalUnavailable("Closing policy event components are malformed")
    if set(effect) != {
        "schemaVersion",
        "candidateDigest",
        "proposalDigest",
        "runId",
        "budgetScopeId",
        "closingWindowId",
        "activationOperationId",
        "authorityDecisionDigest",
        "grantDigest",
        "beforeJournalRevision",
        "afterJournalRevision",
        "beforePolicy",
        "afterPolicy",
    } or any(
        not isinstance(effect[key], str) or not effect[key]
        for key in ("activationOperationId", "authorityDecisionDigest", "grantDigest")
    ):
        raise JournalUnavailable("Closing policy effect is incomplete")
    before = _native_policy(payload["nativeBeforePolicy"])
    after = _native_policy(payload["nativeAfterPolicy"])
    if not isinstance(state.get("scope"), dict):
        raise JournalUnavailable("Closing policy scope is malformed")
    before_identity = {
        "policyId": before.policy_id,
        "revision": before.revision,
        "policyDigest": digest(asdict(before)),
    }
    after_identity = {
        "policyId": after.policy_id,
        "revision": after.revision,
        "policyDigest": digest(asdict(after)),
    }
    expected_revision = effect.get("beforeJournalRevision")
    if (
        state.get("policy") != asdict(before)
        or effect.get("schemaVersion") != "agent-closing-resource-effect.v1"
        or candidate.get("schemaVersion") != "agent-closing-resource-candidate.v1"
        or proposal.get("schemaVersion") != "agent-closing-resource-proposal.v1"
        or effect.get("beforePolicy") != before_identity
        or candidate.get("beforePolicy") != before_identity
        or proposal.get("expectedPolicy") != before_identity
        or effect.get("afterPolicy") != after_identity
        or candidate.get("afterPolicy") != after_identity
        or proposal.get("nextPolicy") != {"policyId": after.policy_id, "revision": after.revision}
        or after.policy_id != before.policy_id
        or after.revision != before.revision + 1
        or after.authorization != EvidenceRef("urn:alk:closing-resource-proposal:" + digest(proposal), digest(proposal))
        or effect.get("proposalDigest") != digest(proposal)
        or effect.get("candidateDigest") != digest(candidate)
        or candidate.get("proposalDigest") != digest(proposal)
        or candidate.get("inventoryDigest") != proposal.get("inventoryDigest")
        or type(expected_revision) is not int
        or expected_revision < 0
        or proposal.get("expectedJournalRevision") != expected_revision
        or candidate.get("expectedJournalRevision") != expected_revision
        or effect.get("afterJournalRevision") != expected_revision + 1
        or (revision is not None and revision != expected_revision)
        or state.get("scope", {}).get("run_id") != effect.get("runId")
        or state.get("scope", {}).get("budget_scope_id") != effect.get("budgetScopeId")
        or state.get("gate") == "CLOSED"
        or any(
            effect.get(key) != candidate.get(key) or effect.get(key) != proposal.get(key)
            for key in ("runId", "budgetScopeId", "closingWindowId")
        )
        or candidate.get("bindingId") != proposal.get("bindingId")
        or candidate.get("journalIdentity") != proposal.get("journalIdentity")
        or candidate.get("preservedReservationSetDigest") != proposal.get("activeReservationSetDigest")
        or candidate.get("preservedViolationSetDigest") != proposal.get("priorViolationSetDigest")
        or candidate.get("retainedGuardSetDigest") != digest(proposal.get("requiredGuards"))
    ):
        raise JournalUnavailable("Closing policy event does not join current native facts")
    state["policy"] = asdict(after)
    state["protected"] = dict(after.protected_closeout)
    return state


__all__ = ["derive_policy_candidate_data", "evaluate_activation_resource_binding"]

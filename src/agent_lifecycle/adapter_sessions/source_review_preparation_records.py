"""Owned source review preparation records helpers."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import sys
import time
from datetime import UTC, datetime, timedelta
from datetime import timezone as timezone
from pathlib import Path
from typing import Any
from typing import cast as _validated_cast

from agent_lifecycle.accounting.declared_ledger import read_coordinator_cost_head
from agent_lifecycle.accounting.declared_ledger_legacy import (
    _R11_REVIEW_ROOT,
    _r11_review_private,
    _r11_worker_directory,
    _r11_worker_sources,
)
from agent_lifecycle.accounting.declared_ledger_records import _r11_transport_binding, _require
from agent_lifecycle.adapter_sessions.attempt_authority import _IDENTITY, _intent, verify_attempt_reservation
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _R11_ENTRYPOINT_PATH,
    _R11_FIXED_WORKER,
    _R11_REQUEST_CAP,
    _r11_fresh_deadline,
    _r11_review_directory,
    _r11_role_authority,
    _r11_role_original_deadline,
    _r11_thread_preparation_basis,
    collect_source_review_qualified_evidence,
    read_source_review_composite,
)
from agent_lifecycle.adapter_sessions.source_review_history import (
    _r11_review_cost_basis,
    _r11_role_operation_start,
    read_source_review_catalog,
    read_source_review_cost,
    read_source_review_opening_origin,
    read_source_review_request,
)
from agent_lifecycle.adapter_sessions.source_review_shards import (
    _r11_cost_before_start,
    _r11_role_send_basis,
    read_source_review_envelope_fit,
)
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.authority_io import normalize_authority_path, read_authority_bytes
from agent_lifecycle.contracts.bounded_json import load_bounded_json as _r11_json
from agent_lifecycle.contracts.bounded_json import matches_closed_schema as _r11_role_schema_matches


def _r11_role_thread_preparation_basis(root: Path, review_id: str, role_id: str, timeout: int) -> dict[str, Any]:
    """Reconstruct metadata input from funded ancestors; never attest a thread."""
    from .codex_input_diagnostics import _file_sha

    _require(
        isinstance(role_id, str)
        and re.fullmatch(r"shared-01|source-(0[1-9]|[12][0-9]|3[0-2])", role_id) is not None
        and type(timeout) is int
        and 1 <= timeout <= 120,
        "r11-role-metadata-input",
        "one funded role metadata operation with bounded timeout required",
    )
    role_id = _validated_cast(str, role_id)
    timeout = _validated_cast(int, timeout)
    operation = _r11_role_operation_start(root, review_id, role_id)
    cost = read_source_review_cost(root, review_id=review_id, role_delivery=True)
    fit = read_source_review_envelope_fit(root, review_id=review_id)
    catalog = read_source_review_catalog(root, review_id=review_id)
    binary = Path(catalog["binaryPath"])
    _require(
        root.resolve(strict=True) == root
        and _R11_ENTRYPOINT_PATH.resolve(strict=True) == root / _R11_FIXED_WORKER
        and cost.get("fundingAdmitted") is True
        and cost.get("rolePrefixesAnchored") is True
        and fit["completeEnvelopeFit"] is True
        and fit["catalogEvidenceSha256"] == catalog["evidenceSha256"]
        and binary.is_absolute()
        and binary.name == "codex"
        and binary.resolve(strict=True) == binary
        and binary.is_file()
        and os.access(binary, os.X_OK)
        and _file_sha(binary) == catalog["selected"]["binarySha256"],
        "r11-role-metadata-basis",
        "current fixed source, complete envelope, funded prefix or selected binary differs",
    )
    binding = {
        "operationId": operation["value"]["operationId"],
        "shardId": "metadata-" + role_id,
        "threadId": "PREPARATION_ONLY",
        "binarySha256": catalog["selected"]["binarySha256"],
        "transportSourceSha256": _file_sha(_R11_ENTRYPOINT_PATH),
    }
    _r11_transport_binding(binding)
    # Exclude only the changing current ledger head: immutable batch/roles,
    # actual source snapshot, all template rows and catalog remain pinned.
    fit_identity = {
        key: fit[key]
        for key in (
            "baseSha256",
            "roleInventorySha256",
            "fundingBatchSha256",
            "modelContextWindow",
            "rows",
            "catalogEvidenceSha256",
            "validationSourcesSha256",
        )
    }
    _require(
        all(
            fit_identity[key] == operation["value"][key]
            for key in ("baseSha256", "roleInventorySha256", "fundingBatchSha256")
        )
        and _r11_role_operation_start(root, review_id, role_id) == operation
        and read_source_review_cost(root, review_id=review_id, role_delivery=True) == cost
        and read_source_review_catalog(root, review_id=review_id) == catalog,
        "r11-role-metadata-stale",
        "operation, source, catalog or funding changed while preparing input",
    )
    return {
        "schemaVersion": "alk-r11-thread-preparation-input.v2-role",
        "projectRoot": str(root),
        "reviewId": review_id,
        "roleId": role_id,
        **({"sharedEvidenceSha256": operation["value"]["sharedEvidenceSha256"]} if role_id != "shared-01" else {}),
        "count": 1,
        "timeoutSeconds": timeout,
        "binding": binding,
        "binaryPath": str(binary),
        "model": catalog["selected"]["model"],
        "catalogEvidenceSha256": catalog["evidenceSha256"],
        "operationStartSha256": operation["sha256"],
        "operationDeadlineUtc": operation["value"]["absoluteDeadlineUtc"],
        "operationDeadlineMonotonicNs": operation["value"]["deadlineMonotonicNs"],
        "envelopeFitIdentitySha256": canonical_digest(fit_identity),
        "heldUnknownTokens": cost["declaredUnknownHoldsAtFunding"],
        "modelRequestsAuthorized": 0,
        "retryAuthorized": False,
    }


def _r11_role_metadata_before_start(root: Path, value: dict[str, Any]) -> None:
    operation = _r11_role_operation_start(root, value["reviewId"], value["roleId"])
    cost = read_source_review_cost(root, review_id=value["reviewId"], role_delivery=True)
    basis = _r11_review_cost_basis(root, value["reviewId"], role_delivery=True)
    roles = basis["identity"]["inventory"]["roles"]
    index = len(cost["reservations"])
    _require(
        index < len(roles)
        and roles[index]["roleId"] == value["roleId"]
        and len(cost["settlements"]) == index
        and all(row["worker"]["state"] == "WORKER_PROCESS_FINISHED" for row in cost["settlements"]),
        "r11-role-metadata-order",
        "metadata requires the next funded role after successful predecessors",
    )
    head = read_coordinator_cost_head(root)
    _require(
        head["headSha256"] == cost["fundingOrigin"]["currentHeadSha256"]
        and (
            head["source"].get("schemaVersion") in {"alk-r11-global-role-funding.v1", "alk-r11-global-role-prefix.v1"}
            or Path(head["head"]["sourcePath"]).name == "cost.json"
        )
        and read_source_review_cost(root, review_id=value["reviewId"], role_delivery=True) == cost,
        "r11-role-metadata-stale",
        "global prefix changed or ordinary coordinator window remains open",
    )
    now = datetime.now(UTC)
    mono = time.monotonic_ns()
    start = operation["value"]
    _require(
        operation["sha256"] == value["operationStartSha256"]
        and cost.get("fundingAdmitted") is True
        and cost.get("rolePrefixesAnchored") is True
        and cost["declaredUnknownHoldsAtFunding"] == value["heldUnknownTokens"]
        and value["modelRequestsAuthorized"] == 0
        and value["count"] == 1
        and datetime.fromisoformat(start["startedAtUtc"]) <= now
        and start["startedMonotonicNs"] <= mono
        and value["timeoutSeconds"]
        < min(
            (datetime.fromisoformat(start["absoluteDeadlineUtc"]) - now).total_seconds(),
            (start["deadlineMonotonicNs"] - mono) / 1_000_000_000,
        ),
        "r11-role-metadata-deadline",
        "metadata is retrospective, unfunded or exceeds the original operation deadline",
    )


def _r11_read_thread_preparation_input(root: Path, path: Path) -> dict[str, Any]:
    pending = path.with_suffix(".pending.json")
    _require(
        not pending.exists() and not pending.is_symlink(), "r11-thread-pending", "metadata input publication unfinished"
    )
    raw = _r11_review_private(root, path)
    value = _r11_json(raw, limit=131_072)
    role = value.get("schemaVersion") == "alk-r11-thread-preparation-input.v2-role"
    if role:
        role_id = value.get("roleId")
        _require(
            isinstance(role_id, str)
            and re.fullmatch(r"shared-01|source-(0[1-9]|[12][0-9]|3[0-2])", role_id) is not None,
            "r11-role-metadata-input",
            "exact bounded role required",
        )
        role_id = _validated_cast(str, role_id)
        expected = _r11_review_directory(root, _validated_cast(str, value.get("reviewId"))) / (
            "thread-preparation-" + role_id + ".json"
        )
        basis = _r11_role_thread_preparation_basis(
            root, value["reviewId"], role_id, _validated_cast(int, value.get("timeoutSeconds"))
        )
    else:
        expected = _r11_review_directory(root, _validated_cast(str, value.get("reviewId"))) / "thread-preparation.json"
        _require(
            value.get("schemaVersion") == "alk-r11-thread-preparation-input.v1",
            "r11-thread-admission",
            "fixed metadata schema differs",
        )
        basis = _r11_thread_preparation_basis(
            root,
            value["reviewId"],
            _validated_cast(int, value.get("count")),
            _validated_cast(int, value.get("timeoutSeconds")),
        )
    _require(
        path == expected and raw == canonical_bytes(basis) and _r11_review_private(root, path) == raw,
        "r11-thread-stale",
        "preparation path/source/catalog/operation/full hold changed",
    )
    return basis


def _r11_composite_inventory(root: Path, review_id: str, role_ids: list[str], *, partial: bool = False) -> bytes:
    """Snapshot fixed proof lanes, excluding later collector/fresh-task outputs.

    A refusal records unreadable entries explicitly, never inventing empty proof.
    The bounded canonical inventory is stored in private chunks, not a request.
    """
    _require(
        type(partial) is bool
        and isinstance(role_ids, list)
        and 2 <= len(role_ids) <= 33
        and role_ids == ["shared-01"] + [f"source-{n:02d}" for n in range(1, len(role_ids))],
        "r11-composite-inventory",
        "exact ordered v6 inventory required",
    )
    role_ids = _validated_cast(list[Any], role_ids)
    directory = _r11_review_directory(root, review_id)
    names = [
        "role-base.json",
        "role-inventory.json",
        "role-funding.json",
        "role-envelope-fit.json",
        "role-preparation.json",
        "cost-opening.json",
        "cost-opening-origin.json",
        "role-funding-origin.json",
        "assignment.json",
        "catalog",
        "support",
        "role-requests",
        "role-cost",
        "role-prefix-receipts",
        "role-operations",
    ]
    names += [prefix + role + ".json" for role in role_ids for prefix in ("worker-", "thread-preparation-")]
    pending = [directory / name for name in names]
    pending += [
        root / _R11_REVIEW_ROOT / "shards" / (prefix + role) for role in role_ids for prefix in ("", "metadata-")
    ]
    rows = {}
    visited = 0
    while pending:
        path = pending.pop()
        visited += 1
        _require(visited <= 262144, "r11-composite-inventory-limit", "private inventory entry bound exceeded")
        name = path.relative_to(root).as_posix()
        try:
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                _require(stat.S_IMODE(mode) == 0o700, "r11-composite-inventory", "private directory mode differs")
                children = []
                for child in path.iterdir():
                    children.append(child)
                    _require(
                        visited + len(pending) + len(children) <= 262144,
                        "r11-composite-inventory-limit",
                        "private inventory entry bound exceeded",
                    )
                pending.extend(children)
                continue
            raw = _r11_review_private(root, path)
            rows[name] = {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        except (LifecycleError, OSError) as exc:
            if not partial or getattr(exc, "code", None) == "r11-composite-inventory-limit":
                raise
            rows[name] = {"path": name, "bytes": None, "sha256": None, "unavailable": True}
    raw = canonical_bytes({"files": [rows[name] for name in sorted(rows)]})
    _require(len(raw) <= 67_108_864, "r11-composite-inventory-limit", "private inventory archive bound exceeded")
    return raw


def _r11_composite_schema(root: Path, verified: bool) -> dict[str, Any]:
    _require(type(verified) is bool, "r11-composite-schema", "explicit collector schema kind required")
    authority = _r11_role_authority(root)
    return authority["schemas"]["verifiedComposite" if verified else "refusal"]


def _r11_composite_verified(
    root: Path, review_id: str, *, ledger_head_sha256: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Only this all-role collector closes the eligible historical finding.

    A saved final ledger head may be an ancestor of today's head. All intervening
    appends and the unchanged complete role prefix are independently replayed;
    the saved receipt does not acquire a new financial identity on reread.
    """
    evidence = collect_source_review_qualified_evidence(root, review_id=review_id, role_delivery=True)
    assignment, cost = evidence["assignment"], evidence["cost"]
    roles = assignment["roles"]
    role_ids = [row["roleId"] for row in roles]
    _require(
        evidence["status"] == "SOURCE_ROLE_REVIEW_QUALIFIED"
        and evidence["producerQualified"] is True
        and evidence["catalogFitQualified"] is True
        and evidence["openingProvenanceQualified"] is True
        and evidence["parentVerdict"] == "FAIL"
        and evidence["parentClosureEligible"] is True
        and evidence["eligibleParentFindingIds"] == ["RB-OBSERVER-TIMEOUT-01"]
        and cost["allRolesSettled"] is True
        and cost["fundingAdmitted"] is True
        and cost["rolePrefixesAnchored"] is True
        and cost["costStatus"] == "UNAVAILABLE"
        and cost["actualModelTokens"] is None
        and 2 <= len(roles) == len(evidence["roleEvidence"]) == len(cost["settlements"]) <= 33
        and evidence["assignmentSha256"] == canonical_digest(assignment)
        and evidence["orderedRoleEvidenceSha256"] == canonical_digest(evidence["roleEvidence"]),
        "r11-composite-qualification",
        "complete v6 source/role/parent/settlement proof required",
    )
    for row, role, settlement in zip(roles, evidence["roleEvidence"], cost["settlements"], strict=False):
        _require(
            row["evidenceSha256"] == canonical_digest(role)
            and row["roleId"] == role["roleId"]
            and row["roleKind"] == role["roleKind"]
            and row["binding"] == role["producer"]["binding"]
            and row["settlementSha256"] == canonical_digest(settlement)
            and role["producer"]["producerQualified"] is True
            and role["bodyMatch"]["closedParentFindingIds"] == [],
            "r11-composite-role",
            "ordered realized role evidence differs",
        )
    approvals = [
        {"scope": scope, "roleId": role["roleId"], "roleEvidenceSha256": row["evidenceSha256"]}
        for row, role in zip(roles, evidence["roleEvidence"], strict=False)
        for scope in role["bodyMatch"]["approvedIntegrationScopes"]
    ]
    approvals.sort(key=lambda row: row["scope"])
    _require(
        approvals == evidence["integrationApprovals"]
        and [row["scope"] for row in approvals] == ["COLLECTOR_FIRST_NATIVE", "OBSERVER_TERMINAL"]
        and all(row["roleId"] != "shared-01" for row in approvals),
        "r11-composite-closure",
        "both designated primary approvals required, without role-level closure",
    )
    history = read_coordinator_cost_head(root, ancestor_head_sha256=evidence["openingOrigin"]["coordinatorHeadSha256"])
    final_head = history["headSha256"] if ledger_head_sha256 is None else ledger_head_sha256
    chain = history["ancestryHeadSha256s"]
    steps = cost["fundingOrigin"]["costPrefix"]["steps"]
    _require(
        isinstance(final_head, str)
        and final_head in chain
        and history["headSha256"] == cost["fundingOrigin"]["currentHeadSha256"]
        and len(steps) == 2 * len(roles)
        and all(
            step["headSha256"] in chain and chain.index(final_head) <= chain.index(step["headSha256"]) for step in steps
        ),
        "r11-composite-ledger",
        "final head must include every settled role prefix and valid later appends",
    )
    final_head = _validated_cast(str, final_head)
    anchor = read_coordinator_cost_head(root, ancestor_head_sha256=final_head)
    _require(
        anchor["headSha256"] == history["headSha256"]
        and anchor["ancestor"]["headSha256"] == final_head
        and anchor["ancestor"]["head"]["unknownHolds"] >= cost["declaredUnknownHoldsAtFunding"],
        "r11-composite-ledger",
        "published financial anchor is absent or loses admitted holds",
    )
    inventory = _r11_composite_inventory(root, review_id, role_ids)
    receipt = {
        "schemaVersion": "alk-route-bootstrap-composite.v6-r11",
        "collectorStatus": "VERIFIED",
        "reviewId": review_id,
        **{
            key: assignment[key]
            for key in ("baseSha256", "roleInventorySha256", "fundingBatchSha256", "sharedEvidenceSha256")
        },
        "completedAssignmentSha256": canonical_digest(assignment),
        "orderedRoleEvidenceSha256": canonical_digest(evidence["roleEvidence"]),
        "coverageUnionSha256": evidence["coverageUnionSha256"],
        "callExpansionSha256": evidence["callExpansionSha256"],
        "integrationApprovalsSha256": canonical_digest(approvals),
        "finalLedgerHeadSha256": final_head,
        "parentVerdict": "FAIL",
        "closedParentFindingIds": ["RB-OBSERVER-TIMEOUT-01"],
        "phase": "PRE_WS01",
        "rb11RuntimeStatus": "NOT_RUN",
        "firstNativeBootstrapEligible": False,
        "privateEvidenceInventorySha256": hashlib.sha256(inventory).hexdigest(),
    }
    _require(
        _r11_role_schema_matches(receipt, _r11_composite_schema(root, True)),
        "r11-composite-schema",
        "exact closed v6 composite required",
    )
    # Only independently replayed current financial-head fields vary after an
    # authorized append. All role records and immutable proof remain pinned.
    stable = {key: value for key, value in evidence.items() if key != "cost"}
    stable["roleCost"] = {key: cost[key] for key in ("costChainSha256", "prefixSha256", "reservations", "settlements")}
    proof = {
        "qualificationScope": evidence["qualificationScope"],
        "evidenceSha256": canonical_digest(stable),
        "producerEvidenceSha256": [canonical_digest(row["producer"]) for row in evidence["roleEvidence"]],
        "costChainSha256": cost["costChainSha256"],
        "openingOriginSha256": canonical_digest(evidence["openingOrigin"]),
        "heldUnknownTokens": anchor["ancestor"]["head"]["unknownHolds"],
        "privateInventoryRaw": inventory,
        "hostContextQualified": False,
        "actualModelTokens": None,
        "firstNativeBootstrapEligible": False,
    }
    _require(
        collect_source_review_qualified_evidence(root, review_id=review_id, role_delivery=True) == evidence
        and read_coordinator_cost_head(root, ancestor_head_sha256=evidence["openingOrigin"]["coordinatorHeadSha256"])
        == history
        and read_coordinator_cost_head(root, ancestor_head_sha256=final_head) == anchor
        and _r11_composite_inventory(root, review_id, role_ids) == inventory,
        "r11-composite-stale",
        "earlier roles/private proof or final ledger changed during composition",
    )
    return receipt, proof


def _r11_lead_summary(review_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": "alk-r11-bootstrap-lead.v1",
        "reviewId": review_id,
        "compositeSha256": canonical_digest(receipt),
        "composite": receipt,
        "nativeRuntime": "NOT_RUN",
        "firstNativeBootstrapEligible": False,
    }


def _r11_native_composite(root: Path) -> tuple[str, dict[str, Any]]:
    directory = root / _R11_REVIEW_ROOT
    names = ("independent-audit-origin.json", "independent-audit.json", "receipt.json")
    raw = {name: _r11_review_private(root, directory / name) for name in names}
    origin = _r11_json(raw[names[0]], limit=131_072)
    _require(
        set(origin) == {"schemaVersion", "reviewId", "receiptSha256"}
        and origin["schemaVersion"] == "alk-r11-composite-selector.v1"
        and raw[names[0]] == canonical_bytes(origin),
        "r11-native-selector",
        "exact deterministic composite selector required",
    )
    receipt = read_source_review_composite(root, review_id=origin["reviewId"])
    _require(
        receipt["schemaVersion"] == "alk-route-bootstrap-composite.v6-r11"
        and receipt["collectorStatus"] == "VERIFIED"
        and receipt["firstNativeBootstrapEligible"] is False
        and raw[names[1]] == canonical_bytes(receipt)
        and origin["receiptSha256"] == canonical_digest(receipt)
        and raw["receipt.json"] == canonical_bytes(_r11_lead_summary(origin["reviewId"], receipt))
        and all(_r11_review_private(root, directory / n) == r for n, r in raw.items()),
        "r11-native-composite",
        "installed v6 composite is negative, stale or substituted",
    )
    return origin["reviewId"], receipt


def _r11_native_task(root: Path, intent_path: Path, state_path: Path) -> dict[str, Any]:
    """Bind a still-unconsumed reserved launch to the actual current task state."""
    from .codex_prompt_preparation import CLAIM, ROUTE_ID

    intent, raw = _intent(root, intent_path)
    verify_attempt_reservation(root, intent_path=intent_path)
    state_path = Path(state_path).absolute()
    _require(
        state_path.is_relative_to(root) and ".." not in state_path.parts,
        "r11-native-task",
        "state must be an owned regular file",
    )
    state_raw = read_authority_bytes(state_path, root=root, max_bytes=2_097_152)
    state = _r11_json(state_raw, limit=2_097_152)
    tasks = state.get("tasks")
    _require(isinstance(tasks, list), "r11-native-task", "current task list required")
    tasks = _validated_cast(list[Any], tasks)
    matches = [row for row in tasks if isinstance(row, dict) and row.get("id") == intent["taskId"]]
    _require(
        len(matches) == 1
        and matches[0].get("status") == "RUNNING"
        and type(matches[0].get("attempt")) is int
        and str(matches[0]["attempt"]) == intent["attemptId"]
        and state.get("runId") == intent["runId"]
        and state.get("sourceRevision") == intent["sourceRevision"]
        and intent["routeId"] == ROUTE_ID
        and intent["requestedClaim"] == CLAIM
        and _intent(root, intent_path)[1] == raw
        and read_authority_bytes(state_path, root=root, max_bytes=2_097_152) == state_raw,
        "r11-native-task",
        "current run/task/attempt/route differs from reserved launch",
    )
    return {
        "intentPath": intent_path.relative_to(root).as_posix(),
        "statePath": state_path.relative_to(root).as_posix(),
        "intentSha256": hashlib.sha256(raw).hexdigest(),
        "stateSha256": hashlib.sha256(state_raw).hexdigest(),
        "identity": {key: intent[key] for key in (*_IDENTITY, "binarySha256")},
    }


def _r11_fresh_operation(
    root: Path,
    review_id: str,
    task: dict[str, Any],
    receipt: dict[str, Any],
    binding: dict[str, str],
    timeout: int,
    funding: dict[str, Any],
) -> dict[str, Any]:
    """Require one separately admitted, current metadata-only coordinator window.

    The admission precedes this call and pins the complete reserved task and
    original operation clocks. An ordinary work window or role budget cannot
    authorize a fresh host read. Its full unknown hold is never refunded here.
    """
    head = read_coordinator_cost_head(root, ancestor_head_sha256=receipt["finalLedgerHeadSha256"])
    source = head["source"]
    operation = source.get("freshMetadataOperation")
    keys = {
        "schemaVersion",
        "reviewId",
        "taskSha256",
        "compositeSha256",
        "binding",
        "timeoutSeconds",
        "startedAtUtc",
        "absoluteDeadlineUtc",
        "startedMonotonicNs",
        "deadlineMonotonicNs",
        "modelRequestsAuthorized",
        "retryAuthorized",
    }
    _require(
        source.get("status") == "ADMITTED_PREAPPROVED_BY_USER"
        and Path(head["head"]["sourcePath"]).name == "admission.json"
        and source.get("modelRequestCount") == 0
        and type(source.get("modelRequestCount")) is int
        and isinstance(operation, dict)
        and set(operation) == keys
        and operation["schemaVersion"] == "alk-r11-fresh-operation.v1"
        and operation["reviewId"] == review_id
        and operation["taskSha256"] == canonical_digest(task)
        and operation["compositeSha256"] == canonical_digest(receipt)
        and operation["binding"] == binding
        and type(operation["timeoutSeconds"]) is int
        and operation["timeoutSeconds"] == timeout
        and type(operation["modelRequestsAuthorized"]) is int
        and operation["modelRequestsAuthorized"] == 0
        and operation["retryAuthorized"] is False
        and all(type(operation[k]) is int and operation[k] > 0 for k in ("startedMonotonicNs", "deadlineMonotonicNs"))
        and all(
            _r11_role_schema_matches(operation[k], {"type": "string", "format": "date-time", "maxLength": 40})
            for k in ("startedAtUtc", "absoluteDeadlineUtc")
        ),
        "r11-native-funding",
        "separate exact task/composite-bound metadata admission required",
    )
    operation = _validated_cast(dict[str, Any], operation)
    start, end, batch_start, batch_end = (
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        for v in (
            operation["startedAtUtc"],
            operation["absoluteDeadlineUtc"],
            funding["admittedAtUtc"],
            funding["absoluteDeadlineUtc"],
        )
    )
    _require(
        batch_start <= start < end == min(start + timedelta(seconds=timeout), batch_end)
        and operation["deadlineMonotonicNs"]
        == operation["startedMonotonicNs"] + int((end - start).total_seconds() * 1_000_000_000)
        and head["head"]["unknownHolds"] == source["unknownHoldsIncludingThisWindow"]
        and head["head"]["unknownHolds"] >= funding["admittedUnknownHolds"] + source["tokenCap"],
        "r11-native-funding",
        "metadata resets original deadline, exceeds batch or loses its separate hold",
    )
    value = {
        "metadataOperation": operation,
        "operationDeadlineMonotonicNs": operation["deadlineMonotonicNs"],
        "metadataOperationSha256": canonical_digest(operation),
        "ledgerHeadSha256": head["headSha256"],
        "metadataAdmissionSourceSha256": head["head"]["sourceSha256"],
        "heldUnknownTokens": head["head"]["unknownHolds"],
    }
    _r11_fresh_deadline(value)
    _require(
        read_coordinator_cost_head(root, ancestor_head_sha256=receipt["finalLedgerHeadSha256"]) == head,
        "r11-native-funding",
        "metadata admission or current financial head changed",
    )
    return value


def _r11_fresh_basis(
    root: Path, review_id: str, intent_path: Path, state_path: Path, timeout: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from .codex_input_diagnostics import _file_sha

    _require(
        type(timeout) is int
        and 1 <= timeout <= 120
        and _R11_ENTRYPOINT_PATH.resolve(strict=True) == root / _R11_FIXED_WORKER,
        "r11-native-input",
        "bounded fixed fresh-read worker required",
    )
    timeout = _validated_cast(int, timeout)
    selected_id, receipt = _r11_native_composite(root)
    _require(selected_id == review_id, "r11-native-selector", "selected review differs")
    task = _r11_native_task(root, intent_path, state_path)
    identity = task["identity"]
    authority = _r11_role_authority(root)
    basis = _r11_review_cost_basis(root, review_id, role_delivery=True)
    catalog = read_source_review_catalog(root, review_id=review_id)
    _require(
        identity["lockDigest"] == _file_sha(root / "tasks/release-2-16/plan.lock.json")
        and identity["planDigest"] == authority["planDigest"]
        and identity["binarySha256"] == catalog["selected"]["binarySha256"],
        "r11-native-identity",
        "task, installed plan/lock or selected binary differs",
    )
    attempt_key = canonical_digest({k: identity[k] for k in ("runId", "taskId", "attemptId")})[:56]
    binding = {
        "operationId": "r11-fresh/" + attempt_key,
        "shardId": "fresh-" + attempt_key,
        "threadId": "FIRST_NATIVE_READ_ONLY",
        "binarySha256": identity["binarySha256"],
        "transportSourceSha256": _file_sha(_R11_ENTRYPOINT_PATH),
    }
    operation = _r11_fresh_operation(root, review_id, task, receipt, binding, timeout, basis["identity"]["funding"])
    # These readers independently reopen completed producers, raw requests,
    # private inventory, both approvals and every original cost prefix.
    evidence = collect_source_review_qualified_evidence(root, review_id=review_id, role_delivery=True)
    roles = evidence["assignment"]["roles"]
    role_ids = [r["roleId"] for r in roles]
    _require(
        role_ids == [r["roleId"] for r in basis["identity"]["inventory"]["roles"]]
        and evidence["assignmentSha256"] == receipt["completedAssignmentSha256"]
        and evidence["orderedRoleEvidenceSha256"] == receipt["orderedRoleEvidenceSha256"]
        and len(roles) == len(evidence["roleEvidence"])
        and 2 <= len(roles) <= 33,
        "r11-native-request",
        "exact completed SHARED and all SOURCE roles required",
    )
    requests = []
    threads = []
    for row, proof in zip(roles, evidence["roleEvidence"], strict=False):
        sealed = read_source_review_request(root, review_id=review_id, role_id=row["roleId"], require_reservation=True)
        request = _r11_json(sealed["requestRaw"], limit=_R11_REQUEST_CAP)
        matched = proof["producer"]["transport"]["transport"]["bodyReadMatch"]
        _require(
            sealed["requestRaw"] == canonical_bytes(request) + b"\n"
            and hashlib.sha256(sealed["requestRaw"]).hexdigest() == row["requestSha256"] == proof["requestSha256"]
            and canonical_digest(proof) == row["evidenceSha256"]
            and proof["roleId"] == row["roleId"]
            and matched["roleId"] == row["roleId"]
            and matched["roleKind"] == row["roleKind"]
            and sealed["seal"]["binding"] == row["binding"] == proof["producer"]["binding"]
            and request["params"]["threadId"] == row["binding"]["threadId"] == matched["threadId"]
            and matched["bodySha256"] == proof["bodyMatch"]["bodyRawSha256"]
            and re.fullmatch("[0-9a-f]{64}", matched["stableProjectionSha256"]) is not None,
            "r11-native-request",
            "actual raw request/body/role/thread differs from completed producer",
        )
        requests.append(request)
        threads.append(
            {
                k: matched[k]
                for k in ("roleId", "roleKind", "threadId", "turnId", "bodySha256", "stableProjectionSha256")
            }
        )
        threads[-1]["requestSha256"] = row["requestSha256"]
    _require(
        len({t["threadId"] for t in threads}) == len(threads), "r11-native-request", "review threads are not distinct"
    )
    value = {
        "schemaVersion": "alk-r11-first-native-input.v2-role",
        "projectRoot": str(root),
        "reviewId": review_id,
        "timeoutSeconds": timeout,
        "binding": binding,
        "task": task,
        **operation,
        "binaryPath": catalog["binaryPath"],
        "model": catalog["selected"]["model"],
        "catalogEvidenceSha256": catalog["evidenceSha256"],
        "compositeSha256": canonical_digest(receipt),
        "qualifiedEvidenceSha256": canonical_digest(evidence),
        "threads": threads,
        "modelRequestsAuthorized": 0,
        "retryAuthorized": False,
    }
    _require(
        _r11_native_composite(root) == (selected_id, receipt)
        and _r11_native_task(root, intent_path, state_path) == task
        and _r11_role_authority(root) == authority
        and read_source_review_catalog(root, review_id=review_id) == catalog
        and collect_source_review_qualified_evidence(root, review_id=review_id, role_delivery=True) == evidence
        and _r11_fresh_operation(root, review_id, task, receipt, binding, timeout, basis["identity"]["funding"])
        == operation,
        "r11-native-stale",
        "current task/roles/raw proof/authority/catalog/ledger changed during reconstruction",
    )
    return value, requests


def _r11_read_fresh_input(root: Path, path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = _r11_review_private(root, path)
    supplied = _r11_json(raw, limit=131_072)
    _require(
        supplied.get("schemaVersion") == "alk-r11-first-native-input.v2-role"
        and isinstance(supplied.get("task"), dict),
        "r11-native-input",
        "fixed task-bound input required",
    )
    task = supplied["task"]
    intent = root / normalize_authority_path(task["intentPath"])
    state = root / normalize_authority_path(task["statePath"])
    value, requests = _r11_fresh_basis(
        root, supplied["reviewId"], intent, state, _validated_cast(int, supplied.get("timeoutSeconds"))
    )
    expected_path = _r11_review_directory(root, value["reviewId"]) / (value["binding"]["shardId"] + ".json")
    _require(
        path == expected_path and raw == canonical_bytes(value) and _r11_review_private(root, path) == raw,
        "r11-native-stale",
        "fresh input/task/source/support/cost no longer matches admission",
    )
    return value, requests


def _r11_fixed_worker_basis(
    root: Path,
    *,
    review_id: str,
    binding: dict[str, str],
    binary_path: Path,
    model: str,
    timeout_seconds: int,
    completed: bool = False,
) -> dict[str, Any]:
    """Reopen a current v6 sealed input, never a v5 planned-thread template.

    This input binds an existing financial reservation and source-fit proof.
    It does not attest how the actual thread was created or start a process.
    Origin-bound v2 seals carry independently collected metadata and original
    clocks; absolute supervisor/complete producer admission is still separate.
    """
    from .codex_input_diagnostics import _file_sha

    _r11_transport_binding(binding)
    _require(type(completed) is bool, "r11-role-worker-completed", "explicit completed reconstruction mode required")
    _require(
        root.is_absolute()
        and root.resolve(strict=True) == root
        and _R11_ENTRYPOINT_PATH.resolve(strict=True) == root / _R11_FIXED_WORKER,
        "r11-worker-entry",
        "fixed worker must belong to this direct execution checkout",
    )
    binary = Path(binary_path)
    _require(
        binary.is_absolute()
        and binary.name == "codex"
        and binary.resolve(strict=True) == binary
        and binary.is_file()
        and os.access(binary, os.X_OK)
        and _file_sha(binary) == binding["binarySha256"]
        and _file_sha(root / _R11_FIXED_WORKER) == binding["transportSourceSha256"]
        and isinstance(model, str)
        and 0 < len(model) <= 256
        and type(timeout_seconds) is int
        and 0 < timeout_seconds <= 1800,
        "r11-worker-entry",
        "selected executable, model, fixed source or timeout differs",
    )
    model = _validated_cast(str, model)
    timeout_seconds = _validated_cast(int, timeout_seconds)
    sealed = read_source_review_request(root, review_id=review_id, role_id=binding["shardId"], require_reservation=True)
    _require(
        sealed["seal"]["binding"] == binding and sealed["subject"]["reviewId"] == review_id,
        "r11-role-worker-request",
        "fixed input differs from the actual reserved role/request",
    )
    _require(
        not completed
        or (
            sealed["seal"].get("schemaVersion") == "alk-r11-role-request-seal.v2-origin"
            and isinstance(sealed["seal"].get("metadataOrigin"), dict)
        ),
        "r11-role-worker-completed",
        "declared-only input cannot qualify completed metadata origin",
    )
    send_basis = _r11_role_send_basis(
        root,
        binding=binding,
        request_raw=sealed["requestRaw"],
        subject=sealed["subject"],
        binary_path=binary,
        model=model,
        **({"completed": True} if completed else {}),
    )
    current = read_source_review_cost(root, review_id=review_id, role_delivery=True)
    if not completed:
        cost = _r11_cost_before_start(
            root, review_id, binding, current["declaredUnknownHoldsAtFunding"], timeout_seconds, role_delivery=True
        )
        _require(
            cost == current
            and send_basis["costChainSha256"] == current["costChainSha256"]
            and send_basis["coordinatorHeadSha256"] == current["fundingOrigin"]["currentHeadSha256"],
            "r11-role-worker-stale",
            "funded prefix or original reservation deadline changed",
        )
    origin = read_source_review_opening_origin(root, review_id=review_id, role_delivery=True)
    reservations = [row for row in current["reservations"] if row["binding"] == binding]
    _require(
        len(reservations) == 1, "r11-role-worker-reservation", "unique reservation for this completed role required"
    )
    reserved = reservations[0]
    metadata_origin = sealed["seal"].get("metadataOrigin")
    if metadata_origin is not None:
        _require(
            send_basis.get("metadataOriginSha256") == canonical_digest(metadata_origin)
            and send_basis.get("deadlineMonotonicNs") == metadata_origin["deadlineMonotonicNs"],
            "r11-role-worker-stale",
            "pre-send original operation differs from the sealed origin",
        )
        if not completed:
            _r11_role_original_deadline(metadata_origin, timeout_seconds)
    instruction = {
        "schemaVersion": "alk-r11-fixed-worker-input.v3-role",
        "projectRoot": str(root),
        "reviewId": review_id,
        "binding": dict(binding),
        "binaryPath": str(binary),
        "model": model,
        "timeoutSeconds": timeout_seconds,
        "roleDelivery": True,
        **{key: sealed["seal"][key] for key in ("baseSha256", "roleInventorySha256", "fundingBatchSha256")},
        "originSha256": canonical_digest(origin),
        "costChainSha256": send_basis["costChainSha256"],
        "heldUnknownTokens": current["declaredUnknownHoldsAtFunding"],
        "requestSha256": sealed["requestSha256"],
        "requestBytes": len(sealed["requestRaw"]),
        "expectedSubjectSha256": canonical_digest(sealed["subject"]),
        "requestSealSha256": sealed["sealSha256"],
        "reservationSha256": canonical_digest(reserved),
        "absoluteDeadlineUtc": reserved["absoluteDeadlineUtc"],
        "sendBasis": send_basis,
        **(
            {"metadataOrigin": metadata_origin, "deadlineMonotonicNs": metadata_origin["deadlineMonotonicNs"]}
            if metadata_origin is not None
            else {}
        ),
        "threadCreationMode": "COLLECTED_ROLE_METADATA"
        if metadata_origin is not None
        else "RESERVED_THREAD_ORIGIN_UNPROVEN",
        "metadataThreadOriginQualified": metadata_origin is not None,
        "hostContextQualified": False,
        "producerQualified": False,
        "dispatchAllowed": False,
        "firstNativeBootstrapEligible": False,
    }
    _require(
        read_source_review_request(root, review_id=review_id, role_id=binding["shardId"], require_reservation=True)
        == sealed
        and read_source_review_opening_origin(root, review_id=review_id, role_delivery=True) == origin
        and read_source_review_cost(root, review_id=review_id, role_delivery=True) == current
        and _file_sha(binary) == binding["binarySha256"]
        and _file_sha(root / _R11_FIXED_WORKER) == binding["transportSourceSha256"],
        "r11-worker-stale",
        "sealed request, origin, funding or executable changed",
    )
    return {"instruction": instruction, "request": sealed["requestRaw"], "subject": sealed["subject"]}


def _r11_read_fixed_worker_input(root: Path, path: Path, *, completed: bool = False) -> dict[str, Any]:
    _require(type(completed) is bool, "r11-worker-entry", "explicit completed read mode required")
    pending = path.with_suffix(".pending.json")
    _require(
        not pending.exists() and not pending.is_symlink(),
        "r11-worker-input-pending",
        "unfinished fixed-input publication is not executable",
    )
    raw = _r11_review_private(root, path)
    instruction = _r11_json(raw, limit=131_072)
    _require(
        instruction.get("schemaVersion") == "alk-r11-fixed-worker-input.v3-role"
        and instruction.get("projectRoot") == str(root)
        and isinstance(instruction.get("binding"), dict),
        "r11-worker-entry",
        "current v6 fixed instruction identity required; old v5 input is not dispatchable",
    )
    binding = instruction["binding"]
    _r11_transport_binding(binding)
    expected_path = _r11_review_directory(root, _validated_cast(str, instruction.get("reviewId"))) / (
        "worker-" + binding["shardId"] + ".json"
    )
    _require(path == expected_path, "r11-worker-entry", "instruction is outside its assigned fixed path")
    basis = _r11_fixed_worker_basis(
        root,
        review_id=instruction["reviewId"],
        binding=binding,
        binary_path=Path(instruction.get("binaryPath", "")),
        model=_validated_cast(str, instruction.get("model")),
        timeout_seconds=_validated_cast(int, instruction.get("timeoutSeconds")),
        **({"completed": True} if completed else {}),
    )
    _require(
        raw == canonical_bytes(basis["instruction"]) and _r11_review_private(root, path) == raw,
        "r11-worker-stale",
        "fixed instruction differs from current sealed request/funding/source basis",
    )
    return basis


def _r11_fixed_supervisor_reservation(
    root: Path, path: Path, basis: dict[str, Any], *, child: bool = False
) -> dict[str, Any]:
    """Reconstruct the exact command/source/financial/original-clock reservation."""
    from agent_lifecycle.contracts.process_execution_schemas import command_identity_hash

    value = basis["instruction"]
    worker = root / _R11_FIXED_WORKER
    _require(
        value.get("metadataThreadOriginQualified") is True
        and value.get("threadCreationMode") == "COLLECTED_ROLE_METADATA"
        and isinstance(value.get("metadataOrigin"), dict)
        and type(value.get("deadlineMonotonicNs")) is int
        and value["deadlineMonotonicNs"] == value["metadataOrigin"].get("deadlineMonotonicNs"),
        "r11-role-supervision-unproven",
        "complete origin-bound input required for absolute model supervision",
    )
    environment = (
        dict(os.environ)
        if child
        else {**os.environ, "PYTHONPATH": str(root / "src"), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
    )
    argv = [str(Path(sys.executable).resolve(strict=True)), "-B", str(worker), str(path)]
    return {
        "schemaVersion": "alk-r11-worker-reservation.v1",
        "binding": value["binding"],
        "workerPath": _R11_FIXED_WORKER,
        "instructionPath": path.relative_to(root).as_posix(),
        "argv": argv,
        "commandIdentityHash": command_identity_hash(argv),
        "environmentSha256": canonical_digest(environment),
        "sourceSha256": _r11_worker_sources(root, worker, path),
        "timeoutSeconds": value["timeoutSeconds"],
        "heldUnknownTokens": value["heldUnknownTokens"],
        "costStatus": "UNAVAILABLE",
        "actualModelTokens": None,
        "retryAuthorized": False,
        "costReviewId": value["reviewId"],
        "costChainSha256": value["costChainSha256"],
        "requestSha256": value["requestSha256"],
        "absoluteDeadlineMonotonicNs": value["deadlineMonotonicNs"],
    }


def _r11_live_supervisor(root: Path, path: Path, basis: dict[str, Any]) -> bytes:
    value = basis["instruction"]
    directory = _r11_worker_directory(root, value["binding"])
    _require(
        {p.name for p in directory.iterdir()} == {"reservation.json", "dispatch.pending.json"},
        "r11-worker-entry",
        "supervisor dispatch is missing, terminal or conflicted",
    )
    raw = _r11_review_private(root, directory / "reservation.json")
    pending_raw = _r11_review_private(root, directory / "dispatch.pending.json")
    expected = _r11_fixed_supervisor_reservation(root, path, basis, child=True)
    _require(
        raw == canonical_bytes(expected)
        and pending_raw
        == canonical_bytes({"reservationSha256": canonical_digest(expected), "state": "START_UNCERTAIN"})
        and _r11_read_fixed_worker_input(root, path) == basis
        and _r11_review_private(root, directory / "reservation.json") == raw
        and _r11_review_private(root, directory / "dispatch.pending.json") == pending_raw,
        "r11-worker-stale",
        "actual fixed child command/source/environment/original deadline differs from reserved dispatch",
    )
    return raw

"""Frozen, source-only usage validation against the existing declared ledger.

The financial selector is independent of producer references. Returned PASS
means the selected limited contract matched, never measured cap conformance.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from datetime import timezone as timezone
from pathlib import Path, PurePosixPath
from typing import Any
from typing import cast as _validated_cast

from agent_lifecycle.accounting.declared_ledger import DeclaredLedgerContext
from agent_lifecycle.accounting.source_usage_context import (
    _declared_context,
    _load_frozen_source_context,
    _read_ref,
    _ref,
    _require,
    load_frozen_source_policy,
)
from agent_lifecycle.accounting.source_usage_context import (
    _load_source_disposition as _load_source_disposition,
)
from agent_lifecycle.accounting.source_usage_context import (
    _load_source_recovery as _load_source_recovery,
)
from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object
from agent_lifecycle.contracts.authority_io import create_authority_bytes, read_authority_bytes
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.scoped_usage_schemas import (
    MAX_CURRENT_SOURCE_REGISTRY_BYTES as MAX_CURRENT_SOURCE_REGISTRY_BYTES,
)
from agent_lifecycle.contracts.scoped_usage_schemas import (
    MAX_SAFE_INTEGER,
    MAX_SOURCE_USAGE_BINDINGS,
    MAX_SOURCE_USAGE_BYTES,
    SOURCE_CURRENT_REGISTRY,
    SOURCE_INVALID_ANNOTATION_REGISTRY,
    SOURCE_RECOVERY_REGISTRY,
    SOURCE_USAGE_MODE,
    SOURCE_USAGE_ROLES,
    validate_source_usage_receipt_shape,
    validate_source_window_binding,
)
from agent_lifecycle.contracts.scoped_usage_schemas import (
    validate_source_conflict_disposition_shape as validate_source_conflict_disposition_shape,
)
from agent_lifecycle.contracts.scoped_usage_schemas import (
    validate_source_conflict_grant_shape as validate_source_conflict_grant_shape,
)
from agent_lifecycle.contracts.scoped_usage_schemas import (
    validate_source_recovery_policy_shape as validate_source_recovery_policy_shape,
)
from agent_lifecycle.contracts.scoped_usage_schemas import (
    validate_source_ref_shape as validate_source_ref_shape,
)
from agent_lifecycle.contracts.scoped_usage_schemas import (
    validate_source_registry_prefix_shape as validate_source_registry_prefix_shape,
)
from agent_lifecycle.contracts.scoped_usage_schemas import (
    validate_source_usage_policy_shape as validate_source_usage_policy_shape,
)
from agent_lifecycle.freeze.package_integrity import verify_plan_package_integrity as verify_plan_package_integrity
from agent_lifecycle.workflow.artifacts import artifact_identity, artifact_path

_HEAD_PATH = "work/release-2-16/enforcement-decision/COORDINATOR-COST-HEAD.json"
_WINDOW = re.compile(r"(work/release-2-16/enforcement-decision/r([1-9][0-9]*)-[a-z0-9-]+)/(admission|cost)\.json")


def _window(value: dict[str, Any], window_id: str, stage: str) -> dict[str, Any] | None:
    """Check original finite admission metadata without rewriting its format."""

    _require(
        {
            "status",
            "costStatus",
            "actualTokens",
            "actualInputTokens",
            "priorBudgetResumed",
            "admittedAtUtc",
            "absoluteDeadlineUtc",
        }
        <= set(value),
        "scoped-usage-window-invalid",
        "original window fields are missing",
    )
    expected = "ADMITTED_PREAPPROVED_BY_USER" if stage == "ADMISSION" else "UNAVAILABLE_FULL_HOLD_RETAINED"
    _require(
        value.get("status") == expected
        and value.get("costStatus") == "UNAVAILABLE"
        and value.get("actualTokens") is None
        and value.get("actualInputTokens") is None
        and value.get("priorBudgetResumed") is False,
        "scoped-usage-window-invalid",
        "original window claims invalid measured usage or status",
    )
    for key in (
        "tokenCap",
        "protectedCloseoutTokens",
        "priorLedgerLowerBound",
        "priorUnknownHolds",
        "ledgerLowerBoundIncludingThisHold",
        "unknownHoldsIncludingThisWindow",
    ):
        n = value.get(key)
        _require(
            type(n) is int and 0 <= n <= MAX_SAFE_INTEGER,
            "scoped-usage-window-invalid",
            "original financial counter is invalid",
        )
        n = _validated_cast(int, n)
    _require(
        0 < value["protectedCloseoutTokens"] < value["tokenCap"] <= 300_000
        and value["priorUnknownHolds"] <= value["priorLedgerLowerBound"]
        and value["ledgerLowerBoundIncludingThisHold"] == value["priorLedgerLowerBound"] + value["tokenCap"]
        and value["unknownHoldsIncludingThisWindow"] == value["priorUnknownHolds"] + value["tokenCap"],
        "scoped-usage-window-invalid",
        "original financial hold was reset or altered",
    )
    accounting_only = value.get("accountingOnly") is True
    if accounting_only:
        _require(
            value.get("sourceUsageBinding") is None
            and all(
                type(value.get(key)) is int and value[key] == 0
                for key in ("maxModelInvocations", "maxTestInvocations", "maxNativeInvocations")
            )
            and value.get("productWriteAuthority", False) is False,
            "scoped-usage-window-invalid",
            "accounting-only liability cannot authorize execution",
        )
    try:
        start = datetime.fromisoformat(value["admittedAtUtc"])
        end = datetime.fromisoformat(value["absoluteDeadlineUtc"])
        ordered = start <= end if accounting_only else start < end
        _require(
            start.utcoffset() == end.utcoffset() == UTC.utcoffset(start) and ordered,
            "scoped-usage-window-invalid",
            "window clocks must be original aware UTC timestamps",
        )
        if stage == "COST":
            closed = datetime.fromisoformat(value["closedAtUtc"])
            _require(
                closed.utcoffset() == UTC.utcoffset(closed)
                and closed >= start
                and value.get("priorUnknownHoldsReleased") == 0,
                "scoped-usage-window-invalid",
                "closure drops a hold or changes original time",
            )
    except (KeyError, ValueError, TypeError) as exc:
        raise LifecycleError("scoped-usage-window-invalid", "original window clocks are missing") from exc
    binding = value.get("sourceUsageBinding")
    if binding is not None:
        validate_source_window_binding(binding)
        _require(
            binding["originalWindowId"] == window_id,
            "scoped-usage-window-invalid",
            "binding changes original window identity",
        )
    return binding


def _invalid_annotation_tracker(selection, chain):
    recovery = selection.get("invalidAnnotationRecovery")
    if recovery is None:
        return None
    disposition = recovery["disposition"]
    authority_sha = disposition["authorizingFinancialHeadRef"]["sha256"]
    _require(
        authority_sha in chain,
        "scoped-usage-recovery-invalid",
        "annotation authority is absent from complete original ancestry",
    )
    return {
        "recovery": recovery,
        "authorityIndex": chain.index(authority_sha),
        "seen": {},
        "windows": {row["windowId"]: row for row in disposition["originalWindows"]},
    }


def _invalid_annotation_binding(tracker, value, source_ref, window_id, stage, index):
    row = tracker["windows"][window_id]
    reference = row["admissionRef"] if stage == "ADMISSION" else row["costRef"]
    _require(
        source_ref == reference and 0 < index < tracker["authorityIndex"],
        "scoped-usage-recovery-invalid",
        "annotation source or original ancestry order differs",
    )
    binding = value.get("sourceUsageBinding")
    _require(
        isinstance(binding, dict)
        and canonical_digest(binding) == row["originalBindingSha256"]
        and binding.get("originalWindowId") == window_id
        and binding.get("originalCostScope") != "COORDINATOR_FINITE_SOURCE_AUTHORING_WINDOW",
        "scoped-usage-recovery-invalid",
        "annotation is not the exact original permitted defect",
    )
    binding = _validated_cast(dict[str, Any], binding)
    canonical = {**binding, "originalCostScope": "COORDINATOR_FINITE_SOURCE_AUTHORING_WINDOW"}
    validate_source_window_binding(canonical)
    identity = (window_id, stage)
    _require(
        identity not in tracker["seen"], "scoped-usage-recovery-invalid", "selected original annotation stage repeated"
    )
    tracker["seen"][identity] = index
    return _window({**value, "sourceUsageBinding": None}, window_id, stage)


def _finish_invalid_annotation_projection(tracker, ordered, result):
    if tracker is None:
        return
    for window_id in tracker["windows"]:
        admission = tracker["seen"].get((window_id, "ADMISSION"))
        cost = tracker["seen"].get((window_id, "COST"))
        _require(
            admission is not None and cost is not None and admission < cost < tracker["authorityIndex"],
            "scoped-usage-recovery-invalid",
            "selected original pair is incomplete or out of order",
        )
        pool = next((pool for pool in ordered if pool["windowId"] == window_id), None)
        _require(
            pool is not None and pool["binding"] is None and pool["closeRef"] is not None,
            "scoped-usage-recovery-invalid",
            "selected historical pool is incomplete or eligible",
        )
        pool["eligibility"] = "HISTORICAL_INELIGIBLE"
    result["schemaVersion"] = SOURCE_INVALID_ANNOTATION_REGISTRY
    result["invalidAnnotationDispositionRef"] = tracker["recovery"]["dispositionRef"]
    result["invalidAnnotationWindows"] = sorted(tracker["windows"])


def _project_financial_record_chain(
    *,
    selection: dict[str, Any],
    current: dict[str, Any],
    context: DeclaredLedgerContext,
    policy: dict[str, Any],
    primary: Path,
    chain: list[str],
    terminal_sha: str,
    invalid_annotations: dict[str, Any] | None,
    read_declared_source: Callable[[DeclaredLedgerContext, dict[str, Any]], tuple[dict[str, Any], bytes]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    unchanged: tuple[str, ...]
    stage: str | None
    records, pools = [], {}
    legacy: list[dict[str, Any]] = []
    original_windows = {}
    for index, head_sha in enumerate(chain):
        if head_sha == terminal_sha:
            head_path, head_raw = _HEAD_PATH, current["headRaw"]
        elif index == 0:
            head_path = policy["openingRef"]["path"]
            head_raw = _read_ref(selection["root"], policy["openingRef"], limit=MAX_SOURCE_USAGE_BYTES)
        else:
            head_path = str(PurePosixPath(_HEAD_PATH).parent / "coordinator-cost-head-history" / (head_sha + ".json"))
            head_raw = read_authority_bytes(primary / head_path, root=primary, max_bytes=131_072)
        _require(
            hashlib.sha256(head_raw).hexdigest() == head_sha,
            "scoped-usage-frontier-stale",
            "financial ancestor changed while projecting",
        )
        head = load_json_object(head_raw, label="verified financial head")
        value, source_raw = read_declared_source(context, head)
        source_ref = _ref(head["sourcePath"], source_raw)
        _require(
            source_ref["sha256"] == head["sourceSha256"],
            "scoped-usage-frontier-stale",
            "original source changed while projecting",
        )
        match = _WINDOW.fullmatch(head["sourcePath"])
        binding, window_id = None, None
        if match and not value.get("schemaVersion"):
            window_id = match[1]
            stage = "ADMISSION" if match[3] == "admission" else "COST"
            # Pre-opening data remains original historical context. New ordinary
            # windows must meet the exact finite format selected by this policy.
            selected_annotation = invalid_annotations is not None and window_id in invalid_annotations["windows"]
            if selected_annotation:
                binding = _invalid_annotation_binding(invalid_annotations, value, source_ref, window_id, stage, index)
            else:
                binding = _window(value, window_id, stage) if index else value.get("sourceUsageBinding")
            if binding is not None:
                validate_source_window_binding(binding)
            kind = "ORDINARY_WINDOW"
            if stage == "ADMISSION":
                _require(
                    window_id not in original_windows, "scoped-usage-window-conflict", "original admission repeated"
                )
                original_windows[window_id] = value
            elif stage == "COST" and window_id in original_windows:
                original = original_windows[window_id]
                unchanged = (
                    "tokenCap",
                    "admittedAtUtc",
                    "absoluteDeadlineUtc",
                    "protectedCloseoutTokens",
                    "priorUnknownHolds",
                    "priorLedgerLowerBound",
                    "ledgerLowerBoundIncludingThisHold",
                    "unknownHoldsIncludingThisWindow",
                )
                original_binding = value.get("sourceUsageBinding") if selected_annotation else binding
                _require(
                    original.get("sourceUsageBinding") == original_binding
                    and all(key in original and value[key] == original[key] for key in unchanged),
                    "scoped-usage-window-conflict",
                    "closure changes original opening identity or clocks",
                )
            if index and stage == "ADMISSION":
                _require(window_id not in pools, "scoped-usage-window-conflict", "window admission repeated")
                pools[window_id] = {
                    "windowId": window_id,
                    "admissionRef": source_ref,
                    "closeRef": None,
                    "binding": binding,
                    "tokenCap": value["tokenCap"],
                    "originalCostScope": binding["originalCostScope"]
                    if binding
                    else "UNAVAILABLE_LEGACY_DECLARED_WINDOW",
                }
            elif stage == "COST" and window_id in pools:
                pool = pools[window_id]
                _require(
                    pool["binding"] == binding and pool["tokenCap"] == value["tokenCap"] and pool["closeRef"] is None,
                    "scoped-usage-window-conflict",
                    "closure changes original admission identity",
                )
                unchanged = (
                    "admittedAtUtc",
                    "absoluteDeadlineUtc",
                    "protectedCloseoutTokens",
                    "priorUnknownHolds",
                    "priorLedgerLowerBound",
                    "ledgerLowerBoundIncludingThisHold",
                    "unknownHoldsIncludingThisWindow",
                )
                _require(
                    all(value[key] == original_windows[window_id][key] for key in unchanged),
                    "scoped-usage-window-conflict",
                    "closure changes original clocks or hold",
                )
                pool["closeRef"] = source_ref
        else:
            kind, stage = "LEGACY_ROLE_SOURCE", value.get("schemaVersion")
        records.append(
            {
                "headRef": _ref(head_path, head_raw),
                "sourceRef": source_ref,
                "recordKind": kind,
                "windowId": window_id,
                "stage": stage,
                "binding": binding,
            }
        )
        if index and binding is None:
            legacy.append(
                {
                    "kind": "UNAVAILABLE_ORIGINAL_ATTRIBUTION",
                    "originalSourceRef": source_ref,
                    "originalWindowId": window_id,
                }
            )
    return records, pools, legacy


def _projection(selection: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Derive the complete bounded opening-to-current interval, oldest first."""

    from agent_lifecycle.accounting.declared_ledger import read_declared_source

    context = _declared_context(selection)

    policy, prefix = selection["policy"], selection["prefix"]
    primary = Path(current["primaryCheckout"])
    chain = list(reversed(current["ancestryHeadSha256s"]))
    invalid_annotations = _invalid_annotation_tracker(selection, chain)
    opening_sha, terminal_sha = chain[0], chain[-1]
    records, pools, legacy = _project_financial_record_chain(
        selection=selection,
        current=current,
        context=context,
        policy=policy,
        primary=primary,
        chain=chain,
        terminal_sha=terminal_sha,
        invalid_annotations=invalid_annotations,
        read_declared_source=read_declared_source,
    )
    ordered = sorted(
        pools.values(),
        key=lambda pool: (
            int(_validated_cast(re.Match[str], _WINDOW.fullmatch(pool["windowId"] + "/admission.json"))[2]),
            pool["windowId"],
        ),
    )
    _require(
        sum(pool["binding"] is not None for pool in ordered) <= MAX_SOURCE_USAGE_BINDINGS,
        "scoped-usage-registry-bound",
        "too many typed original work windows",
    )
    conflict_dispositions = _classify_source_conflict(selection, current, records, ordered)
    operations = set()
    for pool in ordered:
        binding = pool["binding"]
        if binding and pool.get("eligibility") != "HISTORICAL_INELIGIBLE":
            operation = (
                binding["runId"],
                binding["packageId"],
                binding["taskId"],
                binding["attempt"],
                binding["semanticOperationId"],
            )
            _require(operation not in operations, "scoped-usage-window-conflict", "operation binds two windows")
            operations.add(operation)
    prefix_sha = policy["sourceAuthoringRegistryRef"]["sha256"]
    unknown_ids = sorted(
        {f"prefix:{prefix_sha}:{index}" for index in range(len(prefix["unknownIntervals"]))}
        | {"legacy:" + row["originalSourceRef"]["sha256"] for row in legacy}
    )
    dispositions = []
    for role in SOURCE_USAGE_ROLES:
        window_ids = sorted(pool["windowId"] for pool in ordered if pool["binding"] and pool["binding"]["role"] == role)
        status = (
            "RECORDED_ORIGINAL_WINDOW"
            if window_ids
            else ("UNAVAILABLE_UNALLOCATED_POOL" if unknown_ids else "NOT_PLANNED")
        )
        dispositions.append({"role": role, "status": status, "windowIds": window_ids, "unknownContextIds": unknown_ids})
    result = {
        "schemaVersion": SOURCE_CURRENT_REGISTRY,
        "openingHeadSha256": opening_sha,
        "terminalHeadSha256": terminal_sha,
        "terminalSourceRef": records[-1]["sourceRef"],
        "frozenPrefixRawSha256": prefix_sha,
        "records": records,
        "windowPools": ordered,
        "roleDispositions": dispositions,
        "unknownIntervals": prefix["unknownIntervals"] + legacy,
        "balances": {
            "openingExposureLowerBound": selection["opening"]["exposureLowerBound"],
            "openingUnknownHolds": selection["opening"]["unknownHolds"],
            "currentExposureLowerBound": current["head"]["exposureLowerBound"],
            "currentUnknownHolds": current["head"]["unknownHolds"],
            "actualTokens": None,
            "actualInputTokens": None,
        },
        "guarantee": "DECLARED_DERIVED_SOURCE_EVIDENCE_ONLY",
    }
    if conflict_dispositions:
        result["schemaVersion"] = SOURCE_RECOVERY_REGISTRY
        result["conflictDispositions"] = conflict_dispositions
    _finish_invalid_annotation_projection(invalid_annotations, ordered, result)
    _require(
        len(_projection_bytes(result)) <= selection["registryByteLimit"],
        "scoped-usage-registry-bound",
        "derived registry exceeds its byte bound",
    )
    return result


def _projection_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def current_source_snapshot(selection: dict[str, Any]) -> dict[str, Any]:
    """Observe independently selected A/B financial heads; no automatic retry."""

    from agent_lifecycle.accounting.declared_ledger import read_declared_ledger

    kwargs = {"ancestor_head_sha256": selection["policy"]["openingRef"]["sha256"]}
    current = read_declared_ledger(_declared_context(selection), **kwargs)
    projection = _projection(selection, current)
    after = read_declared_ledger(_declared_context(selection), **kwargs)
    _require(
        current["headRaw"] == after["headRaw"] and current["ancestryHeadSha256s"] == after["ancestryHeadSha256s"],
        "scoped-usage-frontier-stale",
        "financial frontier changed during validation",
    )
    return {"current": current, "projection": projection, "projectionBytes": _projection_bytes(projection)}


def require_snapshot_current(selection: dict[str, Any], snapshot: dict[str, Any]) -> None:
    current = current_source_snapshot(selection)
    _require(
        current["current"]["headRaw"] == snapshot["current"]["headRaw"]
        and current["projectionBytes"] == snapshot["projectionBytes"],
        "scoped-usage-frontier-stale",
        "declared frontier changed before durable operation",
    )


def _registry_ref(task: dict[str, Any], raw: bytes) -> dict[str, Any]:
    parent = Path(artifact_path(task, "result", int(task["attempt"]))).parent
    path = (parent / ("source-usage-registry-" + hashlib.sha256(raw).hexdigest() + ".json")).as_posix()
    return _ref(normalize_repo_path(path), raw)


def emit_registry_artifact(repository_root: Path, state: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    """Create immutable evidence only; the live financial selector remains authoritative."""

    selection = load_frozen_source_policy(repository_root, state, task)
    _require(selection is not None, "scoped-usage-policy-missing", "frozen source usage policy is absent")
    selection = _validated_cast(dict[str, Any], selection)
    return _emit_registry_for_context(selection, task)


def _emit_registry_for_context(selection: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    """Emit historical context without granting task limited-mode eligibility."""

    snapshot = current_source_snapshot(selection)
    raw = snapshot["projectionBytes"]
    ref = _registry_ref(task, raw)
    try:
        create_authority_bytes(selection["root"] / ref["path"], raw, root=selection["root"])
    except FileExistsError:
        _read_ref(selection["root"], ref, limit=selection["registryByteLimit"])
    require_snapshot_current(selection, snapshot)
    return ref


def validate_limited_source_usage(
    repository_root: Path,
    state: dict[str, Any],
    task: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    validate_source_usage_receipt_shape(receipt)
    selection = load_frozen_source_policy(
        repository_root, state, task, adapter_id=task.get("adapterId"), adapter_host=receipt["host"]
    )
    _require(selection is not None, "scoped-usage-policy-missing", "receipt cannot select limited mode")
    selection = _validated_cast(dict[str, Any], selection)
    policy = selection["policy"]
    route = task.get("attemptModelRoute") or task.get("modelRoute") or {}
    adopted = (
        task.get("attemptRiskExecutionProfile")
        or task.get("riskExecutionProfile")
        or task.get("attemptExecutionStrategy")
        or task.get("executionStrategy")
        or {}
    )
    _require(
        adopted.get("sourceUsagePolicyDigest") == selection["policyDigest"]
        and adopted.get("usageMode") == SOURCE_USAGE_MODE,
        "scoped-usage-policy-context-required",
        "limited usage requires actual selected attempt authority",
    )
    lineage = {
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "taskId": task.get("id"),
        "attempt": task.get("attempt"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
        "routeDecisionDigest": route.get("decisionDigest"),
    }
    _require(
        receipt["lineage"] == lineage
        and receipt["operationId"] == route.get("operationId")
        and receipt["modelClass"] == route.get("modelClass")
        and receipt["modelClass"] in policy["allowedModelClasses"],
        "scoped-usage-current-identity-mismatch",
        "current operation, route or lineage differs",
    )
    _require(
        receipt["policyDigest"] == selection["policyDigest"]
        and receipt["sourceAuthoringRegistryDigest"] == policy["sourceAuthoringRegistryRef"]["sha256"],
        "scoped-usage-policy-mismatch",
        "receipt selects different frozen source inputs",
    )
    _require(
        (receipt["actorId"], "coordinator")
        in {(owner["actorId"], owner["role"]) for owner in selection["prefix"]["ownerBindings"]},
        "scoped-usage-current-identity-mismatch",
        "actor is not the frozen source coordinator",
    )
    snapshot = current_source_snapshot(selection)
    current, projection = snapshot["current"], snapshot["projection"]
    _require(
        receipt["ledgerRef"] == _ref(_HEAD_PATH, current["headRaw"]),
        "scoped-usage-frontier-stale",
        "receipt omits the actual current financial frontier",
    )
    expected_registry = _registry_ref(task, snapshot["projectionBytes"])
    _require(
        receipt["currentRegistryRef"] == expected_registry,
        "scoped-usage-frontier-stale",
        "registry reference differs from the actual current derived projection",
    )
    _require(
        _read_ref(selection["root"], expected_registry, limit=selection["registryByteLimit"])
        == snapshot["projectionBytes"],
        "scoped-usage-frontier-stale",
        "registry artifact bytes differ",
    )
    pools = [pool for pool in projection["windowPools"] if pool["admissionRef"] == receipt["currentAdmissionRef"]]
    _require(
        len(pools) == 1 and pools[0]["binding"] is not None,
        "scoped-usage-current-admission-unbound",
        "current operation has no original typed admission",
    )
    _require(
        pools[0].get("eligibility", "CURRENT_ELIGIBLE") == "CURRENT_ELIGIBLE",
        "scoped-usage-current-admission-unbound",
        "historical conflict pool is ineligible",
    )
    binding = pools[0]["binding"]
    expected = {
        **lineage,
        "semanticOperationId": receipt["operationId"],
        "sourceUsagePolicyDigest": selection["policyDigest"],
        "actorId": receipt["actorId"],
    }
    _require(
        all(binding[key] == value for key, value in expected.items()),
        "scoped-usage-current-identity-mismatch",
        "original admission belongs to another actor or attempt",
    )
    primary = Path(current["primaryCheckout"])
    original_refs = projection["records"]
    known_refs = [row["sourceRef"] for row in original_refs] + selection["prefix"]["historicalSourceRefs"]
    result_path = artifact_path(task, "result", int(task["attempt"]))
    for ref in receipt["sourceContextRefs"]:
        if ref in known_refs:
            _read_ref(primary, ref, limit=131_072)
        else:
            _require(
                ref["path"] == result_path,
                "scoped-usage-ref-invalid",
                "context is outside original history or the current result",
            )
            _read_ref(selection["root"], ref, limit=MAX_SOURCE_USAGE_BYTES)
    require_snapshot_current(selection, snapshot)
    return {
        "schemaVersion": "agent-lifecycle-model-usage-validation.v2",
        "status": "PASS",
        "operationId": receipt["operationId"],
        "host": receipt["host"],
        "modelClass": receipt["modelClass"],
        "receiptDigest": canonical_digest(receipt),
        "routeDecisionDigest": route["decisionDigest"],
        "usageAssurance": {
            "usageMode": SOURCE_USAGE_MODE,
            "policyDigest": selection["policyDigest"],
            "guarantee": "LIMITED_DECLARED_SOURCE_ACCOUNTING",
            "actualCapConformance": "UNAVAILABLE",
            "actualTokens": None,
            "financialClosure": "OPEN_UNAVAILABLE",
            "ledgerRef": receipt["ledgerRef"],
            "currentRegistryRef": receipt["currentRegistryRef"],
            "sourceAuthoringRegistryDigest": receipt["sourceAuthoringRegistryDigest"],
            "currentAdmissionRef": receipt["currentAdmissionRef"],
            "actorId": receipt["actorId"],
            "observedSnapshot": "DECLARED_FRONTIER_NOT_PROVIDER_ATOMIC",
        },
    }


def refresh_committed_source_assurance(
    repository_root: Path,
    state: dict[str, Any],
    task: dict[str, Any],
) -> dict[str, Any] | None:
    """Observe a newer descendant without changing the committed source result.

    An old receipt is historical input here, never the live frontier selector.
    Only an already committed, validated v2 receipt can use this route. The
    controller derives current declared evidence; no model call is admitted.
    """

    stored = task.get("modelUsageReceipt")
    if not isinstance(stored, dict) or not isinstance(stored.get("usageAssurance"), dict):
        return None
    _require(
        task.get("status") in {"VERIFYING", "ACCEPTED"},
        "scoped-usage-committed-context-required",
        "source result must already be committed",
    )
    root = Path(repository_root).absolute()
    path = normalize_repo_path(stored["path"], label="committed source usage receipt")
    receipt = load_json_object(
        read_authority_bytes(root / path, root=root, max_bytes=MAX_SOURCE_USAGE_BYTES),
        label="committed source usage receipt",
    )
    identity = artifact_identity(root, path, receipt)
    _require(
        all(stored.get(key) == identity[key] for key in ("path", "sha256", "bytes"))
        and stored.get("validation", {}).get("receiptDigest") == canonical_digest(receipt),
        "scoped-usage-committed-context-invalid",
        "committed usage artifact was changed",
    )
    validate_source_usage_receipt_shape(receipt)
    selection = load_frozen_source_policy(
        root, state, task, adapter_id=task.get("adapterId"), adapter_host=receipt["host"]
    )
    _require(selection is not None, "scoped-usage-policy-missing", "current frozen limited policy is absent")
    selection = _validated_cast(dict[str, Any], selection)
    snapshot = current_source_snapshot(selection)
    original_registry = load_json_object(
        _read_ref(root, receipt["currentRegistryRef"], limit=selection["registryByteLimit"]),
        label="original source registry",
    )
    _require(
        receipt["ledgerRef"]["path"] == _HEAD_PATH
        and receipt["ledgerRef"]["sha256"] in snapshot["current"]["ancestryHeadSha256s"]
        and original_registry.get("terminalHeadSha256") == receipt["ledgerRef"]["sha256"]
        and original_registry.get("frozenPrefixRawSha256")
        == selection["policy"]["sourceAuthoringRegistryRef"]["sha256"],
        "scoped-usage-frontier-stale",
        "committed observation is not an original current-ledger ancestor",
    )
    _require(
        receipt["currentRegistryRef"] == _registry_ref(task, _projection_bytes(original_registry)),
        "scoped-usage-ref-invalid",
        "original registry does not use its deterministic artifact path",
    )
    # This is a fresh ALK-declared observation of the same original work window,
    # not a rewritten receipt, expenditure, executor or source-input binding.
    current_view = {
        **receipt,
        "ledgerRef": _ref(_HEAD_PATH, snapshot["current"]["headRaw"]),
        "currentRegistryRef": emit_registry_artifact(root, state, task),
    }
    validation = validate_limited_source_usage(root, state, task, current_view)
    require_snapshot_current(selection, snapshot)
    assurance = validation["usageAssurance"]
    assurance["originalReceiptDigest"] = canonical_digest(receipt)
    assurance["assuranceBasis"] = "FRESH_CONTROLLER_DERIVATION_FROM_COMMITTED_SOURCE_RECEIPT"
    return assurance


def require_task_source_frontier_current(
    repository_root: Path,
    state: dict[str, Any],
    task: dict[str, Any],
) -> None:
    assurance = task.get("sourceUsageAssurance")
    if not isinstance(assurance, dict):
        return
    selection = _load_frozen_source_context(repository_root, state)
    _require(selection is not None, "scoped-usage-policy-missing", "current source policy is absent")
    selection = _validated_cast(dict[str, Any], selection)
    if "currentAdmissionRef" in assurance:
        load_frozen_source_policy(repository_root, state, task)
    snapshot = current_source_snapshot(selection)
    if "currentAdmissionRef" in assurance:
        pools = [
            pool
            for pool in snapshot["projection"]["windowPools"]
            if pool["admissionRef"] == assurance["currentAdmissionRef"]
        ]
        _require(
            len(pools) == 1
            and pools[0]["binding"] is not None
            and pools[0].get("eligibility", "CURRENT_ELIGIBLE") == "CURRENT_ELIGIBLE",
            "scoped-usage-current-admission-unbound",
            "historical conflict pool is ineligible",
        )
    _require(
        assurance["ledgerRef"] == _ref(_HEAD_PATH, snapshot["current"]["headRaw"])
        and assurance["currentRegistryRef"] == _registry_ref(task, snapshot["projectionBytes"]),
        "scoped-usage-frontier-stale",
        "observed source frontier changed before durable commit",
    )


def aggregate_source_usage_assurance(
    repository_root: Path,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    observations = []
    historical = _load_frozen_source_context(repository_root, state)
    for task in state.get("tasks", []):
        if task.get("status") != "ACCEPTED":
            continue
        assurance = refresh_committed_source_assurance(repository_root, state, task)
        if assurance is None:
            selection = historical
            if selection is not None:
                snapshot = current_source_snapshot(selection)
                # The selected source ledger has null actuals even when the
                # producer supplied no explicit interval descriptors. Full-v1
                # executor receipts cannot erase that historical source limit.
                if snapshot["projection"]["guarantee"] == "DECLARED_DERIVED_SOURCE_EVIDENCE_ONLY":
                    assurance = {
                        "usageMode": SOURCE_USAGE_MODE,
                        "policyDigest": selection["policyDigest"],
                        "guarantee": "LIMITED_DECLARED_SOURCE_ACCOUNTING",
                        "actualCapConformance": "UNAVAILABLE",
                        "actualTokens": None,
                        "financialClosure": "OPEN_UNAVAILABLE",
                        "ledgerRef": _ref(_HEAD_PATH, snapshot["current"]["headRaw"]),
                        "currentRegistryRef": _emit_registry_for_context(selection, task),
                        "sourceAuthoringRegistryDigest": selection["policy"]["sourceAuthoringRegistryRef"]["sha256"],
                        "assuranceBasis": "HISTORICAL_UNAVAILABLE_SOURCE_CONTEXT_NOT_CURRENT_EXECUTOR",
                    }
                    require_snapshot_current(selection, snapshot)
        if assurance is not None:
            task["sourceUsageAssurance"] = assurance
            observations.append({"taskId": task["id"], "attempt": task["attempt"], "assurance": assurance})
    if not observations:
        return None
    return {
        "guarantee": "LIMITED_DECLARED_SOURCE_ACCOUNTING",
        "actualCapConformance": "UNAVAILABLE",
        "financialClosure": "OPEN_UNAVAILABLE",
        "actualTokens": None,
        "tasks": observations,
    }


def _classify_source_conflict(
    selection: dict[str, Any], current: dict[str, Any], records: list[dict[str, Any]], pools: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    recovery = selection.get("recovery")
    if recovery is None:
        return []
    groups = recovery.get("groups")
    if groups is None:
        groups = [{"dispositionRef": recovery["policy"]["dispositionRef"], "disposition": recovery["disposition"]}]
    negative_ids: set[str] = set()
    identities = set()
    results = []
    head_ids = list(reversed(current["ancestryHeadSha256s"]))
    for recovery_group in groups:
        disposition = recovery_group["disposition"]
        identity = disposition["identityTuple"]
        key = tuple(identity[name] for name in ("runId", "packageId", "taskId", "attempt", "semanticOperationId"))
        expected = disposition["originalWindows"]
        expected_ids = [row["windowId"] for row in expected]
        _require(
            key not in identities and not negative_ids.intersection(expected_ids),
            "scoped-usage-recovery-invalid",
            "repeated or overlapping recovery groups",
        )
        group = [
            pool
            for pool in pools
            if pool["binding"] and all(pool["binding"][name] == value for name, value in identity.items())
        ]
        by_window = {pool["windowId"]: pool for pool in group}
        _require(
            len(group) == len(by_window) == 2
            and set(by_window) == set(expected_ids)
            and all(
                by_window[row["windowId"]]["admissionRef"] == row["admissionRef"]
                and by_window[row["windowId"]]["closeRef"] == row["costRef"]
                for row in expected
            ),
            "scoped-usage-window-conflict",
            "complete exact historical conflict group differs",
        )
        authority = disposition["authorizingFinancialHeadRef"]["sha256"]
        _require(authority in head_ids, "scoped-usage-recovery-invalid", "authorizing head outside complete interval")
        position = head_ids.index(authority)
        for row in expected:
            for reference in (row["admissionRef"], row["costRef"]):
                found = [i for i, record in enumerate(records) if record["sourceRef"] == reference]
                _require(
                    len(found) == 1 and found[0] < position,
                    "scoped-usage-recovery-invalid",
                    "original conflict stage not before admitted authority",
                )
        identities.add(key)
        negative_ids.update(expected_ids)
        results.append(
            {
                "dispositionRef": recovery_group["dispositionRef"],
                "originalWindowIds": expected_ids,
                "classification": "HISTORICAL_INELIGIBLE",
            }
        )
    # Only now commit classification, preserving every validated earlier group.
    for pool in pools:
        pool["eligibility"] = (
            "HISTORICAL_INELIGIBLE"
            if pool["windowId"] in negative_ids
            else ("CURRENT_ELIGIBLE" if pool["binding"] else "UNAVAILABLE_ORIGINAL_ATTRIBUTION")
        )
    return results


def require_source_operation_unused(selection: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    """Read-only prepublication check; never grants financial or execution authority."""
    binding = validate_source_window_binding(binding)
    names = ("runId", "packageId", "taskId", "attempt", "semanticOperationId")
    identity = {name: binding[name] for name in names}
    snapshot = current_source_snapshot(selection)
    _require(
        not any(
            pool["binding"] and all(pool["binding"][name] == value for name, value in identity.items())
            for pool in snapshot["projection"]["windowPools"]
        ),
        "scoped-usage-window-conflict",
        "prospective operation already has an original window",
    )
    return {
        "status": "UNUSED_DECLARED_SOURCE_OPERATION",
        "identityTuple": identity,
        "financialHeadSha256": snapshot["current"]["headSha256"],
        "executionAuthorized": False,
        "actualCapConformance": "UNAVAILABLE",
    }

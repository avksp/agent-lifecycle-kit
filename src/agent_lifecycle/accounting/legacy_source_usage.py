"""Translator for the unchanged release 2.16 source ledger and wire formats.

This module preserves original bytes, hashes, clocks, UNKNOWN holds and refusal
semantics. It registers no new ledger route and never publishes a financial head.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar
from typing import cast as _validated_cast

from agent_lifecycle.accounting.declared_ledger import DeclaredLedgerContext
from agent_lifecycle.accounting.usage_types import (
    read_source_reference as _read_ref,
)
from agent_lifecycle.accounting.usage_types import (
    require_source_usage as _require,
)
from agent_lifecycle.accounting.usage_types import (
    serialize_source_registry as _projection_bytes,
)
from agent_lifecycle.accounting.usage_types import (
    source_reference as _ref,
)
from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object
from agent_lifecycle.contracts.authority_io import read_authority_bytes
from agent_lifecycle.contracts.scoped_usage_schemas import (
    MAX_SAFE_INTEGER,
    MAX_SOURCE_USAGE_BINDINGS,
    MAX_SOURCE_USAGE_BYTES,
    SOURCE_CURRENT_REGISTRY,
    SOURCE_INVALID_ANNOTATION_REGISTRY,
    SOURCE_RECOVERY_REGISTRY,
    SOURCE_USAGE_ROLES,
    validate_source_window_binding,
)

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
        if pool is None or pool["binding"] is not None or pool["closeRef"] is None:
            raise LifecycleError("scoped-usage-recovery-invalid", "selected historical pool is incomplete or eligible")
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


def _declared_context(selection: dict[str, Any]) -> DeclaredLedgerContext:
    """Reuse checked immutable route values within one frozen source selection."""

    from agent_lifecycle.accounting.declared_ledger import resolve_declared_ledger_context

    if "declaredLedgerContext" not in selection:
        selection["declaredLedgerContext"] = resolve_declared_ledger_context(
            selection["root"],
            selection["manifest"],
            selection["policy"]["openingRef"],
        )
    return selection["declaredLedgerContext"]


@dataclass(frozen=True)
class LegacySourceUsage:
    """Read the sole registered legacy route, retaining its independent checks."""

    selection: dict[str, Any]
    head_path: ClassVar[str] = _HEAD_PATH

    def read_current(self) -> dict[str, Any]:
        from agent_lifecycle.accounting.declared_ledger import read_declared_ledger

        return read_declared_ledger(
            _declared_context(self.selection),
            ancestor_head_sha256=self.selection["policy"]["openingRef"]["sha256"],
        )

    def project(self, current: dict[str, Any]) -> dict[str, Any]:
        return _projection(self.selection, current)


def declared_source_context(selection: dict[str, Any]) -> DeclaredLedgerContext:
    """Accounting-internal compatibility route for frozen recovery validation."""
    return _declared_context(selection)


# Public translator bindings preserve immutable historical executable fixtures.
LEGACY_HEAD_PATH = _HEAD_PATH
LEGACY_WINDOW_PATTERN = _WINDOW
validate_legacy_window = _window

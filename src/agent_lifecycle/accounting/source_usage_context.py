"""Checked Source usage inputs shared by policy and workflow consumers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import cast as _validated_cast

from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object
from agent_lifecycle.contracts.authority_io import read_authority_bytes
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.scoped_usage_schemas import (
    MAX_CURRENT_SOURCE_REGISTRY_BYTES,
    MAX_SOURCE_USAGE_BYTES,
    SOURCE_RECOVERY_POLICY_V3,
    SOURCE_USAGE_MODE,
    validate_source_conflict_disposition_shape,
    validate_source_conflict_grant_shape,
    validate_source_invalid_annotation_disposition_shape,
    validate_source_invalid_annotation_review_shape,
    validate_source_invalid_annotation_subject_shape,
    validate_source_recovery_policy_shape,
    validate_source_ref_shape,
    validate_source_registry_prefix_shape,
    validate_source_usage_policy_shape,
)
from agent_lifecycle.freeze.package_integrity import verify_plan_package_integrity


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise LifecycleError(code, message)


def _ref(path: str, raw: bytes) -> dict[str, Any]:
    return {"path": path, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _read_ref(root: Path, ref: dict[str, Any], *, limit: int) -> bytes:
    validate_source_ref_shape(ref)
    _require(ref["bytes"] <= limit, "scoped-usage-ref-invalid", "reference exceeds its bound")
    raw = read_authority_bytes(root / ref["path"], root=root, max_bytes=limit)
    _require(_ref(ref["path"], raw) == ref, "scoped-usage-ref-invalid", "reference bytes differ")
    return raw


def _load_frozen_source_context(
    repository_root: Path,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    """Select opt-in from actual adopted package bytes, not receipt or state mode."""

    root = Path(repository_root).absolute()
    manifest_path = state.get("manifestPath")
    if not manifest_path:
        return None
    path = normalize_repo_path(manifest_path, label="current frozen manifest")
    raw_manifest = read_authority_bytes(root / path, root=root, max_bytes=1_048_576)
    manifest = load_json_object(raw_manifest, label="current frozen manifest")
    runtime = manifest.get("runtimePolicy")
    if not isinstance(runtime, dict) or "sourceUsageCompletion" not in runtime:
        return None
    policy = validate_source_usage_policy_shape(runtime["sourceUsageCompletion"])
    lock_path = str(Path(path).with_name("plan.lock.json"))
    lock = load_json_object(
        read_authority_bytes(root / lock_path, root=root, max_bytes=1_048_576), label="current frozen lock"
    )
    verify_plan_package_integrity(manifest, lock, repository_root=root)
    package = manifest.get("package", {})
    _require(
        manifest.get("status") == "FROZEN"
        and state.get("planDigest") == canonical_digest(manifest)
        and state.get("planRevision") == manifest.get("planRevision")
        and state.get("packageId") == package.get("id")
        and state.get("sourceRevision") == manifest.get("baseRevision", {}).get("sha"),
        "scoped-usage-plan-stale",
        "current frozen plan lineage differs",
    )
    entries = {entry["path"]: entry for entry in lock["entries"]}
    for key in ("openingRef", "sourceAuthoringRegistryRef"):
        ref = policy[key]
        _require(
            entries.get(ref["path"]) == ref,
            "scoped-usage-policy-unbound",
            "limited policy input is outside the exact frozen inventory",
        )
    opening_raw = _read_ref(root, policy["openingRef"], limit=MAX_SOURCE_USAGE_BYTES)
    prefix_raw = _read_ref(root, policy["sourceAuthoringRegistryRef"], limit=MAX_SOURCE_USAGE_BYTES)
    opening = load_json_object(opening_raw, label="frozen financial opening")
    prefix = validate_source_registry_prefix_shape(load_json_object(prefix_raw, label="frozen source prefix"))
    _require(
        prefix["openingHeadSha256"] == policy["openingRef"]["sha256"],
        "scoped-usage-opening-mismatch",
        "registry prefix selects another opening",
    )
    registry_byte_limit = MAX_SOURCE_USAGE_BYTES
    capacity_path = str(Path(path).with_name("source-usage-registry-capacity.json"))
    if capacity_path in entries:
        _require(
            capacity_path in manifest.get("planFiles", []),
            "scoped-usage-policy-unbound",
            "registry capacity is outside the frozen inventory",
        )
        capacity_raw = _read_ref(root, entries[capacity_path], limit=MAX_SOURCE_USAGE_BYTES)
        capacity = load_json_object(capacity_raw, label="frozen registry capacity")
        _require(
            capacity.get("schemaVersion") == "alk-source-usage-registry-capacity-amendment.v1"
            and capacity.get("originalCurrentRegistryMaxBytes") == MAX_SOURCE_USAGE_BYTES
            and capacity.get("currentRegistryMaxBytes") == MAX_CURRENT_SOURCE_REGISTRY_BYTES
            and capacity.get("frozenOpeningAndPrefixMaxBytes") == MAX_SOURCE_USAGE_BYTES
            and capacity.get("usageReceiptMaxBytes") == MAX_SOURCE_USAGE_BYTES,
            "scoped-usage-capacity-invalid",
            "frozen registry capacity differs from its contract",
        )
        registry_byte_limit = MAX_CURRENT_SOURCE_REGISTRY_BYTES
    selection = {
        "root": root,
        "manifest": manifest,
        "lock": lock,
        "policy": policy,
        "policyDigest": canonical_digest(policy),
        "opening": opening,
        "prefix": prefix,
        "prefixRaw": prefix_raw,
        "registryByteLimit": registry_byte_limit,
    }
    _load_source_recovery(selection, entries, path)
    return selection


def load_frozen_source_policy(
    repository_root: Path,
    state: dict[str, Any],
    task: dict[str, Any],
    *,
    adapter_id: str | None = None,
    adapter_host: str | None = None,
) -> dict[str, Any] | None:
    """Select task eligibility separately from shared historical context."""

    selected = _load_frozen_source_context(repository_root, state)
    if selected is None:
        return None
    policy, manifest = selected["policy"], selected["manifest"]
    _require(
        task.get("id") in policy["taskIds"]
        and any(row.get("id") == task.get("id") for row in manifest.get("workstreams", []) if isinstance(row, dict)),
        "scoped-usage-policy-scope-mismatch",
        "task is outside the frozen limited scope",
    )
    if adapter_id is not None:
        _require(
            policy["adapterId"] == adapter_id,
            "scoped-usage-policy-scope-mismatch",
            "adapter differs from frozen policy",
        )
    if adapter_host is not None:
        _require(
            policy["adapterHost"] == adapter_host,
            "scoped-usage-policy-scope-mismatch",
            "host differs from frozen policy",
        )
    return selected


def _declared_context(selection: dict[str, Any]):
    """Reuse checked immutable route values within one frozen source selection."""

    from agent_lifecycle.accounting.declared_ledger import resolve_declared_ledger_context

    if "declaredLedgerContext" not in selection:
        selection["declaredLedgerContext"] = resolve_declared_ledger_context(
            selection["root"],
            selection["manifest"],
            selection["policy"]["openingRef"],
        )
    return selection["declaredLedgerContext"]


def _load_source_recovery(selection: dict[str, Any], entries: dict[str, Any], path: str) -> None:
    """Select independently authorized groups; no eligibility effects during loading."""
    recovery_path = str(Path(path).with_name("source-usage-conflict-recovery.json"))
    if recovery_path not in entries:
        _require(
            not (selection["root"] / recovery_path).exists() and not (selection["root"] / recovery_path).is_symlink(),
            "scoped-usage-recovery-unbound",
            "unlisted recovery selector exists",
        )
        annotation_path = str(Path(path).with_name("source-invalid-annotation-recovery.json"))
        _require(
            annotation_path not in entries
            and not (selection["root"] / annotation_path).exists()
            and not (selection["root"] / annotation_path).is_symlink(),
            "scoped-usage-recovery-unbound",
            "annotation recovery requires original recovery",
        )
        return
    _require(
        recovery_path in selection["manifest"]["planFiles"],
        "scoped-usage-recovery-unbound",
        "recovery outside frozen inventory",
    )
    policy = validate_source_recovery_policy_shape(
        load_json_object(
            _read_ref(selection["root"], entries[recovery_path], limit=MAX_SOURCE_USAGE_BYTES),
            label="frozen recovery policy",
        )
    )
    _require(
        policy["schemaVersion"] != SOURCE_RECOVERY_POLICY_V3,
        "scoped-usage-recovery-invalid",
        "annotation policy must use its separate frozen selector",
    )
    _require(
        policy["originalOpeningRef"] == selection["policy"]["openingRef"],
        "scoped-usage-recovery-invalid",
        "recovery changes original opening",
    )
    refs = [policy["dispositionRef"]] if "dispositionRef" in policy else policy["dispositionRefs"]
    groups = []
    identities = set()
    windows: set[str] = set()
    for ref in refs:
        _require(
            entries.get(ref["path"]) == ref, "scoped-usage-recovery-unbound", "disposition is outside frozen inventory"
        )
        group = _load_source_disposition(selection, policy, ref)
        disposition = group["disposition"]
        identity = tuple(
            disposition["identityTuple"][key]
            for key in ("runId", "packageId", "taskId", "attempt", "semanticOperationId")
        )
        group_windows = {row["windowId"] for row in disposition["originalWindows"]}
        _require(
            identity not in identities and not windows.intersection(group_windows),
            "scoped-usage-recovery-invalid",
            "repeated or overlapping recovery groups",
        )
        identities.add(identity)
        windows.update(group_windows)
        groups.append(group)
    if "dispositionRef" in policy:
        selection["recovery"] = {"policy": policy, "disposition": groups[0]["disposition"], "grant": groups[0]["grant"]}
    else:
        selection["recovery"] = {"policy": policy, "groups": groups}
    _load_invalid_annotation_policy(selection, entries, path, policy, windows)


def _load_invalid_annotation_policy(selection, entries, path, original_policy, conflict_windows):
    annotation_path = str(Path(path).with_name("source-invalid-annotation-recovery.json"))
    root = selection["root"]
    if annotation_path not in entries:
        _require(
            not (root / annotation_path).exists() and not (root / annotation_path).is_symlink(),
            "scoped-usage-recovery-unbound",
            "unlisted annotation selector exists",
        )
        return
    _require(
        annotation_path in selection["manifest"]["planFiles"],
        "scoped-usage-recovery-unbound",
        "annotation selector outside frozen inventory",
    )
    policy = validate_source_recovery_policy_shape(
        load_json_object(
            _read_ref(root, entries[annotation_path], limit=MAX_SOURCE_USAGE_BYTES),
            label="frozen invalid annotation policy",
        )
    )
    original_refs = (
        [original_policy["dispositionRef"]]
        if "dispositionRef" in original_policy
        else original_policy["dispositionRefs"]
    )
    _require(
        policy["schemaVersion"] == SOURCE_RECOVERY_POLICY_V3
        and policy["originalOpeningRef"] == original_policy["originalOpeningRef"]
        and policy["dispositionRefs"] == original_refs,
        "scoped-usage-recovery-invalid",
        "annotation policy changes original opening or conflicts",
    )
    recovery = _load_invalid_annotation_disposition(selection, policy, entries)
    selected_windows = {row["windowId"] for row in recovery["disposition"]["originalWindows"]}
    _require(
        not selected_windows.intersection(conflict_windows),
        "scoped-usage-recovery-invalid",
        "annotation and conflict windows overlap",
    )
    selection["invalidAnnotationRecovery"] = recovery


def _load_invalid_annotation_disposition(selection, policy, entries):
    root = selection["root"]

    def frozen(reference):
        _require(
            entries.get(reference["path"]) == reference,
            "scoped-usage-recovery-unbound",
            "annotation authority outside frozen inventory",
        )
        return _read_ref(root, reference, limit=MAX_SOURCE_USAGE_BYTES)

    disposition_ref = policy["invalidAnnotationDispositionRef"]
    disposition = validate_source_invalid_annotation_disposition_shape(
        load_json_object(frozen(disposition_ref), label="frozen invalid annotation disposition")
    )
    subject = validate_source_invalid_annotation_subject_shape(
        load_json_object(frozen(disposition["specificationSubjectRef"]), label="annotation specification subject")
    )
    report = validate_source_invalid_annotation_review_shape(
        load_json_object(frozen(disposition["specificationReviewRef"]), label="independent annotation contract review")
    )
    frozen(disposition["specificationRef"])
    frozen(subject["prospectiveAdmissionProcedureRef"])
    decision = load_json_object(frozen(disposition["scopeDecisionRef"]), label="approved annotation scope")
    expected_decision = (
        selection["manifest"]
        .get("runtimePolicy", {})
        .get("sourceWindowConflictRecovery", {})
        .get("invalidAnnotationScopeDecisionRef")
    )
    _require(
        disposition["originalOpeningRef"] == policy["originalOpeningRef"] == subject["originalOpeningRef"]
        and disposition["originalWindows"] == subject["originalWindows"]
        and disposition["specificationRef"] == subject["contractRef"]
        and disposition["scopeDecisionRef"] == subject["scopeDecisionRef"] == expected_decision
        and subject["sourceRevision"] == selection["manifest"]["baseRevision"]["sha"]
        and report["subjectDigest"] == canonical_digest(subject)
        and decision.get("status") == "USER_APPROVED_A_EXACT_HISTORICAL_ANNOTATION_RECOVERY"
        and decision.get("answer") == "A — точечное восстановление учёта (рекомендуется)",
        "scoped-usage-recovery-invalid",
        "annotation authority lineage or approved scope differs",
    )
    from agent_lifecycle.accounting.declared_ledger import read_declared_ledger

    primary = Path(read_declared_ledger(_declared_context(selection))["primaryCheckout"])
    _read_ref(primary, disposition["authorizingFinancialHeadRef"], limit=MAX_SOURCE_USAGE_BYTES)
    return {"policy": policy, "dispositionRef": disposition_ref, "disposition": disposition}


def _load_source_disposition(selection: dict[str, Any], policy: dict[str, Any], ref: dict[str, Any]) -> dict[str, Any]:
    """Validate one exact external frozen negative authority independently."""
    disposition = validate_source_conflict_disposition_shape(
        load_json_object(_read_ref(selection["root"], ref, limit=MAX_SOURCE_USAGE_BYTES), label="frozen disposition")
    )
    _require(
        policy["schemaVersion"] != "alk-source-usage-conflict-recovery-policy.v1"
        or disposition["schemaVersion"] == "alk-source-window-conflict-disposition.v1",
        "scoped-usage-recovery-invalid",
        "legacy recovery policy requires legacy disposition",
    )
    from agent_lifecycle.accounting.declared_ledger import read_declared_ledger

    primary = Path(read_declared_ledger(_declared_context(selection))["primaryCheckout"])

    def external(reference: dict[str, Any], label: str) -> dict[str, Any]:
        return load_json_object(_read_ref(primary, reference, limit=65_536), label=label)

    grant = validate_source_conflict_grant_shape(external(disposition["authorizingGrantRef"], "external repair grant"))
    report = external(disposition["authorizingReviewRef"], "independent repair plan review")
    plan = external(grant["planRef"], "authorizing repair plan")
    lock = external(grant["lockRef"], "authorizing repair lock")
    spec = external(grant["specificationRef"], "authorizing repair specification")
    # These are historical issuance inputs, not assertions that changed source still has before bytes.
    _require(
        disposition["originalOpeningRef"] == policy["originalOpeningRef"]
        and disposition["authorizingFinancialHeadRef"] == grant["authorizingFinancialHeadRef"]
        and disposition["authorizingReviewRef"] == grant["planReviewRef"]
        and grant["sourceRevision"] == selection["manifest"]["baseRevision"]["sha"],
        "scoped-usage-recovery-invalid",
        "disposition/grant lineage differs",
    )
    _require(
        plan.get("status") == "FROZEN"
        and lock.get("manifestHash") == canonical_digest(plan)
        and report.get("schemaVersion") == "agent-plan-review.v1"
        and report.get("verdict") == "READY_TO_FREEZE"
        and report.get("fullReview") is True
        and report.get("findings") == []
        and report.get("reviewedPlanHash") == canonical_digest(plan)
        and report.get("packageId") == grant["repairPackageId"] == plan.get("package", {}).get("id")
        and report.get("planRevision") == plan.get("planRevision")
        and report.get("reviewer", {}).get("independent") is True
        and report.get("reviewer", {}).get("id") == grant["independentReviewerId"],
        "scoped-usage-recovery-invalid",
        "external grant has no exact reviewed frozen plan",
    )
    from agent_lifecycle.freeze.package_integrity import verify_plan_lock_envelope

    verify_plan_lock_envelope(plan, lock)
    inventory = {row["path"]: row for row in lock["entries"]}
    for reference in (
        grant["specificationRef"],
        grant["specificationReviewRef"],
        grant["planReviewRef"],
        grant["planRef"],
        grant["inventoryRef"],
    ):
        _require(
            inventory.get(reference["path"]) == reference,
            "scoped-usage-recovery-invalid",
            "grant authority outside original exact lock",
        )
    basis = external(disposition["basisReviewRef"], "original negative independent review")
    if disposition["schemaVersion"] == "alk-source-window-conflict-disposition.v1":
        _require(
            basis.get("verdict") == "CHANGES_REQUIRED"
            and spec.get("schemaVersion") == "alk-source-window-conflict-recovery-specification.v2",
            "scoped-usage-recovery-invalid",
            "negative recovery basis differs",
        )
    else:
        _require(
            spec.get("schemaVersion") == "alk-source-window-conflict-recovery-specification.v3"
            and disposition["basisReviewRef"] == disposition["authorizingReviewRef"]
            and basis == report,
            "scoped-usage-recovery-invalid",
            "integrated recovery basis differs",
        )
        wire = spec.get("wireContracts", {}).get("disposition", {})
        refusal = external(wire.get("basisRefusalRef"), "original pre-effect refusal")
        _read_ref(primary, wire.get("actualGuardFailureRef"), limit=65_536)
        _require(
            refusal.get("code") == "scoped-usage-window-conflict"
            and refusal.get("financialAdmissionPublished") is True
            and refusal.get("sourceExecutionAdmitted") is False
            and refusal.get("originalWindowIds") == spec.get("exactConflict", {}).get("originalWindowIds")
            and all(
                type(refusal.get(key)) is int and refusal[key] == 0
                for key in (
                    "newProductWrites",
                    "testInvocations",
                    "modelInvocations",
                    "nativeInvocations",
                    "holdReleased",
                )
            ),
            "scoped-usage-recovery-invalid",
            "reviewed pre-effect refusal differs",
        )
    expected = spec.get("exactConflict", {})
    windows = disposition["originalWindows"]
    _require(
        disposition["identityTuple"] == expected.get("identityTuple")
        and [row["windowId"] for row in windows] == expected.get("originalWindowIds")
        and [reference for row in windows for reference in (row["admissionRef"], row["costRef"])]
        == expected.get("originalRecords")
        and (
            disposition["schemaVersion"] != "alk-source-window-conflict-disposition.v1"
            or disposition["basisReviewRef"]
            == spec.get("wireContracts", {}).get("disposition", {}).get("basisReviewRef")
        ),
        "scoped-usage-recovery-invalid",
        "disposition is not the exact reviewed conflict",
    )
    admission = external(grant["admissionRef"], "original repair admission")
    _require(
        "sourceUsageBinding" not in admission
        and admission.get("repairOperationId") == grant["repairOperationId"]
        and admission.get("inputSubjectDigest") == grant["inputSubjectDigest"]
        and admission.get("absoluteDeadlineUtc") == grant["absoluteDeadlineUtc"]
        and admission.get("tokenCap") == grant["tokenCap"]
        and admission.get("protectedCloseoutTokens") == grant["protectedCloseoutTokens"],
        "scoped-usage-recovery-invalid",
        "repair admission/grant differs",
    )
    head_raw = _read_ref(primary, disposition["authorizingFinancialHeadRef"], limit=65_536)
    head = load_json_object(head_raw, label="authorizing admitted head")
    _require(
        head.get("sourcePath") == grant["admissionRef"]["path"]
        and head.get("sourceSha256") == grant["admissionRef"]["sha256"],
        "scoped-usage-recovery-invalid",
        "authorizing head is not the original admitted grant",
    )
    return {"dispositionRef": ref, "disposition": disposition, "grant": grant}


@dataclass(frozen=True)
class SourceUsageContext:
    """Internal immutable value; its constructor is not an authority boundary."""

    manifestDigest: str
    stateDigest: str
    runId: str
    taskId: str
    adapterId: str
    adapterHost: str
    policyDigest: str
    appliesToTask: bool
    allowedModelClasses: tuple[str, ...]
    usageMode: str


def load_source_usage_context(
    repository_root: Path,
    manifest: dict[str, Any],
    state: dict[str, Any],
    task: dict[str, Any],
    adapter_id: str,
    adapter_host: str,
) -> SourceUsageContext | None:
    """Read frozen authority independently before deriving a policy value."""

    selected = _load_frozen_source_context(repository_root, state)
    runtime = manifest.get("runtimePolicy")
    opted_in = isinstance(runtime, dict) and "sourceUsageCompletion" in runtime
    if selected is None:
        _require(not opted_in, "scoped-usage-policy-missing", "Source requires current frozen selection")
        return None
    _require(
        canonical_digest(selected["manifest"]) == canonical_digest(manifest),
        "scoped-usage-policy-missing",
        "caller manifest differs from frozen selection",
    )
    task_id = task.get("id")
    _require(
        any(row == task for row in state.get("tasks", []) if isinstance(row, dict))
        and any(row.get("id") == task_id for row in manifest.get("workstreams", []) if isinstance(row, dict)),
        "scoped-usage-policy-scope-mismatch",
        "task differs from current state or plan",
    )
    policy = selected["policy"]
    applies = task_id in policy["taskIds"]
    if applies:
        _require(
            policy["adapterId"] == adapter_id and policy["adapterHost"] == adapter_host,
            "scoped-usage-policy-scope-mismatch",
            "adapter/host differs from frozen policy",
        )
    return SourceUsageContext(
        manifestDigest=canonical_digest(manifest),
        stateDigest=canonical_digest(state),
        runId=state["runId"],
        taskId=_validated_cast(str, task_id),
        adapterId=adapter_id,
        adapterHost=adapter_host,
        policyDigest=selected["policyDigest"],
        appliesToTask=applies,
        allowedModelClasses=tuple(policy["allowedModelClasses"]),
        usageMode=SOURCE_USAGE_MODE,
    )


def validate_source_usage_context(
    context: SourceUsageContext | None,
    *,
    manifest: dict[str, Any],
    state: dict[str, Any],
    task_id: str,
    adapter_id: str,
    adapter_host: str,
) -> SourceUsageContext | None:
    """Compare immutable values and digests only; perform no authority reads."""

    runtime = manifest.get("runtimePolicy")
    if not isinstance(runtime, dict) or "sourceUsageCompletion" not in runtime:
        _require(context is None, "scoped-usage-context-rebound", "unexpected Source context")
        return None
    _require(
        isinstance(context, SourceUsageContext),
        "scoped-usage-policy-missing",
        "Source policy requires a checked context",
    )
    context = _validated_cast(SourceUsageContext, context)
    policy = validate_source_usage_policy_shape(runtime["sourceUsageCompletion"])
    _require(
        context.manifestDigest == canonical_digest(manifest)
        and context.stateDigest == canonical_digest(state)
        and context.runId == state.get("runId")
        and context.taskId == task_id
        and context.adapterId == adapter_id
        and context.adapterHost == adapter_host
        and context.policyDigest == canonical_digest(policy)
        and context.appliesToTask is (task_id in policy["taskIds"])
        and type(context.allowedModelClasses) is tuple
        and context.allowedModelClasses == tuple(policy["allowedModelClasses"])
        and context.usageMode == SOURCE_USAGE_MODE,
        "scoped-usage-context-rebound",
        "Source context differs from current inputs",
    )
    if context.appliesToTask:
        _require(
            policy["adapterId"] == adapter_id and policy["adapterHost"] == adapter_host,
            "scoped-usage-policy-scope-mismatch",
            "adapter/host differs from Source scope",
        )
    return context

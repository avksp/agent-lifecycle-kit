"""Frozen, source-only usage validation against the existing declared ledger.

The financial selector is independent of producer references. Returned PASS
means the selected limited contract matched, never measured cap conformance.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import cast as _validated_cast

from agent_lifecycle.accounting import legacy_source_usage
from agent_lifecycle.accounting.source_usage_context import (
    load_frozen_source_policy as load_frozen_source_policy,
)
from agent_lifecycle.accounting.source_usage_context import (
    load_frozen_usage_context,
)
from agent_lifecycle.accounting.usage_types import (
    UsageContext,
)
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
from agent_lifecycle.contracts import canonical_digest, load_json_object
from agent_lifecycle.contracts.authority_io import create_authority_bytes, read_authority_bytes
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.scoped_usage_schemas import (
    MAX_CURRENT_SOURCE_REGISTRY_BYTES as MAX_CURRENT_SOURCE_REGISTRY_BYTES,
)
from agent_lifecycle.contracts.scoped_usage_schemas import (
    MAX_SOURCE_USAGE_BYTES,
    SOURCE_USAGE_MODE,
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

# Compatibility exports for already frozen historical executable fixtures only.
# Workflow operations below consume the selected neutral reader instead.
_HEAD_PATH = legacy_source_usage.LEGACY_HEAD_PATH
_WINDOW = legacy_source_usage.LEGACY_WINDOW_PATTERN
_window = legacy_source_usage.validate_legacy_window


def current_source_snapshot(selection: UsageContext) -> dict[str, Any]:
    """Observe independently selected A/B financial heads; no automatic retry."""

    current = selection.source.read_current()
    projection = selection.source.project(current)
    after = selection.source.read_current()
    _require(
        current["headRaw"] == after["headRaw"] and current["ancestryHeadSha256s"] == after["ancestryHeadSha256s"],
        "scoped-usage-frontier-stale",
        "financial frontier changed during validation",
    )
    return {"current": current, "projection": projection, "projectionBytes": _projection_bytes(projection)}


def require_snapshot_current(selection: UsageContext, snapshot: dict[str, Any]) -> None:
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
    selection = _validated_cast(UsageContext, selection)
    return _emit_registry_for_context(selection, task)


@dataclass(frozen=True)
class PreparedSourceRegistry:
    """A declared observation, not a persisted receipt or host attestation."""

    selection: UsageContext
    snapshot: dict[str, Any]
    reference: dict[str, Any]

    def persist(self) -> None:
        require_snapshot_current(self.selection, self.snapshot)
        raw = self.snapshot["projectionBytes"]
        _require(
            self.reference == _ref(self.reference["path"], raw), "scoped-usage-ref-invalid", "prepared registry changed"
        )
        try:
            create_authority_bytes(self.selection.root / self.reference["path"], raw, root=self.selection.root)
        except FileExistsError:
            _read_ref(self.selection.root, self.reference, limit=self.selection.registry_byte_limit)
        require_snapshot_current(self.selection, self.snapshot)


def _prepare_registry_for_context(selection: UsageContext, task: dict[str, Any]) -> PreparedSourceRegistry:
    snapshot = current_source_snapshot(selection)
    raw = snapshot["projectionBytes"]
    _require(
        len(raw) <= selection.registry_byte_limit, "scoped-usage-ref-invalid", "prepared registry exceeds its reader"
    )
    require_snapshot_current(selection, snapshot)
    return PreparedSourceRegistry(selection, snapshot, _registry_ref(task, raw))


def _emit_registry_for_context(
    selection: UsageContext,
    task: dict[str, Any],
    *,
    prepared_registries: list[PreparedSourceRegistry] | None = None,
) -> dict[str, Any]:
    """Prepare historical context without granting task limited eligibility."""
    prepared = _prepare_registry_for_context(selection, task)
    if prepared_registries is None:
        prepared.persist()
    else:
        prepared_registries.append(prepared)
    return prepared.reference


def validate_limited_source_usage(
    repository_root: Path,
    state: dict[str, Any],
    task: dict[str, Any],
    receipt: dict[str, Any],
    *,
    _prepared_registry_bytes: bytes | None = None,
) -> dict[str, Any]:
    validate_source_usage_receipt_shape(receipt)
    selection = load_frozen_source_policy(
        repository_root, state, task, adapter_id=task.get("adapterId"), adapter_host=receipt["host"]
    )
    _require(selection is not None, "scoped-usage-policy-missing", "receipt cannot select limited mode")
    selection = _validated_cast(UsageContext, selection)
    policy = selection.policy
    route = task.get("attemptModelRoute") or task.get("modelRoute") or {}
    adopted = (
        task.get("attemptRiskExecutionProfile")
        or task.get("riskExecutionProfile")
        or task.get("attemptExecutionStrategy")
        or task.get("executionStrategy")
        or {}
    )
    _require(
        adopted.get("sourceUsagePolicyDigest") == selection.policy_digest
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
        receipt["policyDigest"] == selection.policy_digest
        and receipt["sourceAuthoringRegistryDigest"] == policy["sourceAuthoringRegistryRef"]["sha256"],
        "scoped-usage-policy-mismatch",
        "receipt selects different frozen source inputs",
    )
    _require(
        (receipt["actorId"], "coordinator")
        in {(owner["actorId"], owner["role"]) for owner in selection.prefix["ownerBindings"]},
        "scoped-usage-current-identity-mismatch",
        "actor is not the frozen source coordinator",
    )
    snapshot = current_source_snapshot(selection)
    current, projection = snapshot["current"], snapshot["projection"]
    _require(
        receipt["ledgerRef"] == _ref(selection.source.head_path, current["headRaw"]),
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
        (
            _read_ref(selection.root, expected_registry, limit=selection.registry_byte_limit)
            if _prepared_registry_bytes is None
            else _prepared_registry_bytes
        )
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
        "sourceUsagePolicyDigest": selection.policy_digest,
        "actorId": receipt["actorId"],
    }
    _require(
        all(binding[key] == value for key, value in expected.items()),
        "scoped-usage-current-identity-mismatch",
        "original admission belongs to another actor or attempt",
    )
    primary = Path(current["primaryCheckout"])
    original_refs = projection["records"]
    known_refs = [row["sourceRef"] for row in original_refs] + selection.prefix["historicalSourceRefs"]
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
            _read_ref(selection.root, ref, limit=MAX_SOURCE_USAGE_BYTES)
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
            "policyDigest": selection.policy_digest,
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
    *,
    prepared_registries: list[PreparedSourceRegistry] | None = None,
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
    selection = _validated_cast(UsageContext, selection)
    snapshot = current_source_snapshot(selection)
    original_registry = load_json_object(
        _read_ref(root, receipt["currentRegistryRef"], limit=selection.registry_byte_limit),
        label="original source registry",
    )
    _require(
        receipt["ledgerRef"]["path"] == selection.source.head_path
        and receipt["ledgerRef"]["sha256"] in snapshot["current"]["ancestryHeadSha256s"]
        and original_registry.get("terminalHeadSha256") == receipt["ledgerRef"]["sha256"]
        and original_registry.get("frozenPrefixRawSha256") == selection.policy["sourceAuthoringRegistryRef"]["sha256"],
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
    prepared = _prepare_registry_for_context(selection, task)
    current_view = {
        **receipt,
        "ledgerRef": _ref(selection.source.head_path, snapshot["current"]["headRaw"]),
        "currentRegistryRef": prepared.reference,
    }
    validation = validate_limited_source_usage(
        root, state, task, current_view, _prepared_registry_bytes=prepared.snapshot["projectionBytes"]
    )
    if prepared_registries is None:
        prepared.persist()
    else:
        prepared_registries.append(prepared)
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
    selection = load_frozen_usage_context(repository_root, state)
    _require(selection is not None, "scoped-usage-policy-missing", "current source policy is absent")
    selection = _validated_cast(UsageContext, selection)
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
        assurance["ledgerRef"] == _ref(selection.source.head_path, snapshot["current"]["headRaw"])
        and assurance["currentRegistryRef"] == _registry_ref(task, snapshot["projectionBytes"]),
        "scoped-usage-frontier-stale",
        "observed source frontier changed before durable commit",
    )


def aggregate_source_usage_assurance(
    repository_root: Path,
    state: dict[str, Any],
    *,
    prepared_registries: list[PreparedSourceRegistry] | None = None,
) -> dict[str, Any] | None:
    observations = []
    historical = load_frozen_usage_context(repository_root, state)
    for task in state.get("tasks", []):
        if task.get("status") != "ACCEPTED":
            continue
        assurance = refresh_committed_source_assurance(
            repository_root, state, task, prepared_registries=prepared_registries
        )
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
                        "policyDigest": selection.policy_digest,
                        "guarantee": "LIMITED_DECLARED_SOURCE_ACCOUNTING",
                        "actualCapConformance": "UNAVAILABLE",
                        "actualTokens": None,
                        "financialClosure": "OPEN_UNAVAILABLE",
                        "ledgerRef": _ref(selection.source.head_path, snapshot["current"]["headRaw"]),
                        "currentRegistryRef": _emit_registry_for_context(
                            selection, task, prepared_registries=prepared_registries
                        ),
                        "sourceAuthoringRegistryDigest": selection.policy["sourceAuthoringRegistryRef"]["sha256"],
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


def require_source_operation_unused(selection: UsageContext, binding: dict[str, Any]) -> dict[str, Any]:
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

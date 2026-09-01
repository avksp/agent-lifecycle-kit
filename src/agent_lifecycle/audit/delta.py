"""Read-only rework delta audit and prior-finding disposition evidence."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_lifecycle.changesets import capture_task_change_set, require_current_task_change_set
from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object, sha256_hex
from agent_lifecycle.contracts.finding_check_schemas import (
    FINDING_IMPACT_SCOPE_SCHEMA,
    validate_finding_check_binding,
    validate_finding_check_evidence,
    validate_finding_impact_scope,
)
from agent_lifecycle.contracts.ownership_paths import is_under_authority_path
from agent_lifecycle.contracts.paths import normalize_repo_path, read_stable_repository_file
from agent_lifecycle.freeze.locks import verify_plan_lock
from agent_lifecycle.quality.dependency_impact import (
    graph_from_report,
    module_paths_from_report,
    transitive_dependents,
    validate_module_dependency_report,
)
from agent_lifecycle.quality.validation_ladder import BUILT_IN_PROTECTED_PATH_PREFIXES
from agent_lifecycle.workflow.artifacts import package_root, require_artifact_identity, validate_attempt_history
from agent_lifecycle.workflow.selectors import find_task
from agent_lifecycle.workflow.state import load_state

DELTA_AUDIT_SCHEMA = "agent-rework-delta-audit-receipt.v1"
DELTA_AUDIT_VALIDATION_SCHEMA = "agent-rework-delta-audit-receipt-validation.v1"
FINDING_DISPOSITIONS = (
    "CONFIRMED_OPEN",
    "VERIFIED_CLOSED",
    "NOT_AFFECTED",
    "UNAVAILABLE",
    "APPROVAL_REQUIRED",
)
_FINAL_GATE_PREFIX = re.compile(r"^\[([^\]]+)\]")


def build_rework_delta_audit(
    *,
    manifest_path: Path,
    lock_path: Path,
    state_path: Path,
    task_id: str,
    dependency_report_path: Path,
    validation_selection_path: Path,
    finding_check_binding_paths: list[Path],
    finding_check_evidence_paths: list[Path],
) -> dict[str, Any]:
    """Derive adjacent attempts from state and build command-free delta evidence."""

    context = _load_attempt_context(manifest_path, lock_path, state_path, task_id)
    inputs = _load_delta_inputs(
        context,
        dependency_report_path=dependency_report_path,
        validation_selection_path=validation_selection_path,
        binding_paths=finding_check_binding_paths,
        evidence_paths=finding_check_evidence_paths,
    )
    dispositions, fallback_reasons = _finding_dispositions(context, inputs)
    body = _delta_receipt_body(context, inputs, dispositions, fallback_reasons)
    return {**body, "receiptDigest": canonical_digest(body)}


def _load_attempt_context(manifest_path: Path, lock_path: Path, state_path: Path, task_id: str) -> dict[str, Any]:
    manifest = read_json_object(manifest_path, label="plan manifest")
    lock = read_json_object(lock_path, label="plan lock")
    verify_plan_lock(manifest, lock)
    state = load_state(state_path)
    root = package_root(state_path, state)
    task = find_task(state, task_id)
    validate_attempt_history(state_path, state, task)
    _require_plan_lineage(manifest, lock, state)
    current_attempt = _positive_int(task.get("attempt"), "current task attempt")
    history = task.get("attemptHistory")
    if not isinstance(history, list) or not history:
        raise LifecycleError("delta-audit-history-missing", "delta audit requires an archived previous attempt")
    previous = history[-1]
    previous_attempt = _positive_int(previous.get("attempt"), "previous task attempt")
    if previous_attempt + 1 != current_attempt:
        raise LifecycleError("delta-audit-attempt-not-adjacent", "delta audit requires adjacent attempts")
    prior_audit_identity = previous.get("implementationAuditReport")
    if not isinstance(prior_audit_identity, dict):
        raise LifecycleError("delta-audit-prior-audit-missing", "previous attempt has no implementation audit")
    prior_audit = require_artifact_identity(root, prior_audit_identity, label="previous implementation audit")
    _require_prior_audit(prior_audit, state=state, task_id=task_id, attempt=previous_attempt)
    previous_snapshot = _snapshot_from_audit(prior_audit)
    current_result_identity = task.get("result")
    if not isinstance(current_result_identity, dict):
        raise LifecycleError("delta-audit-current-result-missing", "current attempt has no committed result")
    current_result = require_artifact_identity(root, current_result_identity, label="current task result")
    current_snapshot = capture_task_change_set(
        root,
        baseline=str(state.get("sourceRevision") or ""),
        write_paths=[path for path in task.get("writes", []) if isinstance(path, str)],
    )
    require_current_task_change_set(current_result, current_snapshot)
    return {
        "manifest": manifest,
        "lock": lock,
        "state": state,
        "root": root,
        "taskId": task_id,
        "previous": previous,
        "previousAttempt": previous_attempt,
        "currentAttempt": current_attempt,
        "priorAuditIdentity": prior_audit_identity,
        "currentResultIdentity": current_result_identity,
        "previousSnapshot": previous_snapshot,
        "currentSnapshot": current_snapshot,
        "attemptDelta": _attempt_delta(previous_snapshot, current_snapshot),
    }


def _load_delta_inputs(
    context: dict[str, Any],
    *,
    dependency_report_path: Path,
    validation_selection_path: Path,
    binding_paths: list[Path],
    evidence_paths: list[Path],
) -> dict[str, Any]:
    dependency_payload = read_json_object(dependency_report_path, label="module dependency report")
    nested_report = dependency_payload.get("dependencyReport")
    dependency_report = nested_report if isinstance(nested_report, dict) else dependency_payload
    dependency_validation = validate_module_dependency_report(dependency_report)
    dependency_fresh = dependency_validation["status"] == "PASS" and _dependency_sources_fresh(
        context["root"], dependency_report
    )
    selection = read_json_object(validation_selection_path, label="validation selection")
    selection_valid = _valid_selection(
        selection,
        manifest=context["manifest"],
        lock=context["lock"],
        state=context["state"],
        snapshot=context["currentSnapshot"],
    )
    return {
        "dependencyReport": dependency_report,
        "dependencyFresh": dependency_fresh,
        "selection": selection,
        "selectionValid": selection_valid,
        "bindings": _load_bindings(binding_paths),
        "evidence": _load_evidence(evidence_paths),
    }


def _finding_dispositions(context: dict[str, Any], inputs: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    fallback = []
    if not inputs["dependencyFresh"]:
        fallback.append("DEPENDENCY_REPORT_INVALID_OR_STALE")
    if not inputs["selectionValid"]:
        fallback.append("VALIDATION_SELECTION_INVALID_OR_STALE")
    delta_paths = context["attemptDelta"]["changedPaths"]
    if any(_protected_path(path) for path in delta_paths):
        fallback.append("PROTECTED_PATH")
    previous_paths = {entry["path"] for entry in context["previousSnapshot"]["entries"]}
    if set(context["currentSnapshot"]["changedFiles"]).difference(previous_paths):
        fallback.append("UNEXPECTED_DELTA_PATH")
    finding_ids = context["previous"].get("findingIds")
    if not isinstance(finding_ids, list) or not finding_ids:
        raise LifecycleError("delta-audit-findings-missing", "previous attempt has no remediation finding IDs")
    dispositions = []
    for finding_id in finding_ids:
        binding = inputs["bindings"].get(finding_id)
        evidence = inputs["evidence"].get(finding_id)
        disposition, reasons = _disposition_for_finding(
            finding_id,
            binding=binding,
            evidence=evidence,
            manifest=context["manifest"],
            state=context["state"],
            dependency_report=inputs["dependencyReport"] if inputs["dependencyFresh"] else None,
            delta_paths=delta_paths,
            selected_check_ids=set(inputs["selection"].get("selectedCheckIds", []))
            if inputs["selectionValid"]
            else set(),
        )
        dispositions.append(_finding_disposition(finding_id, disposition, reasons, binding, evidence))
        if disposition not in {"VERIFIED_CLOSED", "NOT_AFFECTED"}:
            fallback.extend(reasons or [disposition])
    return dispositions, sorted(set(fallback))


def _finding_disposition(
    finding_id: str,
    disposition: str,
    reasons: list[str],
    binding: dict[str, Any] | None,
    evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    scope = binding.get("scope") if isinstance(binding, dict) else None
    return {
        "findingId": finding_id,
        "findingDigest": binding.get("findingDigest") if isinstance(binding, dict) else None,
        "bindingDigest": binding.get("bindingDigest") if isinstance(binding, dict) else None,
        "scopeDigest": scope.get("scopeDigest") if isinstance(scope, dict) else None,
        "checkIdentity": binding.get("checkIdentity") if isinstance(binding, dict) else None,
        "evidenceDigest": evidence.get("evidenceDigest") if isinstance(evidence, dict) else None,
        "disposition": disposition,
        "reasons": reasons,
    }


def _delta_receipt_body(
    context: dict[str, Any],
    inputs: dict[str, Any],
    dispositions: list[dict[str, Any]],
    fallback_reasons: list[str],
) -> dict[str, Any]:
    state = context["state"]
    manifest = context["manifest"]
    lock = context["lock"]
    disposition = "DELTA_REVIEW_AVAILABLE" if not fallback_reasons else "FULL_AUDIT_REQUIRED"
    blockers = [{"code": "delta-audit-full-audit-required", "reason": reason} for reason in fallback_reasons]
    selection = inputs["selection"]
    return {
        "schemaVersion": DELTA_AUDIT_SCHEMA,
        "status": "PASS" if disposition == "DELTA_REVIEW_AVAILABLE" else "FAIL",
        "disposition": disposition,
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "taskId": context["taskId"],
        "previousAttempt": context["previousAttempt"],
        "currentAttempt": context["currentAttempt"],
        "planLineage": {
            "planRevision": state.get("planRevision"),
            "planDigest": state.get("planDigest"),
            "planLockDigest": canonical_digest(lock),
            "acceptanceDigest": canonical_digest(manifest.get("acceptance", {})),
            "finalAuditGatesDigest": canonical_digest(manifest.get("finalAuditGates", [])),
            "sourceRevision": state.get("sourceRevision"),
        },
        "attemptArtifacts": {
            "previousResult": context["previous"].get("result"),
            "previousReview": context["previous"].get("review"),
            "previousImplementationAudit": context["priorAuditIdentity"],
            "currentResult": context["currentResultIdentity"],
        },
        "attemptDelta": context["attemptDelta"],
        "findingDispositions": dispositions,
        "validationSelection": {
            "selectionDigest": selection.get("selectionDigest"),
            "level": selection.get("level"),
            "selectedCheckIds": selection.get("selectedCheckIds", []),
        },
        "dependencyReportDigest": inputs["dependencyReport"].get("reportDigest") if inputs["dependencyFresh"] else None,
        "commandsExecuted": False,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "authorityClaimed": False,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }


def validate_rework_delta_audit(receipt: dict[str, Any]) -> dict[str, Any]:
    """Validate immutable delta evidence without granting acceptance authority."""

    blockers: list[dict[str, Any]] = []
    expected_fields = {
        "schemaVersion",
        "status",
        "disposition",
        "runId",
        "packageId",
        "taskId",
        "previousAttempt",
        "currentAttempt",
        "planLineage",
        "attemptArtifacts",
        "attemptDelta",
        "findingDispositions",
        "validationSelection",
        "dependencyReportDigest",
        "commandsExecuted",
        "modelCallsStarted",
        "hostLaunchStarted",
        "authorityClaimed",
        "blockers",
        "productionPromotionClaimed",
        "receiptDigest",
    }
    if set(receipt) != expected_fields:
        blockers.append({"code": "delta-audit-shape-invalid"})
    if receipt.get("schemaVersion") != DELTA_AUDIT_SCHEMA:
        blockers.append({"code": "delta-audit-schema-invalid"})
    if receipt.get("disposition") not in {"DELTA_REVIEW_AVAILABLE", "FULL_AUDIT_REQUIRED", "BLOCKED"}:
        blockers.append({"code": "delta-audit-disposition-invalid"})
    dispositions = receipt.get("findingDispositions")
    if not isinstance(dispositions, list) or not dispositions:
        blockers.append({"code": "delta-audit-finding-dispositions-missing"})
        dispositions = []
    ids: list[str] = []
    for item in dispositions:
        if (
            not isinstance(item, dict)
            or set(item)
            != {
                "findingId",
                "findingDigest",
                "bindingDigest",
                "scopeDigest",
                "checkIdentity",
                "evidenceDigest",
                "disposition",
                "reasons",
            }
            or not isinstance(item.get("findingId"), str)
            or item.get("disposition") not in FINDING_DISPOSITIONS
            or not isinstance(item.get("reasons"), list)
        ):
            blockers.append({"code": "delta-audit-finding-disposition-invalid"})
            continue
        for field in ("findingDigest", "bindingDigest", "scopeDigest", "evidenceDigest"):
            if item.get(field) is not None and not _is_digest(item.get(field)):
                blockers.append({"code": "delta-audit-finding-identity-invalid", "field": field})
        if item.get("checkIdentity") is not None and not isinstance(item.get("checkIdentity"), dict):
            blockers.append({"code": "delta-audit-finding-identity-invalid", "field": "checkIdentity"})
        if item.get("disposition") == "NOT_AFFECTED" and any(
            not _is_digest(item.get(field)) for field in ("findingDigest", "bindingDigest", "scopeDigest")
        ):
            blockers.append({"code": "delta-audit-not-affected-proof-missing"})
        if item.get("disposition") == "VERIFIED_CLOSED" and not _is_digest(item.get("evidenceDigest")):
            blockers.append({"code": "delta-audit-verified-evidence-missing"})
        ids.append(item["findingId"])
    if ids != sorted(set(ids)):
        blockers.append({"code": "delta-audit-finding-dispositions-not-canonical"})
    previous_attempt = receipt.get("previousAttempt")
    current_attempt = receipt.get("currentAttempt")
    if (
        not isinstance(previous_attempt, int)
        or isinstance(previous_attempt, bool)
        or not isinstance(current_attempt, int)
        or isinstance(current_attempt, bool)
        or previous_attempt < 1
        or current_attempt != previous_attempt + 1
    ):
        blockers.append({"code": "delta-audit-attempt-not-adjacent"})
    _validate_receipt_plan_lineage(receipt.get("planLineage"), blockers)
    _validate_receipt_attempt_delta(receipt.get("attemptDelta"), blockers)
    authority_fields = {
        "commandsExecuted": False,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "authorityClaimed": False,
        "productionPromotionClaimed": False,
    }
    if any(receipt.get(key) is not value for key, value in authority_fields.items()):
        blockers.append({"code": "delta-audit-authority-boundary"})
    expected_status = "PASS" if receipt.get("disposition") == "DELTA_REVIEW_AVAILABLE" else "FAIL"
    if receipt.get("status") != expected_status:
        blockers.append({"code": "delta-audit-status-mismatch"})
    if expected_status == "PASS" and receipt.get("blockers") != []:
        blockers.append({"code": "delta-audit-open-blockers"})
    if expected_status == "FAIL" and not receipt.get("blockers"):
        blockers.append({"code": "delta-audit-fallback-reason-missing"})
    body = {key: value for key, value in receipt.items() if key != "receiptDigest"}
    if receipt.get("receiptDigest") != canonical_digest(body):
        blockers.append({"code": "delta-audit-digest-mismatch"})
    result = {
        "schemaVersion": DELTA_AUDIT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "receiptDisposition": receipt.get("disposition"),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**result, "validationDigest": canonical_digest(result)}


def _disposition_for_finding(
    finding_id: str,
    *,
    binding: dict[str, Any] | None,
    evidence: dict[str, Any] | None,
    manifest: dict[str, Any],
    state: dict[str, Any],
    dependency_report: dict[str, Any] | None,
    delta_paths: list[str],
    selected_check_ids: set[str],
) -> tuple[str, list[str]]:
    if binding is None:
        return "UNAVAILABLE", ["FINDING_CHECK_BINDING_MISSING"]
    validation = validate_finding_check_binding(binding)
    if validation["status"] != "PASS" or binding.get("findingId") != finding_id:
        return "UNAVAILABLE", ["FINDING_CHECK_BINDING_INVALID"]
    if binding.get("status") == "PROPOSED":
        return "APPROVAL_REQUIRED", ["FINDING_CHECK_APPROVAL_REQUIRED"]
    if binding.get("status") not in {"ACCEPTED", "IMPLEMENTED", "VERIFIED"}:
        return "UNAVAILABLE", ["FINDING_CHECK_NOT_ACTIVE"]
    check = binding.get("checkIdentity")
    check_id = check.get("id") if isinstance(check, dict) else None
    if check_id not in selected_check_ids:
        return "UNAVAILABLE", ["FINDING_CHECK_NOT_SELECTED"]
    if evidence is not None:
        evidence_validation = validate_finding_check_evidence(evidence, binding)
        if evidence_validation["status"] != "PASS":
            return "UNAVAILABLE", ["FINDING_CHECK_EVIDENCE_INVALID"]
        result = evidence.get("result")
        if result == "PASS" and result == binding.get("expectedResult"):
            scope_reasons = _scope_impact_reasons(
                finding_id,
                binding=binding,
                manifest=manifest,
                state=state,
                dependency_report=dependency_report,
                delta_paths=delta_paths,
            )
            return ("VERIFIED_CLOSED", []) if not scope_reasons else ("UNAVAILABLE", scope_reasons)
        if result == "FAIL":
            return "CONFIRMED_OPEN", ["FINDING_CHECK_FAILED"]
        return "UNAVAILABLE", ["FINDING_CHECK_BLOCKED"]
    reasons = _scope_impact_reasons(
        finding_id,
        binding=binding,
        manifest=manifest,
        state=state,
        dependency_report=dependency_report,
        delta_paths=delta_paths,
    )
    return ("NOT_AFFECTED", []) if not reasons else ("UNAVAILABLE", reasons)


def _scope_impact_reasons(
    finding_id: str,
    *,
    binding: dict[str, Any],
    manifest: dict[str, Any],
    state: dict[str, Any],
    dependency_report: dict[str, Any] | None,
    delta_paths: list[str],
) -> list[str]:
    scope = binding.get("scope")
    if not isinstance(scope, dict) or scope.get("schemaVersion") != FINDING_IMPACT_SCOPE_SCHEMA:
        return ["FINDING_IMPACT_SCOPE_MISSING"]
    expected = {
        "findingId": finding_id,
        "findingDigest": binding.get("findingDigest"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
    }
    if validate_finding_impact_scope(scope, expected=expected)["status"] != "PASS":
        return ["FINDING_IMPACT_SCOPE_INVALID_OR_STALE"]
    if dependency_report is None:
        return ["DEPENDENCY_REPORT_INVALID_OR_STALE"]
    if not _scope_references_exist(scope, manifest):
        return ["FINDING_IMPACT_SCOPE_REFERENCE_MISSING"]
    path_modules = module_paths_from_report(dependency_report)
    if any(path not in path_modules for path in delta_paths):
        return ["DELTA_PATH_OUTSIDE_MODULE_GRAPH"]
    if any(_protected_path(path) for path in delta_paths):
        return ["PROTECTED_PATH"]
    if any(
        is_under_authority_path(path, prefix)
        for path in delta_paths
        for prefix in [*scope["paths"], *scope["ownershipPaths"]]
    ):
        return ["FINDING_SCOPE_PATH_AFFECTED"]
    graph = graph_from_report(dependency_report)
    impacted = transitive_dependents(graph, {path_modules[path] for path in delta_paths})
    if impacted.intersection(scope["modules"]):
        return ["FINDING_SCOPE_TRANSITIVELY_AFFECTED"]
    return []


def _attempt_delta(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    previous_by_path = {entry["path"]: entry for entry in previous["entries"]}
    current_by_path = {entry["path"]: entry for entry in current["entries"]}
    changed_paths = sorted(
        path
        for path in set(previous_by_path).union(current_by_path)
        if previous_by_path.get(path) != current_by_path.get(path)
    )
    entries = [
        {"path": path, "previous": previous_by_path.get(path), "current": current_by_path.get(path)}
        for path in changed_paths
    ]
    body = {
        "schemaVersion": "agent-rework-attempt-delta.v1",
        "previousSnapshotHash": previous["snapshotHash"],
        "currentSnapshotHash": current["snapshotHash"],
        "changedPaths": changed_paths,
        "entries": entries,
    }
    return {**body, "deltaDigest": canonical_digest(body)}


def _snapshot_from_audit(audit: dict[str, Any]) -> dict[str, Any]:
    result = audit.get("result")
    snapshot = result.get("changeSetEvidence") if isinstance(result, dict) else None
    if not _complete_snapshot(snapshot):
        raise LifecycleError(
            "delta-audit-prior-snapshot-incomplete",
            "previous implementation audit has no bounded entry snapshot",
        )
    assert isinstance(snapshot, dict)
    return snapshot


def _complete_snapshot(value: Any) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("entries"), list):
        return False
    changed = value.get("changedFiles")
    if not isinstance(changed, list) or len(value["entries"]) != len(changed):
        return False
    return all(_valid_snapshot_entry(item) for item in value["entries"])


def _valid_snapshot_entry(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {"path", "kind", "mode", "sha256", "bytes"}:
        return False
    if value.get("kind") not in {"file", "symlink", "missing"}:
        return False
    raw_path = value.get("path")
    if not isinstance(raw_path, str):
        return False
    try:
        path = normalize_repo_path(raw_path, label="snapshot entry")
    except LifecycleError:
        return False
    if path != raw_path:
        return False
    kind = value["kind"]
    mode = value.get("mode")
    digest = value.get("sha256")
    size = value.get("bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        return False
    if kind == "missing":
        return mode is None and digest is None and size == 0
    if not _is_digest(digest):
        return False
    return (kind == "file" and mode in {"100644", "100755"}) or (kind == "symlink" and mode == "120000")


def _require_prior_audit(audit: dict[str, Any], *, state: dict[str, Any], task_id: str, attempt: int) -> None:
    from agent_lifecycle.audit.implementation import validate_implementation_audit_report

    validation = validate_implementation_audit_report(audit)
    if validation["status"] != "PASS":
        raise LifecycleError("delta-audit-prior-audit-invalid", "previous implementation audit is invalid")
    expected = {
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "taskId": task_id,
        "attempt": attempt,
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
    }
    if any(audit.get(key) != value for key, value in expected.items()):
        raise LifecycleError("delta-audit-prior-audit-lineage", "previous implementation audit lineage changed")


def _require_plan_lineage(manifest: dict[str, Any], lock: dict[str, Any], state: dict[str, Any]) -> None:
    plan_digest = canonical_digest(manifest)
    if (
        manifest.get("status") != "FROZEN"
        or state.get("planDigest") != plan_digest
        or lock.get("manifestHash") != plan_digest
        or state.get("planRevision") != manifest.get("planRevision")
        or state.get("packageId") != manifest.get("package", {}).get("id")
        or state.get("sourceRevision") != manifest.get("baseRevision", {}).get("sha")
    ):
        raise LifecycleError("delta-audit-plan-lineage", "plan, lock, state, or source lineage does not match")


def _dependency_sources_fresh(root: Path, report: dict[str, Any]) -> bool:
    for identity in report.get("sourceFiles", []):
        try:
            path = normalize_repo_path(identity["path"], label="dependency source")
            data = read_stable_repository_file(root, path, max_bytes=64 * 1024 * 1024, label="dependency source")
        except (LifecycleError, KeyError):
            return False
        if len(data) != identity.get("bytes"):
            return False
        if sha256_hex(data) != identity.get("sha256"):
            return False
    return True


def _valid_selection(
    selection: dict[str, Any],
    *,
    manifest: dict[str, Any],
    lock: dict[str, Any],
    state: dict[str, Any],
    snapshot: dict[str, Any],
) -> bool:
    selected = selection.get("selectedCheckIds")
    if (
        selection.get("schemaVersion") != "agent-validation-selection.v1"
        or selection.get("status") != "PASS"
        or selection.get("disposition") != "SELECTED"
        or selection.get("commandsExecuted") is not False
        or selection.get("stateWritten") is not False
        or selection.get("planDigest") != canonical_digest(manifest)
        or selection.get("planLockDigest") != canonical_digest(lock)
        or selection.get("stateRevision") != state.get("stateRevision")
        or selection.get("sourceRevision") != state.get("sourceRevision")
        or selection.get("currentTreeDigest") != snapshot.get("snapshotHash")
        or not isinstance(selected, list)
        or selected != sorted(set(selected))
        or any(not isinstance(item, str) or not item for item in selected)
        or selection.get("blockers") != []
    ):
        return False
    body = {key: value for key, value in selection.items() if key != "selectionDigest"}
    return selection.get("selectionDigest") == canonical_digest(body)


def _load_bindings(paths: list[Path]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in paths:
        binding = read_json_object(path, label="finding-check binding")
        finding_id = binding.get("findingId")
        if not isinstance(finding_id, str) or finding_id in result:
            raise LifecycleError("delta-audit-binding-duplicate", "finding-check bindings must be unique by findingId")
        result[finding_id] = binding
    return result


def _load_evidence(paths: list[Path]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in paths:
        item = read_json_object(path, label="finding-check evidence")
        finding_id = item.get("findingId")
        if not isinstance(finding_id, str) or finding_id in result:
            raise LifecycleError("delta-audit-evidence-duplicate", "finding-check evidence must be unique by findingId")
        result[finding_id] = item
    return result


def _scope_references_exist(scope: dict[str, Any], manifest: dict[str, Any]) -> bool:
    criteria = manifest.get("acceptance", {}).get("criteria", [])
    acceptance_ids = {item.get("id") for item in criteria if isinstance(item, dict)}
    declared_gates = _declared_gate_ids(manifest.get("finalAuditGates", []))
    return set(scope["acceptanceIds"]).issubset(acceptance_ids) and set(scope["gateIds"]).issubset(declared_gates)


def _declared_gate_ids(value: Any) -> set[str]:
    result: set[str] = set()
    if not isinstance(value, list):
        return result
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
            result.add(item["id"])
            continue
        if not isinstance(item, str) or not item:
            continue
        result.add(item)
        match = _FINAL_GATE_PREFIX.match(item)
        if match:
            result.update(part for part in match.group(1).split("|") if part)
    return result


def _validate_receipt_plan_lineage(value: Any, blockers: list[dict[str, Any]]) -> None:
    expected_fields = {
        "planRevision",
        "planDigest",
        "planLockDigest",
        "acceptanceDigest",
        "finalAuditGatesDigest",
        "sourceRevision",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        blockers.append({"code": "delta-audit-plan-lineage-invalid"})
        return
    if (
        not isinstance(value.get("planRevision"), int)
        or isinstance(value.get("planRevision"), bool)
        or value["planRevision"] < 1
        or not isinstance(value.get("sourceRevision"), str)
        or not value["sourceRevision"]
        or any(
            not _is_digest(value.get(field))
            for field in ("planDigest", "planLockDigest", "acceptanceDigest", "finalAuditGatesDigest")
        )
    ):
        blockers.append({"code": "delta-audit-plan-lineage-invalid"})


def _validate_receipt_attempt_delta(value: Any, blockers: list[dict[str, Any]]) -> None:
    expected_fields = {
        "schemaVersion",
        "previousSnapshotHash",
        "currentSnapshotHash",
        "changedPaths",
        "entries",
        "deltaDigest",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        blockers.append({"code": "delta-audit-attempt-delta-invalid"})
        return
    changed_paths = value.get("changedPaths")
    entries = value.get("entries")
    if (
        value.get("schemaVersion") != "agent-rework-attempt-delta.v1"
        or not _is_digest(value.get("previousSnapshotHash"))
        or not _is_digest(value.get("currentSnapshotHash"))
        or not isinstance(changed_paths, list)
        or changed_paths != sorted(set(changed_paths))
        or any(not isinstance(path, str) for path in changed_paths)
        or not isinstance(entries, list)
        or len(entries) != len(changed_paths)
        or any(
            not isinstance(entry, dict)
            or set(entry) != {"path", "previous", "current"}
            or entry.get("path") != path
            or any(
                snapshot is not None and not _valid_snapshot_entry(snapshot)
                for snapshot in (entry.get("previous"), entry.get("current"))
            )
            for path, entry in zip(changed_paths, entries, strict=True)
        )
    ):
        blockers.append({"code": "delta-audit-attempt-delta-invalid"})
    body = {key: item for key, item in value.items() if key != "deltaDigest"}
    if value.get("deltaDigest") != canonical_digest(body):
        blockers.append({"code": "delta-audit-attempt-delta-digest-mismatch"})


def _protected_path(path: str) -> bool:
    return any(is_under_authority_path(path, prefix) for prefix in BUILT_IN_PROTECTED_PATH_PREFIXES)


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise LifecycleError("delta-audit-attempt-invalid", f"{label} must be a positive integer")
    return value


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


__all__ = [
    "DELTA_AUDIT_SCHEMA",
    "DELTA_AUDIT_VALIDATION_SCHEMA",
    "FINDING_DISPOSITIONS",
    "build_rework_delta_audit",
    "validate_rework_delta_audit",
]

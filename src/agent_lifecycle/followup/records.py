"""Follow-up records for explicit out-of-scope or externally blocked work."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_lifecycle.context.profiles import resolve_window, validate_context_profile
from agent_lifecycle.context.rendering import estimate_tokens
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest, read_json_object, sha256_hex
from agent_lifecycle.contracts.paths import normalize_repo_path

LINEAGE_KEYS = ("runId", "packageId", "planRevision", "planDigest", "sourceRevision")
OPEN_STATUSES = {"OPEN", "BLOCKED", "SCHEDULED"}
CLOSED_STATUSES = {"CLOSED", "CANCELLED"}
FOLLOWUP_STATUSES = OPEN_STATUSES | CLOSED_STATUSES
FINALIZATION_BLOCKING_IMPACTS = {"current-acceptance", "completion-proof"}


def load_followup_register(path: Path) -> dict[str, Any]:
    return read_json_object(path, label="follow-up register")


def validate_followup_register(
    register: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(register, dict):
        raise LifecycleError("invalid-follow-up-register", "follow-up register must be an object")
    if register.get("schemaVersion") != "agent-follow-up-register.v1":
        raise LifecycleError("invalid-follow-up-register", "follow-up register schemaVersion is unsupported")
    lineage = _lineage(register.get("lineage"))
    if state is not None:
        _validate_state_binding(lineage, state)
    items = register.get("items")
    if not isinstance(items, list):
        raise LifecycleError("invalid-follow-up-register", "follow-up register items must be an array")
    seen: set[str] = set()
    item_results: list[dict[str, Any]] = []
    open_items: list[str] = []
    closing_errors: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for item in items:
        item_result = _validate_item(item, seen=seen, root=root)
        item_results.append(item_result)
        if item_result["status"] in OPEN_STATUSES:
            open_items.append(item_result["id"])
        closing_errors.extend(item_result["closingErrors"])
        if _is_finalization_blocking(item):
            blockers.append(
                {
                    "id": item["id"],
                    "status": item["status"],
                    "currentScopeImpact": item.get("currentScopeImpact"),
                    "reason": item.get("reason", ""),
                }
            )
    if closing_errors:
        raise LifecycleError("follow-up-closure-invalid", "follow-up closure evidence is invalid", {"items": closing_errors})
    body = {
        "schemaVersion": "agent-follow-up-register-validation.v1",
        "status": "PASS",
        "registerDigest": canonical_digest(register),
        "lineage": lineage,
        "itemCount": len(items),
        "openItemIds": open_items,
        "finalizationBlockers": blockers,
        "items": item_results,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def finalization_blockers(register: dict[str, Any], *, state: dict[str, Any] | None = None, root: Path | None = None) -> list[dict[str, Any]]:
    validation = validate_followup_register(register, state=state, root=root)
    return validation["finalizationBlockers"]


def add_followup_item(register: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    validation = validate_followup_register(register)
    if item.get("id") in set(validation["openItemIds"]) or any(existing.get("id") == item.get("id") for existing in register.get("items", [])):
        raise LifecycleError("duplicate-follow-up-item", "follow-up item id already exists")
    updated = {**register, "items": [*register.get("items", []), item], "updatedAt": _now_iso()}
    validate_followup_register(updated)
    return updated


def followup_item_from_completion_gate(
    receipt: dict[str, Any],
    *,
    item_id: str,
    title: str,
    owner_id: str,
    target_release: str,
    reason: str,
    source: dict[str, Any] | None = None,
    closure_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert a non-blocking completion gate decision into a follow-up item."""

    if not isinstance(receipt, dict) or receipt.get("schemaVersion") != "agent-completion-gate-receipt.v1":
        raise LifecycleError("invalid-completion-gate-receipt", "completion gate receipt is required")
    if receipt.get("decision") != "FOLLOW_UP":
        raise LifecycleError("completion-gate-follow-up-not-allowed", "only FOLLOW_UP decisions can create follow-up items")
    if receipt.get("blockers"):
        raise LifecycleError("completion-gate-follow-up-blocked", "blocking completion gate receipts cannot create follow-up items")
    _required_string(item_id, label="itemId")
    _required_string(title, label="title")
    _required_string(owner_id, label="ownerId")
    _required_string(target_release, label="targetRelease")
    _required_string(reason, label="reason")
    item_source = source or {
        "outOfScopeReason": "Completion gate classified this work as non-blocking follow-up.",
    }
    item = {
        "id": item_id,
        "title": title,
        "owner": {"id": owner_id},
        "status": "SCHEDULED",
        "source": item_source,
        "targetRelease": target_release,
        "currentScopeImpact": "none",
        "closureEvidence": closure_evidence or {"requiredEvidenceIds": [], "requiredArtifacts": []},
        "reason": reason,
        "completionGate": {
            "decision": receipt["decision"],
            "reasonCodes": list(receipt.get("reasonCodes", [])),
            "gateDigest": receipt.get("gateDigest"),
        },
    }
    _validate_item(item, seen=set(), root=None)
    return item


def close_followup_item(
    register: dict[str, Any],
    *,
    item_id: str,
    evidence_ids: list[str],
    artifact_paths: list[str],
    verifier: str,
    reason: str,
    root: Path,
) -> dict[str, Any]:
    _required_string(item_id, label="itemId")
    _required_string(verifier, label="verifier")
    _required_string(reason, label="reason")
    evidence_ids = _string_list(evidence_ids, label="evidenceIds", allow_empty=True)
    artifacts = [_artifact_identity(root, path) for path in artifact_paths]
    items = register.get("items")
    if not isinstance(items, list):
        raise LifecycleError("invalid-follow-up-register", "follow-up register items must be an array")
    updated_items: list[dict[str, Any]] = []
    found = False
    for item in items:
        if not isinstance(item, dict) or item.get("id") != item_id:
            updated_items.append(item)
            continue
        found = True
        if item.get("status") in CLOSED_STATUSES:
            raise LifecycleError("follow-up-item-already-closed", "follow-up item is already closed")
        closure = {
            "status": "PASS",
            "evidenceIds": evidence_ids,
            "artifacts": artifacts,
            "verifier": {"id": verifier},
            "reason": reason,
            "closedAt": _now_iso(),
        }
        updated_items.append({**item, "status": "CLOSED", "closure": closure})
    if not found:
        raise LifecycleError("follow-up-item-not-found", "follow-up item is missing", {"itemId": item_id})
    updated = {**register, "items": updated_items, "updatedAt": _now_iso()}
    validate_followup_register(updated, root=root)
    return updated


def build_followup_summary(
    register: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
    window: str | None = None,
) -> dict[str, Any]:
    validation = validate_followup_register(register, state=state)
    open_items = [
        {
            "id": item["id"],
            "status": item["status"],
            "owner": item["owner"]["id"],
            "targetRelease": item.get("targetRelease"),
            "blocker": item.get("blocker"),
            "currentScopeImpact": item.get("currentScopeImpact"),
            "requiredEvidenceIds": item.get("closureEvidence", {}).get("requiredEvidenceIds", []),
        }
        for item in register.get("items", [])
        if isinstance(item, dict) and item.get("status") in OPEN_STATUSES
    ]
    body = {
        "schemaVersion": "agent-follow-up-summary.v1",
        "status": "PASS",
        "lineage": validation["lineage"],
        "registerDigest": validation["registerDigest"],
        "counts": {
            "total": validation["itemCount"],
            "open": len(validation["openItemIds"]),
            "finalizationBlockers": len(validation["finalizationBlockers"]),
        },
        "openItems": open_items[:20],
        "finalizationBlockers": validation["finalizationBlockers"],
    }
    token_estimate = estimate_tokens(body)
    target = None
    if profile is not None:
        validate_context_profile(profile)
        selected = resolve_window(profile, window)
        limit = selected["limits"]["maxStateSummaryTokens"]
        target = {"window": selected["name"], "limit": limit}
        if token_estimate > limit:
            raise LifecycleError(
                "follow-up-summary-overflow",
                "follow-up summary exceeds compact context state-summary limit",
                {"estimatedTokens": token_estimate, "limit": limit, "window": selected["name"]},
            )
    body["estimatedTokens"] = token_estimate
    if target is not None:
        body["target"] = target
    return {**body, "summaryDigest": canonical_digest(body)}


def write_followup_register(path: Path, register: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(canonical_bytes(register))
    tmp.replace(path)


def _validate_item(item: Any, *, seen: set[str], root: Path | None) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise LifecycleError("invalid-follow-up-item", "follow-up item must be an object")
    item_id = _required_string(item.get("id"), label="item.id")
    if item_id in seen:
        raise LifecycleError("duplicate-follow-up-item", "follow-up item id already exists", {"itemId": item_id})
    seen.add(item_id)
    _required_string(item.get("title"), label="item.title")
    owner = item.get("owner")
    if not isinstance(owner, dict):
        raise LifecycleError("invalid-follow-up-item", "follow-up item owner is required")
    _required_string(owner.get("id"), label="item.owner.id")
    status = item.get("status")
    if status not in FOLLOWUP_STATUSES:
        raise LifecycleError("invalid-follow-up-item", "follow-up item status is unsupported", {"itemId": item_id})
    source = item.get("source")
    if not isinstance(source, dict):
        raise LifecycleError("invalid-follow-up-item", "follow-up item source is required", {"itemId": item_id})
    _validate_source(source, item_id=item_id)
    _validate_target(item, item_id=item_id)
    closing_errors = _validate_closure(item, root=root)
    return {
        "id": item_id,
        "status": status,
        "owner": owner["id"],
        "finalizationBlocking": _is_finalization_blocking(item),
        "closingErrors": closing_errors,
    }


def _validate_source(source: dict[str, Any], *, item_id: str) -> None:
    keys = ("requirementIds", "acceptanceIds", "evidenceIds")
    for key in keys:
        if key in source:
            _string_list(source[key], label=f"source.{key}", allow_empty=True)
    has_trace = any(source.get(key) for key in keys)
    has_reason = isinstance(source.get("outOfScopeReason"), str) and bool(source["outOfScopeReason"])
    has_blocker = isinstance(source.get("externalBlocker"), str) and bool(source["externalBlocker"])
    if not (has_trace or has_reason or has_blocker):
        raise LifecycleError("invalid-follow-up-item", "follow-up source needs trace ids, out-of-scope reason, or external blocker", {"itemId": item_id})


def _validate_target(item: dict[str, Any], *, item_id: str) -> None:
    target_release = item.get("targetRelease")
    blocker = item.get("blocker")
    if target_release is not None:
        _required_string(target_release, label="item.targetRelease")
    if blocker is not None and not isinstance(blocker, dict):
        raise LifecycleError("invalid-follow-up-item", "follow-up blocker must be an object", {"itemId": item_id})
    if isinstance(blocker, dict):
        _required_string(blocker.get("code"), label="item.blocker.code")
        _required_string(blocker.get("reason"), label="item.blocker.reason")
    if item.get("status") in OPEN_STATUSES and not target_release and not blocker:
        raise LifecycleError("invalid-follow-up-item", "open follow-up item requires targetRelease or blocker", {"itemId": item_id})
    impact = item.get("currentScopeImpact", "none")
    if impact not in {"none", "current-acceptance", "completion-proof"}:
        raise LifecycleError("invalid-follow-up-item", "currentScopeImpact is unsupported", {"itemId": item_id})
    evidence = item.get("closureEvidence")
    if not isinstance(evidence, dict):
        raise LifecycleError("invalid-follow-up-item", "closureEvidence is required", {"itemId": item_id})
    _string_list(evidence.get("requiredEvidenceIds", []), label="closureEvidence.requiredEvidenceIds", allow_empty=True)
    if "requiredArtifacts" in evidence:
        _string_list(evidence["requiredArtifacts"], label="closureEvidence.requiredArtifacts", allow_empty=True)


def _validate_closure(item: dict[str, Any], *, root: Path | None) -> list[dict[str, Any]]:
    status = item.get("status")
    closure = item.get("closure")
    if status in OPEN_STATUSES:
        if closure is not None:
            raise LifecycleError("invalid-follow-up-item", "open follow-up item must not carry closure", {"itemId": item["id"]})
        return []
    if status == "CANCELLED":
        return []
    if not isinstance(closure, dict):
        raise LifecycleError("invalid-follow-up-item", "closed follow-up item requires closure", {"itemId": item["id"]})
    if closure.get("status") != "PASS":
        return [{"id": item["id"], "code": "closure-status-not-pass"}]
    provided = set(_string_list(closure.get("evidenceIds", []), label="closure.evidenceIds", allow_empty=True))
    required = set(item.get("closureEvidence", {}).get("requiredEvidenceIds", []))
    missing = sorted(required - provided)
    errors: list[dict[str, Any]] = []
    if missing:
        errors.append({"id": item["id"], "code": "closure-evidence-missing", "missingEvidenceIds": missing})
    artifacts = closure.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise LifecycleError("invalid-follow-up-item", "closure artifacts must be an array", {"itemId": item["id"]})
    required_artifacts = set(item.get("closureEvidence", {}).get("requiredArtifacts", []))
    artifact_paths = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise LifecycleError("invalid-follow-up-item", "closure artifact must be an object", {"itemId": item["id"]})
        artifact_paths.add(_validate_artifact_identity(artifact, root=root))
    missing_artifacts = sorted(required_artifacts - artifact_paths)
    if missing_artifacts:
        errors.append({"id": item["id"], "code": "closure-artifact-missing", "missingArtifacts": missing_artifacts})
    return errors


def _validate_artifact_identity(artifact: dict[str, Any], *, root: Path | None) -> str:
    path = normalize_repo_path(_required_string(artifact.get("path"), label="artifact.path"), label="artifact.path")
    _digest(artifact.get("sha256"), label="artifact.sha256")
    if not isinstance(artifact.get("bytes"), int) or isinstance(artifact.get("bytes"), bool) or artifact["bytes"] < 0:
        raise LifecycleError("invalid-follow-up-item", "artifact bytes must be a non-negative integer")
    if root is not None:
        actual = _artifact_identity(root, path)
        if artifact["sha256"] != actual["sha256"] or artifact["bytes"] != actual["bytes"]:
            raise LifecycleError("follow-up-artifact-stale", "follow-up closure artifact identity is stale", {"path": path})
    return path


def _artifact_identity(root: Path, path: str) -> dict[str, Any]:
    normalized = normalize_repo_path(path, label="artifact path")
    artifact_path = root / normalized
    if not artifact_path.is_file():
        raise LifecycleError("follow-up-artifact-missing", "follow-up artifact is missing", {"path": normalized})
    data = artifact_path.read_bytes()
    return {"path": normalized, "sha256": sha256_hex(data), "bytes": len(data)}


def _is_finalization_blocking(item: dict[str, Any]) -> bool:
    return item.get("status") in OPEN_STATUSES and item.get("currentScopeImpact") in FINALIZATION_BLOCKING_IMPACTS


def _lineage(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError("invalid-follow-up-register", "follow-up lineage is required")
    result = {key: value.get(key) for key in LINEAGE_KEYS}
    for key, item in result.items():
        if key == "planRevision":
            if not isinstance(item, int) or isinstance(item, bool) or item < 1:
                raise LifecycleError("invalid-follow-up-register", "follow-up lineage.planRevision must be a positive integer")
        elif not isinstance(item, str) or not item:
            raise LifecycleError("invalid-follow-up-register", f"follow-up lineage.{key} is required")
    return result


def _validate_state_binding(lineage: dict[str, Any], state: dict[str, Any]) -> None:
    for key in LINEAGE_KEYS:
        if lineage.get(key) != state.get(key):
            raise LifecycleError("follow-up-lineage-mismatch", f"follow-up {key} mismatch")


def _required_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError("invalid-follow-up-item", f"{label} is required")
    return value


def _string_list(value: Any, *, label: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise LifecycleError("invalid-follow-up-item", f"{label} must be a list of non-empty strings")
    if not value and not allow_empty:
        raise LifecycleError("invalid-follow-up-item", f"{label} must not be empty")
    return list(value)


def _digest(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise LifecycleError("invalid-follow-up-item", f"{label} must be a 64-character digest")
    return value


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

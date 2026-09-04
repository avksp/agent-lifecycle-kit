"""Build bounded release accounting from explicit local evidence."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object, sha256_hex
from agent_lifecycle.contracts.canonical import MAX_JSON_INPUT_BYTES
from agent_lifecycle.contracts.paths import normalize_repo_path, read_stable_repository_file
from agent_lifecycle.metrics.costs import COST_CATEGORIES
from agent_lifecycle.metrics.phase_resources import (
    PHASE_RESOURCE_MEASUREMENT_SCHEMA,
    require_phase_resource_measurement_pass,
    validate_phase_resource_measurement,
)
from agent_lifecycle.metrics.workflow_economics import (
    build_workflow_metric_set,
    build_workflow_resource_summary,
    validate_workflow_resource_summary,
)

RELEASE_ACCOUNTING_SOURCE_SCHEMA = "agent-release-accounting-source.v1"
RELEASE_ACCOUNTING_SCHEMA = "agent-release-accounting.v1"
RELEASE_ACCOUNTING_VALIDATION_SCHEMA = "agent-release-accounting-validation.v1"
MAX_RELEASE_ACCOUNTING_ARTIFACTS = 64
MAX_RELEASE_ACCOUNTING_ENTRIES = 1024

ACCOUNTING_VIEWS = ("alkProcess", "implementation", "audit", "postAuditRemediation")
METRIC_KEYS = ("tokens", "steps", "elapsedWallMs", "computeMs")
METRIC_STATUSES = ("MEASURED", "ESTIMATED", "TIME_WINDOW_ONLY", "UNAVAILABLE")
PROVENANCE_FIELDS = (
    "controllerVersion",
    "coreVersion",
    "hostPluginVersion",
    "skillPackageVersion",
    "runAlkVersion",
    "runId",
    "sourceRevision",
    "measurementDigest",
)

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+-]{0,255}\Z")
_PHASE_VIEW = {
    "PLANNING": ("alkProcess", "pipelineCompliance"),
    "IMPLEMENTATION": ("implementation", "implementation"),
    "AUDIT": ("audit", "productValidation"),
    "REMEDIATION": ("postAuditRemediation", "implementation"),
}


def build_release_accounting_source(
    release_id: str,
    entries: list[dict[str, Any]],
    *,
    provenance: dict[str, Any] | None = None,
    enclosing_elapsed_wall: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one normalized source artifact for release accounting."""

    normalized_release_id = _token(release_id, label="releaseId")
    if not isinstance(entries, list) or not entries:
        raise LifecycleError("release-accounting-entries-required", "accounting source entries are required")
    if len(entries) > MAX_RELEASE_ACCOUNTING_ENTRIES:
        raise LifecycleError(
            "release-accounting-entry-limit",
            "accounting source exceeds the entry limit",
            {"entryCount": len(entries), "maxEntries": MAX_RELEASE_ACCOUNTING_ENTRIES},
        )
    normalized_entries = []
    for entry in entries:
        normalized = _normalize_entry(entry)
        normalized.setdefault("workflowMetrics", build_workflow_metric_set())
        normalized_entries.append(normalized)
    _require_unique_entry_ids(normalized_entries)
    body = {
        "schemaVersion": RELEASE_ACCOUNTING_SOURCE_SCHEMA,
        "status": "PASS",
        "releaseId": normalized_release_id,
        "entryCount": len(normalized_entries),
        "entries": normalized_entries,
        "workflowEconomics": build_workflow_resource_summary(
            [entry["workflowMetrics"] for entry in normalized_entries],
            enclosing_elapsed_wall=enclosing_elapsed_wall,
        ),
        "provenance": _normalize_provenance_values(provenance or {}),
        "blockers": [],
        "productionPromotionClaimed": False,
    }
    return {**body, "sourceDigest": canonical_digest(body)}


def validate_release_accounting_source(source: dict[str, Any]) -> dict[str, Any]:
    """Validate a normalized release-accounting source artifact."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(source, dict):
        raise LifecycleError("invalid-release-accounting-source", "accounting source must be an object")
    if source.get("schemaVersion") != RELEASE_ACCOUNTING_SOURCE_SCHEMA:
        blockers.append({"code": "release-accounting-source-schema-invalid"})
    if source.get("status") != "PASS":
        blockers.append({"code": "release-accounting-source-status-invalid"})
    _check_token(source.get("releaseId"), "release-accounting-release-id-invalid", blockers)
    raw_entries = source.get("entries")
    entries = raw_entries if isinstance(raw_entries, list) else []
    if not entries or len(entries) > MAX_RELEASE_ACCOUNTING_ENTRIES:
        blockers.append({"code": "release-accounting-source-entries-invalid"})
    for index, entry in enumerate(entries):
        _validate_entry(entry, index, blockers)
    if len([entry.get("entryId") for entry in entries if isinstance(entry, dict)]) != len(
        {entry.get("entryId") for entry in entries if isinstance(entry, dict)}
    ):
        blockers.append({"code": "release-accounting-entry-id-duplicate"})
    if source.get("entryCount") != len(entries):
        blockers.append({"code": "release-accounting-source-count-mismatch"})
    _validate_provenance_values(source.get("provenance"), blockers)
    if source.get("workflowEconomics") is not None:
        _validate_accounting_workflow_economics(source, entries, blockers)
    if source.get("blockers") != []:
        blockers.append({"code": "release-accounting-source-blockers-invalid"})
    if source.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "release-accounting-source-production-claim"})
    expected = canonical_digest({key: value for key, value in source.items() if key != "sourceDigest"})
    if source.get("sourceDigest") != expected:
        blockers.append({"code": "release-accounting-source-digest-mismatch"})
    return {
        "status": "PASS" if not blockers else "FAIL",
        "entryCount": len(entries),
        "blockers": blockers,
        "sourceDigest": source.get("sourceDigest"),
    }


def build_release_accounting(
    release_id: str,
    artifact_paths: list[Path],
    *,
    project_root: Path | None = None,
    declared_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic accounting without host, model or network calls."""

    normalized_release_id = _token(release_id, label="releaseId")
    if not artifact_paths:
        raise LifecycleError("release-accounting-artifacts-required", "at least one accounting artifact is required")
    if len(artifact_paths) > MAX_RELEASE_ACCOUNTING_ARTIFACTS:
        raise LifecycleError(
            "release-accounting-artifact-limit",
            "accounting artifact count exceeds the limit",
            {"artifactCount": len(artifact_paths), "maxArtifacts": MAX_RELEASE_ACCOUNTING_ARTIFACTS},
        )

    root = (project_root or Path.cwd()).resolve()
    source_artifacts: list[dict[str, Any]] = []
    source_workflow_summaries: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    observed_provenance: dict[str, set[str]] = {field: set() for field in PROVENANCE_FIELDS}
    for artifact_index, raw_path in enumerate(artifact_paths):
        payload, descriptor = _load_artifact(raw_path, root)
        _require_unique_source_artifact(source_artifacts, descriptor)
        source_artifacts.append(descriptor)
        schema = payload.get("schemaVersion")
        if schema == PHASE_RESOURCE_MEASUREMENT_SCHEMA:
            require_phase_resource_measurement_pass(validate_phase_resource_measurement(payload))
            entries.extend(_entries_from_phase_measurement(payload, artifact_index, descriptor["payloadDigest"]))
            if isinstance(payload.get("workflowEconomics"), dict):
                source_workflow_summaries.append(payload["workflowEconomics"])
            _collect_provenance(payload.get("usageExport", {}).get("lineage"), observed_provenance)
            observed_provenance["measurementDigest"].add(str(payload["measurementDigest"]))
        elif schema == RELEASE_ACCOUNTING_SOURCE_SCHEMA:
            validation = validate_release_accounting_source(payload)
            if validation["status"] != "PASS":
                raise LifecycleError(
                    "release-accounting-source-validation-failed",
                    "release accounting source did not pass validation",
                    {"validation": validation},
                )
            if payload.get("releaseId") != normalized_release_id:
                raise LifecycleError(
                    "release-accounting-release-mismatch",
                    "accounting source belongs to another release",
                )
            for entry in payload["entries"]:
                entries.append({**entry, "sourceArtifactDigest": descriptor["payloadDigest"]})
            if isinstance(payload.get("workflowEconomics"), dict):
                source_workflow_summaries.append(payload["workflowEconomics"])
            _collect_provenance(payload.get("provenance"), observed_provenance)
        else:
            raise LifecycleError(
                "release-accounting-source-unsupported",
                "accounting source schema is unsupported",
                {"schemaVersion": schema},
            )
        if len(entries) > MAX_RELEASE_ACCOUNTING_ENTRIES:
            raise LifecycleError(
                "release-accounting-entry-limit",
                "accounting entries exceed the aggregate limit",
                {"entryCount": len(entries), "maxEntries": MAX_RELEASE_ACCOUNTING_ENTRIES},
            )

    _require_unique_entry_ids(entries)
    inherited_elapsed_wall = None
    if len(source_artifacts) == 1 and len(source_workflow_summaries) == 1:
        inherited_elapsed_wall = source_workflow_summaries[0].get("enclosingElapsedWall")
    summaries = _summaries(entries, enclosing_elapsed_wall=inherited_elapsed_wall)
    provenance = _build_provenance(declared_provenance or {}, observed_provenance, source_artifacts)
    body = {
        "schemaVersion": RELEASE_ACCOUNTING_SCHEMA,
        "status": "PASS",
        "releaseId": normalized_release_id,
        "generatedBy": "agent-lifecycle metrics release-accounting",
        "sourceArtifacts": source_artifacts,
        "entryCount": len(entries),
        "entries": entries,
        "views": summaries["views"],
        "categoryTotals": summaries["categoryTotals"],
        "totals": summaries["totals"],
        "workflowEconomics": summaries["workflowEconomics"],
        "exclusions": summaries["exclusions"],
        "provenance": provenance,
        "blockers": [],
        "liveCallsStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "accountingDigest": canonical_digest(body)}


def validate_release_accounting(accounting: dict[str, Any]) -> dict[str, Any]:
    """Validate digest, accounting semantics and provenance without I/O."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(accounting, dict):
        raise LifecycleError("invalid-release-accounting", "release accounting must be an object")
    if accounting.get("schemaVersion") != RELEASE_ACCOUNTING_SCHEMA:
        blockers.append({"code": "release-accounting-schema-invalid"})
    if accounting.get("status") != "PASS":
        blockers.append({"code": "release-accounting-status-invalid"})
    if accounting.get("generatedBy") != "agent-lifecycle metrics release-accounting":
        blockers.append({"code": "release-accounting-generator-invalid"})
    _check_token(accounting.get("releaseId"), "release-accounting-release-id-invalid", blockers)
    raw_entries = accounting.get("entries")
    entries = raw_entries if isinstance(raw_entries, list) else []
    if not entries or len(entries) > MAX_RELEASE_ACCOUNTING_ENTRIES:
        blockers.append({"code": "release-accounting-entries-invalid"})
    for index, entry in enumerate(entries):
        _validate_entry(entry, index, blockers, require_source_digest=True)
    entry_ids = [entry.get("entryId") for entry in entries if isinstance(entry, dict)]
    if len(entry_ids) != len(set(entry_ids)):
        blockers.append({"code": "release-accounting-entry-id-duplicate"})
    if accounting.get("entryCount") != len(entries):
        blockers.append({"code": "release-accounting-count-mismatch"})
    if entries:
        workflow_economics = accounting.get("workflowEconomics")
        enclosing_elapsed_wall = (
            workflow_economics.get("enclosingElapsedWall") if isinstance(workflow_economics, dict) else None
        )
        source_artifacts = accounting.get("sourceArtifacts")
        source_count = len(source_artifacts) if isinstance(source_artifacts, list) else 0
        unbound_wall = (
            source_count != 1
            and isinstance(enclosing_elapsed_wall, dict)
            and enclosing_elapsed_wall.get("status") != "UNAVAILABLE"
        )
        if unbound_wall:
            blockers.append({"code": "release-accounting-enclosing-wall-unbound"})
        expected = _summaries(
            entries,
            enclosing_elapsed_wall=None if unbound_wall else enclosing_elapsed_wall,
        )
        for key in ("views", "categoryTotals", "totals", "exclusions"):
            if accounting.get(key) != expected[key]:
                blockers.append({"code": f"release-accounting-{key}-mismatch"})
        if accounting.get("workflowEconomics") is not None:
            if accounting.get("workflowEconomics") != expected["workflowEconomics"]:
                blockers.append({"code": "release-accounting-workflow-economics-mismatch"})
            workflow_validation = validate_workflow_resource_summary(accounting["workflowEconomics"])
            if workflow_validation["status"] != "PASS":
                blockers.append(
                    {"code": "release-accounting-workflow-economics-invalid", "validation": workflow_validation}
                )
    _validate_source_artifacts(accounting.get("sourceArtifacts"), blockers)
    allowed_payload_digests = {
        item.get("payloadDigest")
        for item in accounting.get("sourceArtifacts", [])
        if isinstance(item, dict) and _is_digest(item.get("payloadDigest"))
    }
    for index, entry in enumerate(entries):
        if isinstance(entry, dict) and entry.get("sourceArtifactDigest") not in allowed_payload_digests:
            blockers.append({"code": "release-accounting-entry-source-unknown", "index": index})
    _validate_provenance_report(accounting.get("provenance"), accounting.get("sourceArtifacts"), blockers)
    if accounting.get("blockers") != []:
        blockers.append({"code": "release-accounting-blockers-invalid"})
    if accounting.get("liveCallsStarted") is not False:
        blockers.append({"code": "release-accounting-live-call-claim"})
    if accounting.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "release-accounting-production-claim"})
    expected_digest = canonical_digest({key: value for key, value in accounting.items() if key != "accountingDigest"})
    if accounting.get("accountingDigest") != expected_digest:
        blockers.append({"code": "release-accounting-digest-mismatch"})
    body = {
        "schemaVersion": RELEASE_ACCOUNTING_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "releaseId": accounting.get("releaseId"),
        "entryCount": len(entries),
        "blockers": blockers,
        "accountingDigest": accounting.get("accountingDigest"),
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_release_accounting_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError(
            "release-accounting-validation-failed",
            "release accounting did not pass validation",
            {"validation": validation},
        )
    return validation


def _load_artifact(raw_path: Path, root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        relative = raw_path.resolve().relative_to(root).as_posix() if raw_path.is_absolute() else raw_path.as_posix()
    except ValueError as exc:
        raise LifecycleError(
            "release-accounting-artifact-outside-root",
            "accounting artifacts must remain inside the project root",
        ) from exc
    relative = normalize_repo_path(relative, label="accounting artifact")
    data = read_stable_repository_file(
        root,
        relative,
        max_bytes=MAX_JSON_INPUT_BYTES,
        label="accounting artifact",
    )
    payload = load_json_object(data, label="accounting artifact")
    return payload, {
        "path": relative,
        "sha256": sha256_hex(data),
        "bytes": len(data),
        "schemaVersion": payload.get("schemaVersion"),
        "payloadDigest": canonical_digest(payload),
    }


def _entries_from_phase_measurement(
    measurement: dict[str, Any],
    artifact_index: int,
    source_digest: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for phase_index, phase in enumerate(measurement["phases"]):
        phase_kind = str(phase["phaseKind"]).upper()
        view, category = _PHASE_VIEW.get(phase_kind, ("alkProcess", "pipelineCompliance"))
        result.append(
            {
                "entryId": f"artifact-{artifact_index + 1}-phase-{phase_index + 1}",
                "view": view,
                "costCategory": category,
                "scope": {"kind": "release-phase", "id": _token(phase["phaseId"], label="phaseId"), "additive": True},
                "metrics": {
                    "tokens": _metric("MEASURED", phase["tokens"]["total"], additive=True),
                    "steps": _metric("MEASURED", phase["steps"], additive=True),
                    "elapsedWallMs": _metric("MEASURED", phase["durationMs"], additive=True),
                    "computeMs": _metric("UNAVAILABLE", None, additive=False),
                },
                "workflowMetrics": phase.get("workflowMetrics", build_workflow_metric_set()),
                "sourceArtifactDigest": source_digest,
            }
        )
    return result


def _normalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise LifecycleError("release-accounting-entry-invalid", "accounting entries must be objects")
    allowed_entry_fields = {
        "entryId",
        "view",
        "costCategory",
        "scope",
        "metrics",
        "workflowMetrics",
        "sourceArtifactDigest",
    }
    if not set(entry).issubset(allowed_entry_fields):
        raise LifecycleError("release-accounting-entry-invalid", "accounting entry contains unsupported fields")
    view = entry.get("view")
    if view not in ACCOUNTING_VIEWS:
        raise LifecycleError("release-accounting-view-invalid", "accounting view is unsupported")
    category = entry.get("costCategory")
    if category not in COST_CATEGORIES:
        raise LifecycleError("release-accounting-category-invalid", "cost category is unsupported")
    raw_scope = entry.get("scope")
    if (
        not isinstance(raw_scope, dict)
        or set(raw_scope) != {"kind", "id", "additive"}
        or not isinstance(raw_scope.get("additive"), bool)
    ):
        raise LifecycleError("release-accounting-scope-invalid", "accounting scope is invalid")
    raw_metrics = entry.get("metrics")
    if not isinstance(raw_metrics, dict) or set(raw_metrics) != set(METRIC_KEYS):
        raise LifecycleError("release-accounting-metrics-invalid", "all accounting metrics are required")
    normalized = {
        "entryId": _token(entry.get("entryId"), label="entryId"),
        "view": view,
        "costCategory": category,
        "scope": {
            "kind": _token(raw_scope.get("kind"), label="scope.kind"),
            "id": _token(raw_scope.get("id"), label="scope.id"),
            "additive": raw_scope["additive"],
        },
        "metrics": {key: _normalize_metric(raw_metrics[key], key) for key in METRIC_KEYS},
    }
    if "workflowMetrics" in entry:
        normalized["workflowMetrics"] = build_workflow_metric_set(entry["workflowMetrics"])
    return normalized


def _normalize_metric(metric: Any, label: str) -> dict[str, Any]:
    if (
        not isinstance(metric, dict)
        or set(metric) != {"status", "value", "additive"}
        or metric.get("status") not in METRIC_STATUSES
    ):
        raise LifecycleError("release-accounting-metric-invalid", f"{label} metric status is invalid")
    if not isinstance(metric.get("additive"), bool):
        raise LifecycleError("release-accounting-metric-invalid", f"{label} additive flag is invalid")
    status = metric["status"]
    value = metric.get("value")
    if status == "UNAVAILABLE":
        if value is not None:
            raise LifecycleError("release-accounting-metric-invalid", f"{label} unavailable value must be null")
    elif not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LifecycleError("release-accounting-metric-invalid", f"{label} value must be a non-negative integer")
    return {"status": status, "value": value, "additive": metric["additive"]}


def _metric(status: str, value: int | None, *, additive: bool) -> dict[str, Any]:
    return {"status": status, "value": value, "additive": additive}


def _summaries(
    entries: list[dict[str, Any]],
    *,
    enclosing_elapsed_wall: dict[str, Any] | None = None,
) -> dict[str, Any]:
    additive_entries = [entry for entry in entries if entry["scope"]["additive"]]
    views = {
        view: _summarize_group([entry for entry in additive_entries if entry["view"] == view])
        for view in ACCOUNTING_VIEWS
    }
    categories = {
        category: _summarize_group([entry for entry in additive_entries if entry["costCategory"] == category])
        for category in COST_CATEGORIES
    }
    exclusions = [
        {"entryId": entry["entryId"], "reason": "NON_ADDITIVE_SCOPE"}
        for entry in entries
        if not entry["scope"]["additive"]
    ]
    return {
        "views": views,
        "categoryTotals": categories,
        "totals": _summarize_group(additive_entries),
        "workflowEconomics": build_workflow_resource_summary(
            [_entry_workflow_metrics(entry) for entry in additive_entries],
            enclosing_elapsed_wall=enclosing_elapsed_wall,
        ),
        "exclusions": exclusions,
    }


def _validate_accounting_workflow_economics(
    container: dict[str, Any],
    entries: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> None:
    workflow_economics = container.get("workflowEconomics")
    validation = validate_workflow_resource_summary(workflow_economics)
    if validation["status"] != "PASS":
        blockers.append({"code": "release-accounting-workflow-economics-invalid", "validation": validation})
        return
    if not isinstance(workflow_economics, dict):
        blockers.append({"code": "release-accounting-workflow-economics-invalid"})
        return
    expected = build_workflow_resource_summary(
        [_entry_workflow_metrics(entry) for entry in entries],
        enclosing_elapsed_wall=workflow_economics.get("enclosingElapsedWall"),
    )
    if workflow_economics != expected:
        blockers.append({"code": "release-accounting-workflow-economics-mismatch"})


def _entry_workflow_metrics(entry: dict[str, Any]) -> dict[str, Any]:
    value = entry.get("workflowMetrics")
    return value if isinstance(value, dict) else build_workflow_metric_set()


def _summarize_group(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "entryCount": len(entries),
        "metrics": {key: _sum_metric(entries, key) for key in METRIC_KEYS},
    }


def _sum_metric(entries: list[dict[str, Any]], key: str) -> dict[str, Any]:
    metrics = [entry["metrics"][key] for entry in entries if entry["metrics"][key]["additive"]]
    known = [metric for metric in metrics if metric["status"] != "UNAVAILABLE"]
    if not known:
        return {"status": "UNAVAILABLE", "value": None}
    known_statuses = {metric["status"] for metric in known}
    if len(known) != len(metrics):
        status = "PARTIAL"
    elif len(known_statuses) == 1:
        status = next(iter(known_statuses))
    else:
        status = "MIXED"
    return {"status": status, "value": sum(metric["value"] for metric in known)}


def _build_provenance(
    declared: dict[str, Any],
    observed: dict[str, set[str]],
    source_artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    declared_values = _normalize_provenance_values(declared)
    identities: dict[str, Any] = {}
    for field in PROVENANCE_FIELDS:
        declared_value = declared_values.get(field)
        observed_values = sorted(observed[field])
        if declared_value is None and not observed_values:
            status = "UNAVAILABLE"
        elif declared_value is None:
            status = "OBSERVED_ONLY"
        elif not observed_values:
            status = "DECLARED_ONLY"
        elif observed_values == [declared_value]:
            status = "MATCHED"
        else:
            status = "MISMATCH"
        identities[field] = {
            "declared": declared_value,
            "observed": observed_values,
            "status": status,
        }
    return {
        "status": "MISMATCH" if any(item["status"] == "MISMATCH" for item in identities.values()) else "REPORTED",
        "identities": identities,
        "sourceArtifactDigests": [item["sha256"] for item in source_artifacts],
        "confidencePromotionClaimed": False,
    }


def _normalize_provenance_values(value: dict[str, Any]) -> dict[str, str]:
    if not isinstance(value, dict):
        raise LifecycleError("release-accounting-provenance-invalid", "provenance must be an object")
    unknown = set(value).difference(PROVENANCE_FIELDS)
    if unknown:
        raise LifecycleError(
            "release-accounting-provenance-invalid",
            "provenance contains unsupported fields",
            {"fields": sorted(unknown)},
        )
    normalized = {field: _token(item, label=field) for field, item in value.items()}
    measurement_digest = normalized.get("measurementDigest")
    if measurement_digest is not None and not _is_digest(measurement_digest):
        raise LifecycleError(
            "release-accounting-provenance-invalid",
            "measurementDigest must be a lowercase SHA-256 digest",
        )
    return normalized


def _collect_provenance(value: Any, observed: dict[str, set[str]]) -> None:
    if not isinstance(value, dict):
        return
    for field in PROVENANCE_FIELDS:
        item = value.get(field)
        if item is not None:
            observed[field].add(_token(item, label=field))


def _validate_entry(
    entry: Any,
    index: int,
    blockers: list[dict[str, Any]],
    *,
    require_source_digest: bool = False,
) -> None:
    try:
        normalized = _normalize_entry(entry)
    except LifecycleError as exc:
        blockers.append({"code": exc.code, "index": index})
        return
    comparable = (
        {key: value for key, value in entry.items() if key != "sourceArtifactDigest"}
        if require_source_digest
        else entry
    )
    if comparable != normalized:
        blockers.append({"code": "release-accounting-entry-shape-invalid", "index": index})
    if require_source_digest and not _is_digest(entry.get("sourceArtifactDigest")):
        blockers.append({"code": "release-accounting-entry-source-digest-invalid", "index": index})


def _validate_provenance_values(value: Any, blockers: list[dict[str, Any]]) -> None:
    try:
        normalized = _normalize_provenance_values(value)
    except LifecycleError as exc:
        blockers.append({"code": exc.code})
        return
    if value != normalized:
        blockers.append({"code": "release-accounting-provenance-shape-invalid"})


def _validate_source_artifacts(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or not value or len(value) > MAX_RELEASE_ACCOUNTING_ARTIFACTS:
        blockers.append({"code": "release-accounting-source-artifacts-invalid"})
        return
    required = {"path", "sha256", "bytes", "schemaVersion", "payloadDigest"}
    seen_sha256: dict[str, int] = {}
    seen_payload_digests: dict[str, int] = {}
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != required:
            blockers.append({"code": "release-accounting-source-artifact-shape-invalid", "index": index})
            continue
        try:
            normalize_repo_path(item["path"], label="source artifact")
        except (LifecycleError, TypeError):
            blockers.append({"code": "release-accounting-source-artifact-path-invalid", "index": index})
        if not _is_digest(item.get("sha256")) or not _is_digest(item.get("payloadDigest")):
            blockers.append({"code": "release-accounting-source-artifact-digest-invalid", "index": index})
        if not isinstance(item.get("bytes"), int) or isinstance(item.get("bytes"), bool) or item["bytes"] < 0:
            blockers.append({"code": "release-accounting-source-artifact-bytes-invalid", "index": index})
        if item.get("schemaVersion") is not None and not isinstance(item.get("schemaVersion"), str):
            blockers.append({"code": "release-accounting-source-artifact-schema-invalid", "index": index})
        for field, seen in (("sha256", seen_sha256), ("payloadDigest", seen_payload_digests)):
            digest = item.get(field)
            if not isinstance(digest, str) or not _is_digest(digest):
                continue
            if digest in seen:
                blockers.append(
                    {
                        "code": "release-accounting-source-artifact-duplicate",
                        "field": field,
                        "firstIndex": seen[digest],
                        "index": index,
                    }
                )
            else:
                seen[digest] = index


def _require_unique_source_artifact(
    source_artifacts: list[dict[str, Any]],
    candidate: dict[str, Any],
) -> None:
    for index, existing in enumerate(source_artifacts):
        duplicate_fields = [field for field in ("sha256", "payloadDigest") if existing[field] == candidate[field]]
        if duplicate_fields:
            raise LifecycleError(
                "release-accounting-source-artifact-duplicate",
                "accounting source artifacts must have unique content",
                {
                    "duplicateFields": duplicate_fields,
                    "firstIndex": index,
                    "index": len(source_artifacts),
                },
            )


def _validate_provenance_report(value: Any, artifacts: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict) or set(value) != {
        "status",
        "identities",
        "sourceArtifactDigests",
        "confidencePromotionClaimed",
    }:
        blockers.append({"code": "release-accounting-provenance-report-invalid"})
        return
    if value.get("status") not in {"REPORTED", "MISMATCH"} or value.get("confidencePromotionClaimed") is not False:
        blockers.append({"code": "release-accounting-provenance-status-invalid"})
    identities = value.get("identities")
    if not isinstance(identities, dict) or set(identities) != set(PROVENANCE_FIELDS):
        blockers.append({"code": "release-accounting-provenance-identities-invalid"})
    else:
        expected_overall = "REPORTED"
        for field, identity in identities.items():
            if not isinstance(identity, dict) or set(identity) != {"declared", "observed", "status"}:
                blockers.append({"code": "release-accounting-provenance-identity-invalid", "field": field})
                continue
            if identity.get("status") not in {
                "MATCHED",
                "MISMATCH",
                "DECLARED_ONLY",
                "OBSERVED_ONLY",
                "UNAVAILABLE",
            }:
                blockers.append({"code": "release-accounting-provenance-identity-status-invalid", "field": field})
            observed_values = identity.get("observed")
            if not isinstance(observed_values, list) or observed_values != sorted(set(observed_values)):
                blockers.append({"code": "release-accounting-provenance-observed-invalid", "field": field})
            for item in ([identity.get("declared")] if identity.get("declared") is not None else []) + list(
                observed_values if isinstance(observed_values, list) else []
            ):
                if not isinstance(item, str) or not _TOKEN.fullmatch(item):
                    blockers.append({"code": "release-accounting-provenance-value-invalid", "field": field})
            declared_value = identity.get("declared")
            comparable_observed = observed_values if isinstance(observed_values, list) else []
            if declared_value is None and not comparable_observed:
                expected_status = "UNAVAILABLE"
            elif declared_value is None:
                expected_status = "OBSERVED_ONLY"
            elif not comparable_observed:
                expected_status = "DECLARED_ONLY"
            elif comparable_observed == [declared_value]:
                expected_status = "MATCHED"
            else:
                expected_status = "MISMATCH"
            if identity.get("status") != expected_status:
                blockers.append({"code": "release-accounting-provenance-status-mismatch", "field": field})
            if expected_status == "MISMATCH":
                expected_overall = "MISMATCH"
        if value.get("status") != expected_overall:
            blockers.append({"code": "release-accounting-provenance-overall-status-mismatch"})
    expected_digests = [item.get("sha256") for item in artifacts] if isinstance(artifacts, list) else []
    if value.get("sourceArtifactDigests") != expected_digests:
        blockers.append({"code": "release-accounting-provenance-source-digest-mismatch"})


def _require_unique_entry_ids(entries: list[dict[str, Any]]) -> None:
    ids = [entry["entryId"] for entry in entries]
    if len(ids) != len(set(ids)):
        raise LifecycleError("release-accounting-entry-id-duplicate", "accounting entry IDs must be unique")


def _check_token(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        blockers.append({"code": code})


def _token(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise LifecycleError("release-accounting-token-invalid", f"{label} must be a bounded identifier")
    return value


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)

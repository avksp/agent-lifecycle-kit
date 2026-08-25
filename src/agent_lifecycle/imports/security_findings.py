"""Read-only import and normalization of untrusted security findings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.security_analysis_schemas import (
    SECURITY_FINDING_IMPORT_SCHEMA,
    SECURITY_FINDING_IMPORT_VALIDATION_SCHEMA,
)
from agent_lifecycle.quality.security_analysis import (
    build_security_finding,
    validate_security_finding,
)

MAX_SECURITY_IMPORT_BYTES = 4 * 1024 * 1024


def import_security_findings(
    source: Path | dict[str, Any] | list[dict[str, Any]],
    *,
    source_revision: str | None = None,
    expected_source_revision: str | None = None,
    source_lineage_digest: str | None = None,
    max_input_bytes: int = MAX_SECURITY_IMPORT_BYTES,
) -> dict[str, Any]:
    """Import SARIF or normalized findings without granting workflow authority."""

    raw, source_format = _load_source(source, max_input_bytes=max_input_bytes)
    revision = source_revision or _source_revision(raw)
    lineage = source_lineage_digest or canonical_digest(
        {"sourceRevision": revision, "sourceFormat": source_format, "source": _source_metadata(raw)}
    )
    blockers: list[dict[str, Any]] = []
    if not isinstance(revision, str) or not revision:
        blockers.append({"code": "security-analysis-source-revision-required"})
        revision = "unavailable"
    if expected_source_revision is not None and revision != expected_source_revision:
        blockers.append({"code": "security-analysis-source-revision-mismatch"})
    findings: list[dict[str, Any]] = []
    for index, item in enumerate(_finding_items(raw, source_format)):
        try:
            finding = _normalize_item(
                item, source_format=source_format, source_revision=revision, source_lineage_digest=lineage
            )
            validation = validate_security_finding(
                finding,
                expected_source_revision=expected_source_revision,
                expected_source_lineage_digest=source_lineage_digest,
            )
            if validation["status"] != "PASS":
                blockers.extend({**blocker, "index": index} for blocker in validation["blockers"])
            findings.append(finding)
        except LifecycleError as exc:
            blockers.append({"code": exc.code, "index": index, "message": exc.message})
    body = {
        "schemaVersion": SECURITY_FINDING_IMPORT_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "sourceFormat": source_format,
        "sourceRevision": revision,
        "sourceLineageDigest": lineage,
        "findings": findings,
        "trusted": False,
        "authorityClaimed": False,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "importDigest": canonical_digest(body)}


def validate_security_finding_import(
    imported: dict[str, Any], *, expected_source_revision: str | None = None
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(imported, dict) or imported.get("schemaVersion") != SECURITY_FINDING_IMPORT_SCHEMA:
        blockers.append({"code": "security-analysis-import-schema-invalid"})
    if not isinstance(imported, dict):
        return _validation(imported, blockers)
    if imported.get("status") not in {"PASS", "FAIL"}:
        blockers.append({"code": "security-analysis-import-status-invalid"})
    if expected_source_revision is not None and imported.get("sourceRevision") != expected_source_revision:
        blockers.append({"code": "security-analysis-source-revision-mismatch"})
    if imported.get("trusted") is not False or imported.get("authorityClaimed") is not False:
        blockers.append({"code": "security-analysis-import-authority-claim"})
    if imported.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "security-analysis-import-production-claim"})
    findings = imported.get("findings")
    if not isinstance(findings, list):
        blockers.append({"code": "security-analysis-import-findings-invalid"})
        findings = []
    for index, finding in enumerate(findings):
        result = validate_security_finding(finding, expected_source_revision=expected_source_revision)
        if result["status"] != "PASS":
            blockers.extend({**item, "index": index} for item in result["blockers"])
    if imported.get("importDigest") != canonical_digest(_without(imported, "importDigest")):
        blockers.append({"code": "security-analysis-import-digest-mismatch"})
    body = {
        "schemaVersion": SECURITY_FINDING_IMPORT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "findingCount": len(findings),
        "blockers": blockers,
        "importDigest": imported.get("importDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_security_finding_import_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError(
            "security-analysis-import-invalid",
            "security finding import failed validation",
            {"validation": validation},
        )
    return validation


def export_security_findings_sarif(findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Export normalized findings to SARIF without changing their trust state."""

    results = []
    for finding in findings:
        locations = []
        for location in finding.get("locations", []):
            physical: dict[str, Any] = {"artifactLocation": {"uri": location.get("path")}}
            region = {
                key: location[key] for key in ("startLine", "endLine", "startColumn", "endColumn") if key in location
            }
            if region:
                physical["region"] = region
            locations.append({"physicalLocation": physical})
        results.append(
            {
                "ruleId": finding.get("findingId"),
                "level": _sarif_level(finding.get("severity")),
                "message": {"text": finding.get("title", "")},
                "locations": locations,
                "properties": {
                    "alkSeverity": finding.get("severity"),
                    "alkConfidence": finding.get("confidence"),
                    "alkFindingDigest": finding.get("findingDigest"),
                    "alkTrusted": False,
                },
            }
        )
    return {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [{"tool": {"driver": {"name": "agent-lifecycle-kit"}}, "results": results}],
    }


def _load_source(source: Path | dict[str, Any] | list[dict[str, Any]], *, max_input_bytes: int) -> tuple[Any, str]:
    if isinstance(source, Path):
        data = source.read_bytes()
        if len(data) > max_input_bytes:
            raise LifecycleError("security-analysis-import-too-large", "security finding import exceeds byte limit")
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LifecycleError(
                "security-analysis-import-invalid-json", "security finding import is not valid JSON"
            ) from exc
    else:
        value = source
    if isinstance(value, dict) and isinstance(value.get("runs"), list):
        return value, "SARIF"
    return value, "NORMALIZED"


def _finding_items(raw: Any, source_format: str) -> list[dict[str, Any]]:
    if source_format == "SARIF":
        result: list[dict[str, Any]] = []
        for run in raw.get("runs", []):
            if not isinstance(run, dict):
                continue
            for item in run.get("results", []):
                if isinstance(item, dict):
                    result.append(item)
        return result
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        values = raw.get("findings", [raw])
        return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []
    return []


def _normalize_item(
    item: dict[str, Any], *, source_format: str, source_revision: str, source_lineage_digest: str
) -> dict[str, Any]:
    if source_format == "SARIF":
        properties_value = item.get("properties")
        properties: dict[str, Any] = properties_value if isinstance(properties_value, dict) else {}
        severity = properties.get("alkSeverity") or _severity_from_sarif(item.get("level"))
        confidence = properties.get("alkConfidence", "UNKNOWN")
        message_value = item.get("message")
        message: dict[str, Any] = message_value if isinstance(message_value, dict) else {}
        locations = [_sarif_location(value) for value in item.get("locations", []) if isinstance(value, dict)]
        return build_security_finding(
            title=str(message.get("text") or item.get("ruleId") or "security finding"),
            description=str(message.get("text") or ""),
            severity=severity,
            confidence=confidence,
            finding_id=item.get("ruleId") or properties.get("alkFindingId"),
            source={"format": "SARIF", "ruleId": item.get("ruleId")},
            source_revision=source_revision,
            source_lineage_digest=source_lineage_digest,
            locations=locations,
        )
    return build_security_finding(
        title=item.get("title") or item.get("message") or item.get("ruleId") or "security finding",
        description=item.get("description", item.get("message", "")),
        severity=item.get("severity", "INFO"),
        confidence=item.get("confidence", "UNKNOWN"),
        finding_id=item.get("findingId") or item.get("id"),
        source=item.get("source") if isinstance(item.get("source"), dict) else {"format": "NORMALIZED"},
        source_revision=source_revision,
        source_lineage_digest=source_lineage_digest,
        locations=item.get("locations") if isinstance(item.get("locations"), list) else _locations_from_item(item),
        remediation=item.get("remediation") if isinstance(item.get("remediation"), dict) else None,
        evidence_ids=item.get("evidenceIds") if isinstance(item.get("evidenceIds"), list) else [],
    )


def _sarif_location(value: dict[str, Any]) -> dict[str, Any]:
    physical_value = value.get("physicalLocation")
    physical: dict[str, Any] = physical_value if isinstance(physical_value, dict) else {}
    artifact_value = physical.get("artifactLocation")
    artifact: dict[str, Any] = artifact_value if isinstance(artifact_value, dict) else {}
    region_value = physical.get("region")
    region: dict[str, Any] = region_value if isinstance(region_value, dict) else {}
    return {
        "path": artifact.get("uri"),
        **{key: region[key] for key in ("startLine", "endLine", "startColumn", "endColumn") if key in region},
    }


def _locations_from_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(item.get("path"), str):
        return [{"path": item["path"], **{key: item[key] for key in ("startLine", "endLine") if key in item}}]
    return []


def _severity_from_sarif(level: Any) -> str:
    return {"error": "HIGH", "warning": "MEDIUM", "note": "LOW", "none": "INFO"}.get(level, "INFO")


def _sarif_level(severity: Any) -> str:
    return {
        "BLOCKER": "error",
        "CRITICAL": "error",
        "HIGH": "error",
        "MEDIUM": "warning",
        "LOW": "note",
        "INFO": "none",
    }.get(severity, "none")


def _source_revision(raw: Any) -> str | None:
    if isinstance(raw, dict):
        if isinstance(raw.get("sourceRevision"), str):
            return raw["sourceRevision"]
        properties = raw.get("properties")
        if isinstance(properties, dict) and isinstance(properties.get("sourceRevision"), str):
            return properties["sourceRevision"]
    return None


def _source_metadata(raw: Any) -> Any:
    if isinstance(raw, dict):
        return {key: raw[key] for key in ("version", "$schema", "sourceRevision") if key in raw}
    return {"kind": type(raw).__name__}


def _validation(value: Any, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    body = {
        "schemaVersion": SECURITY_FINDING_IMPORT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "findingCount": 0,
        "blockers": blockers,
        "importDigest": value.get("importDigest") if isinstance(value, dict) else None,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _without(value: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: item for name, item in value.items() if name != key}


__all__ = [
    "MAX_SECURITY_IMPORT_BYTES",
    "export_security_findings_sarif",
    "import_security_findings",
    "require_security_finding_import_pass",
    "validate_security_finding_import",
]

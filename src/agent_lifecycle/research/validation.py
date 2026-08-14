"""Fail-closed validation and summaries for research evidence packages."""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.redaction import contains_local_absolute_path, is_sensitive_key, redact_text
from agent_lifecycle.contracts.research_evidence_schemas import (
    RESEARCH_CITATION_MATCH_STATUSES,
    RESEARCH_EVIDENCE_STATUSES,
    RESEARCH_PROVENANCE_RELATIONSHIPS,
    RESEARCH_SOURCE_KINDS,
)
from agent_lifecycle.research.evidence import (
    MAX_CLAIM_RECORDS,
    MAX_CITATION_RECORDS,
    MAX_EVIDENCE_BYTES,
    MAX_PROVENANCE_EDGES,
    MAX_SOURCE_RECORDS,
    claim_digest,
    decode_snapshot,
    package_digest,
    quote_digest,
    snapshot_digest,
)
from agent_lifecycle.research.provenance import analyze_provenance


_AUTHORITY_MARKERS = re.compile(
    r"\b(?:ignore\s+(?:all\s+)?previous|system\s+instruction|developer\s+instruction|"
    r"bypass\s+(?:review|freeze)|approve\s+(?:all\s+)?tools|execute\s+(?:the\s+)?(?:tool|command)|"
    r"freeze\s+(?:the\s+)?plan|accept\s+(?:the\s+)?task)\b",
    re.IGNORECASE,
)
_FORBIDDEN_CONTENT_KEYS = {
    "rawtext",
    "sourcetext",
    "sourcebody",
    "body",
    "content",
    "transcript",
    "prompt",
    "systeminstruction",
    "developerinstruction",
    "instruction",
    "command",
    "environment",
    "cwd",
    "localpath",
    "absolutepath",
}
_PROVIDER_KEYS = {"provider", "model", "providername", "modelname", "providermodel", "providermodelnames"}


def validate_evidence_package(
    package: dict[str, Any],
    *,
    snapshots: dict[str, str | bytes] | None = None,
    max_bytes: int = MAX_EVIDENCE_BYTES,
) -> dict[str, Any]:
    """Validate package structure, bindings, provenance and untrusted content."""

    if not isinstance(package, dict):
        raise LifecycleError("research-package-not-object", "research evidence package must be an object")
    blockers: list[dict[str, Any]] = []
    binding_checks: list[dict[str, Any]] = []
    lifecycle_checks: list[dict[str, Any]] = []
    security_checks: list[dict[str, Any]] = []
    snapshots = snapshots or {}
    _check_package_header(package, blockers)
    sources = _records(package, "sources", MAX_SOURCE_RECORDS, blockers)
    claims = _records(package, "claims", MAX_CLAIM_RECORDS, blockers)
    citations = _records(package, "citations", MAX_CITATION_RECORDS, blockers)
    provenance = _records(package, "provenance", MAX_PROVENANCE_EDGES, blockers)
    source_map = _index_records(sources, "sourceId", "source", blockers)
    claim_map = _index_records(claims, "claimId", "claim", blockers)
    citation_map = _index_records(citations, "citationId", "citation", blockers)

    for source in sources:
        _validate_source(source, source_map, lifecycle_checks, blockers)
    for claim in claims:
        _validate_claim(claim, claim_map, lifecycle_checks, blockers)
    for citation in citations:
        _validate_citation(citation, source_map, claim_map, citation_map, snapshots, binding_checks, blockers)

    provenance_report = analyze_provenance(sources, provenance)
    blockers.extend(provenance_report["blockers"])
    for edge in provenance:
        if isinstance(edge, dict) and edge.get("relationship") in RESEARCH_PROVENANCE_RELATIONSHIPS:
            binding_checks.append(
                {
                    "kind": "provenance-edge",
                    "sourceId": edge.get("sourceId"),
                    "relatedSourceId": edge.get("relatedSourceId"),
                    "relationship": edge.get("relationship"),
                    "status": "PASS" if not provenance_report["blockers"] else "FAIL",
                }
            )

    security_report = _security_report(package, max_bytes=max_bytes)
    security_checks.extend(security_report["checks"])
    blockers.extend(security_report["blockers"])
    body = {
        "schemaVersion": "agent-research-evidence-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "packageDigest": package.get("packageDigest"),
        "bindingChecks": binding_checks,
        "provenanceChecks": [
            {
                "status": provenance_report["status"],
                "cycleCount": len(provenance_report["cycles"]),
                "disconnectedSourceGroups": provenance_report["disconnectedSourceGroups"],
                "duplicateGroups": provenance_report["duplicateGroups"],
                "independentSourceIds": provenance_report["independentSourceIds"],
            }
        ],
        "lifecycleChecks": lifecycle_checks,
        "securityChecks": security_checks,
        "blockers": _bounded_blockers(blockers),
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def build_evidence_summary(package: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    """Build a bounded summary without copying source bodies or snapshots."""

    claims = package.get("claims") if isinstance(package.get("claims"), list) else []
    citations = package.get("citations") if isinstance(package.get("citations"), list) else []
    citation_claim_ids = {item.get("claimId") for item in citations if isinstance(item, dict) and item.get("matchStatus") == "MATCHED"}
    supported_claims = sorted(
        str(item.get("claimId"))
        for item in claims
        if isinstance(item, dict) and item.get("claimId") in citation_claim_ids and item.get("status") not in {"stale", "disputed"}
    )
    lifecycle_counts = Counter(
        str(item.get("status"))
        for item in [*(package.get("sources") or []), *(package.get("claims") or [])]
        if isinstance(item, dict) and item.get("status") in RESEARCH_EVIDENCE_STATUSES
    )
    blockers = validation.get("blockers") if isinstance(validation.get("blockers"), list) else []
    body = {
        "schemaVersion": "agent-research-evidence-summary.v1",
        "status": "PASS" if validation.get("status") == "PASS" else "FAIL",
        "packageDigest": package.get("packageDigest"),
        "counts": {
            "sources": len(package.get("sources") or []),
            "claims": len(claims),
            "citations": len(citations),
            "provenance": len(package.get("provenance") or []),
            "blockers": len(blockers),
        },
        "supportedClaims": supported_claims,
        "evidenceGaps": _evidence_gaps(claims, citations),
        "duplicateGroups": _duplicate_groups(validation),
        "lifecycleCounts": dict(sorted(lifecycle_counts.items())),
        "redaction": package.get("redaction") if isinstance(package.get("redaction"), dict) else {"status": "UNKNOWN"},
        "sourceOfTruth": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "summaryDigest": canonical_digest(body)}


def require_evidence_validation_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError("research-evidence-validation-failed", "research evidence validation failed", {"validation": validation})
    return validation


def _check_package_header(package: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    if package.get("schemaVersion") != "agent-research-evidence-package.v1":
        blockers.append({"code": "research-package-schema-invalid"})
    if not isinstance(package.get("packageId"), str) or not package["packageId"].strip():
        blockers.append({"code": "research-package-id-invalid"})
    if package.get("sourceOfTruth") is not False:
        blockers.append({"code": "research-package-source-of-truth"})
    if package.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "research-package-production-claim"})
    if not _is_digest(package.get("packageDigest")):
        blockers.append({"code": "research-package-digest-missing"})
    elif package.get("packageDigest") != package_digest(package):
        blockers.append({"code": "research-package-digest-mismatch"})
    resource_caps = package.get("resourceCaps")
    if not isinstance(resource_caps, dict):
        blockers.append({"code": "research-package-resource-caps-invalid"})
    else:
        declared_bytes = resource_caps.get("maxEvidenceBytes")
        if isinstance(declared_bytes, int) and declared_bytes > MAX_EVIDENCE_BYTES:
            blockers.append({"code": "research-package-byte-cap-exceeded", "maxEvidenceBytes": declared_bytes})


def _records(package: dict[str, Any], key: str, limit: int, blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    value = package.get(key)
    if not isinstance(value, list):
        blockers.append({"code": f"research-{key}-not-array"})
        return []
    if len(value) > limit:
        blockers.append({"code": f"research-{key}-limit-exceeded", "count": len(value), "limit": limit})
    return [item for item in value if isinstance(item, dict)]


def _index_records(records: list[dict[str, Any]], key: str, label: str, blockers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for position, record in enumerate(records):
        value = record.get(key)
        if not isinstance(value, str) or not value.strip():
            blockers.append({"code": f"research-{label}-id-invalid", "index": position})
            continue
        if value in index:
            blockers.append({"code": f"research-{label}-id-duplicate", "id": value})
            continue
        index[value] = record
    return index


def _validate_source(source: dict[str, Any], source_map: dict[str, dict[str, Any]], lifecycle: list[dict[str, Any]], blockers: list[dict[str, Any]]) -> None:
    source_id = source.get("sourceId")
    if source.get("kind") not in RESEARCH_SOURCE_KINDS:
        blockers.append({"code": "research-source-kind-invalid", "sourceId": source_id})
    if not isinstance(source.get("title"), str) or not source["title"].strip() or len(source["title"]) > 4096:
        blockers.append({"code": "research-source-title-invalid", "sourceId": source_id})
    if not _is_digest(source.get("sourceDigest")):
        blockers.append({"code": "research-source-digest-invalid", "sourceId": source_id})
    if not _is_optional_digest(source.get("snapshotDigest")):
        blockers.append({"code": "research-source-snapshot-digest-invalid", "sourceId": source_id})
    if source.get("sourceOfTruth") is not False or source.get("rawContentStored") is not False:
        blockers.append({"code": "research-source-authority-or-content", "sourceId": source_id})
    if source.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "research-source-production-claim", "sourceId": source_id})
    _validate_lifecycle(source, "source", source_id, lifecycle, blockers)
    _validate_locator(source.get("locator"), source_id, blockers)


def _validate_claim(claim: dict[str, Any], claim_map: dict[str, dict[str, Any]], lifecycle: list[dict[str, Any]], blockers: list[dict[str, Any]]) -> None:
    claim_id = claim.get("claimId")
    value = claim.get("claim")
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        blockers.append({"code": "research-claim-text-invalid", "claimId": claim_id})
    elif claim.get("claimDigest") != claim_digest(value):
        blockers.append({"code": "research-claim-digest-mismatch", "claimId": claim_id})
    if not isinstance(claim.get("supportingSourceIds"), list) or not claim["supportingSourceIds"]:
        blockers.append({"code": "research-claim-sources-missing", "claimId": claim_id})
    if not isinstance(claim.get("citationIds"), list):
        blockers.append({"code": "research-claim-citations-invalid", "claimId": claim_id})
    if claim.get("sourceOfTruth") is not False or claim.get("lifecycleAuthority") != "none":
        blockers.append({"code": "research-claim-authority", "claimId": claim_id})
    if claim.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "research-claim-production-claim", "claimId": claim_id})
    _validate_lifecycle(claim, "claim", claim_id, lifecycle, blockers)


def _validate_citation(
    citation: dict[str, Any],
    source_map: dict[str, dict[str, Any]],
    claim_map: dict[str, dict[str, Any]],
    citation_map: dict[str, dict[str, Any]],
    snapshots: dict[str, str | bytes],
    checks: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> None:
    citation_id = citation.get("citationId")
    source_id = citation.get("sourceId")
    claim_id = citation.get("claimId")
    source = source_map.get(source_id)
    claim = claim_map.get(claim_id)
    if source is None:
        blockers.append({"code": "research-citation-source-missing", "citationId": citation_id})
    if claim is None:
        blockers.append({"code": "research-citation-claim-missing", "citationId": citation_id})
    if source is not None and claim is not None and source_id not in (claim.get("supportingSourceIds") or []):
        blockers.append({"code": "research-citation-claim-source-unbound", "citationId": citation_id})
    if not _is_digest(citation.get("quoteDigest")):
        blockers.append({"code": "research-citation-quote-digest-invalid", "citationId": citation_id})
    if not _is_optional_digest(citation.get("snapshotDigest")):
        blockers.append({"code": "research-citation-snapshot-digest-invalid", "citationId": citation_id})
    match_status = citation.get("matchStatus")
    if match_status not in RESEARCH_CITATION_MATCH_STATUSES:
        blockers.append({"code": "research-citation-match-status-invalid", "citationId": citation_id})
    _validate_locator(citation.get("locator"), citation_id, blockers)
    if source is not None and source.get("snapshotDigest") != citation.get("snapshotDigest") and citation.get("snapshotDigest") is not None:
        blockers.append({"code": "research-citation-source-snapshot-mismatch", "citationId": citation_id})
    snapshot = snapshots.get(source_id)
    if snapshot is None:
        if match_status == "MATCHED":
            blockers.append({"code": "research-citation-snapshot-required", "citationId": citation_id})
        if match_status == "MISMATCH":
            checks.append({"kind": "citation", "citationId": citation_id, "status": "REPORTED_MISMATCH"})
        else:
            checks.append({"kind": "citation", "citationId": citation_id, "status": "UNAVAILABLE"})
        return
    raw = snapshot.encode("utf-8") if isinstance(snapshot, str) else snapshot
    actual_snapshot_digest = snapshot_digest(raw)
    if source is not None and source.get("snapshotDigest") != actual_snapshot_digest:
        blockers.append({"code": "research-source-snapshot-mismatch", "sourceId": source_id})
    if citation.get("snapshotDigest") != actual_snapshot_digest:
        blockers.append({"code": "research-citation-snapshot-mismatch", "citationId": citation_id})
    try:
        text = decode_snapshot(raw)
        locator = citation.get("locator") if isinstance(citation.get("locator"), dict) else {}
        start = locator.get("start")
        end = locator.get("end")
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end < start or end > len(text):
            blockers.append({"code": "research-citation-range-invalid", "citationId": citation_id})
            return
        actual_quote_digest = quote_digest(text[start:end])
        if citation.get("quoteDigest") != actual_quote_digest:
            blockers.append({"code": "research-citation-quote-mismatch", "citationId": citation_id})
        if match_status != "MATCHED":
            blockers.append({"code": "research-citation-status-mismatch", "citationId": citation_id})
        checks.append({"kind": "citation", "citationId": citation_id, "status": "PASS" if not blockers else "CHECKED"})
    except LifecycleError as exc:
        blockers.append({"code": exc.code, "citationId": citation_id})


def _validate_lifecycle(record: dict[str, Any], kind: str, record_id: Any, checks: list[dict[str, Any]], blockers: list[dict[str, Any]]) -> None:
    status = record.get("status")
    if status not in RESEARCH_EVIDENCE_STATUSES:
        blockers.append({"code": f"research-{kind}-status-invalid", "id": record_id})
    else:
        checks.append({"kind": kind, "id": record_id, "status": status, "authority": "none"})


def _validate_locator(locator: Any, record_id: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(locator, dict) or not locator:
        blockers.append({"code": "research-locator-invalid", "id": record_id})
        return
    for key, value in locator.items():
        if isinstance(value, str):
            if contains_local_absolute_path(value):
                blockers.append({"code": "research-locator-private-path", "id": record_id, "field": key})
            if value.startswith("file://"):
                blockers.append({"code": "research-locator-file-uri", "id": record_id, "field": key})


def _security_report(package: dict[str, Any], *, max_bytes: int) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    encoded = json.dumps(package, ensure_ascii=False, sort_keys=True)
    if len(encoded.encode("utf-8")) > max_bytes:
        blockers.append({"code": "research-package-serialized-cap-exceeded"})
    for path, key, value in _walk(package):
        normalized = key.replace("-", "").replace("_", "").lower()
        if normalized in _FORBIDDEN_CONTENT_KEYS:
            blockers.append({"code": "research-raw-content-field", "path": path})
        if normalized in _PROVIDER_KEYS:
            blockers.append({"code": "research-provider-model-field", "path": path})
        if isinstance(value, str):
            if _AUTHORITY_MARKERS.search(value):
                blockers.append({"code": "research-prompt-authority-marker", "path": path})
            redacted, changed = redact_text(value)
            if changed and redacted != value:
                blockers.append({"code": "research-sensitive-content", "path": path})
    checks.append({"name": "bounded-content", "status": "FAIL" if blockers else "PASS"})
    return {"checks": checks, "blockers": blockers}


def _walk(value: Any, path: str = "$") -> list[tuple[str, str, Any]]:
    result: list[tuple[str, str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            result.append((child_path, key_text, item))
            result.extend(_walk(item, child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.extend(_walk(item, f"{path}[{index}]"))
    return result


def _evidence_gaps(claims: list[Any], citations: list[Any]) -> list[dict[str, Any]]:
    cited = {item.get("claimId") for item in citations if isinstance(item, dict) and item.get("matchStatus") == "MATCHED"}
    return [
        {"claimId": item.get("claimId"), "reason": "no-matched-citation"}
        for item in claims
        if isinstance(item, dict) and item.get("claimId") not in cited
    ]


def _duplicate_groups(validation: dict[str, Any]) -> list[dict[str, Any]]:
    for check in validation.get("provenanceChecks", []):
        if isinstance(check, dict):
            return [{"sourceIds": group, "independent": False} for group in check.get("duplicateGroups", [])]
    return []


def _bounded_blockers(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return blockers[:128]


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _is_optional_digest(value: Any) -> bool:
    return value is None or _is_digest(value)

"""Portable contracts for bounded research evidence packages."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.public_locators import MAX_PUBLIC_LOCATOR_BYTES
from agent_lifecycle.contracts.schema_builders import open_object_schema

RESEARCH_SOURCE_SCHEMA = "agent-research-source.v1"
RESEARCH_CLAIM_SCHEMA = "agent-research-claim.v1"
RESEARCH_CITATION_SCHEMA = "agent-research-citation.v1"
RESEARCH_PROVENANCE_SCHEMA = "agent-research-provenance-edge.v1"
RESEARCH_PACKAGE_SCHEMA = "agent-research-evidence-package.v1"
RESEARCH_VALIDATION_SCHEMA = "agent-research-evidence-validation.v1"
RESEARCH_SUMMARY_SCHEMA = "agent-research-evidence-summary.v1"

RESEARCH_EVIDENCE_STATUSES = ("draft", "reviewed", "accepted", "stale", "disputed")
RESEARCH_SOURCE_KINDS = ("web", "file", "repository", "issue", "conversation", "paper", "other")
RESEARCH_CITATION_MATCH_STATUSES = ("MATCHED", "UNAVAILABLE", "MISMATCH", "NOT_REQUESTED")
RESEARCH_PROVENANCE_RELATIONSHIPS = ("seed", "suggested-by", "derived-from", "duplicate-of")
RESEARCH_INDEPENDENCE_STATUSES = ("independent", "derivative", "duplicate", "unknown")

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}
_OPTIONAL_DIGEST = {"type": ["string", "null"], "minLength": 64, "maxLength": 64}
_BLOCKERS = {"type": "array", "items": {"type": "object"}, "maxItems": 128}
_BOUNDED_METADATA = {"type": "object", "maxProperties": 32}
_BOUNDED_TEXT = {"type": "string", "minLength": 1, "maxLength": 4096}
_BOUNDED_ID = {"type": "string", "minLength": 1, "maxLength": 160}
_BOUNDED_LOCATOR = {
    "type": "object",
    "maxProperties": 8,
    "properties": {
        "kind": {"type": "string", "minLength": 1, "maxLength": 32},
        "value": {"type": "string", "minLength": 1, "maxLength": MAX_PUBLIC_LOCATOR_BYTES},
    },
}


RESEARCH_EVIDENCE_SCHEMAS: dict[str, dict[str, Any]] = {
    RESEARCH_SOURCE_SCHEMA: open_object_schema(
        RESEARCH_SOURCE_SCHEMA,
        required=[
            "schemaVersion",
            "sourceId",
            "kind",
            "locator",
            "title",
            "status",
            "sourceDigest",
            "snapshotDigest",
            "metadata",
            "redactionStatus",
            "sourceOfTruth",
            "rawContentStored",
            "productionPromotionClaimed",
        ],
        properties={
            "sourceId": _BOUNDED_ID,
            "kind": {"enum": list(RESEARCH_SOURCE_KINDS)},
            "locator": _BOUNDED_LOCATOR,
            "title": _BOUNDED_TEXT,
            "status": {"enum": list(RESEARCH_EVIDENCE_STATUSES)},
            "sourceDigest": _DIGEST,
            "snapshotDigest": _OPTIONAL_DIGEST,
            "metadata": _BOUNDED_METADATA,
            "redactionStatus": {"type": "object", "maxProperties": 16},
            "sourceOfTruth": {"const": False},
            "rawContentStored": {"const": False},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    RESEARCH_CLAIM_SCHEMA: open_object_schema(
        RESEARCH_CLAIM_SCHEMA,
        required=[
            "schemaVersion",
            "claimId",
            "claim",
            "claimDigest",
            "status",
            "supportingSourceIds",
            "citationIds",
            "sourceOfTruth",
            "lifecycleAuthority",
            "productionPromotionClaimed",
        ],
        properties={
            "claimId": _BOUNDED_ID,
            "claim": _BOUNDED_TEXT,
            "claimDigest": _DIGEST,
            "status": {"enum": list(RESEARCH_EVIDENCE_STATUSES)},
            "supportingSourceIds": {"type": "array", "items": _BOUNDED_ID, "maxItems": 128},
            "citationIds": {"type": "array", "items": _BOUNDED_ID, "maxItems": 256},
            "sourceOfTruth": {"const": False},
            "lifecycleAuthority": {"const": "none"},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    RESEARCH_CITATION_SCHEMA: open_object_schema(
        RESEARCH_CITATION_SCHEMA,
        required=[
            "schemaVersion",
            "citationId",
            "claimId",
            "sourceId",
            "locator",
            "quoteDigest",
            "snapshotDigest",
            "matchStatus",
            "redactionStatus",
            "productionPromotionClaimed",
        ],
        properties={
            "citationId": _BOUNDED_ID,
            "claimId": _BOUNDED_ID,
            "sourceId": _BOUNDED_ID,
            "locator": _BOUNDED_LOCATOR,
            "quoteDigest": _DIGEST,
            "snapshotDigest": _OPTIONAL_DIGEST,
            "matchStatus": {"enum": list(RESEARCH_CITATION_MATCH_STATUSES)},
            "redactionStatus": {"type": "object", "maxProperties": 16},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    RESEARCH_PROVENANCE_SCHEMA: open_object_schema(
        RESEARCH_PROVENANCE_SCHEMA,
        required=[
            "schemaVersion",
            "edgeId",
            "sourceId",
            "relatedSourceId",
            "relationship",
            "independence",
            "attestation",
            "productionPromotionClaimed",
        ],
        properties={
            "edgeId": _BOUNDED_ID,
            "sourceId": _BOUNDED_ID,
            "relatedSourceId": _BOUNDED_ID,
            "relationship": {"enum": list(RESEARCH_PROVENANCE_RELATIONSHIPS)},
            "independence": {"enum": list(RESEARCH_INDEPENDENCE_STATUSES)},
            "attestation": {"type": "object", "maxProperties": 16},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    RESEARCH_PACKAGE_SCHEMA: open_object_schema(
        RESEARCH_PACKAGE_SCHEMA,
        required=[
            "schemaVersion",
            "packageId",
            "status",
            "sources",
            "claims",
            "citations",
            "provenance",
            "resourceCaps",
            "redaction",
            "sourceOfTruth",
            "blockers",
            "productionPromotionClaimed",
            "packageDigest",
        ],
        properties={
            "packageId": _BOUNDED_ID,
            "status": {"enum": ["PASS", "FAIL", "BLOCKED", "REVIEW_REQUIRED"]},
            "sources": {"type": "array", "items": {"type": "object"}, "maxItems": 128},
            "claims": {"type": "array", "items": {"type": "object"}, "maxItems": 256},
            "citations": {"type": "array", "items": {"type": "object"}, "maxItems": 256},
            "provenance": {"type": "array", "items": {"type": "object"}, "maxItems": 512},
            "resourceCaps": _BOUNDED_METADATA,
            "redaction": {"type": "object", "maxProperties": 16},
            "sourceOfTruth": {"const": False},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "packageDigest": _DIGEST,
        },
    ),
    RESEARCH_VALIDATION_SCHEMA: open_object_schema(
        RESEARCH_VALIDATION_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "packageDigest",
            "bindingChecks",
            "provenanceChecks",
            "lifecycleChecks",
            "securityChecks",
            "blockers",
            "productionPromotionClaimed",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "packageDigest": _OPTIONAL_DIGEST,
            "bindingChecks": {"type": "array", "items": {"type": "object"}, "maxItems": 256},
            "provenanceChecks": {"type": "array", "items": {"type": "object"}, "maxItems": 512},
            "lifecycleChecks": {"type": "array", "items": {"type": "object"}, "maxItems": 256},
            "securityChecks": {"type": "array", "items": {"type": "object"}, "maxItems": 256},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
    RESEARCH_SUMMARY_SCHEMA: open_object_schema(
        RESEARCH_SUMMARY_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "packageDigest",
            "counts",
            "supportedClaims",
            "evidenceGaps",
            "duplicateGroups",
            "lifecycleCounts",
            "redaction",
            "sourceOfTruth",
            "productionPromotionClaimed",
            "summaryDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "packageDigest": _DIGEST,
            "counts": {"type": "object", "maxProperties": 16},
            "supportedClaims": {"type": "array", "items": _BOUNDED_ID, "maxItems": 256},
            "evidenceGaps": {"type": "array", "items": {"type": "object"}, "maxItems": 256},
            "duplicateGroups": {"type": "array", "items": {"type": "object"}, "maxItems": 128},
            "lifecycleCounts": {"type": "object", "maxProperties": 8},
            "redaction": {"type": "object", "maxProperties": 16},
            "sourceOfTruth": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "summaryDigest": _DIGEST,
        },
    ),
}


__all__ = [
    "RESEARCH_CITATION_MATCH_STATUSES",
    "RESEARCH_CITATION_SCHEMA",
    "RESEARCH_CLAIM_SCHEMA",
    "RESEARCH_EVIDENCE_SCHEMAS",
    "RESEARCH_EVIDENCE_STATUSES",
    "RESEARCH_INDEPENDENCE_STATUSES",
    "RESEARCH_PACKAGE_SCHEMA",
    "RESEARCH_PROVENANCE_RELATIONSHIPS",
    "RESEARCH_PROVENANCE_SCHEMA",
    "RESEARCH_SOURCE_KINDS",
    "RESEARCH_SOURCE_SCHEMA",
    "RESEARCH_SUMMARY_SCHEMA",
    "RESEARCH_VALIDATION_SCHEMA",
]

"""Versioned contracts for optional project domain language artifacts."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema

DOMAIN_LANGUAGE_SCHEMA = "agent-project-domain-language.v1"
DOMAIN_LANGUAGE_VALIDATION_SCHEMA = "agent-project-domain-language-validation.v1"
DOMAIN_LANGUAGE_DELTA_SCHEMA = "agent-project-domain-language-delta.v1"
DOMAIN_LANGUAGE_AUDIT_SCHEMA = "agent-project-domain-language-audit.v1"
DOMAIN_LANGUAGE_CONTINUITY_SCHEMA = "agent-project-domain-language-continuity.v1"
DOMAIN_LANGUAGE_CONTINUITY_VALIDATION_SCHEMA = "agent-project-domain-language-continuity-validation.v1"

DOMAIN_LANGUAGE_LOCALES = ("en", "ru")
DOMAIN_LANGUAGE_REFERENCE_KINDS = ("requirement", "api", "symbol", "test", "documentation")
DOMAIN_LANGUAGE_ALIAS_STATUSES = ("ACTIVE", "DEPRECATED")

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}
_OPTIONAL_DIGEST = {"type": ["string", "null"], "minLength": 0, "maxLength": 64}
_OPTIONAL_ID = {"type": ["string", "null"], "minLength": 0, "maxLength": 160}
_BOUNDED_ID = {"type": "string", "minLength": 1, "maxLength": 160}
_BOUNDED_TEXT = {"type": "string", "minLength": 1, "maxLength": 2048}
_LOCALE = {"enum": list(DOMAIN_LANGUAGE_LOCALES)}
_BILINGUAL_TEXT = {
    "type": "object",
    "required": list(DOMAIN_LANGUAGE_LOCALES),
    "properties": {locale: _BOUNDED_TEXT for locale in DOMAIN_LANGUAGE_LOCALES},
    "maxProperties": 2,
}
_REFERENCE = {
    "type": "object",
    "required": ["kind", "path"],
    "properties": {
        "kind": {"enum": list(DOMAIN_LANGUAGE_REFERENCE_KINDS)},
        "path": {"type": "string", "minLength": 1, "maxLength": 1024},
        "locator": {"type": "string", "minLength": 1, "maxLength": 256},
    },
    "maxProperties": 3,
}
_ALIAS = {
    "type": "object",
    "required": ["value", "locale", "status"],
    "properties": {
        "value": _BOUNDED_TEXT,
        "locale": _LOCALE,
        "status": {"enum": list(DOMAIN_LANGUAGE_ALIAS_STATUSES)},
        "replacementTermId": _BOUNDED_ID,
    },
    "maxProperties": 4,
}
_TERM = {
    "type": "object",
    "required": ["termId", "labels", "definitions", "aliases", "contexts", "references"],
    "properties": {
        "termId": _BOUNDED_ID,
        "labels": _BILINGUAL_TEXT,
        "definitions": _BILINGUAL_TEXT,
        "aliases": {"type": "array", "maxItems": 32, "items": _ALIAS},
        "contexts": {"type": "array", "minItems": 1, "maxItems": 16, "items": _BOUNDED_ID},
        "references": {"type": "array", "maxItems": 64, "items": _REFERENCE},
    },
    "maxProperties": 6,
}

DOMAIN_LANGUAGE_SCHEMAS: dict[str, dict[str, Any]] = {
    DOMAIN_LANGUAGE_SCHEMA: open_object_schema(
        DOMAIN_LANGUAGE_SCHEMA,
        required=[
            "schemaVersion",
            "languageId",
            "revision",
            "defaultLocale",
            "terms",
            "authority",
            "source",
            "productionPromotionClaimed",
            "languageDigest",
        ],
        properties={
            "languageId": _BOUNDED_ID,
            "revision": {"type": "integer", "minimum": 1, "maximum": 1_000_000},
            "defaultLocale": _LOCALE,
            "terms": {"type": "array", "minItems": 1, "maxItems": 128, "items": _TERM},
            "authority": {"type": "object", "maxProperties": 8},
            "source": {"type": "object", "maxProperties": 8},
            "productionPromotionClaimed": {"const": False},
            "languageDigest": _DIGEST,
        },
    ),
    DOMAIN_LANGUAGE_VALIDATION_SCHEMA: open_object_schema(
        DOMAIN_LANGUAGE_VALIDATION_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "languageDigest",
            "termCount",
            "referenceCount",
            "blockers",
            "productionPromotionClaimed",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "languageDigest": _OPTIONAL_DIGEST,
            "termCount": {"type": "integer", "minimum": 0, "maximum": 128},
            "referenceCount": {"type": "integer", "minimum": 0, "maximum": 8192},
            "blockers": {"type": "array", "items": {"type": "object"}, "maxItems": 256},
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
    DOMAIN_LANGUAGE_DELTA_SCHEMA: open_object_schema(
        DOMAIN_LANGUAGE_DELTA_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "beforeDigest",
            "afterDigest",
            "addedTermIds",
            "removedTermIds",
            "changedTermIds",
            "renamedTerms",
            "deprecatedAliases",
            "impactedReferences",
            "readOnly",
            "blockers",
            "productionPromotionClaimed",
            "deltaDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "BLOCKED"]},
            "beforeDigest": _OPTIONAL_DIGEST,
            "afterDigest": _OPTIONAL_DIGEST,
            "addedTermIds": {"type": "array", "maxItems": 128, "items": _BOUNDED_ID},
            "removedTermIds": {"type": "array", "maxItems": 128, "items": _BOUNDED_ID},
            "changedTermIds": {"type": "array", "maxItems": 128, "items": _BOUNDED_ID},
            "renamedTerms": {"type": "array", "maxItems": 128, "items": {"type": "object"}},
            "deprecatedAliases": {"type": "array", "maxItems": 256, "items": {"type": "object"}},
            "impactedReferences": {"type": "array", "maxItems": 8192, "items": _REFERENCE},
            "readOnly": {"const": True},
            "blockers": {"type": "array", "items": {"type": "object"}, "maxItems": 256},
            "productionPromotionClaimed": {"const": False},
            "deltaDigest": _DIGEST,
        },
    ),
    DOMAIN_LANGUAGE_AUDIT_SCHEMA: open_object_schema(
        DOMAIN_LANGUAGE_AUDIT_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "languageDigest",
            "selectedTermIds",
            "impactedReferences",
            "staleAliases",
            "blockers",
            "readOnly",
            "productionPromotionClaimed",
            "auditDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "DRIFT", "FAIL"]},
            "languageDigest": _OPTIONAL_DIGEST,
            "selectedTermIds": {"type": "array", "maxItems": 128, "items": _BOUNDED_ID},
            "impactedReferences": {"type": "array", "maxItems": 8192, "items": _REFERENCE},
            "staleAliases": {"type": "array", "maxItems": 2048, "items": {"type": "object"}},
            "blockers": {"type": "array", "items": {"type": "object"}, "maxItems": 256},
            "readOnly": {"const": True},
            "productionPromotionClaimed": {"const": False},
            "auditDigest": _DIGEST,
        },
    ),
    DOMAIN_LANGUAGE_CONTINUITY_SCHEMA: open_object_schema(
        DOMAIN_LANGUAGE_CONTINUITY_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "languageId",
            "revision",
            "languageDigest",
            "planDigest",
            "sourceRevision",
            "blockers",
            "productionPromotionClaimed",
            "continuityDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "languageId": _OPTIONAL_ID,
            "revision": {"type": ["integer", "null"], "minimum": 0, "maximum": 1_000_000},
            "languageDigest": _OPTIONAL_DIGEST,
            "planDigest": _OPTIONAL_DIGEST,
            "sourceRevision": {"type": ["string", "null"], "minLength": 0, "maxLength": 128},
            "blockers": {"type": "array", "items": {"type": "object"}, "maxItems": 256},
            "productionPromotionClaimed": {"const": False},
            "continuityDigest": _DIGEST,
        },
    ),
    DOMAIN_LANGUAGE_CONTINUITY_VALIDATION_SCHEMA: open_object_schema(
        DOMAIN_LANGUAGE_CONTINUITY_VALIDATION_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "blockers",
            "productionPromotionClaimed",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "blockers": {"type": "array", "items": {"type": "object"}, "maxItems": 256},
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
}


__all__ = [
    "DOMAIN_LANGUAGE_ALIAS_STATUSES",
    "DOMAIN_LANGUAGE_AUDIT_SCHEMA",
    "DOMAIN_LANGUAGE_CONTINUITY_SCHEMA",
    "DOMAIN_LANGUAGE_CONTINUITY_VALIDATION_SCHEMA",
    "DOMAIN_LANGUAGE_DELTA_SCHEMA",
    "DOMAIN_LANGUAGE_LOCALES",
    "DOMAIN_LANGUAGE_REFERENCE_KINDS",
    "DOMAIN_LANGUAGE_SCHEMA",
    "DOMAIN_LANGUAGE_SCHEMAS",
    "DOMAIN_LANGUAGE_VALIDATION_SCHEMA",
]

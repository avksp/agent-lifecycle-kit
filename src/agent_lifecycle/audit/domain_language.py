"""Read-only impact and stale-alias audits for project vocabularies."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.domain_language_schemas import DOMAIN_LANGUAGE_AUDIT_SCHEMA
from agent_lifecycle.contracts.paths import is_under_repo_path, normalize_repo_path
from agent_lifecycle.project.domain_language import (
    domain_language_digest,
    language_terms,
    validate_domain_language,
)

MAX_AUDIT_FILE_BYTES = 131072


def build_domain_language_impact_audit(
    language: dict[str, Any],
    *,
    changed_term_ids: list[str] | None = None,
    changed_paths: list[str] | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Report affected references and deprecated aliases without modifying files."""

    blockers: list[dict[str, Any]] = []
    validation = validate_domain_language(language, project_root=project_root)
    if validation["status"] != "PASS":
        blockers.append({"code": "domain-language-invalid", "validation": validation})

    terms = language_terms(language)
    selected = sorted(set(changed_term_ids or terms))
    for term_id in selected:
        if term_id not in terms:
            blockers.append({"code": "domain-language-term-missing", "termId": term_id})

    normalized_paths: list[str] = []
    for raw_path in changed_paths or []:
        try:
            normalized_paths.append(normalize_repo_path(raw_path, label="changed domain language path"))
        except (LifecycleError, TypeError):
            blockers.append({"code": "domain-language-changed-path-invalid", "path": raw_path})

    references: dict[tuple[str, str, str], dict[str, Any]] = {}
    stale_aliases: list[dict[str, Any]] = []
    for term_id in selected:
        term = terms.get(term_id)
        if not isinstance(term, dict):
            continue
        term_references = term.get("references", [])
        for reference in term_references if isinstance(term_references, list) else []:
            if not isinstance(reference, dict):
                continue
            path = reference.get("path")
            if not isinstance(path, str):
                continue
            try:
                normalized = normalize_repo_path(path, label="domain language reference path")
            except (LifecycleError, TypeError):
                continue
            if normalized_paths and not any(is_under_repo_path(normalized, root) for root in normalized_paths):
                continue
            normalized_reference = {
                "kind": reference.get("kind"),
                "path": normalized,
                **({"locator": reference["locator"]} if isinstance(reference.get("locator"), str) else {}),
            }
            references[(str(reference.get("kind")), normalized, str(reference.get("locator", "")))] = (
                normalized_reference
            )
            content: str | None = None
            reference_error: str | None = None
            if project_root is not None:
                content, reference_error = _read_reference(project_root, normalized)
                if reference_error is not None:
                    blockers.append({"code": reference_error, "path": normalized})

            aliases = term.get("aliases")
            if not isinstance(aliases, list):
                continue
            for alias in aliases:
                if not isinstance(alias, dict) or alias.get("status") != "DEPRECATED":
                    continue
                value = alias.get("value")
                locale = alias.get("locale")
                if not isinstance(value, str) or not isinstance(locale, str):
                    continue
                record = {
                    "termId": term_id,
                    "value": value,
                    "locale": locale,
                    "path": normalized,
                    "locator": reference.get("locator"),
                    "status": "DECLARED_DEPRECATED",
                }
                if (
                    project_root is not None
                    and reference_error is None
                    and content is not None
                    and value.casefold() in content.casefold()
                ):
                    record["status"] = "FOUND_IN_REFERENCE"
                stale_aliases.append(record)

    stale_aliases.sort(key=lambda item: (item["termId"], item["locale"], item["value"], item["path"]))
    body = {
        "schemaVersion": DOMAIN_LANGUAGE_AUDIT_SCHEMA,
        "status": "FAIL" if blockers else ("DRIFT" if stale_aliases else "PASS"),
        "languageDigest": domain_language_digest(language) if isinstance(language, dict) else None,
        "selectedTermIds": selected,
        "impactedReferences": [references[key] for key in sorted(references)],
        "staleAliases": stale_aliases,
        "blockers": blockers,
        "readOnly": True,
        "productionPromotionClaimed": False,
    }
    return {**body, "auditDigest": canonical_digest(body)}


def validate_domain_language_impact_audit(audit: dict[str, Any]) -> dict[str, Any]:
    """Validate an audit envelope and preserve its read-only boundary."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(audit, dict):
        blockers.append({"code": "domain-language-audit-invalid"})
        audit = {}
    if audit.get("schemaVersion") != DOMAIN_LANGUAGE_AUDIT_SCHEMA:
        blockers.append({"code": "domain-language-audit-schema-invalid"})
    if audit.get("readOnly") is not True:
        blockers.append({"code": "domain-language-audit-not-read-only"})
    if audit.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "domain-language-audit-production-claim"})
    expected = canonical_digest({key: value for key, value in audit.items() if key != "auditDigest"})
    if audit.get("auditDigest") != expected:
        blockers.append({"code": "domain-language-audit-digest-mismatch", "expected": expected})
    if audit.get("status") not in {"PASS", "DRIFT", "FAIL"}:
        blockers.append({"code": "domain-language-audit-status-invalid"})
    report = {
        "schemaVersion": "agent-project-domain-language-audit-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "auditStatus": audit.get("status"),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**report, "validationDigest": canonical_digest(report)}


def _read_reference(root: Path, relative_path: str) -> tuple[str | None, str | None]:
    resolved_root = root.resolve()
    raw_candidate = resolved_root / relative_path
    if _has_symlink_component(resolved_root, relative_path):
        return None, "domain-language-reference-symlink"
    candidate = raw_candidate.resolve(strict=False)
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None, "domain-language-reference-escape"
    if not candidate.exists() or not candidate.is_file():
        return None, "domain-language-reference-missing"
    try:
        if candidate.stat().st_size > MAX_AUDIT_FILE_BYTES:
            return None, "domain-language-reference-too-large"
        return candidate.read_text(encoding="utf-8", errors="ignore"), None
    except OSError:
        return None, "domain-language-reference-unreadable"


def _has_symlink_component(root: Path, relative_path: str) -> bool:
    candidate = root
    for component in Path(relative_path).parts:
        candidate /= component
        if candidate.is_symlink():
            return True
    return False

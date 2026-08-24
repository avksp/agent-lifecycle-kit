"""Validation and deterministic deltas for optional project vocabularies."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest, load_json_object
from agent_lifecycle.contracts.domain_language_schemas import (
    DOMAIN_LANGUAGE_ALIAS_STATUSES,
    DOMAIN_LANGUAGE_DELTA_SCHEMA,
    DOMAIN_LANGUAGE_LOCALES,
    DOMAIN_LANGUAGE_REFERENCE_KINDS,
    DOMAIN_LANGUAGE_SCHEMA,
    DOMAIN_LANGUAGE_VALIDATION_SCHEMA,
)
from agent_lifecycle.contracts.paths import normalize_repo_path

MAX_DOMAIN_LANGUAGE_BYTES = 131072
MAX_DOMAIN_LANGUAGE_TERMS = 128
MAX_DOMAIN_LANGUAGE_ALIASES = 32
MAX_DOMAIN_LANGUAGE_REFERENCES = 64
MAX_DOMAIN_LANGUAGE_TEXT_BYTES = 2048

_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,159}$")
_FORBIDDEN_KEYS = {
    "apikey",
    "authorization",
    "bearer",
    "credential",
    "password",
    "prompt",
    "provider",
    "secret",
    "systemprompt",
    "token",
}
_EXECUTABLE_TEXT = re.compile(
    r"(?:^|\s)(?:bash|zsh|sh|python(?:3)?|pip(?:3)?|npm|pnpm|yarn|git|curl|wget|powershell|cmd)"
    r"(?:\s|$)|(?:^|\s)(?:run|execute|invoke|launch)\s+(?:the\s+)?"
    r"(?:command|script|process)\b",
    re.IGNORECASE,
)
_REFERENCE_KINDS = set(DOMAIN_LANGUAGE_REFERENCE_KINDS)
_LOCALES = set(DOMAIN_LANGUAGE_LOCALES)
_ALIAS_STATUSES = set(DOMAIN_LANGUAGE_ALIAS_STATUSES)


def load_domain_language(path: Path, *, project_root: Path | None = None) -> dict[str, Any]:
    """Load a contained vocabulary artifact and validate its digest and shape."""

    root = (project_root or Path.cwd()).resolve()
    candidate = path if path.is_absolute() else root / path
    _require_contained_file(candidate, root)
    if candidate.stat().st_size > MAX_DOMAIN_LANGUAGE_BYTES:
        raise LifecycleError("domain-language-too-large", "project domain language exceeds the byte limit")
    payload = load_json_object(candidate.read_bytes(), label="project domain language")
    validation = validate_domain_language(payload, project_root=root, source_path=candidate)
    if validation["status"] != "PASS":
        raise LifecycleError("domain-language-invalid", "project domain language failed validation", validation)
    return payload


def domain_language_digest(language: dict[str, Any]) -> str:
    """Return the digest of vocabulary content without its self-reference."""

    body = {key: value for key, value in language.items() if key != "languageDigest"}
    return canonical_digest(body)


def validate_domain_language(
    language: dict[str, Any],
    *,
    project_root: Path | None = None,
    source_path: Path | None = None,
) -> dict[str, Any]:
    """Validate a bounded, bilingual vocabulary without executing its content."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(language, dict):
        return _validation(language, blockers=[{"code": "domain-language-not-object"}], term_count=0, reference_count=0)

    if language.get("schemaVersion") != DOMAIN_LANGUAGE_SCHEMA:
        blockers.append({"code": "domain-language-schema-invalid"})
    _reject_unsafe_content(language, blockers)
    if len(canonical_bytes(language)) > MAX_DOMAIN_LANGUAGE_BYTES:
        blockers.append({"code": "domain-language-artifact-too-large", "limit": MAX_DOMAIN_LANGUAGE_BYTES})

    language_id = language.get("languageId")
    if not _valid_id(language_id):
        blockers.append({"code": "domain-language-id-invalid"})
    revision = language.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or not 1 <= revision <= 1_000_000:
        blockers.append({"code": "domain-language-revision-invalid"})
    if language.get("defaultLocale") not in _LOCALES:
        blockers.append({"code": "domain-language-default-locale-invalid"})

    terms = language.get("terms")
    term_count = len(terms) if isinstance(terms, list) else 0
    if not isinstance(terms, list) or not terms:
        blockers.append({"code": "domain-language-terms-required"})
        terms = []
    if len(terms) > MAX_DOMAIN_LANGUAGE_TERMS:
        blockers.append({"code": "domain-language-term-limit", "limit": MAX_DOMAIN_LANGUAGE_TERMS})

    term_ids: set[str] = set()
    labels: dict[tuple[str, str], str] = {}
    reference_count = 0
    for index, term in enumerate(terms):
        if not isinstance(term, dict):
            blockers.append({"code": "domain-language-term-invalid", "index": index})
            continue
        term_id = term.get("termId")
        term_id_value = term_id if isinstance(term_id, str) else None
        if not _valid_id(term_id_value):
            blockers.append({"code": "domain-language-term-id-invalid", "index": index})
        elif term_id_value is not None and term_id_value in term_ids:
            blockers.append({"code": "domain-language-term-id-duplicate", "termId": term_id_value})
        elif term_id_value is not None:
            term_ids.add(term_id_value)
        _validate_bilingual(term.get("labels"), "labels", index, blockers)
        _validate_bilingual(term.get("definitions"), "definitions", index, blockers)
        _validate_contexts(term.get("contexts"), index, blockers)

        labels_value = term.get("labels")
        if isinstance(labels_value, dict):
            for locale in DOMAIN_LANGUAGE_LOCALES:
                label = labels_value.get(locale)
                if isinstance(label, str) and label.strip():
                    key = (locale, label.casefold())
                    previous = labels.get(key)
                    if previous is not None and previous != term_id:
                        blockers.append({"code": "domain-language-label-ambiguous", "locale": locale, "value": label})
                    elif term_id_value is not None:
                        labels[key] = term_id_value

        aliases = term.get("aliases")
        if not isinstance(aliases, list):
            blockers.append({"code": "domain-language-aliases-invalid", "index": index})
            aliases = []
        if len(aliases) > MAX_DOMAIN_LANGUAGE_ALIASES:
            blockers.append({"code": "domain-language-alias-limit", "index": index})
        alias_keys: set[tuple[str, str]] = set()
        for alias_index, alias in enumerate(aliases):
            if not isinstance(alias, dict):
                blockers.append({"code": "domain-language-alias-invalid", "index": index, "aliasIndex": alias_index})
                continue
            value = alias.get("value")
            alias_locale = alias.get("locale")
            status = alias.get("status")
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value.encode("utf-8")) > MAX_DOMAIN_LANGUAGE_TEXT_BYTES
            ):
                blockers.append(
                    {"code": "domain-language-alias-value-invalid", "index": index, "aliasIndex": alias_index}
                )
            if alias_locale not in _LOCALES:
                blockers.append(
                    {"code": "domain-language-alias-locale-invalid", "index": index, "aliasIndex": alias_index}
                )
            if status not in _ALIAS_STATUSES:
                blockers.append(
                    {"code": "domain-language-alias-status-invalid", "index": index, "aliasIndex": alias_index}
                )
            if isinstance(value, str) and isinstance(alias_locale, str) and alias_locale in _LOCALES:
                key = (alias_locale, value.casefold())
                if key in alias_keys:
                    blockers.append({"code": "domain-language-alias-duplicate", "index": index, "value": value})
                alias_keys.add(key)
                previous = labels.get(key)
                if previous is not None and previous != term_id:
                    blockers.append({"code": "domain-language-alias-ambiguous", "locale": locale, "value": value})
                elif term_id_value is not None:
                    labels[key] = term_id_value
            replacement = alias.get("replacementTermId")
            if replacement is not None and not _valid_id(replacement):
                blockers.append({"code": "domain-language-alias-replacement-invalid", "index": index})

        references = term.get("references")
        if not isinstance(references, list):
            blockers.append({"code": "domain-language-references-invalid", "index": index})
            references = []
        if len(references) > MAX_DOMAIN_LANGUAGE_REFERENCES:
            blockers.append({"code": "domain-language-reference-limit", "index": index})
        reference_count += len(references)
        for reference_index, reference in enumerate(references):
            if not isinstance(reference, dict):
                blockers.append(
                    {"code": "domain-language-reference-invalid", "index": index, "referenceIndex": reference_index}
                )
                continue
            kind = reference.get("kind")
            if kind not in _REFERENCE_KINDS:
                blockers.append({"code": "domain-language-reference-kind-invalid", "index": index})
            reference_path = reference.get("path")
            try:
                if not isinstance(reference_path, str):
                    raise TypeError("reference path must be a string")
                normalize_repo_path(reference_path, label="domain language reference path")
            except (LifecycleError, TypeError):
                blockers.append({"code": "domain-language-reference-path-invalid", "index": index})
            locator = reference.get("locator")
            if locator is not None and (not isinstance(locator, str) or not locator.strip()):
                blockers.append({"code": "domain-language-reference-locator-invalid", "index": index})

    expected_authority = {
        "role": "terminology-reference",
        "sourceOfTruth": "specification-and-frozen-plan",
        "semanticReview": "independent-review",
    }
    if language.get("authority") != expected_authority:
        blockers.append({"code": "domain-language-authority-invalid"})

    source = language.get("source")
    if not isinstance(source, dict) or source.get("kind") != "project-local":
        blockers.append({"code": "domain-language-source-invalid"})
    else:
        try:
            source_path_value = source.get("path")
            if not isinstance(source_path_value, str):
                raise TypeError("source path must be a string")
            normalized = normalize_repo_path(source_path_value, label="domain language source path")
            if project_root is not None:
                candidate = (project_root.resolve() / PurePosixPath(normalized)).resolve(strict=False)
                if not _is_relative_to(candidate, project_root.resolve()):
                    blockers.append({"code": "domain-language-source-escape"})
            if source_path is not None and normalized != _relative_path(source_path, project_root):
                blockers.append({"code": "domain-language-source-mismatch", "path": normalized})
        except (LifecycleError, TypeError):
            blockers.append({"code": "domain-language-source-path-invalid"})

    if language.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "domain-language-production-claim"})
    expected_digest = domain_language_digest(language)
    if language.get("languageDigest") != expected_digest:
        blockers.append({"code": "domain-language-digest-mismatch", "expected": expected_digest})
    return _validation(language, blockers=blockers, term_count=term_count, reference_count=reference_count)


def build_domain_language_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Build a read-only term-change report with a deterministic impact set."""

    blockers: list[dict[str, Any]] = []
    before_validation = validate_domain_language(before)
    after_validation = validate_domain_language(after)
    if before_validation["status"] != "PASS":
        blockers.append({"code": "domain-language-before-invalid", "validation": before_validation})
    if after_validation["status"] != "PASS":
        blockers.append({"code": "domain-language-after-invalid", "validation": after_validation})
    before_revision = before.get("revision") if isinstance(before, dict) else None
    after_revision = after.get("revision") if isinstance(after, dict) else None
    if not isinstance(before_revision, int) or not isinstance(after_revision, int) or after_revision <= before_revision:
        blockers.append({"code": "domain-language-revision-not-increasing"})

    before_terms = _term_map(before)
    after_terms = _term_map(after)
    added = sorted(set(after_terms) - set(before_terms))
    removed = sorted(set(before_terms) - set(after_terms))
    common = sorted(set(before_terms) & set(after_terms))
    changed = [term_id for term_id in common if before_terms[term_id] != after_terms[term_id]]
    renamed: list[dict[str, Any]] = []
    deprecated: list[dict[str, Any]] = []
    changed_ids = set(added) | set(removed) | set(changed)
    for term_id in common:
        before_term = before_terms[term_id]
        after_term = after_terms[term_id]
        if before_term.get("labels") != after_term.get("labels"):
            renamed.append(
                {
                    "termId": term_id,
                    "beforeLabels": before_term.get("labels"),
                    "afterLabels": after_term.get("labels"),
                    "kind": "RENAME",
                }
            )
        before_aliases = _alias_map(before_term)
        after_aliases = _alias_map(after_term)
        for key in sorted(set(before_aliases) & set(after_aliases)):
            previous = before_aliases[key]
            current = after_aliases[key]
            if previous.get("status") != "DEPRECATED" and current.get("status") == "DEPRECATED":
                deprecated.append({"termId": term_id, **current})
        if before_term != after_term:
            changed_ids.add(term_id)

    impacted: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for term_id in sorted(changed_ids):
        for term in (before_terms.get(term_id), after_terms.get(term_id)):
            if not isinstance(term, dict):
                continue
            for reference in term.get("references", []):
                if isinstance(reference, dict):
                    normalized = _normalized_reference(reference)
                    if normalized is not None:
                        impacted[_reference_key(normalized)] = normalized

    body = {
        "schemaVersion": DOMAIN_LANGUAGE_DELTA_SCHEMA,
        "status": "PASS" if not blockers else "BLOCKED",
        "beforeDigest": before_validation.get("languageDigest"),
        "afterDigest": after_validation.get("languageDigest"),
        "addedTermIds": added,
        "removedTermIds": removed,
        "changedTermIds": sorted(changed_ids),
        "renamedTerms": sorted(renamed, key=lambda item: item["termId"]),
        "deprecatedAliases": sorted(deprecated, key=lambda item: (item["termId"], item["locale"], item["value"])),
        "impactedReferences": [impacted[key] for key in sorted(impacted)],
        "readOnly": True,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "deltaDigest": canonical_digest(body)}


def language_terms(language: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return a stable term index for read-only consumers."""

    return _term_map(language)


def _validation(
    language: Any, *, blockers: list[dict[str, Any]], term_count: int, reference_count: int
) -> dict[str, Any]:
    digest = domain_language_digest(language) if isinstance(language, dict) else None
    body = {
        "schemaVersion": DOMAIN_LANGUAGE_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "languageDigest": digest,
        "termCount": term_count,
        "referenceCount": reference_count,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _term_map(language: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(language, dict) or not isinstance(language.get("terms"), list):
        return {}
    return {
        term["termId"]: term
        for term in language["terms"]
        if isinstance(term, dict) and isinstance(term.get("termId"), str)
    }


def _alias_map(term: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    aliases = term.get("aliases")
    if not isinstance(aliases, list):
        return {}
    return {
        (alias["locale"], alias["value"].casefold()): alias
        for alias in aliases
        if isinstance(alias, dict) and isinstance(alias.get("locale"), str) and isinstance(alias.get("value"), str)
    }


def _normalized_reference(reference: dict[str, Any]) -> dict[str, Any] | None:
    reference_path = reference.get("path")
    if not isinstance(reference_path, str):
        return None
    try:
        path = normalize_repo_path(reference_path, label="domain language reference path")
    except (LifecycleError, TypeError):
        return None
    return {
        "kind": reference.get("kind"),
        "path": path,
        **({"locator": reference["locator"]} if isinstance(reference.get("locator"), str) else {}),
    }


def _reference_key(reference: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(reference.get("kind", "")),
        str(reference.get("path", "")),
        str(reference.get("locator", "")),
        canonical_digest(reference),
    )


def _validate_bilingual(value: Any, field: str, index: int, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict):
        blockers.append({"code": f"domain-language-{field}-invalid", "index": index})
        return
    for locale in DOMAIN_LANGUAGE_LOCALES:
        text = value.get(locale)
        if not isinstance(text, str) or not text.strip():
            blockers.append({"code": f"domain-language-{field}-locale-required", "index": index, "locale": locale})
        elif len(text.encode("utf-8")) > MAX_DOMAIN_LANGUAGE_TEXT_BYTES:
            blockers.append({"code": f"domain-language-{field}-too-large", "index": index, "locale": locale})


def _validate_contexts(value: Any, index: int, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or not value:
        blockers.append({"code": "domain-language-contexts-required", "index": index})
        return
    seen: set[str] = set()
    for context in value:
        if not _valid_id(context):
            blockers.append({"code": "domain-language-context-invalid", "index": index})
        elif context in seen:
            blockers.append({"code": "domain-language-context-duplicate", "index": index, "context": context})
        seen.add(context)


def _reject_unsafe_content(value: Any, blockers: list[dict[str, Any]], *, path: str = "") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            compact = "".join(character for character in str(key).lower() if character.isalnum())
            if compact in _FORBIDDEN_KEYS:
                blockers.append({"code": "domain-language-sensitive-field", "path": f"{path}.{key}".strip(".")})
            _reject_unsafe_content(nested, blockers, path=f"{path}.{key}".strip("."))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_unsafe_content(nested, blockers, path=f"{path}[{index}]")
    elif isinstance(value, str):
        if _EXECUTABLE_TEXT.search(value):
            blockers.append({"code": "domain-language-executable-guidance", "path": path})
        if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", value):
            blockers.append({"code": "domain-language-absolute-path", "path": path})


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID_PATTERN.fullmatch(value))


def _require_contained_file(path: Path, root: Path) -> None:
    resolved = path.resolve(strict=False)
    if not _is_relative_to(resolved, root) or path.is_symlink() or not path.exists() or not path.is_file():
        raise LifecycleError("domain-language-path-invalid", "domain language must be a contained regular file")


def _relative_path(path: Path, root: Path | None) -> str | None:
    if root is None:
        return path.as_posix()
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True

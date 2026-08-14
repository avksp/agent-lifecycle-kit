"""Bounded, digest-bound project principles.

Principles provide project context for profile composition.  They are not a
specification, a prompt, or an execution policy; frozen plans and locks retain
authority over implementation.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_bytes,
    canonical_digest,
    load_json_object,
)
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.plan_delta_schemas import PROJECT_PRINCIPLES_SCHEMA

MAX_PRINCIPLES_BYTES = 65536
MAX_PRINCIPLES_ENTRIES = 32
MAX_ENTRY_BYTES = 4096
MAX_TEXT_BYTES = 2048

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
    r"(?:^|\s)(?:bash|zsh|sh|python(?:3)?|pip(?:3)?|npm|pnpm|yarn|git|curl|wget|powershell|cmd)(?:\s|$)|"
    r"(?:^|\s)(?:run|execute|invoke|launch)\s+(?:the\s+)?(?:command|script|process)\b",
    re.IGNORECASE,
)


def load_project_principles(path: Path, *, project_root: Path | None = None) -> dict[str, Any]:
    """Load a contained principles artifact and verify its digest."""

    root = (project_root or Path.cwd()).resolve()
    candidate = path if path.is_absolute() else root / path
    _require_contained_file(candidate, root)
    if candidate.stat().st_size > MAX_PRINCIPLES_BYTES:
        raise LifecycleError("project-principles-too-large", "project principles exceed the configured byte limit")
    payload = load_json_object(candidate.read_bytes(), label="project principles")
    validate_project_principles(payload, project_root=root, source_path=candidate)
    return payload


def project_principles_digest(principles: dict[str, Any]) -> str:
    """Return the digest of principles content without its self-reference."""

    body = {key: value for key, value in principles.items() if key != "principlesDigest"}
    return canonical_digest(body)


def validate_project_principles(
    principles: dict[str, Any],
    *,
    project_root: Path | None = None,
    source_path: Path | None = None,
) -> dict[str, Any]:
    """Validate bounded principles and return a deterministic validation report."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(principles, dict):
        blockers.append({"code": "principles-not-object"})
        return _validation(principles, blockers, entry_count=0)

    if principles.get("schemaVersion") != PROJECT_PRINCIPLES_SCHEMA:
        blockers.append({"code": "principles-schema-invalid"})
    _reject_forbidden_keys(principles, blockers)
    _check_text_limits(principles, blockers)

    principles_id = principles.get("principlesId")
    if not isinstance(principles_id, str) or not principles_id.strip():
        blockers.append({"code": "principles-id-required"})
    revision = principles.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or not 1 <= revision <= 1_000_000:
        blockers.append({"code": "principles-revision-invalid"})

    entries = principles.get("entries")
    entry_count = len(entries) if isinstance(entries, list) else 0
    if not isinstance(entries, list) or not entries:
        blockers.append({"code": "principles-entries-required"})
        entries = []
    if len(entries) > MAX_PRINCIPLES_ENTRIES:
        blockers.append({"code": "principles-entry-limit", "limit": MAX_PRINCIPLES_ENTRIES})
    entry_ids: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            blockers.append({"code": "principles-entry-invalid", "index": index})
            continue
        entry_id = entry.get("id")
        category = entry.get("category")
        statement = entry.get("statement")
        if not isinstance(entry_id, str) or not entry_id.strip():
            blockers.append({"code": "principles-entry-id-required", "index": index})
        elif entry_id in entry_ids:
            blockers.append({"code": "principles-entry-id-duplicate", "id": entry_id})
        else:
            entry_ids.add(entry_id)
        if not isinstance(category, str) or not category.strip():
            blockers.append({"code": "principles-entry-category-required", "index": index})
        if not isinstance(statement, str) or not statement.strip():
            blockers.append({"code": "principles-entry-statement-required", "index": index})
        elif len(statement.encode("utf-8")) > MAX_TEXT_BYTES:
            blockers.append({"code": "principles-entry-statement-too-large", "index": index})
        if len(str(entry).encode("utf-8")) > MAX_ENTRY_BYTES:
            blockers.append({"code": "principles-entry-too-large", "index": index})

    authority = principles.get("authority")
    expected_authority = {
        "principlesRole": "defaults-and-constraints",
        "sourceOfTruth": "frozen-plan-and-lock",
        "semanticReview": "independent-review",
    }
    if authority != expected_authority:
        blockers.append({"code": "principles-authority-invalid"})

    source = principles.get("source")
    if not isinstance(source, dict) or source.get("kind") != "project-local":
        blockers.append({"code": "principles-source-invalid"})
    else:
        source_value = source.get("path")
        try:
            normalized = normalize_repo_path(source_value, label="principles.source.path")
            if project_root is not None:
                candidate = (project_root.resolve() / PurePosixPath(normalized)).resolve(strict=False)
                if not _is_relative_to(candidate, project_root.resolve()):
                    blockers.append({"code": "principles-source-escape"})
            if source_path is not None and normalized != _relative_path(source_path, project_root):
                blockers.append({"code": "principles-source-mismatch", "path": normalized})
        except (LifecycleError, TypeError):
            blockers.append({"code": "principles-source-path-invalid"})

    if principles.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "principles-production-claim"})
    expected_digest = project_principles_digest(principles)
    if principles.get("principlesDigest") != expected_digest:
        blockers.append({"code": "principles-digest-mismatch", "expected": expected_digest})

    return _validation(principles, blockers, entry_count=entry_count)


def _validation(principles: Any, blockers: list[dict[str, Any]], *, entry_count: int) -> dict[str, Any]:
    digest = project_principles_digest(principles) if isinstance(principles, dict) else None
    body = {
        "schemaVersion": "agent-project-principles-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "principlesDigest": digest,
        "entryCount": entry_count,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _reject_forbidden_keys(value: Any, blockers: list[dict[str, Any]], *, path: str = "") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            compact = "".join(character for character in str(key).lower() if character.isalnum())
            if compact in _FORBIDDEN_KEYS:
                blockers.append({"code": "principles-sensitive-field", "path": f"{path}.{key}".strip(".")})
            _reject_forbidden_keys(nested, blockers, path=f"{path}.{key}".strip("."))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_forbidden_keys(nested, blockers, path=f"{path}[{index}]")
    elif isinstance(value, str):
        if _EXECUTABLE_TEXT.search(value):
            blockers.append({"code": "principles-executable-guidance", "path": path})
        if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", value):
            blockers.append({"code": "principles-absolute-path", "path": path})


def _check_text_limits(value: Any, blockers: list[dict[str, Any]]) -> None:
    if len(canonical_bytes(value)) > MAX_PRINCIPLES_BYTES:
        blockers.append({"code": "principles-artifact-too-large", "limit": MAX_PRINCIPLES_BYTES})


def _require_contained_file(path: Path, root: Path) -> None:
    resolved = path.resolve(strict=False)
    if not _is_relative_to(resolved, root) or path.is_symlink() or not path.exists() or not path.is_file():
        raise LifecycleError("project-principles-path-invalid", "principles must be a contained regular file")


def _relative_path(path: Path, root: Path | None) -> str:
    if root is None:
        return path.as_posix()
    return path.resolve().relative_to(root.resolve()).as_posix()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True

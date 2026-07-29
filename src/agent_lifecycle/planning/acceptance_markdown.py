"""Validate human acceptance checklists against plan manifests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent_lifecycle.contracts import LifecycleError


_BACKTICK_RE = re.compile(r"`([^`]+)`")


@dataclass(frozen=True)
class AcceptanceChecklistRow:
    id: str
    requirement_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]


def validate_acceptance_checklist(manifest: dict[str, Any], markdown: str) -> dict[str, Any]:
    """Validate checklist criterion IDs and links against manifest authority."""

    package_id = _package_id(manifest)
    manifest_rows = _manifest_rows(manifest)
    markdown_rows = _markdown_rows(markdown)

    manifest_by_id = {row.id: row for row in manifest_rows}
    markdown_by_id = {row.id: row for row in markdown_rows}
    duplicate_markdown_ids = _duplicates([row.id for row in markdown_rows])
    missing_in_markdown = [row.id for row in manifest_rows if row.id not in markdown_by_id]
    extra_in_markdown = [row.id for row in markdown_rows if row.id not in manifest_by_id]
    link_mismatches = _link_mismatches(manifest_rows, markdown_by_id)

    result = {
        "schemaVersion": "agent-acceptance-checklist-validation.v1",
        "packageId": package_id,
        "criterionCount": len(manifest_rows),
        "markdownCriterionCount": len(markdown_rows),
        "missingInMarkdown": missing_in_markdown,
        "extraInMarkdown": extra_in_markdown,
        "duplicateMarkdownIds": duplicate_markdown_ids,
        "linkMismatches": link_mismatches,
        "status": "PASS",
    }
    if missing_in_markdown or extra_in_markdown or duplicate_markdown_ids or link_mismatches:
        result["status"] = "FAIL"
        raise LifecycleError("acceptance-checklist-mismatch", "acceptance checklist does not match manifest", result)
    return result


def _package_id(manifest: dict[str, Any]) -> str:
    package = manifest.get("package")
    if not isinstance(package, dict) or not isinstance(package.get("id"), str):
        raise LifecycleError("invalid-plan-manifest", "package.id is required")
    return package["id"]


def _manifest_rows(manifest: dict[str, Any]) -> list[AcceptanceChecklistRow]:
    acceptance = manifest.get("acceptance")
    criteria = acceptance.get("criteria") if isinstance(acceptance, dict) else None
    if not isinstance(criteria, list) or not criteria:
        raise LifecycleError("invalid-plan-manifest", "acceptance.criteria are required")
    rows: list[AcceptanceChecklistRow] = []
    for item in criteria:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise LifecycleError("invalid-plan-manifest", "acceptance criteria require id")
        rows.append(
            AcceptanceChecklistRow(
                id=item["id"],
                requirement_ids=_string_tuple(item.get("requirementIds"), label=f"{item['id']}.requirementIds"),
                evidence_ids=_string_tuple(item.get("evidenceIds"), label=f"{item['id']}.evidenceIds"),
            )
        )
    return rows


def _markdown_rows(markdown: str) -> list[AcceptanceChecklistRow]:
    rows: list[AcceptanceChecklistRow] = []
    for line_number, line in enumerate(markdown.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 4:
            continue
        criterion_id = _first_backtick(cells[0])
        if criterion_id is None:
            continue
        if not criterion_id.startswith("AC"):
            continue
        rows.append(
            AcceptanceChecklistRow(
                id=criterion_id,
                requirement_ids=_backtick_tuple(cells[1], line_number=line_number, column="Requirements"),
                evidence_ids=_backtick_tuple(cells[2], line_number=line_number, column="Evidence"),
            )
        )
    if not rows:
        raise LifecycleError("invalid-acceptance-checklist", "acceptance checklist table has no AC rows")
    return rows


def _string_tuple(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise LifecycleError("invalid-plan-manifest", f"{label} must be a list of strings")
    return tuple(value)


def _first_backtick(cell: str) -> str | None:
    match = _BACKTICK_RE.search(cell)
    return match.group(1) if match else None


def _backtick_tuple(cell: str, *, line_number: int, column: str) -> tuple[str, ...]:
    values = tuple(match.group(1).strip() for match in _BACKTICK_RE.finditer(cell))
    if not values:
        raise LifecycleError(
            "invalid-acceptance-checklist",
            f"{column} cell has no backticked IDs",
            {"line": line_number, "column": column},
        )
    return values


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def _link_mismatches(
    manifest_rows: list[AcceptanceChecklistRow],
    markdown_by_id: dict[str, AcceptanceChecklistRow],
) -> list[dict[str, object]]:
    mismatches: list[dict[str, object]] = []
    for manifest_row in manifest_rows:
        markdown_row = markdown_by_id.get(manifest_row.id)
        if markdown_row is None:
            continue
        if (
            manifest_row.requirement_ids != markdown_row.requirement_ids
            or manifest_row.evidence_ids != markdown_row.evidence_ids
        ):
            mismatches.append(
                {
                    "id": manifest_row.id,
                    "manifestRequirementIds": list(manifest_row.requirement_ids),
                    "markdownRequirementIds": list(markdown_row.requirement_ids),
                    "manifestEvidenceIds": list(manifest_row.evidence_ids),
                    "markdownEvidenceIds": list(markdown_row.evidence_ids),
                }
            )
    return mismatches

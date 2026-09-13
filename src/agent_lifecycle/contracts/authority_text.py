"""Reject deceptive controls in the closed inventory of authority-bearing fields."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from agent_lifecycle.contracts.errors import LifecycleError

_HIDDEN = frozenset(
    {0x061C, 0x2060, 0xFEFF, 0x2028, 0x2029}
    | set(range(0x200B, 0x2010))
    | set(range(0x202A, 0x202F))
    | set(range(0x2066, 0x206A))
)
_PROSE_EXCEPTIONS = frozenset("\t\n\r\u200c\u200d")
_FINDING_TOKENS = ("id", "code", "severity", "status", "category", "path")
_FINDING_PROSE = ("title", "summary", "message", "description", "recommendation")
_GATE_LINK_RE = re.compile(r"\[([^|\]]+)\|([^\]]+)\]")


def require_authority_text(value: Any, *, prose: bool = False) -> None:
    """Check present strings without changing their bytes or imposing a new type contract."""

    if not isinstance(value, str):
        return
    for character in value:
        if prose and character in _PROSE_EXCEPTIONS:
            continue
        if unicodedata.category(character) in {"Cc", "Cs"} or ord(character) in _HIDDEN:
            raise LifecycleError("authority-text-control", "authority text contains a prohibited control")


def _fields(value: Any, names: tuple[str, ...], *, prose: bool = False) -> None:
    if isinstance(value, dict):
        for name in names:
            require_authority_text(value.get(name), prose=prose)


def _strings(value: Any, *, prose: bool = False) -> None:
    if isinstance(value, list):
        for item in value:
            require_authority_text(item, prose=prose)


def _objects(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def require_finding_text(findings: Any) -> None:
    """Validate text before severity/status filtering or reporting a finding ID."""

    for finding in _objects(findings):
        _fields(finding, _FINDING_TOKENS)
        _fields(finding, _FINDING_PROSE, prose=True)


def require_review_text(review: Any) -> None:
    """Cover review envelopes, routing and findings without interpreting their authority."""

    if not isinstance(review, dict):
        return
    _fields(review, ("reviewId", "resultId", "verdict", "overall", "status"))
    _fields(review, _FINDING_PROSE, prose=True)
    require_finding_text(review.get("findings"))
    for key in ("findingIds", "openFindingIds"):
        _strings(review.get(key))
    _fields(review.get("reviewer"), ("id", "surface", "runId"))
    _fields(review.get("routing"), ("nextAction", "target"))
    dimensions = review.get("dimensions")
    if isinstance(dimensions, dict):
        for dimension in dimensions.values():
            _fields(dimension, ("status", "reasonCode"))
            _fields(dimension, ("summary",), prose=True)
    structured = review.get("reviewVerdict")
    if isinstance(structured, dict):
        # The structured verdict has a closed shape, not recursively nested reviews.
        require_review_text({key: value for key, value in structured.items() if key != "reviewVerdict"})


def _ownership_text(value: Any) -> None:
    if not isinstance(value, dict):
        return
    for key in ("readOnly", "forbiddenWrites", "writes"):
        _strings(value.get(key))
    for entry in _objects(value.get("leadOwned")):
        _fields(entry, ("path",))
        _fields(entry, ("reason",), prose=True)


def _criterion_text(value: dict[str, Any]) -> None:
    _fields(value, ("id",))
    _fields(value, ("title", "description"), prose=True)
    for key in ("requirementIds", "evidenceIds"):
        _strings(value.get(key))


def require_manifest_text(manifest: dict[str, Any]) -> None:
    """Apply the token/prose policy only to documented manifest fields."""

    _fields(manifest.get("package"), ("id", "artifactRoot", "planArtifactRoot", "workspaceRoot", "root"))
    _fields(manifest.get("package"), ("title",), prose=True)
    require_authority_text(manifest.get("author"))
    _fields(manifest.get("author"), ("id", "surface", "runId"))
    _fields(manifest.get("baseRevision"), ("ref", "sha"))
    _fields(manifest.get("releaseTarget"), ("targetVersion", "targetTag"))
    _fields(manifest.get("orchestration"), ("stateFile", "eventLog"))
    _fields(manifest.get("planReview"), ("report",))
    _strings(manifest.get("planFiles"))
    _ownership_text(manifest)
    for workstream in _objects(manifest.get("workstreams")):
        _fields(workstream, ("id", "owner"))
        _fields(workstream, ("title",), prose=True)
        for key in ("dependsOn", "acceptanceIds", "evidenceIds"):
            _strings(workstream.get(key))
        _ownership_text(workstream)
    specification = manifest.get("specification")
    if isinstance(specification, dict):
        for requirement in _objects(specification.get("requirements")):
            _criterion_text(requirement)
    acceptance = manifest.get("acceptance")
    criteria = acceptance.get("criteria") if isinstance(acceptance, dict) else acceptance
    for criterion in _objects(criteria) + _objects(manifest.get("acceptanceCriteria")):
        _criterion_text(criterion)
    validation = manifest.get("validation")
    if isinstance(validation, dict):
        for key in ("commands", "extraEvidence"):
            _strings(validation.get(key))
    _strings(manifest.get("finalAuditGates"), prose=True)
    gates = manifest.get("finalAuditGates")
    if isinstance(gates, list):
        for gate in gates:
            if isinstance(gate, str):
                for acceptance_id, evidence_id in _GATE_LINK_RE.findall(gate):
                    require_authority_text(acceptance_id)
                    require_authority_text(evidence_id)

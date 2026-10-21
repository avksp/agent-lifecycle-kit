"""Closed, bounded compact authoring input; no review or execution authority."""

from __future__ import annotations

import json
import re
from typing import Any, NoReturn

from agent_lifecycle.contracts.canonical import canonical_bytes
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.paths import normalize_repo_path

COMPACT_PLAN_SCHEMA = "agent-compact-plan.v1"
MAX_COMPACT_INPUT_BYTES = 65536
MAX_COMPACT_OUTPUT_BYTES = 262144
MAX_COMPACT_CHANGES = 12
MAX_COMPACT_COMMANDS = 32
COMPACT_RISKS = frozenset(
    (
        "architecture",
        "security",
        "performance",
        "browser",
        "externalEnvironment",
        "data",
        "release",
        "externalSpecification",
    )
)
ORCHESTRATION_FIELDS = frozenset(
    (
        "startMode",
        "remediationMode",
        "maxPlanReviewRounds",
        "maxTaskAttempts",
        "maxParallelTasks",
        "maxValidationRunsPerTask",
        "maxToolCallsPerIteration",
        "maxUsageIterationsPerAttempt",
        "maxToolCallsPerTask",
        "maxToolCallsPerRun",
        "maxReportedTokensPerTask",
        "maxReportedTokensPerRun",
        "maxEvidenceArtifactBytes",
        "maxEvidenceBytesPerTask",
        "maxEvidenceBytesPerRun",
        "maxTaskWallSeconds",
        "maxRunWallSeconds",
        "maxContextBytes",
        "maxRenderedPacketBytes",
    )
)
_ROOT_FIELDS = frozenset(
    (
        "schemaVersion",
        "tier",
        "mechanical",
        "package",
        "author",
        "baseRevision",
        "owner",
        "riskFlags",
        "changes",
        "orchestration",
        "releaseImpact",
        "readOnly",
        "forbiddenWrites",
        "securityGates",
        "contextLimits",
    )
)
_CHANGE_FIELDS = frozenset(
    ("id", "title", "requirement", "acceptance", "evidenceDescription", "evidencePath", "writes", "validationCommands")
)
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,39}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")


def load_compact_plan_input(raw: bytes) -> dict[str, Any]:
    """Parse only bounded UTF-8 JSON with unique keys and finite numbers."""
    if not isinstance(raw, bytes) or len(raw) > MAX_COMPACT_INPUT_BYTES:
        _fail("input-too-large", "Compact input must be bytes within 65536 bytes")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_nonfinite)
    except (UnicodeError, ValueError, RecursionError):
        _fail("json-invalid", "Compact input must be finite, bounded UTF-8 JSON")
    return require_compact_plan_input(value)


def require_compact_plan_input(value: Any) -> dict[str, Any]:
    """Validate the exact source shape without inferring low risk or missing facts."""
    source = _object(value, _ROOT_FIELDS, "input")
    if source["schemaVersion"] != COMPACT_PLAN_SCHEMA:
        _fail("schema-unsupported", "Unsupported compact input schema")
    if source["tier"] not in ("S0", "S1"):
        _fail("full-s2-required", "Compact authoring requires explicit S0/S1; use the full S2 route")
    if type(source["mechanical"]) is not bool:
        _fail("mechanical-invalid", "mechanical must be a boolean")
    if source["tier"] == "S0" and source["mechanical"] is not True:
        _fail("full-s2-required", "S0 requires explicitly bounded mechanical work")
    package = _object(source["package"], {"id", "title", "planArtifactRoot", "artifactRoot"}, "package")
    for field in ("id", "title"):
        _text(package[field], "package." + field, 200)
    for field in ("planArtifactRoot", "artifactRoot"):
        _path(package[field], "package." + field)
    for field in ("author", "owner"):
        _text(source[field], field, 200)
    base = _object(source["baseRevision"], {"ref", "sha"}, "baseRevision")
    _text(base["ref"], "baseRevision.ref", 200)
    if not isinstance(base["sha"], str) or _SHA.fullmatch(base["sha"]) is None:
        _fail("base-invalid", "baseRevision.sha must be exactly 40 lowercase hex characters")
    risks = _object(source["riskFlags"], COMPACT_RISKS, "riskFlags")
    if any(type(flag) is not bool for flag in risks.values()):
        _fail("risk-invalid", "Every risk flag must be a strict boolean")
    if any(risks.values()):
        _fail("full-s2-required", "Elevated risk requires the full S2 route")
    changes = _list(source["changes"], "changes", 1, MAX_COMPACT_CHANGES)
    if source["tier"] == "S0" and len(changes) != 1:
        _fail("full-s2-required", "S0 requires exactly one change")
    _changes(changes)
    _orchestration(source["orchestration"])
    _text(source["releaseImpact"], "releaseImpact")
    _paths(source["readOnly"], "readOnly", 0)
    _paths(source["forbiddenWrites"], "forbiddenWrites", 0)
    for gate in _list(source["securityGates"], "securityGates", 1, 32):
        _text(gate, "securityGates[]")
    _context(source["contextLimits"])
    if len(canonical_bytes(source)) > MAX_COMPACT_INPUT_BYTES:
        _fail("input-too-large", "Compact input exceeds 65536 UTF-8 bytes")
    return source


def _changes(changes: list[Any]) -> None:
    seen: set[str] = set()
    command_count = 0
    for item in changes:
        change = _object(item, _CHANGE_FIELDS, "change")
        identity = change["id"]
        if not isinstance(identity, str) or _ID.fullmatch(identity) is None:
            _fail("change-id-invalid", "Change id must be a bounded literal identifier")
        if identity.casefold() in seen:
            _fail("change-id-duplicate", "Change ids must be unique without ambiguous case aliases")
        seen.add(identity.casefold())
        _text(change["title"], "change.title", 200)
        for name in ("requirement", "acceptance", "evidenceDescription"):
            _text(change[name], "change." + name)
        _path(change["evidencePath"], "change.evidencePath")
        _paths(change["writes"], "change.writes", 1)
        commands = _list(change["validationCommands"], "change.validationCommands", 1, MAX_COMPACT_COMMANDS)
        for command in commands:
            _text(command, "change.validationCommands[]")
        command_count += len(commands)
    if command_count > MAX_COMPACT_COMMANDS:
        _fail("commands-too-many", "Total validation command occurrences exceed 32")


def _orchestration(value: Any) -> None:
    policy = _object(value, ORCHESTRATION_FIELDS, "orchestration")
    if policy["startMode"] != "manual-after-freeze" or policy["remediationMode"] not in ("ask", "bounded-auto"):
        _fail("execution-mode-invalid", "Compact plans require reviewed freeze and separate manual authorization")
    for field in ORCHESTRATION_FIELDS - {"startMode", "remediationMode"}:
        _positive_integer(policy[field], "orchestration." + field)
    if policy["maxParallelTasks"] != 1 or policy["maxTaskAttempts"] > 3 or policy["maxPlanReviewRounds"] > 4:
        _fail("execution-limits-invalid", "Compact work is serial with at most 3 attempts and 4 review rounds")
    pairs = (
        ("maxToolCallsPerTask", "maxToolCallsPerRun"),
        ("maxReportedTokensPerTask", "maxReportedTokensPerRun"),
        ("maxTaskWallSeconds", "maxRunWallSeconds"),
        ("maxEvidenceArtifactBytes", "maxEvidenceBytesPerTask"),
        ("maxEvidenceBytesPerTask", "maxEvidenceBytesPerRun"),
    )
    if any(policy[small] > policy[large] for small, large in pairs):
        _fail("execution-limits-invalid", "Per-task and per-artifact caps must fit enclosing caps")


def _context(value: Any) -> None:
    limits = _object(
        value,
        {"targetReviewerPacketTokens", "maxReviewerPacketTokens", "smallContextProfilesRequired"},
        "contextLimits",
    )
    for field in ("targetReviewerPacketTokens", "maxReviewerPacketTokens"):
        _positive_integer(limits[field], "contextLimits." + field)
    if limits["targetReviewerPacketTokens"] > limits["maxReviewerPacketTokens"]:
        _fail("context-invalid", "Target reviewer packet must fit its maximum")
    if limits["smallContextProfilesRequired"] is not True:
        _fail("context-invalid", "Small-context profiles must remain required")


def _object(value: Any, fields: set[str] | frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        _fail("fields-invalid", label + " must contain exactly its declared fields")
    return value


def _list(value: Any, label: str, minimum: int, maximum: int) -> list[Any]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        _fail("list-invalid", label + " has an invalid type or item count")
    return value


def _text(value: Any, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        _fail("text-invalid", label + " must be nonempty bounded text without NUL")
    try:
        value.encode("utf-8")
    except UnicodeError:
        _fail("text-invalid", label + " must be valid UTF-8 text")
    return value


def _positive_integer(value: Any, label: str) -> None:
    if type(value) is not int or value <= 0:
        _fail("integer-invalid", label + " must be a strict positive integer")


def _path(value: Any, label: str) -> str:
    _text(value, label, 1024)
    if any(character in value for character in "*?[]"):
        _fail("path-invalid", label + " must be a literal path without wildcards")
    normalized = normalize_repo_path(value, label=label)
    if normalized != value:
        _fail("path-invalid", label + " must already be a canonical literal relative path")
    return normalized


def _paths(value: Any, label: str, minimum: int) -> None:
    paths = _list(value, label, minimum, 128)
    normalized = [_path(path, label + "[]") for path in paths]
    if len({path.casefold() for path in normalized}) != len(normalized):
        _fail("path-duplicate", label + " contains duplicate or ambiguous paths")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("json-duplicate-key", "Duplicate JSON keys are forbidden")
        result[key] = value
    return result


def _nonfinite(_: str) -> Any:
    _fail("json-nonfinite", "Non-finite JSON numbers are forbidden")


def _fail(code: str, message: str) -> NoReturn:
    raise LifecycleError("compact-plan-" + code, message)


__all__ = [
    "COMPACT_PLAN_SCHEMA",
    "COMPACT_RISKS",
    "MAX_COMPACT_CHANGES",
    "MAX_COMPACT_COMMANDS",
    "MAX_COMPACT_INPUT_BYTES",
    "MAX_COMPACT_OUTPUT_BYTES",
    "ORCHESTRATION_FIELDS",
    "load_compact_plan_input",
    "require_compact_plan_input",
]

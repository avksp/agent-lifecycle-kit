"""Bounded decision evidence for an explicitly frozen task input scope.

This module reads no files during structural validation. Native callers supply
the already verified manifest and must validate the returned independent review
with the existing review validator before changing state or dispatching work.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from pathlib import Path
from typing import Any, NoReturn

from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_digest,
    load_json_object,
    sha256_hex,
)
from agent_lifecycle.contracts.authority_io import read_authority_bytes
from agent_lifecycle.contracts.canonical import MAX_JSON_INPUT_BYTES
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.plan_manifest_schemas import (
    DECISION_CAPS,
    DECISION_CRITERIA,
    DECISION_RECORD_SCHEMA,
    DECISION_REQUIREMENT_SCHEMA,
    DECISION_SCOPE,
    PLAN_MANIFEST_SCHEMAS,
)
from agent_lifecycle.research.evidence import snapshot_digest
from agent_lifecycle.research.validation import validate_evidence_package

_REQUIREMENT = PLAN_MANIFEST_SCHEMAS[DECISION_REQUIREMENT_SCHEMA]
_RECORD = PLAN_MANIFEST_SCHEMAS[DECISION_RECORD_SCHEMA]
_SCOPE_FIELDS = (
    "id",
    "title",
    "owner",
    "dependsOn",
    "writes",
    "plannedItems",
    "acceptanceIds",
    "evidenceIds",
)
_LIST_SCOPE_FIELDS = frozenset(_SCOPE_FIELDS[3:])


def _refuse(reason: str, index: int | None = None) -> NoReturn:
    details = {} if index is None else {"index": index}
    raise LifecycleError(
        f"decision-research-{reason}",
        "Decision research preflight refused",
        details,
    )


def _object(value: Any, schema: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        _refuse("shape-invalid")
    if set(value) - set(schema["properties"]):
        _refuse("shape-invalid")
    if not set(schema["required"]).issubset(value):
        _refuse("shape-invalid")
    return value


def _text(value: Any, limit: int = 128) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        _refuse("text-invalid")
    return value


def _integer(value: Any, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        _refuse("limit-invalid")
    return value


def _choice(value: Any, choices: Collection[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        _refuse("value-invalid")
    return value


def _items(value: Any, low: int, high: int) -> list[Any]:
    if not isinstance(value, list) or not low <= len(value) <= high:
        _refuse("list-invalid")
    return value


def _unique_texts(value: Any, low: int, high: int) -> list[str]:
    values = [_text(item) for item in _items(value, low, high)]
    if len(set(values)) != len(values):
        _refuse("duplicate")
    return values


def _digest(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        _refuse("digest-invalid")
    return value


def _leaf(value: Any) -> str:
    name = _text(value, 255)
    if name in {".", ".."} or any(c in name for c in "/\\:\x00"):
        _refuse("reference-invalid")
    return name


def decision_scope_digest(manifest: dict[str, Any], workstream: dict[str, Any]) -> str:
    """Hash only the selected frozen subject, excluding physical containers.

    Arrays retain declared order. Requirement and acceptance entries retain
    their manifest order after selection by this task's explicit IDs.
    """
    spec = manifest.get("specification", {})
    if not isinstance(spec, dict):
        _refuse("subject-invalid")
    requirement_ids = workstream.get("plannedItems", [])
    acceptance_ids = workstream.get("acceptanceIds", [])
    requirements = [
        {"id": item.get("id"), "description": item.get("description")}
        for item in spec.get("requirements", [])
        if isinstance(item, dict) and item.get("id") in requirement_ids
    ]
    acceptance = [
        {key: item.get(key, []) if key != "id" else item.get(key) for key in ("id", "requirementIds", "evidenceIds")}
        for item in manifest.get("acceptance", {}).get("criteria", [])
        if isinstance(item, dict) and item.get("id") in acceptance_ids
    ]
    return canonical_digest(
        {
            "packageId": manifest.get("package", {}).get("id"),
            "baseRevision": manifest.get("baseRevision"),
            "tier": spec.get("tier"),
            "task": {key: workstream.get(key, [] if key in _LIST_SCOPE_FIELDS else None) for key in _SCOPE_FIELDS},
            "requirements": requirements,
            "acceptance": acceptance,
        }
    )


def decision_policy_digest(requirement: dict[str, Any]) -> str:
    return canonical_digest({"scope": requirement["scope"], "profile": requirement["profile"]})


def decision_input_digest(inputs: list[dict[str, Any]]) -> str:
    return canonical_digest(inputs)


def _resolve_references(
    manifest: dict[str, Any],
    workstream: dict[str, Any],
    requirement: dict[str, Any],
) -> dict[str, str]:
    inventory = manifest.get("planFiles")
    context = workstream.get("contextRefs")
    if not isinstance(inventory, list) or not isinstance(context, list):
        _refuse("frozen-references-required")
    paths: dict[str, list[str]] = {}
    for raw in inventory:
        try:
            normalized = normalize_repo_path(raw, label="research reference")
        except (LifecycleError, TypeError, ValueError):
            _refuse("reference-invalid")
        if raw != normalized:
            _refuse("reference-invalid")
        paths.setdefault(Path(normalized).name, []).append(raw)
    review = manifest.get("planReview", {})
    excluded = {"plan.manifest.json", "plan.lock.json"}
    if isinstance(review, dict) and isinstance(review.get("report"), str):
        excluded.add(Path(review["report"]).name)
    resolved: dict[str, str] = {}
    record_name = requirement["record"]["path"]
    if record_name in {item["path"] for item in requirement["inputs"]}:
        _refuse("record-input-overlap")
    names = [item["path"] for item in requirement["inputs"]] + [record_name]
    for index, name in enumerate(names):
        matches = paths.get(name, [])
        if name in excluded or len(matches) != 1:
            _refuse("reference-invalid", index)
        if name != record_name and matches[0] not in context:
            _refuse("reference-outside-context", index)
        resolved[name] = matches[0]
    specification = manifest.get("specification", {}).get("source")
    if specification is not None:
        actual_inputs = {resolved[item["path"]] for item in requirement["inputs"]}
        if specification not in actual_inputs:
            _refuse("specification-input-required")
    return resolved


def validate_decision_requirement(manifest: dict[str, Any], workstream: dict[str, Any]) -> dict[str, str]:
    """Validate an enabled declaration without reading the filesystem."""
    if manifest.get("schemaVersion") != "agent-plan-manifest.v1":
        _refuse("canonical-plan-required")
    requirement = _object(workstream.get("decisionResearch"), _REQUIREMENT)
    if requirement["schemaVersion"] != DECISION_REQUIREMENT_SCHEMA:
        _refuse("schema-unsupported")
    if requirement["scope"] != DECISION_SCOPE:
        _refuse("scope-unsupported")
    profile_schema = _REQUIREMENT["properties"]["profile"]
    profile = _object(requirement["profile"], profile_schema)
    tier = _choice(profile["tier"], DECISION_CRITERIA)
    frozen_tier = manifest.get("specification", {}).get("tier")
    if not isinstance(frozen_tier, str) or frozen_tier not in DECISION_CRITERIA:
        _refuse("quality-floor-invalid")
    if tier < frozen_tier:
        _refuse("quality-floor-invalid")
    criteria = _unique_texts(profile["requiredCriteria"], 1, 16)
    if not set(DECISION_CRITERIA[tier]).issubset(criteria):
        _refuse("criteria-incomplete")
    for name, (low, high) in DECISION_CAPS.items():
        _integer(profile[name], low, high)
    inputs = _items(requirement["inputs"], 1, profile["maxInputs"])
    ids: set[str] = set()
    names: set[str] = set()
    for item in inputs:
        _object(item, _REQUIREMENT["properties"]["inputs"]["items"])
        source_id = _text(item["sourceId"])
        name = _leaf(item["path"])
        _digest(item["sha256"])
        if source_id in ids or name in names:
            _refuse("duplicate")
        ids.add(source_id)
        names.add(name)
    record = _object(requirement["record"], _REQUIREMENT["properties"]["record"])
    _leaf(record["path"])
    _digest(record["sha256"])
    for name, expected in (
        ("policyDigest", decision_policy_digest(requirement)),
        ("inputDigest", decision_input_digest(inputs)),
        ("scopeDigest", decision_scope_digest(manifest, workstream)),
    ):
        if _digest(requirement[name]) != expected:
            _refuse("binding-mismatch")
    return _resolve_references(manifest, workstream, requirement)


def decision_research_blockers(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Return safe structural blockers; absence is the legacy opt-out."""
    blockers: list[dict[str, Any]] = []
    workstreams = manifest.get("workstreams", [])
    if not isinstance(workstreams, list):
        return blockers
    for index, workstream in enumerate(workstreams):
        if not isinstance(workstream, dict) or "decisionResearch" not in workstream:
            continue
        try:
            validate_decision_requirement(manifest, workstream)
        except LifecycleError as exc:
            blockers.append(
                {
                    "code": exc.code,
                    "message": exc.message,
                    "details": {"workstreamIndex": index},
                }
            )
    return blockers


def _read(root: Path, path: str, limit: int, digest: str) -> bytes:
    try:
        data = read_authority_bytes(root / path, root=root, max_bytes=limit)
    except (LifecycleError, OSError, ValueError):
        _refuse("input-unavailable")
    if sha256_hex(data) != digest:
        _refuse("input-stale")
    return data


def _json(data: bytes) -> dict[str, Any]:
    try:
        return load_json_object(data, label="decision research")
    except LifecycleError:
        _refuse("json-invalid")


def _validate_budget(value: Any) -> None:
    budget = _object(value, _RECORD["properties"]["budget"])
    commands = _integer(budget["maxCommands"], 1, 100)
    seconds = _integer(budget["maxActiveSeconds"], 1, 3600)
    _integer(budget["reservedCommands"], 1, commands - 1)
    if budget["usageStatus"] == "UNAVAILABLE":
        if budget["usedCommands"] is not None or budget["usedActiveSeconds"] is not None:
            _refuse("usage-invalid")
    elif budget["usageStatus"] == "DECLARED":
        _integer(budget["usedCommands"], 0, commands)
        active = budget["usedActiveSeconds"]
        if type(active) not in (int, float) or not 0 <= active <= seconds:
            _refuse("usage-invalid")
    else:
        _refuse("usage-invalid")


def _validate_alternatives(record: dict[str, Any], profile: dict[str, Any]) -> None:
    alternatives = _items(record["alternatives"], 1, profile["maxAlternatives"])
    ids: set[str] = set()
    no_change = False
    for alternative in alternatives:
        _object(alternative, _RECORD["properties"]["alternatives"]["items"])
        identifier = _text(alternative["id"])
        if identifier in ids:
            _refuse("duplicate")
        ids.add(identifier)
        _choice(alternative["kind"], {"NO_CHANGE", "SIMPLIFY", "REPLACE"})
        no_change = no_change or alternative["kind"] == "NO_CHANGE"
        _text(alternative["title"])
        _text(alternative["rationale"], 4096)
    if not no_change or _text(record["selectedAlternativeId"]) not in ids:
        _refuse("alternative-invalid")
    _choice(record["outcome"], {"KEEP", "SIMPLIFY", "REPLACE", "SPLIT", "STOP"})
    if record["outcome"] in {"SPLIT", "STOP"}:
        _refuse("decision-not-launchable")


def _validate_assessments(record: dict[str, Any], requirement: dict[str, Any]) -> None:
    criteria = requirement["profile"]["requiredCriteria"]
    assessments = _items(record["assessments"], len(criteria), len(criteria))
    seen: set[str] = set()
    sources = {item["sourceId"] for item in requirement["inputs"]}
    for assessment in assessments:
        _object(assessment, _RECORD["properties"]["assessments"]["items"])
        criterion = _text(assessment["criterion"])
        if criterion in seen or criterion not in criteria:
            _refuse("criteria-incomplete")
        seen.add(criterion)
        _choice(assessment["status"], {"ADDRESSED", "NOT_APPLICABLE"})
        _text(assessment["rationale"], 4096)
        refs = _unique_texts(assessment.get("sourceIds", []), 0, 8)
        if not set(refs).issubset(sources):
            _refuse("assessment-invalid")


def validate_decision_record(
    value: Any,
    requirement: dict[str, Any],
    *,
    owner: str,
    snapshots: dict[str, bytes],
) -> dict[str, Any]:
    """Validate lower-authority research, not its claimed global optimality."""
    record = _object(value, _RECORD)
    if record["schemaVersion"] != DECISION_RECORD_SCHEMA:
        _refuse("schema-unsupported")
    for name in ("scopeDigest", "inputDigest", "policyDigest"):
        if _digest(record[name]) != requirement[name]:
            _refuse("binding-mismatch")
    if _text(record["ownerId"]) != owner:
        _refuse("owner-mismatch")
    for name in ("sourceOfTruth", "productionPromotionClaimed", "optimalityClaimed"):
        if record[name] is not False:
            _refuse("authority-invalid")
    if record["lifecycleAuthority"] != "none":
        _refuse("authority-invalid")
    profile = requirement["profile"]
    entrypoints = _items(record["entryPoints"], 1, profile["maxEntryPoints"])
    points = [_text(item, 255) for item in entrypoints]
    if len(set(points)) != len(points):
        _refuse("duplicate")
    _integer(record["probeCount"], 0, profile["maxProbes"])
    _integer(record["reviewRoundCount"], 1, profile["maxReviewRounds"])
    _validate_alternatives(record, profile)
    _validate_assessments(record, requirement)
    _validate_budget(record["budget"])
    if "evidencePackage" in record:
        _validate_evidence(record["evidencePackage"], requirement, snapshots)
    return record


def _validate_evidence(package: Any, requirement: dict[str, Any], snapshots: dict[str, bytes]) -> None:
    try:
        evidence_snapshots: dict[str, str | bytes] = dict(snapshots)
        result = validate_evidence_package(
            package,
            snapshots=evidence_snapshots,
            max_bytes=requirement["profile"]["maxRecordBytes"],
        )
        if result.get("status") != "PASS":
            _refuse("evidence-invalid")
        declared = {item["sourceId"] for item in requirement["inputs"]}
        for source in package["sources"]:
            identifier = source["sourceId"]
            if identifier not in declared or identifier not in snapshots:
                _refuse("evidence-snapshot-required")
            actual = snapshot_digest(snapshots[identifier].decode("utf-8"))
            if source.get("snapshotDigest") != actual:
                _refuse("evidence-snapshot-mismatch")
        if any(citation.get("matchStatus") != "MATCHED" for citation in package["citations"]):
            _refuse("evidence-citation-unavailable")
    except (LifecycleError, KeyError, TypeError, ValueError, UnicodeError):
        _refuse("evidence-invalid")


def _read_adopted_review(root: Path, manifest: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    identity = state.get("lastPlanReview")
    review_config = manifest.get("planReview")
    if not isinstance(identity, dict) or not isinstance(review_config, dict):
        _refuse("review-required")
    path = review_config.get("report")
    if identity.get("path") != path or not isinstance(path, str):
        _refuse("review-mismatch")
    try:
        if normalize_repo_path(path, label="research review") != path:
            _refuse("review-mismatch")
    except (LifecycleError, TypeError, ValueError):
        _refuse("review-mismatch")
    raw = _read(root, path, MAX_JSON_INPUT_BYTES, _digest(identity.get("sha256")))
    if len(raw) != identity.get("bytes"):
        _refuse("review-mismatch")
    review = _json(raw)
    reviewer = review.get("reviewer")
    author = manifest.get("author")
    if not isinstance(reviewer, dict) or not isinstance(author, dict):
        _refuse("review-invalid")
    if reviewer.get("independent") is not True or review.get("fullReview") is not True:
        _refuse("review-invalid")
    if review.get("reviewedPlanHash") != state.get("planDigest"):
        _refuse("review-mismatch")
    if review.get("planRevision") != manifest.get("planRevision"):
        _refuse("review-mismatch")
    if review.get("verdict") != "READY_TO_FREEZE":
        _refuse("review-invalid")
    for key, identity_key in (("id", "reviewer"), ("runId", "reviewerRunId"), ("surface", "surface")):
        if _text(reviewer.get(key), 255) != identity.get(identity_key):
            _refuse("review-mismatch")
    if reviewer["id"] == author.get("id") or reviewer["runId"] == author.get("runId"):
        _refuse("review-not-independent")
    if review.get("reviewId") != identity.get("reviewId"):
        _refuse("review-mismatch")
    return review


def check_decision_preflight(
    root: Path,
    manifest: dict[str, Any] | None,
    state: dict[str, Any],
    task: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Check the verified frozen task before native mutation, never dispatch."""
    workstreams = [] if manifest is None else manifest.get("workstreams", [])
    matches = [item for item in workstreams if item.get("id") == task.get("id")]
    frozen = matches[0] if len(matches) == 1 else {}
    enabled = "decisionResearch" in task or "decisionResearch" in frozen
    if not enabled:
        return None, None
    if manifest is None or len(matches) != 1 or not state.get("manifestPath"):
        _refuse("adopted-context-required")
    if "decisionResearch" not in task or "decisionResearch" not in frozen:
        _refuse("task-policy-mismatch")
    if canonical_digest(task["decisionResearch"]) != canonical_digest(frozen["decisionResearch"]):
        _refuse("task-policy-mismatch")
    if task.get("contextRefs") != frozen.get("contextRefs"):
        _refuse("task-context-mismatch")
    resolved = validate_decision_requirement(manifest, frozen)
    requirement = frozen["decisionResearch"]
    profile = requirement["profile"]
    snapshots = {}
    for item in requirement["inputs"]:
        data = _read(root, resolved[item["path"]], profile["maxInputBytes"], item["sha256"])
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            _refuse("input-encoding-invalid")
        snapshots[item["sourceId"]] = data
    ref = requirement["record"]
    record = _json(_read(root, resolved[ref["path"]], profile["maxRecordBytes"], ref["sha256"]))
    validate_decision_record(record, requirement, owner=frozen["owner"], snapshots=snapshots)
    review = _read_adopted_review(root, manifest, state)
    fact = {
        "scope": DECISION_SCOPE,
        **{name: requirement[name] for name in ("scopeDigest", "inputDigest", "policyDigest")},
        "inputCount": len(snapshots),
        "inputBytes": sum(len(data) for data in snapshots.values()),
    }
    return fact, review

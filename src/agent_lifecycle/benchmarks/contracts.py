"""Load and validate reference-task suite inputs."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object, sha256_hex

SUITE_SCHEMA = "agent-reference-task-suite.v1"
ORACLE_SCHEMA = "agent-reference-task-oracle.v1"
SUBMISSION_SCHEMA = "agent-reference-task-submission.v1"
TASK_FAMILIES = {"planning", "architecture-review", "bug-forensics", "s1-managed-task", "s2-evidence-task"}
BUNDLED_SUITE_PATH = Path("benchmarks/reference-tasks/manifest.json")
MAX_SUBMISSION_EVIDENCE_DEPTH = 64
MAX_SUBMISSION_EVIDENCE_NODES = 100_000


@dataclass(frozen=True)
class LoadedSuite:
    payload: dict[str, Any]
    root: Path
    digest: str


@dataclass(frozen=True)
class LoadedTask:
    row: dict[str, Any]
    oracle: dict[str, Any]
    task_digest: str
    oracle_digest: str


def load_suite(path: Path) -> LoadedSuite:
    path = resolve_suite_path(path)
    payload, _ = _load_json(path, label="reference task suite")
    _require_schema(payload, SUITE_SCHEMA, code="reference-suite-schema")
    _require_text(payload, "suiteId", code="reference-suite-id")
    _require_text(payload, "suiteVersion", code="reference-suite-version")
    if payload.get("productionPromotionClaimed") is not False:
        raise LifecycleError("reference-suite-production-claim", "reference task suites cannot claim production promotion")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise LifecycleError("reference-suite-tasks", "reference task suite requires tasks")
    seen: set[str] = set()
    for row in tasks:
        if not isinstance(row, dict):
            raise LifecycleError("reference-suite-task-row", "reference task rows must be objects")
        task_id = _require_text(row, "id", code="reference-suite-task-id")
        if task_id in seen:
            raise LifecycleError("reference-suite-task-duplicate", "reference task ids must be unique", {"taskId": task_id})
        seen.add(task_id)
        if row.get("family") not in TASK_FAMILIES:
            raise LifecycleError("reference-suite-task-family", "reference task family is unsupported", {"taskId": task_id})
        if row.get("tier") not in {"S0", "S1", "S2"}:
            raise LifecycleError("reference-suite-task-tier", "reference task tier is unsupported", {"taskId": task_id})
        _require_text(row, "version", code="reference-suite-task-version")
        _require_text(row, "taskPath", code="reference-suite-task-path")
        _require_text(row, "oraclePath", code="reference-suite-oracle-path")
    return LoadedSuite(payload=payload, root=path.resolve().parent, digest=canonical_digest(payload))


def resolve_suite_path(path: Path) -> Path:
    if path.is_file() or path.is_absolute() or path != BUNDLED_SUITE_PATH:
        return path
    installed = Path(sys.prefix) / BUNDLED_SUITE_PATH
    return installed if installed.is_file() else path


def load_task(suite: LoadedSuite, task_id: str) -> LoadedTask:
    row = next((item for item in suite.payload["tasks"] if item.get("id") == task_id), None)
    if row is None:
        raise LifecycleError("reference-task-unknown", "submission task is not part of the suite", {"taskId": task_id})
    task_path = _contained_path(suite.root, row["taskPath"], code="reference-task-path")
    oracle_path = _contained_path(suite.root, row["oraclePath"], code="reference-oracle-path")
    task_bytes = _read_bytes(task_path, label="reference task text")
    oracle, oracle_bytes = _load_json(oracle_path, label="reference task oracle")
    _require_schema(oracle, ORACLE_SCHEMA, code="reference-oracle-schema")
    if oracle.get("taskId") != row["id"] or oracle.get("taskVersion") != row["version"]:
        raise LifecycleError("reference-oracle-lineage", "oracle task identity does not match suite manifest", {"taskId": row["id"]})
    if oracle.get("oracleType") != row["family"]:
        raise LifecycleError("reference-oracle-type", "oracle type does not match task family", {"taskId": row["id"]})
    if oracle.get("productionPromotionClaimed") is not False:
        raise LifecycleError("reference-oracle-production-claim", "reference task oracles cannot claim production promotion")
    required = oracle.get("requiredEvidenceSchemas")
    if not isinstance(required, list) or not required or any(not isinstance(item, str) or not item for item in required):
        raise LifecycleError("reference-oracle-evidence-schemas", "oracle requiredEvidenceSchemas must be non-empty strings")
    return LoadedTask(
        row=dict(row),
        oracle=oracle,
        task_digest=sha256_hex(task_bytes),
        oracle_digest=sha256_hex(oracle_bytes),
    )


def load_submission(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, data = _load_json(path, label="reference task submission")
    _require_schema(payload, SUBMISSION_SCHEMA, code="reference-submission-schema")
    _require_text(payload, "taskId", code="reference-submission-task-id")
    _require_text(payload, "taskVersion", code="reference-submission-task-version")
    if not isinstance(payload.get("accepted"), bool):
        raise LifecycleError("reference-submission-accepted", "submission accepted must be boolean")
    if not isinstance(payload.get("evidence"), dict):
        raise LifecycleError("reference-submission-evidence", "submission evidence must be an object")
    _validate_evidence_limits(payload["evidence"])
    if payload.get("productionPromotionClaimed") is not False:
        raise LifecycleError("reference-submission-production-claim", "benchmark submissions cannot claim production promotion")
    identity = {
        "sha256": sha256_hex(data),
        "bytes": len(data),
        "schemaVersion": payload["schemaVersion"],
        "payloadDigest": canonical_digest(payload),
    }
    return payload, identity


def _load_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    data = _read_bytes(path, label=label)
    try:
        return load_json_object(data, label=label), data
    except RecursionError as exc:
        raise LifecycleError("reference-json-nesting", f"{label} nesting exceeds the supported limit") from exc


def _read_bytes(path: Path, *, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise LifecycleError("reference-artifact-unavailable", f"{label} is unavailable") from exc


def _contained_path(root: Path, value: str, *, code: str) -> Path:
    path = (root / value).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise LifecycleError(code, "reference suite paths must remain inside the suite directory") from exc
    return path


def _require_schema(payload: dict[str, Any], expected: str, *, code: str) -> None:
    if payload.get("schemaVersion") != expected:
        raise LifecycleError(code, "unsupported schemaVersion", {"expected": expected})


def _require_text(payload: dict[str, Any], key: str, *, code: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise LifecycleError(code, f"{key} must be a non-empty string")
    return value


def _validate_evidence_limits(evidence: dict[str, Any]) -> None:
    stack: list[tuple[Any, int]] = [(evidence, 0)]
    node_count = 0
    while stack:
        value, depth = stack.pop()
        node_count += 1
        if node_count > MAX_SUBMISSION_EVIDENCE_NODES:
            raise LifecycleError(
                "reference-submission-evidence-size",
                "submission evidence contains too many values",
                {"maxNodes": MAX_SUBMISSION_EVIDENCE_NODES},
            )
        is_container = isinstance(value, (dict, list))
        if is_container and depth > MAX_SUBMISSION_EVIDENCE_DEPTH:
            raise LifecycleError(
                "reference-submission-evidence-depth",
                "submission evidence nesting exceeds the supported limit",
                {"maxDepth": MAX_SUBMISSION_EVIDENCE_DEPTH},
            )
        if isinstance(value, dict):
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)

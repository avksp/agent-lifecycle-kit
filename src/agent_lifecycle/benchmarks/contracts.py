"""Load and validate reference-task suite inputs."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object, sha256_hex

SUITE_SCHEMA = "agent-reference-task-suite.v1"
ORACLE_SCHEMA = "agent-reference-task-oracle.v1"
SUBMISSION_SCHEMA = "agent-reference-task-submission.v1"
TASK_FAMILIES = {"planning", "architecture-review", "bug-forensics", "s1-managed-task", "s2-evidence-task"}
TASK_SHAPES = {"planning", "review", "investigation", "implementation", "evidence"}
_LEGACY_SHAPE_BY_FAMILY = {
    "planning": "planning",
    "architecture-review": "review",
    "bug-forensics": "investigation",
    "s1-managed-task": "implementation",
    "s2-evidence-task": "evidence",
}
RUN_RECEIPT_SCHEMA = "agent-benchmark-run-receipt.v1"
RUN_RECEIPT_VALIDATION_SCHEMA = "agent-benchmark-run-receipt-validation.v1"
STRUCTURED_RESULT_MEASUREMENT_SCHEMA = "agent-structured-result-measurement.v1"
BUNDLED_SUITE_PATH = Path("benchmarks/reference-tasks/manifest.json")
MAX_SUBMISSION_EVIDENCE_DEPTH = 64
MAX_SUBMISSION_EVIDENCE_NODES = 100_000
_DIGEST_FIELDS = {
    "taskDigest": "task",
    "routeDigest": "route",
    "environmentDigest": "environment",
    "scorerDigest": "scorer",
    "sourceDigest": "source",
}
_FORBIDDEN_RECEIPT_KEYS = {
    "apiKey",
    "accessToken",
    "argv",
    "command",
    "commands",
    "credential",
    "credentials",
    "executable",
    "localPath",
    "model",
    "modelName",
    "password",
    "path",
    "prompt",
    "provider",
    "providerName",
    "secret",
    "secrets",
}
_SENSITIVE_TEXT = re.compile(
    r"(?:-----BEGIN [^-]+-----|\bBearer\s+\S+|(?:^|[\\/])(?:Users|home|private|workspace)(?:[\\/]|$)|[A-Za-z]:\\\\)",
    re.IGNORECASE,
)


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
        if row.get("shape") is not None and row.get("shape") not in TASK_SHAPES:
            raise LifecycleError("reference-suite-task-shape", "reference task shape is unsupported", {"taskId": task_id})
        _require_text(row, "version", code="reference-suite-task-version")
        _require_text(row, "taskPath", code="reference-suite-task-path")
        _require_text(row, "oraclePath", code="reference-suite-oracle-path")
    return LoadedSuite(payload=payload, root=path.resolve().parent, digest=canonical_digest(payload))


def resolve_suite_path(path: Path) -> Path:
    if path.is_absolute() or path != BUNDLED_SUITE_PATH:
        return path
    local = Path.cwd() / path
    if local.is_file():
        return local
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
    task_row = dict(row)
    task_row.setdefault("shape", _LEGACY_SHAPE_BY_FAMILY[task_row["family"]])
    return LoadedTask(
        row=task_row,
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


def load_benchmark_run_receipt(
    path: Path,
    *,
    suite: LoadedSuite | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and validate one externally produced benchmark-run receipt."""

    payload, data = _load_json(path, label="benchmark run receipt")
    validation = validate_benchmark_run_receipt(payload, suite=suite)
    if validation["status"] != "PASS":
        raise LifecycleError("benchmark-run-receipt-invalid", "benchmark run receipt failed validation", validation)
    return payload, {
        "sha256": sha256_hex(data),
        "bytes": len(data),
        "schemaVersion": payload["schemaVersion"],
        "payloadDigest": canonical_digest(payload),
    }


def validate_benchmark_run_receipt(
    receipt: dict[str, Any],
    *,
    suite: LoadedSuite | None = None,
) -> dict[str, Any]:
    """Validate a bounded receipt without executing its declared runner."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(receipt, dict):
        return _run_receipt_validation([{"code": "benchmark-receipt-not-object"}])
    if receipt.get("schemaVersion") != RUN_RECEIPT_SCHEMA:
        blockers.append({"code": "benchmark-receipt-schema"})
    for field in ("receiptId", "taskId", "taskVersion", "shape"):
        if not isinstance(receipt.get(field), str) or not receipt[field].strip():
            blockers.append({"code": "benchmark-receipt-field", "field": field})
    if receipt.get("tier") not in {"S0", "S1", "S2"}:
        blockers.append({"code": "benchmark-receipt-tier"})
    if not isinstance(receipt.get("completed"), bool):
        blockers.append({"code": "benchmark-receipt-completed"})
    if receipt.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "benchmark-receipt-production-claim"})
    for key in ("route", "environment", "scorer", "source", "quality", "measurements"):
        if not isinstance(receipt.get(key), dict):
            blockers.append({"code": "benchmark-receipt-object", "field": key})
    _check_digest(receipt, "taskDigest", blockers)
    for field in ("routeDigest", "environmentDigest", "scorerDigest", "sourceDigest"):
        container = _digest_container(receipt, field)
        if container is None:
            blockers.append({"code": "benchmark-receipt-digest", "field": field})
        else:
            _check_digest(container, field, blockers)
    route = receipt.get("route") if isinstance(receipt.get("route"), dict) else {}
    if not _non_empty_text(route.get("adapterClass")) or not _non_empty_text(route.get("routeClass")):
        blockers.append({"code": "benchmark-receipt-route-class"})
    quality = receipt.get("quality") if isinstance(receipt.get("quality"), dict) else {}
    total = quality.get("criteriaTotal")
    passed = quality.get("criteriaPassed")
    if not _non_negative_int(total) or not _non_negative_int(passed) or passed > total:
        blockers.append({"code": "benchmark-receipt-quality-counts"})
    if not isinstance(quality.get("falseAcceptance"), bool):
        blockers.append({"code": "benchmark-receipt-false-acceptance"})
    if not isinstance(quality.get("measurementGap"), list) or not all(isinstance(item, str) for item in quality["measurementGap"]):
        blockers.append({"code": "benchmark-receipt-quality-gap"})
    _check_portable_value(receipt, blockers)
    measurements = receipt.get("measurements") if isinstance(receipt.get("measurements"), dict) else {}
    structured_result = measurements.get("structuredResult")
    if structured_result is not None:
        validation = validate_structured_result_measurement(structured_result)
        if validation["status"] != "PASS":
            blockers.extend(
                {"code": item.get("code", "structured-result-measurement-invalid"), "details": item}
                for item in validation["blockers"]
            )
    if suite is not None and not blockers:
        try:
            task = load_task(suite, receipt["taskId"])
        except LifecycleError as exc:
            blockers.append({"code": "benchmark-receipt-task-lineage", "detail": exc.code})
        else:
            expected = {
                "taskId": task.row["id"],
                "taskVersion": task.row["version"],
                "taskDigest": task.task_digest,
                "family": task.row["family"],
                "tier": task.row["tier"],
                "shape": task.row["shape"],
            }
            for field, expected_value in expected.items():
                if receipt.get(field) != expected_value:
                    blockers.append({"code": "benchmark-receipt-task-lineage", "field": field})
    expected_digest = canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"})
    if receipt.get("receiptDigest") != expected_digest:
        blockers.append({"code": "benchmark-receipt-digest-mismatch", "expected": expected_digest})
    return _run_receipt_validation(blockers, receipt_digest=receipt.get("receiptDigest"))


def build_benchmark_run_receipt(
    *,
    receipt_id: str,
    task: dict[str, Any],
    route: dict[str, Any],
    environment: dict[str, Any],
    scorer: dict[str, Any],
    source: dict[str, Any],
    completed: bool,
    quality: dict[str, Any],
    measurements: dict[str, Any],
    structured_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a portable receipt from host-owned, already redacted facts."""

    measurement_body = dict(measurements)
    if structured_result is not None:
        measurement_body["structuredResult"] = dict(structured_result)
    body = {
        "schemaVersion": RUN_RECEIPT_SCHEMA,
        "receiptId": receipt_id,
        "taskId": task.get("taskId"),
        "taskVersion": task.get("taskVersion"),
        "taskDigest": task.get("taskDigest"),
        "family": task.get("family"),
        "tier": task.get("tier"),
        "shape": task.get("shape"),
        "route": dict(route),
        "environment": dict(environment),
        "scorer": dict(scorer),
        "source": dict(source),
        "completed": completed,
        "quality": dict(quality),
        "measurements": measurement_body,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def build_structured_result_measurement(
    *,
    operation_id: str,
    mode: str,
    valid: bool,
    repair_attempts: int,
    selection_digest: str,
    required_schema_digest: str,
    validation_digest: str,
    fixture_results: dict[str, bool],
    evidence_complete: bool = True,
) -> dict[str, Any]:
    """Build portable structured-result measurements for one benchmark run."""

    body = {
        "schemaVersion": STRUCTURED_RESULT_MEASUREMENT_SCHEMA,
        "operationId": operation_id,
        "mode": mode,
        "valid": valid,
        "repairAttempts": repair_attempts,
        "maxRepairAttempts": 2,
        "selectionDigest": selection_digest,
        "requiredSchemaDigest": required_schema_digest,
        "validationDigest": validation_digest,
        "fixtureResults": dict(fixture_results),
        "evidenceComplete": evidence_complete,
        "productionPromotionClaimed": False,
    }
    return {**body, "measurementDigest": canonical_digest(body)}


def validate_structured_result_measurement(measurement: dict[str, Any]) -> dict[str, Any]:
    """Validate structured-result measurements without treating them as authority."""

    blockers: list[dict[str, Any]] = []
    required = (
        "operationId",
        "mode",
        "valid",
        "repairAttempts",
        "maxRepairAttempts",
        "selectionDigest",
        "requiredSchemaDigest",
        "validationDigest",
        "fixtureResults",
        "evidenceComplete",
        "measurementDigest",
    )
    for field in required:
        if field not in measurement:
            blockers.append({"code": "structured-result-measurement-field", "field": field})
    if measurement.get("schemaVersion") != STRUCTURED_RESULT_MEASUREMENT_SCHEMA:
        blockers.append({"code": "structured-result-measurement-schema"})
    if measurement.get("mode") not in {"SCHEMA_ENFORCED", "JSON_ENFORCED", "VALIDATED_TEXT", "UNAVAILABLE"}:
        blockers.append({"code": "structured-result-measurement-mode"})
    if not isinstance(measurement.get("valid"), bool):
        blockers.append({"code": "structured-result-measurement-validity"})
    repair_attempts = measurement.get("repairAttempts")
    max_repairs = measurement.get("maxRepairAttempts")
    if not isinstance(repair_attempts, int) or isinstance(repair_attempts, bool) or not 0 <= repair_attempts <= 2:
        blockers.append({"code": "structured-result-measurement-repair-attempts"})
    if max_repairs != 2:
        blockers.append({"code": "structured-result-measurement-repair-limit"})
    for field in ("selectionDigest", "requiredSchemaDigest", "validationDigest", "measurementDigest"):
        if not _is_digest(measurement.get(field)):
            blockers.append({"code": "structured-result-measurement-digest", "field": field})
    fixtures = measurement.get("fixtureResults")
    if not isinstance(fixtures, dict) or any(
        not isinstance(fixtures.get(key), bool) for key in ("positive", "boundary", "malformed")
    ):
        blockers.append({"code": "structured-result-measurement-fixtures"})
    if not isinstance(measurement.get("evidenceComplete"), bool):
        blockers.append({"code": "structured-result-measurement-completeness"})
    expected_digest = canonical_digest({key: value for key, value in measurement.items() if key != "measurementDigest"})
    if measurement.get("measurementDigest") != expected_digest:
        blockers.append({"code": "structured-result-measurement-digest-mismatch"})
    body = {
        "schemaVersion": "agent-structured-result-measurement-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "operationId": measurement.get("operationId"),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


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


def _run_receipt_validation(blockers: list[dict[str, Any]], *, receipt_digest: Any = None) -> dict[str, Any]:
    body = {
        "schemaVersion": RUN_RECEIPT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "blockers": blockers,
        "receiptDigest": receipt_digest if isinstance(receipt_digest, str) else None,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _digest_container(receipt: dict[str, Any], field: str) -> dict[str, Any] | None:
    for value in receipt.values():
        if isinstance(value, dict) and field in value:
            return value
    return None


def _check_digest(value: dict[str, Any], field: str, blockers: list[dict[str, Any]]) -> None:
    digest = value.get(field)
    if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
        blockers.append({"code": "benchmark-receipt-digest", "field": field})


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value.lower())


def _check_portable_value(value: Any, blockers: list[dict[str, Any]], *, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _FORBIDDEN_RECEIPT_KEYS:
                blockers.append({"code": "benchmark-receipt-forbidden-field", "field": ".".join((*path, str(key)))})
            _check_portable_value(child, blockers, path=(*path, str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _check_portable_value(child, blockers, path=(*path, str(index)))
    elif isinstance(value, str) and _SENSITIVE_TEXT.search(value):
        blockers.append({"code": "benchmark-receipt-sensitive-text", "field": ".".join(path)})


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0

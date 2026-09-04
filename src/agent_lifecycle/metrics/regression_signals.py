"""Summarize lifecycle regression signals for policy decisions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.metrics.workflow_economics import WORKFLOW_METRIC_KEYS

REGRESSION_SCHEMA = "agent-lifecycle-regression-signals.v1"
COMPARISON_VIEW_VERSION = "workflow-economics-comparison.v1"
COMPARISON_STATUSES = ("IMPROVED", "REGRESSED", "MIXED", "NO_COMPARABLE_BASELINE")
BLOCKING_SIGNAL_TYPES = {
    "failedFinalAudit",
    "reopenedWork",
    "rollback",
    "repeatedRemediation",
}
_DERIVED_STATUSES = {"MIXED", "PARTIAL"}
_SOURCE_STATUSES = {"MEASURED", "ESTIMATED", "TIME_WINDOW_ONLY", "UNAVAILABLE"}
_COST_METRICS = tuple(
    name for name in WORKFLOW_METRIC_KEYS if name not in {"requiredGateCount", "passedGateCount", "failedGateCount"}
)
_WINDOW_METRICS = {"elapsedWallMs", "toolWallMs"}


def summarize_regression_signals(signals: list[dict[str, Any]] | None) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for index, signal in enumerate(signals or []):
        item = _normalize_signal(index, signal, blockers)
        if item is not None:
            normalized.append(item)
    blocking_signals = [
        item
        for item in normalized
        if item["count"] > 0 and (item["type"] in BLOCKING_SIGNAL_TYPES or item["severity"] in {"HIGH", "BLOCKER"})
    ]
    body = {
        "schemaVersion": REGRESSION_SCHEMA,
        "status": "FAIL" if blockers else ("BLOCK" if blocking_signals else "PASS"),
        "signalCount": len(normalized),
        "signals": normalized,
        "blockingSignals": blocking_signals,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "signalsDigest": canonical_digest(body)}


def build_audit_regression_signals(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert sample quality failures into the existing regression contract."""

    signals: list[dict[str, Any]] = []
    false_acceptances = sum(
        1
        for sample in samples
        if isinstance(sample.get("quality"), dict) and sample["quality"].get("falseAcceptance") is True
    )
    corrections = sum(
        int(sample.get("quality", {}).get("correctionCount", 0))
        for sample in samples
        if isinstance(sample.get("quality"), dict) and isinstance(sample["quality"].get("correctionCount", 0), int)
    )
    mixed_attestation = sum(
        1
        for sample in samples
        if isinstance(sample.get("attestation"), dict) and sample["attestation"].get("overall") == "MIXED"
    )
    if false_acceptances:
        signals.append(
            {"type": "falseAcceptance", "count": false_acceptances, "severity": "BLOCKER", "source": "audit-samples"}
        )
    if corrections:
        signals.append(
            {"type": "repeatedRemediation", "count": corrections, "severity": "HIGH", "source": "audit-samples"}
        )
    if mixed_attestation:
        signals.append(
            {"type": "mixedAttestation", "count": mixed_attestation, "severity": "MEDIUM", "source": "audit-samples"}
        )
    return summarize_regression_signals(signals)


def build_workflow_comparison_context(
    *,
    source_digest: str,
    workload_identity_digest: str,
    implementation: dict[str, Any],
    role: str,
    metrics: dict[str, Any],
    gate_outcomes: dict[str, Any] | None,
    comparison_pair_id: str | None = None,
    measured_at: str | None = None,
    source_schema_version: str | None = None,
) -> dict[str, Any]:
    """Build a digest-bound comparison context without granting decision authority."""

    blockers: list[dict[str, Any]] = []
    if not _is_digest(source_digest):
        blockers.append({"code": "workflow-comparison-source-digest-invalid"})
    if not _is_digest(workload_identity_digest):
        blockers.append({"code": "workflow-comparison-workload-identity-invalid"})
    if not isinstance(implementation, dict) or not implementation:
        blockers.append({"code": "workflow-comparison-implementation-invalid"})
    if role not in {"before", "after"}:
        blockers.append({"code": "workflow-comparison-role-invalid"})
    normalized_metrics = _normalize_metrics(metrics, blockers)
    normalized_gates = _normalize_gate_outcomes(gate_outcomes, workload_identity_digest, blockers)
    if comparison_pair_id is not None and not _is_digest(comparison_pair_id):
        blockers.append({"code": "workflow-comparison-pair-id-invalid"})
    if measured_at is not None and _parse_timestamp(measured_at) is None:
        blockers.append({"code": "workflow-comparison-measured-at-invalid"})
    if blockers:
        raise LifecycleError(
            "workflow-comparison-context-invalid",
            "workflow comparison context is invalid",
            {"blockers": blockers},
        )
    body = {
        "contextVersion": "workflow-comparison-context.v1",
        "sourceSchemaVersion": source_schema_version,
        "sourceDigest": source_digest,
        "workloadIdentityDigest": workload_identity_digest,
        "implementation": _implementation_identity(implementation),
        "role": role,
        "comparisonPairId": comparison_pair_id,
        "measuredAt": measured_at,
        "metrics": normalized_metrics,
        "gateOutcomes": normalized_gates,
        "authorityClaimed": False,
    }
    return {**body, "contextDigest": canonical_digest(body)}


def workflow_comparison_context_from_fixture(
    fixture: dict[str, Any],
    *,
    role: str | None = None,
    gate_outcomes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project a historical immutable fixture into the common comparison context."""

    blockers: list[dict[str, Any]] = []
    source_digest = _fixture_digest(fixture, blockers)
    workload_digest = _workload_identity_digest(fixture, blockers)
    implementation = _fixture_implementation(fixture)
    resolved_role = role or _fixture_role(fixture)
    metrics = _fixture_metrics(fixture)
    identity = fixture.get("workloadIdentity")
    gate_floor = identity.get("requiredGateFloorDigest") if isinstance(identity, dict) else None
    resolved_gates = gate_outcomes if gate_outcomes is not None else _fixture_gate_outcomes(fixture, gate_floor)
    if blockers:
        return _invalid_context(fixture, blockers)
    try:
        return build_workflow_comparison_context(
            source_digest=source_digest,
            workload_identity_digest=workload_digest,
            implementation=implementation,
            role=resolved_role,
            metrics=metrics,
            gate_outcomes=resolved_gates,
            comparison_pair_id=fixture.get("comparisonPairId"),
            measured_at=fixture.get("measuredAt"),
            source_schema_version=fixture.get("schemaVersion"),
        )
    except LifecycleError as exc:
        details = exc.details if isinstance(exc.details, dict) else {}
        return _invalid_context(fixture, list(details.get("blockers", [])))


def compare_workflow_economics(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    comparison_pair: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare two immutable contexts without treating missing assurance as savings."""

    blockers: list[dict[str, Any]] = []
    for role, context in (("before", before), ("after", after)):
        blockers.extend(_context_blockers(context, role))
    stable_identity = before.get("workloadIdentityDigest")
    if stable_identity != after.get("workloadIdentityDigest") or not _is_digest(stable_identity):
        blockers.append({"code": "workflow-comparison-stable-identity-mismatch"})
    implementation_status = _implementation_status(before, after, comparison_pair, blockers)
    assurance = _compare_assurance(before.get("gateOutcomes"), after.get("gateOutcomes"))
    metric_deltas = {
        name: _metric_delta(before.get("metrics", {}).get(name), after.get("metrics", {}).get(name))
        for name in _COST_METRICS
    }
    status = _comparison_status(blockers, metric_deltas, assurance)
    body = {
        "viewVersion": COMPARISON_VIEW_VERSION,
        "status": status,
        "comparable": not blockers,
        "workloadIdentityDigest": stable_identity if _is_digest(stable_identity) else None,
        "implementationStatus": implementation_status,
        "comparisonPairId": before.get("comparisonPairId") if implementation_status == "PREDECLARED_PAIR" else None,
        "assurance": assurance,
        "metrics": metric_deltas,
        "sourceDigests": [before.get("sourceDigest"), after.get("sourceDigest")],
        "blockers": blockers,
        "advisoryOnly": True,
        "authorityClaimed": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "comparisonDigest": canonical_digest(body)}


def validate_workflow_economics_comparison_view(view: Any) -> dict[str, Any]:
    """Validate comparison integrity and the non-authoritative improvement boundary."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(view, dict):
        view = {}
        blockers.append({"code": "workflow-comparison-view-invalid"})
    if view.get("viewVersion") != COMPARISON_VIEW_VERSION:
        blockers.append({"code": "workflow-comparison-view-version-invalid"})
    if view.get("status") not in COMPARISON_STATUSES:
        blockers.append({"code": "workflow-comparison-status-invalid"})
    if view.get("advisoryOnly") is not True or view.get("authorityClaimed") is not False:
        blockers.append({"code": "workflow-comparison-authority-invalid"})
    if view.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "workflow-comparison-production-claim"})
    if view.get("status") == "IMPROVED":
        assurance = view.get("assurance")
        metrics = view.get("metrics")
        if not isinstance(assurance, dict) or assurance.get("status") != "EQUAL_OR_STRONGER":
            blockers.append({"code": "workflow-comparison-improvement-assurance-invalid"})
        metric_values = (
            list(metrics.values()) if isinstance(metrics, dict) and set(metrics) == set(_COST_METRICS) else []
        )
        if (
            not metric_values
            or not all(isinstance(item, dict) for item in metric_values)
            or any(
                item.get("direction") not in {"IMPROVED", "EQUAL"}
                or item.get("status") not in {"MEASURED", "TIME_WINDOW_ONLY"}
                for item in metric_values
            )
            or not any(item.get("direction") == "IMPROVED" for item in metric_values)
        ):
            blockers.append({"code": "workflow-comparison-improvement-metrics-invalid"})
    expected = canonical_digest({key: value for key, value in view.items() if key != "comparisonDigest"})
    if view.get("comparisonDigest") != expected:
        blockers.append({"code": "workflow-comparison-digest-invalid"})
    body = {
        "status": "PASS" if not blockers else "FAIL",
        "comparisonStatus": view.get("status"),
        "blockers": blockers,
        "comparisonDigest": view.get("comparisonDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _context_blockers(context: Any, role: str) -> list[dict[str, Any]]:
    if not isinstance(context, dict):
        return [{"code": "workflow-comparison-context-invalid", "role": role}]
    blockers = [{**item, "role": role} for item in context.get("blockers", []) if isinstance(item, dict)]
    if context.get("contextVersion") != "workflow-comparison-context.v1":
        blockers.append({"code": "workflow-comparison-context-version-invalid", "role": role})
    if context.get("role") != role:
        blockers.append({"code": "workflow-comparison-role-mismatch", "role": role})
    if context.get("authorityClaimed") is not False:
        blockers.append({"code": "workflow-comparison-context-authority-invalid", "role": role})
    if not _is_digest(context.get("sourceDigest")) or not _is_digest(context.get("workloadIdentityDigest")):
        blockers.append({"code": "workflow-comparison-context-lineage-invalid", "role": role})
    if not isinstance(context.get("implementation"), dict) or not context["implementation"]:
        blockers.append({"code": "workflow-comparison-context-implementation-invalid", "role": role})
    structural_blockers: list[dict[str, Any]] = []
    _normalize_metrics(context.get("metrics"), structural_blockers)
    workload_digest = context.get("workloadIdentityDigest")
    _normalize_gate_outcomes(
        context.get("gateOutcomes"),
        workload_digest if isinstance(workload_digest, str) else "",
        structural_blockers,
    )
    blockers.extend({**item, "role": role} for item in structural_blockers)
    expected = canonical_digest({key: value for key, value in context.items() if key != "contextDigest"})
    if context.get("contextDigest") != expected:
        blockers.append({"code": "workflow-comparison-context-digest-invalid", "role": role})
    return blockers


def _implementation_status(
    before: dict[str, Any],
    after: dict[str, Any],
    declaration: dict[str, Any] | None,
    blockers: list[dict[str, Any]],
) -> str:
    before_implementation = before.get("implementation")
    after_implementation = after.get("implementation")
    if before_implementation == after_implementation and isinstance(before_implementation, dict):
        return "EQUAL"
    if not isinstance(declaration, dict):
        blockers.append({"code": "workflow-comparison-implementation-mismatch"})
        return "MISMATCH"
    declaration_body = {key: value for key, value in declaration.items() if key != "comparisonPairId"}
    pair_id = declaration.get("comparisonPairId")
    if pair_id != canonical_digest(declaration_body):
        blockers.append({"code": "workflow-comparison-pair-digest-invalid"})
    if declaration.get("declaredBeforeMeasurements") is not True or declaration.get("status") != "DECLARED":
        blockers.append({"code": "workflow-comparison-pair-authority-invalid"})
    if declaration.get("schemaVersion") != "agent-workflow-economics-comparison-pair.v1":
        blockers.append({"code": "workflow-comparison-pair-schema-invalid"})
    if declaration.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "workflow-comparison-pair-production-claim"})
    identity = declaration.get("workloadIdentity")
    if not isinstance(identity, dict):
        blockers.append({"code": "workflow-comparison-pair-workload-invalid"})
    else:
        identity_body = {key: value for key, value in identity.items() if key != "workloadIdentityDigest"}
        if identity.get("workloadIdentityDigest") != canonical_digest(identity_body):
            blockers.append({"code": "workflow-comparison-pair-workload-digest-invalid"})
        if identity.get("workloadIdentityDigest") != before.get("workloadIdentityDigest"):
            blockers.append({"code": "workflow-comparison-pair-workload-mismatch"})
    for role, context in (("before", before), ("after", after)):
        expected = declaration.get(role)
        actual = {**context.get("implementation", {}), "role": role}
        if expected != actual:
            blockers.append({"code": "workflow-comparison-pair-implementation-mismatch", "role": role})
        if context.get("comparisonPairId") != pair_id:
            blockers.append({"code": "workflow-comparison-pair-membership-invalid", "role": role})
        if not _declared_before_measurement(declaration.get("declaredAt"), context.get("measuredAt")):
            blockers.append({"code": "workflow-comparison-pair-retrospective", "role": role})
    return "PREDECLARED_PAIR" if not blockers else "MISMATCH"


def _declared_before_measurement(declared_at: Any, measured_at: Any) -> bool:
    declared = _parse_timestamp(declared_at)
    measured = _parse_timestamp(measured_at)
    return declared is not None and measured is not None and declared < measured


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _compare_assurance(before: Any, after: Any) -> dict[str, Any]:
    if not isinstance(before, dict) or not isinstance(after, dict):
        return {"status": "UNAVAILABLE", "reasons": ["gate-outcomes-unavailable"]}
    before_required = set(before.get("requiredGateIds", []))
    after_required = set(after.get("requiredGateIds", []))
    after_passed = set(after.get("passedGateIds", []))
    after_failed = set(after.get("failedGateIds", []))
    reasons: list[str] = []
    before_passed = set(before.get("passedGateIds", []))
    before_failed = set(before.get("failedGateIds", []))
    if before_failed or before.get("acceptanceStatus") != "PASS" or before_passed != before_required:
        reasons.append("baseline-assurance-invalid")
    if before.get("qualityFloorDigest") != after.get("qualityFloorDigest"):
        reasons.append("quality-floor-mismatch")
    if not before_required.issubset(after_required):
        reasons.append("required-gates-removed")
    if not before_required.issubset(after_passed):
        reasons.append("required-gates-not-passed")
    if after_failed:
        reasons.append("failed-gates-present")
    if before.get("acceptanceStatus") == "PASS" and after.get("acceptanceStatus") != "PASS":
        reasons.append("acceptance-outcome-degraded")
    return {
        "status": "WEAKER" if reasons else "EQUAL_OR_STRONGER",
        "baselineRequiredGateIds": sorted(before_required),
        "currentRequiredGateIds": sorted(after_required),
        "currentPassedGateIds": sorted(after_passed),
        "currentFailedGateIds": sorted(after_failed),
        "reasons": reasons,
    }


def _metric_delta(before: Any, after: Any) -> dict[str, Any]:
    if not _known_metric(before) or not _known_metric(after):
        return {"status": "UNAVAILABLE", "before": None, "after": None, "delta": None, "direction": "UNKNOWN"}
    before_value = before["value"]
    after_value = after["value"]
    delta = after_value - before_value
    statuses = {before["status"], after["status"]}
    if _DERIVED_STATUSES.intersection(statuses):
        status = "MIXED"
    elif "ESTIMATED" in statuses:
        status = "ESTIMATED"
    elif "TIME_WINDOW_ONLY" in statuses:
        status = "TIME_WINDOW_ONLY"
    else:
        status = "MEASURED"
    return {
        "status": status,
        "before": before_value,
        "after": after_value,
        "delta": delta,
        "direction": "IMPROVED" if delta < 0 else ("REGRESSED" if delta > 0 else "EQUAL"),
    }


def _comparison_status(
    blockers: list[dict[str, Any]],
    metrics: dict[str, dict[str, Any]],
    assurance: dict[str, Any],
) -> str:
    if blockers:
        return "NO_COMPARABLE_BASELINE"
    directions = {item["direction"] for item in metrics.values()}
    complete = all(item["status"] in {"MEASURED", "TIME_WINDOW_ONLY"} for item in metrics.values())
    if assurance.get("status") == "WEAKER":
        return "REGRESSED"
    if assurance.get("status") != "EQUAL_OR_STRONGER" or not complete:
        return "MIXED"
    improved = "IMPROVED" in directions
    regressed = "REGRESSED" in directions
    if improved and not regressed:
        return "IMPROVED"
    if regressed and not improved:
        return "REGRESSED"
    return "MIXED"


def _normalize_metrics(value: Any, blockers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    supplied = value if isinstance(value, dict) else {}
    if not isinstance(value, dict):
        blockers.append({"code": "workflow-comparison-metrics-invalid"})
    unknown = set(supplied).difference(_COST_METRICS)
    if unknown:
        blockers.append({"code": "workflow-comparison-metrics-unknown", "metrics": sorted(unknown)})
    result: dict[str, dict[str, Any]] = {}
    for name in _COST_METRICS:
        metric = supplied.get(name, {"status": "UNAVAILABLE", "value": None})
        if not _valid_metric(metric, name):
            blockers.append({"code": "workflow-comparison-metric-invalid", "metric": name})
            result[name] = {"status": "UNAVAILABLE", "value": None}
        else:
            result[name] = {"status": metric["status"], "value": metric["value"]}
    return result


def _valid_metric(metric: Any, name: str) -> bool:
    if not isinstance(metric, dict) or set(metric) != {"status", "value"}:
        return False
    status = metric.get("status")
    value = metric.get("value")
    if status not in _SOURCE_STATUSES | _DERIVED_STATUSES:
        return False
    if status == "TIME_WINDOW_ONLY" and name not in _WINDOW_METRICS:
        return False
    if status == "UNAVAILABLE":
        return value is None
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _known_metric(metric: Any) -> bool:
    return isinstance(metric, dict) and metric.get("status") != "UNAVAILABLE" and isinstance(metric.get("value"), int)


def _fixture_digest(fixture: Any, blockers: list[dict[str, Any]]) -> str:
    if not isinstance(fixture, dict):
        blockers.append({"code": "workflow-comparison-fixture-invalid"})
        return ""
    digest_fields = [
        name for name in ("measurementDigest", "accountingDigest", "fixtureDigest", "inputDigest") if name in fixture
    ]
    if len(digest_fields) != 1:
        blockers.append({"code": "workflow-comparison-fixture-digest-field-invalid"})
        return ""
    field = digest_fields[0]
    expected = canonical_digest({key: value for key, value in fixture.items() if key != field})
    if fixture.get(field) != expected:
        blockers.append({"code": "workflow-comparison-fixture-digest-invalid", "field": field})
    _historical_availability_blockers(fixture, blockers)
    digest = fixture.get(field)
    return digest if isinstance(digest, str) and _is_digest(digest) else ""


def _historical_availability_blockers(value: Any, blockers: list[dict[str, Any]], path: str = "$") -> None:
    if isinstance(value, dict):
        if value.get("status") == "UNAVAILABLE":
            for field in ("value", "inputTokens", "cachedInputTokens", "outputTokens"):
                if field in value and value[field] is not None:
                    blockers.append(
                        {
                            "code": "workflow-comparison-unavailable-backfill",
                            "path": f"{path}.{field}",
                        }
                    )
        for key, item in value.items():
            _historical_availability_blockers(item, blockers, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _historical_availability_blockers(item, blockers, f"{path}[{index}]")


def _workload_identity_digest(fixture: dict[str, Any], blockers: list[dict[str, Any]]) -> str:
    identity = fixture.get("workloadIdentity")
    if isinstance(identity, dict):
        expected = canonical_digest({key: value for key, value in identity.items() if key != "workloadIdentityDigest"})
        if identity.get("workloadIdentityDigest") != expected:
            blockers.append({"code": "workflow-comparison-fixture-workload-digest-invalid"})
        digest = identity.get("workloadIdentityDigest")
        return digest if isinstance(digest, str) else ""
    digest = fixture.get("workloadIdentityDigest")
    if not _is_digest(digest):
        blockers.append({"code": "workflow-comparison-fixture-workload-unavailable"})
        return ""
    return digest if isinstance(digest, str) else ""


def _fixture_implementation(fixture: dict[str, Any]) -> dict[str, Any]:
    implementation = fixture.get("implementation")
    if isinstance(implementation, dict):
        return implementation
    source = fixture.get("source")
    if isinstance(source, dict) and source.get("coreVersion"):
        result: dict[str, Any] = {
            "sourceRevision": source.get("sourceRevision") or source.get("baseRevision"),
            "coreVersion": source.get("coreVersion"),
        }
        if isinstance(source.get("publicationVersions"), dict):
            result["publicationVersions"] = source["publicationVersions"]
        return result
    return {}


def _implementation_identity(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "role"}


def _fixture_role(fixture: dict[str, Any]) -> str:
    role = fixture.get("role")
    if role in {"before", "after"}:
        return role
    implementation = fixture.get("implementation")
    if isinstance(implementation, dict) and implementation.get("role") in {"before", "after"}:
        return str(implementation["role"])
    return "after"


def _fixture_metrics(fixture: dict[str, Any]) -> dict[str, Any]:
    workflow = fixture.get("workflowEconomics")
    if isinstance(workflow, dict) and isinstance(workflow.get("metrics"), dict):
        return {key: value for key, value in workflow["metrics"].items() if key in _COST_METRICS}
    schema = fixture.get("schemaVersion")
    if schema == "agent-workflow-economics-measurement.v1":
        return _measurement_metrics(fixture)
    if schema == "agent-delta-audit-economics-baseline.v1":
        return _delta_audit_metrics(fixture)
    if schema == "agent-execution-strategy-economics-baseline.v1":
        return _strategy_metrics(fixture)
    return {}


def _measurement_metrics(fixture: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for source, target in (
        ("modelTurns", "modelTurns"),
        ("commandCount", "toolCalls"),
        ("outputBytes", "toolOutputBytes"),
        ("packetBytes", "packetBytes"),
        ("transitionCount", "controllerTransitions"),
    ):
        value = fixture.get(source)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            metrics[target] = {"status": "MEASURED", "value": value}
    wall = fixture.get("wallSeconds")
    if isinstance(wall, (int, float)) and not isinstance(wall, bool) and wall >= 0:
        metrics["elapsedWallMs"] = {"status": "MEASURED", "value": round(wall * 1000)}
    return metrics


def _delta_audit_metrics(fixture: dict[str, Any]) -> dict[str, Any]:
    full = fixture.get("routes", {}).get("fullRepeat", {})
    metrics: dict[str, Any] = {}
    tokens = full.get("tokens") if isinstance(full, dict) else None
    if isinstance(tokens, dict) and tokens.get("status") == "MEASURED":
        metrics.update(
            {
                "modelInputTokens": _measured(tokens.get("inputTokens")),
                "modelCachedInputTokens": _measured(
                    _safe_sum(tokens.get("cacheCreationInputTokens"), tokens.get("cacheReadInputTokens"))
                ),
                "modelOutputTokens": _measured(tokens.get("outputTokens")),
            }
        )
    for source, target in (("turns", "modelTurns"), ("toolCalls", "toolCalls")):
        metric = full.get(source) if isinstance(full, dict) else None
        if isinstance(metric, dict) and metric.get("status") in _SOURCE_STATUSES:
            metrics[target] = {"status": metric["status"], "value": metric.get("value")}
    time = full.get("time") if isinstance(full, dict) else None
    if isinstance(time, dict) and time.get("status") == "MEASURED":
        metrics["elapsedWallMs"] = _measured(time.get("elapsedMs"))
    return metrics


def _strategy_metrics(fixture: dict[str, Any]) -> dict[str, Any]:
    cases = fixture.get("cases")
    if not isinstance(cases, list):
        return {}
    selected = next((item for item in cases if isinstance(item, dict) and item.get("caseId") == "audit-heavy-s2"), None)
    if not isinstance(selected, dict):
        return {}
    adoption = selected.get("automaticAdoption")
    if not isinstance(adoption, dict) or adoption.get("status") != "MEASURED":
        return {}
    metrics: dict[str, Any] = {}
    for source, target in (("modelTurns", "modelTurns"), ("commandCount", "toolCalls"), ("packetBytes", "packetBytes")):
        if source in adoption:
            metrics[target] = _measured(adoption[source])
    wall = adoption.get("strategyResolutionWallSeconds")
    if isinstance(wall, (int, float)) and not isinstance(wall, bool) and wall >= 0:
        metrics["elapsedWallMs"] = _measured(round(wall * 1000))
    return metrics


def _measured(value: Any) -> dict[str, Any]:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return {"status": "MEASURED", "value": value}
    return {"status": "UNAVAILABLE", "value": None}


def _safe_sum(*values: Any) -> int | None:
    return (
        sum(values)
        if all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in values)
        else None
    )


def _fixture_gate_outcomes(fixture: dict[str, Any], gate_floor: Any) -> dict[str, Any] | None:
    gates = fixture.get("gateOutcomes")
    if not isinstance(gates, dict):
        return None
    if "requiredGateIds" in gates:
        return gates
    required = sorted(key for key, value in gates.items() if isinstance(key, str) and isinstance(value, str))
    passed = sorted(key for key in required if gates[key] == "PASS")
    failed = sorted(set(required).difference(passed))
    return {
        "requiredGateIds": required,
        "passedGateIds": passed,
        "failedGateIds": failed,
        "qualityFloorDigest": gate_floor,
        "acceptanceStatus": "PASS" if not failed else "FAIL",
    }


def _normalize_gate_outcomes(
    value: Any,
    workload_identity_digest: str,
    blockers: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        blockers.append({"code": "workflow-comparison-gate-outcomes-invalid"})
        return None
    required = _string_set(value.get("requiredGateIds"))
    passed = _string_set(value.get("passedGateIds"))
    failed = _string_set(value.get("failedGateIds"))
    quality_floor = value.get("qualityFloorDigest")
    acceptance = value.get("acceptanceStatus")
    if required is None or passed is None or failed is None or not _is_digest(quality_floor):
        blockers.append({"code": "workflow-comparison-gate-outcomes-invalid"})
        return None
    if passed.intersection(failed) or passed.union(failed) != required:
        blockers.append({"code": "workflow-comparison-gate-outcomes-inconsistent"})
    if value.get("workloadIdentityDigest") not in {None, workload_identity_digest}:
        blockers.append({"code": "workflow-comparison-gate-lineage-mismatch"})
    if acceptance not in {"PASS", "FAIL", "BLOCKED", "UNAVAILABLE"}:
        blockers.append({"code": "workflow-comparison-acceptance-status-invalid"})
    return {
        "requiredGateIds": sorted(required),
        "passedGateIds": sorted(passed),
        "failedGateIds": sorted(failed),
        "qualityFloorDigest": quality_floor,
        "acceptanceStatus": acceptance,
        "workloadIdentityDigest": workload_identity_digest,
    }


def _string_set(value: Any) -> set[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        return None
    return set(value)


def _invalid_context(fixture: Any, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "contextVersion": "workflow-comparison-context.v1",
        "sourceSchemaVersion": fixture.get("schemaVersion") if isinstance(fixture, dict) else None,
        "sourceDigest": None,
        "workloadIdentityDigest": None,
        "implementation": None,
        "role": None,
        "comparisonPairId": None,
        "measuredAt": None,
        "metrics": {},
        "gateOutcomes": None,
        "authorityClaimed": False,
        "blockers": blockers,
    }
    return {**body, "contextDigest": canonical_digest(body)}


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _normalize_signal(index: int, signal: dict[str, Any], blockers: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(signal, dict):
        blockers.append({"code": "regression-signal-type", "index": index})
        return None
    signal_type = signal.get("type")
    if not isinstance(signal_type, str) or not signal_type:
        blockers.append({"code": "regression-signal-missing-type", "index": index})
        return None
    count = signal.get("count", 1)
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        blockers.append({"code": "regression-signal-count", "index": index, "type": signal_type})
        return None
    severity = signal.get("severity", "MEDIUM")
    if severity not in {"LOW", "MEDIUM", "HIGH", "BLOCKER"}:
        blockers.append({"code": "regression-signal-severity", "index": index, "type": signal_type})
        return None
    return {
        "type": signal_type,
        "count": count,
        "severity": severity,
        "source": signal.get("source"),
        "note": signal.get("note"),
    }

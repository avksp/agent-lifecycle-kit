"""Deterministic predicates for the bundled reference tasks."""

from __future__ import annotations

from typing import Any, Callable

from agent_lifecycle.contracts import LifecycleError, canonical_digest

Oracle = Callable[[dict[str, Any], list[dict[str, Any]]], None]


def evaluate_oracle(oracle: dict[str, Any], submission: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    evidence = submission.get("evidence") if isinstance(submission.get("evidence"), dict) else {}
    observed_schemas = _schema_versions(evidence)
    for schema in oracle["requiredEvidenceSchemas"]:
        _record(checks, code="required-evidence-schema", passed=schema in observed_schemas, evidence_schema=schema)
    handlers: dict[str, Oracle] = {
        "planning": _planning,
        "architecture-review": _architecture_review,
        "bug-forensics": _bug_forensics,
        "s1-managed-task": _s1_managed_task,
        "s2-evidence-task": _s2_evidence_task,
    }
    oracle_type = oracle.get("oracleType")
    handler = handlers.get(oracle_type)
    if handler is None:
        raise LifecycleError("reference-oracle-type", "reference task oracle type is unsupported")
    handler(evidence, checks)
    blockers = [{"code": item["code"]} for item in checks if not item["passed"]]
    body = {
        "status": "PASS" if not blockers else "FAIL",
        "oracleType": oracle["oracleType"],
        "checks": checks,
        "blockers": blockers,
        "oracleDigest": canonical_digest(oracle),
    }
    return {**body, "resultDigest": canonical_digest(body)}


def _planning(evidence: dict[str, Any], checks: list[dict[str, Any]]) -> None:
    plan = _object(evidence, "planValidation")
    completeness = _object(evidence, "completenessValidation")
    acceptance = _object(evidence, "acceptanceValidation")
    _record(checks, code="plan-frozen", passed=plan.get("schemaVersion") == "agent-plan-validation.v1" and plan.get("status") == "FROZEN")
    _record(
        checks,
        code="plan-completeness-pass",
        passed=completeness.get("schemaVersion") == "agent-plan-completeness-validation.v1"
        and completeness.get("status") == "PASS"
        and completeness.get("blockers") == [],
    )
    _record(
        checks,
        code="plan-acceptance-crosswalk-pass",
        passed=acceptance.get("schemaVersion") == "agent-acceptance-checklist-validation.v1"
        and acceptance.get("status") == "PASS"
        and all(acceptance.get(key) == [] for key in ("missingInMarkdown", "extraInMarkdown", "linkMismatches")),
    )


def _architecture_review(evidence: dict[str, Any], checks: list[dict[str, Any]]) -> None:
    quorum = _object(evidence, "reviewMeshQuorum")
    _record(
        checks,
        code="review-quorum-pass",
        passed=quorum.get("schemaVersion") == "agent-review-mesh-quorum-receipt.v1"
        and quorum.get("status") == "PASS"
        and quorum.get("requiredRolesSatisfied") is True
        and quorum.get("quorumSatisfied") is True
        and quorum.get("blockingFindingsUnresolved") is False
        and quorum.get("blockers") == [],
    )


def _bug_forensics(evidence: dict[str, Any], checks: list[dict[str, Any]]) -> None:
    reproduction = _object(evidence, "reproductionReceipt")
    proof = _object(evidence, "regressionProof")
    validation = _object(evidence, "regressionProofValidation")
    _record(
        checks,
        code="bug-reproduction-bound",
        passed=reproduction.get("schemaVersion") == "agent-bug-reproduction-receipt.v1"
        and reproduction.get("status") == "PASS"
        and proof.get("reproductionReceiptDigest") == reproduction.get("receiptDigest"),
    )
    _record(
        checks,
        code="regression-proof-pass",
        passed=proof.get("schemaVersion") == "agent-regression-proof-receipt.v1"
        and proof.get("status") == "PASS"
        and validation.get("schemaVersion") == "agent-regression-proof-receipt-validation.v1"
        and validation.get("status") == "PASS"
        and validation.get("proofStatus") == "PASS"
        and validation.get("proofDigest") == proof.get("proofDigest")
        and validation.get("blockers") == [],
    )


def _s1_managed_task(evidence: dict[str, Any], checks: list[dict[str, Any]]) -> None:
    result = _object(evidence, "taskResult")
    audit = _object(evidence, "implementationAuditValidation")
    outcomes = result.get("itemOutcomes")
    commands = result.get("commands")
    _record(
        checks,
        code="s1-task-result-complete",
        passed=result.get("schemaVersion") == "agent-task-result.v2"
        and result.get("blocker") is None
        and result.get("contractChangeRequest") is None
        and isinstance(outcomes, list)
        and bool(outcomes)
        and all(isinstance(item, dict) and item.get("status") == "COMPLETE" for item in outcomes)
        and isinstance(commands, list)
        and all(isinstance(item, dict) and item.get("status") == "PASS" for item in commands),
    )
    _record(
        checks,
        code="s1-implementation-audit-pass",
        passed=audit.get("schemaVersion") == "agent-implementation-audit-report-validation.v1"
        and audit.get("status") == "PASS"
        and audit.get("verdict") == "ACCEPTED"
        and audit.get("blockers") == [],
    )


def _s2_evidence_task(evidence: dict[str, Any], checks: list[dict[str, Any]]) -> None:
    proof = _object(evidence, "finalProof")
    implementation = _object(evidence, "finalImplementationAuditValidation")
    integrity = _object(evidence, "proofIntegrityValidation")
    accepted = proof.get("acceptedTasks")
    _record(
        checks,
        code="s2-final-proof-ready",
        passed=proof.get("schemaVersion") == "agent-run-final-proof.v1"
        and proof.get("semanticStatus") == "READY_FOR_FINALIZATION"
        and proof.get("productionPromotionClaimed") is False
        and isinstance(accepted, list)
        and bool(accepted)
        and all(isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"] for item in accepted),
    )
    _record(
        checks,
        code="s2-final-audits-pass",
        passed=implementation.get("schemaVersion") == "agent-final-implementation-audit-validation.v1"
        and implementation.get("status") == "PASS"
        and implementation.get("blockers") == []
        and integrity.get("schemaVersion") == "agent-proof-integrity-validation.v1"
        and integrity.get("status") == "PASS"
        and integrity.get("blockers") == [],
    )
    quorum = evidence.get("reviewMeshQuorum")
    if quorum is not None:
        _record(
            checks,
            code="s2-opted-review-quorum-pass",
            passed=isinstance(quorum, dict)
            and quorum.get("schemaVersion") == "agent-review-mesh-quorum-receipt.v1"
            and quorum.get("status") == "PASS"
            and quorum.get("quorumSatisfied") is True
            and quorum.get("blockingFindingsUnresolved") is False
            and quorum.get("blockers") == [],
        )


def _record(checks: list[dict[str, Any]], *, code: str, passed: bool, evidence_schema: str | None = None) -> None:
    row: dict[str, Any] = {"code": code, "passed": bool(passed)}
    if evidence_schema:
        row["evidenceSchema"] = evidence_schema
    checks.append(row)


def _object(value: dict[str, Any], key: str) -> dict[str, Any]:
    candidate = value.get(key)
    return candidate if isinstance(candidate, dict) else {}


def _schema_versions(value: Any) -> set[str]:
    found: set[str] = set()
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            schema = item.get("schemaVersion")
            if isinstance(schema, str):
                found.add(schema)
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return found

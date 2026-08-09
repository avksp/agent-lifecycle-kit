"""Build deterministic evaluation receipts from supplied ALK artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.benchmarks.contracts import load_submission, load_suite, load_task
from agent_lifecycle.benchmarks.oracles import evaluate_oracle
from agent_lifecycle.benchmarks.reporting import build_measurements, redact_evaluation_payload
from agent_lifecycle.contracts import LifecycleError, canonical_digest


def evaluate_reference_task(*, suite_path: Path, artifact_path: Path) -> dict[str, Any]:
    suite = load_suite(suite_path)
    submission, input_identity = load_submission(artifact_path)
    task = load_task(suite, submission["taskId"])
    if submission.get("taskVersion") != task.row["version"]:
        raise LifecycleError("reference-submission-lineage", "submission task version does not match suite", {"taskId": task.row["id"]})
    oracle_result = evaluate_oracle(task.oracle, submission)
    measurements, measurement_blockers = build_measurements(submission, oracle_result)
    accepted = submission["accepted"]
    oracle_passed = oracle_result["status"] == "PASS"
    false_acceptance = accepted and not oracle_passed
    blockers = [*oracle_result["blockers"], *measurement_blockers]
    status = "PASS" if accepted and oracle_passed and not blockers else "FAIL"
    body: dict[str, Any] = {
        "schemaVersion": "agent-reference-task-evaluation.v1",
        "status": status,
        "suite": {"id": suite.payload["suiteId"], "version": suite.payload["suiteVersion"], "digest": suite.digest},
        "task": {
            "id": task.row["id"],
            "version": task.row["version"],
            "family": task.row["family"],
            "tier": task.row["tier"],
            "taskDigest": task.task_digest,
            "oracleDigest": task.oracle_digest,
        },
        "inputArtifacts": [input_identity],
        "oracle": oracle_result,
        "measurements": measurements,
        "summary": {
            "acceptedClaimed": accepted,
            "oraclePassed": oracle_passed,
            "falseAcceptanceCount": 1 if false_acceptance else 0,
            "measurementGapCount": len(measurements["measurementGaps"]),
        },
        "blockers": blockers,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    redacted, redaction = redact_evaluation_payload(body)
    redacted["redaction"] = redaction
    return {**redacted, "evaluationDigest": canonical_digest(redacted)}

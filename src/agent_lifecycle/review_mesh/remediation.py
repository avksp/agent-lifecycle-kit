"""Join remedy data to existing review evidence; never launch or apply remedies."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from agent_lifecycle.changesets.snapshot import capture_task_change_set
from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.canonical import load_json_object
from agent_lifecycle.contracts.independent_evidence_schemas import (
    build_independence_requirement,
    validate_independent_evidence,
)
from agent_lifecycle.contracts.paths import read_stable_repository_file
from agent_lifecycle.contracts.review_remedy_schemas import (
    PARTICIPATION_VERSION,
    bounded_list,
    closed,
    remedy_error,
    require_bound_digest,
    require_decisions,
    require_evidence_index,
    require_recheck,
    require_remedy_policy,
)
from agent_lifecycle.contracts.review_round_schemas import (
    validate_finding_disposition,
    validate_review_round_participation,
)
from agent_lifecycle.contracts.workflow_state_schemas import has_current_workflow_semantics, validate_workflow_state

_KINDS = {
    "assignment": ("agent-review-mesh-assignment.v2", "assignmentDigest"),
    "result": ("agent-review-mesh-result.v2", "resultDigest"),
    "decision": ("agent-review-remedy-decisions.v1", "decisionsDigest"),
    "participation": (PARTICIPATION_VERSION, "qualificationDigest"),
    "disposition": ("agent-finding-disposition.v1", "dispositionDigest"),
    "recheck": ("agent-review-remedy-recheck.v1", "recheckDigest"),
    "delta": ("agent-rework-delta-audit-receipt.v1", "receiptDigest"),
    "dependency": ("agent-module-dependency-report.v1", "reportDigest"),
    "validation-selection": ("agent-validation-selection.v1", "selectionDigest"),
    "finding-binding": ("agent-finding-check-binding.v1", "bindingDigest"),
    "finding-evidence": ("agent-finding-check-evidence.v1", "evidenceDigest"),
    "manifest": ("agent-plan-manifest.v1", None),
    "lock": ("agent-plan-lock.v2", None),
    "state": ("agent-workflow-state.v6", None),
}


def load_remedy_evidence(root: Path, path: str) -> dict[str, Any]:
    """Read a bounded portable index and exact stable artifact bytes."""
    raw = read_stable_repository_file(root, path, max_bytes=65536, label="remedy evidence index")
    index = require_evidence_index(load_json_object(raw))
    loaded = []
    total = len(raw)
    for reference in index["artifacts"]:
        if reference["path"] == path:
            raise remedy_error("evidence index cannot include itself")
        content = read_stable_repository_file(root, reference["path"], max_bytes=8388608, label="remedy evidence")
        total += len(content)
        if total > 67108864 or hashlib.sha256(content).hexdigest() != reference["sha256"]:
            raise remedy_error("evidence bytes exceed cap or differ from reference")
        payload = load_json_object(content)
        _require_artifact_kind(reference["kind"], payload, reference["digest"])
        loaded.append({"reference": reference, "value": payload})
    return {
        "index": index,
        "artifacts": loaded,
        "reference": {"path": path, "sha256": hashlib.sha256(raw).hexdigest(), "digest": index["bundleDigest"]},
    }


def _require_artifact_kind(kind: str, value: dict[str, Any], expected_digest: str) -> None:
    schema, field = _KINDS[kind]
    actual = value.get("schemaVersion")
    valid_schema = actual == schema
    if kind == "lock":
        valid_schema = isinstance(actual, str) and actual in {"agent-plan-lock.v1", "agent-plan-lock.v2"}
    if not valid_schema:
        raise remedy_error("artifact kind differs from its typed content")
    if field is None:
        computed = canonical_digest(value)
    else:
        require_bound_digest(value, field, 8388608)
        computed = value[field]
    if computed != expected_digest:
        raise remedy_error("artifact digest differs from index")


def evidence_values(bundle: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [item["value"] for item in bundle["artifacts"] if item["reference"]["kind"] == kind]


def evidence_value(bundle: dict[str, Any], kind: str, digest: str) -> dict[str, Any]:
    matches = [
        item["value"]
        for item in bundle["artifacts"]
        if item["reference"]["kind"] == kind and item["reference"]["digest"] == digest
    ]
    if len(matches) != 1:
        raise remedy_error(f"exact {kind} evidence is missing")
    return matches[0]


def native_remedy_context(
    root: Path,
    manifest: dict[str, Any],
    lock: dict[str, Any],
    *,
    phase: str,
    state: dict[str, Any] | None = None,
    task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Native consumers pass their loaded authority; receipts never choose it."""
    source = manifest["baseRevision"]["sha"]
    context = {
        "phase": phase,
        "packageId": manifest["package"]["id"],
        "planRevision": manifest["planRevision"],
        "planDigest": canonical_digest(manifest),
        "planLockDigest": canonical_digest(lock),
        "sourceRevision": source,
        "sourceLineageDigest": canonical_digest(
            {
                "kind": "PLAN_MANIFEST",
                "planDigest": canonical_digest(manifest),
                "baseRevision": manifest["baseRevision"],
            }
        ),
    }
    if phase == "freeze":
        files = []
        pending = manifest.get("planReview", {}).get("report")
        for path in sorted(manifest.get("planFiles", [])):
            if path == pending:
                continue
            raw = read_stable_repository_file(root, path, max_bytes=8388608)
            files.append({"path": path, "sha256": hashlib.sha256(raw).hexdigest()})
        context["sourceSnapshotDigest"] = canonical_digest(files)
    else:
        if state is None:
            raise remedy_error("current native state is required")
        if any(state.get(key) != context[key] for key in ("packageId", "planRevision", "planDigest", "sourceRevision")):
            raise remedy_error("native state and manifest lineage differ")
        context["runId"] = state["runId"]
        tasks = [task] if task is not None else state["tasks"]
        writes = sorted({path for entry in tasks for path in entry.get("writes", [])})
        snapshot = capture_task_change_set(root, baseline=source, write_paths=writes)
        context["sourceSnapshotDigest"] = snapshot["snapshotHash"]
        if task is not None:
            context.update(taskId=task["id"], attempt=task["attempt"])
    return context


def prepared_remedy_context(root: Path, manifest: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    """Bind prepared inputs now; the native gate independently recomputes later."""
    authority = []
    for entry in request["inputs"]:
        if entry["id"] in request["authorityRefs"]:
            raw = read_stable_repository_file(root, entry["path"], max_bytes=8388608)
            authority.append(load_json_object(raw))
    locks = [item for item in authority if item.get("schemaVersion") in {"agent-plan-lock.v1", "agent-plan-lock.v2"}]
    if len(locks) != 1:
        raise remedy_error("prepared remedy requires the exact plan lock input")
    phase = "freeze" if request["phase"] == "plan-review" else request["phase"]
    state, task = None, None
    if phase != "freeze":
        states = [item for item in authority if has_current_workflow_semantics(item)]
        if len(states) != 1:
            raise remedy_error("prepared remedy requires the current native state input")
        state = validate_workflow_state(states[0])
        if phase == "implementation-audit":
            ids = request["scope"]["taskIds"]
            tasks = [item for item in state["tasks"] if item["id"] in ids]
            if len(tasks) != 1 or len(ids) != 1 or tasks[0].get("attempt", 0) < 1:
                raise remedy_error("implementation remedy requires one actual current task attempt")
            task = tasks[0]
    return native_remedy_context(root, manifest, locks[0], phase=phase, state=state, task=task)


def qualify_remedy_candidate(
    profile: dict[str, Any],
    assignment: dict[str, Any],
    candidate: dict[str, Any],
    bundle: dict[str, Any],
) -> dict[str, Any]:
    """Build a separate qualified result while retaining the original candidate."""
    from agent_lifecycle.review_mesh.contracts import build_review_mesh_result

    wrappers = [
        value
        for value in evidence_values(bundle, "participation")
        if value.get("assignmentDigest") == assignment["assignmentDigest"]
    ]
    if len(wrappers) != 1:
        raise remedy_error("exact independently qualified participation is required")
    wrapper = wrappers[0]
    context = _qualified_participation(wrapper, assignment, candidate, profile)
    result = build_review_mesh_result(
        profile=profile,
        assignment=assignment,
        budget_usage=candidate["budgetUsage"],
        findings=candidate["findings"],
        status=candidate["status"],
        independent_evidence=wrapper["independentEvidence"],
        session_usage_context=context,
    )
    for key in ("commandOutcomes", "redaction", "import"):
        if key in candidate:
            result[key] = candidate[key]
    result["remedyQualification"] = {"participationDigest": wrapper["qualificationDigest"], "candidate": candidate}
    result["roundParticipation"] = {"eligible": True, "participationDigest": wrapper["qualificationDigest"]}
    result["resultDigest"] = canonical_digest({key: item for key, item in result.items() if key != "resultDigest"})
    return result


def _qualified_participation(
    value: Any,
    assignment: dict[str, Any],
    candidate: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    from agent_lifecycle.review_mesh.contracts import cumulative_reviewer_budget

    value = closed(
        value,
        {
            "schemaVersion",
            "assignmentDigest",
            "rawOutputDigest",
            "participation",
            "independentEvidence",
            "sessionUsageContext",
            "qualificationDigest",
        },
        "qualified participation",
    )
    require_bound_digest(value, "qualificationDigest", 262144)
    if value["schemaVersion"] != PARTICIPATION_VERSION or value["assignmentDigest"] != assignment["assignmentDigest"]:
        raise remedy_error("participation assignment differs")
    if value["rawOutputDigest"] != candidate.get("import", {}).get("outputDigest"):
        raise remedy_error("participation raw response differs")
    participation = value["participation"]
    checked = validate_review_round_participation(participation)
    if checked["status"] != "PASS" or participation.get("participating") is not True:
        raise remedy_error("terminal job and review verdict do not qualify")
    if (
        participation["reviewerId"] != assignment["reviewer"]["id"]
        or participation["findings"] != candidate["findings"]
    ):
        raise remedy_error("participation reviewer or normalized findings differ")
    expected_status = "PASS" if participation["reviewVerdict"]["overall"] == "ACCEPTED" else "FAIL"
    if candidate["status"] != expected_status:
        raise remedy_error("candidate status differs from the qualified review verdict")
    _require_terminal_output_binding(participation["reviewVerdict"], assignment, candidate)
    _participation_bindings(participation, assignment)
    _participation_independence(value["independentEvidence"], assignment, candidate)
    context = closed(value["sessionUsageContext"], {"receipt", "qualification", "previous"}, "scoped usage context")
    observed = participation["jobResult"].get("observation", {}).get("sessionUsage")
    if observed is None or context["receipt"] != observed:
        raise remedy_error("available usage must join the actual terminal job observation")
    cumulative_reviewer_budget(profile, assignment, candidate["budgetUsage"], context)
    return context


def _participation_bindings(participation: dict[str, Any], assignment: dict[str, Any]) -> None:
    request = participation["jobRequest"]
    observation = participation["jobResult"].get("observation", {})
    context = assignment["subject"].get("remedyContext")
    if not isinstance(context, dict):
        raise remedy_error("prepared native remedy context is missing")
    expected = {
        "descriptorDigest": assignment["assignmentDigest"],
        "planDigest": context["planDigest"],
        "planLockDigest": context["planLockDigest"],
        "sourceRevision": context["sourceRevision"],
        "sourceSnapshotDigest": context["sourceSnapshotDigest"],
    }
    if any(request.get(key) != item for key, item in expected.items()):
        raise remedy_error("terminal request source/plan/assignment binding differs")
    if observation.get("assignmentDigest") != assignment["assignmentDigest"] or observation.get(
        "subjectDigest"
    ) != canonical_digest(assignment["subject"]):
        raise remedy_error("terminal observation does not bind the complete review subject")


def qualified_results(
    profile: dict[str, Any], results: list[dict[str, Any]], bundle: dict[str, Any]
) -> list[dict[str, Any]]:
    """Revalidate qualified producer chains each time, not their PASS labels."""
    bounded_list(results, 32, "reviewer results", nonempty=True)
    seen = set()
    for result in results:
        proof = closed(result.get("remedyQualification"), {"participationDigest", "candidate"}, "result qualification")
        candidate = proof["candidate"]
        require_bound_digest(candidate, "resultDigest", 8388608)
        assignment = evidence_value(bundle, "assignment", candidate["import"]["assignmentDigest"])
        rebuilt = qualify_remedy_candidate(profile, assignment, candidate, bundle)
        if rebuilt != result or result["reviewer"]["id"] in seen:
            raise remedy_error("qualified result changed or reviewer identity is duplicated")
        seen.add(result["reviewer"]["id"])
    return results


def finding_origins(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs = []
    for result in results:
        for finding in result["findings"]:
            refs.append(
                {
                    "findingId": finding["id"],
                    "findingDigest": canonical_digest(finding),
                    "assignmentDigest": result["import"]["assignmentDigest"],
                    "resultDigest": result["resultDigest"],
                    "reviewEvidenceDigest": result["remedyQualification"]["participationDigest"],
                }
            )
    bounded_list(refs, 256, "synthesis finding origins")
    return sorted(refs, key=canonical_digest)


def validate_decision_inputs(
    profile: dict[str, Any],
    results: list[dict[str, Any]],
    decisions: dict[str, Any],
    bundle: dict[str, Any],
) -> list[dict[str, Any]]:
    decisions = require_decisions(decisions)
    policy = require_remedy_policy(profile["remedyProfile"])
    subject = results[0]["subject"]
    expected = {
        "policyDigest": policy["policyDigest"],
        "profileDigest": profile["profileDigest"],
        "responseContractDigest": subject["responseContract"]["contractDigest"],
        "subjectDigest": subject["subjectDigest"],
        "sourceRevision": subject["sourceRevision"],
        "sourceLineageDigest": subject["sourceLineageDigest"],
        "inputResultDigests": sorted(result["resultDigest"] for result in results),
    }
    if any(decisions[key] != item for key, item in expected.items()):
        raise remedy_error("decision input epoch differs from complete result/source/policy set")
    if any(result["subject"] != subject or result["phase"] != results[0]["phase"] for result in results):
        raise remedy_error("mixed source or phase results cannot be synthesized")
    refs = finding_origins(results)
    declared = [ref for item in decisions["decisions"] for ref in item["findingRefs"]]
    if sorted(declared, key=canonical_digest) != refs:
        raise remedy_error("decisions must preserve every exact finding origin once")
    by_digest = {result["resultDigest"]: result for result in results}
    for decision in decisions["decisions"]:
        _validate_choice(decision, by_digest, policy, bundle)
    return refs


def _validate_choice(
    decision: dict[str, Any], results: dict[str, Any], policy: dict[str, Any], bundle: dict[str, Any]
) -> None:
    proposals, proposal_paths = _decision_proposals(decision, results)
    if len(proposals) > policy["maxProposalsPerFinding"]:
        raise remedy_error("decision group exceeds the shared proposal cap")
    selected = decision["selected"]
    if selected is not None and selected not in proposals:
        raise remedy_error("selection does not identify an exact normalized proposal")
    expected_paths = (
        proposal_paths[(selected["resultDigest"], selected["findingId"], selected["proposalId"])]
        if selected is not None
        else []
    )
    if decision["executionPaths"] != expected_paths:
        raise remedy_error("execution scope differs from the selected normalized proposal")
    alternatives = [proposal for proposal in proposals if proposal != selected]
    comparisons = [item["proposalRef"] for item in decision["comparisons"]]
    if sorted(comparisons, key=canonical_digest) != sorted(alternatives, key=canonical_digest):
        raise remedy_error("compare every real unselected alternative exactly once")
    disposition_digest = decision["dispositionDigest"]
    if disposition_digest is not None:
        disposition = evidence_value(bundle, "disposition", disposition_digest)
        if validate_finding_disposition(disposition)["status"] != "PASS":
            raise remedy_error("finding disposition did not validate")
        if any(
            disposition["findingDigest"] != ref["findingDigest"] or disposition["findingId"] != ref["findingId"]
            for ref in decision["findingRefs"]
        ):
            raise remedy_error("disposition does not bind the decision findings")


def remedy_synthesis_section(
    profile: dict[str, Any], results: list[dict[str, Any]], decisions: dict[str, Any], bundle: dict[str, Any]
) -> dict[str, Any]:
    qualified_results(profile, results, bundle)
    originals = _decision_epoch(results, decisions, bundle)
    qualified_results(profile, originals, bundle)
    refs = validate_decision_inputs(profile, originals, decisions, bundle)
    if any(result["subject"] != results[0]["subject"] or result["phase"] != results[0]["phase"] for result in results):
        raise remedy_error("current recheck epoch must have one exact source and phase")
    return {
        "policyDigest": profile["remedyProfile"]["policyDigest"],
        "responseContractDigest": decisions["responseContractDigest"],
        "decisionsDigest": decisions["decisionsDigest"],
        "originFindingRefs": refs,
        "evidenceBundleDigest": bundle["index"]["bundleDigest"],
    }


def _decision_epoch(
    results: list[dict[str, Any]], decisions: dict[str, Any], bundle: dict[str, Any]
) -> list[dict[str, Any]]:
    require_decisions(decisions)
    if sorted(result["resultDigest"] for result in results) == decisions["inputResultDigests"]:
        return results
    rechecks = evidence_values(bundle, "recheck")
    if len(rechecks) != 1 or rechecks[0].get("decisionsDigest") != decisions["decisionsDigest"]:
        raise remedy_error("historical decision epoch requires an explicit repair recheck")
    require_recheck(rechecks[0])
    originals = [evidence_value(bundle, "result", item) for item in decisions["inputResultDigests"]]
    if sorted(rechecks[0]["findingRefs"], key=canonical_digest) != finding_origins(originals):
        raise remedy_error("recheck must retain the complete original finding epoch")
    if not rechecks[0]["findingRefs"]:
        raise remedy_error("no recheck may be invented without findings")
    return originals


def remedy_quorum_inputs(profile: dict[str, Any], synthesis: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    results = [evidence_value(bundle, "result", item) for item in synthesis["resultDigests"]]
    decisions = evidence_value(bundle, "decision", synthesis["remedy"]["decisionsDigest"])
    expected = remedy_synthesis_section(profile, results, decisions, bundle)
    if synthesis["remedy"] != expected or any(result["subject"] != synthesis["subject"] for result in results):
        raise remedy_error("synthesis remedy chain differs")
    roles = sorted({result["reviewer"]["role"] for result in results})
    return {
        "results": results,
        "decisions": decisions,
        "roles": roles,
        "originals": _decision_epoch(results, decisions, bundle),
    }


def required_recheck_roles(
    policy: dict[str, Any], delta: dict[str, Any] | None, *, phase: str
) -> tuple[str, list[str], list[str]]:
    """Consume only a trusted fresh audit delta; do not duplicate its impact algorithm."""
    scopes = policy["roleScopes"]
    all_roles = sorted(scope["role"] for scope in scopes)
    if phase == "final-audit" or delta is None or delta.get("disposition") != "DELTA_REVIEW_AVAILABLE":
        return (
            "FULL_AUDIT_REQUIRED",
            all_roles,
            ["fresh-full-final-audit" if phase == "final-audit" else "impact-unavailable-or-uncertain"],
        )
    if any(scope["modules"] for scope in scopes):
        return "FULL_AUDIT_REQUIRED", all_roles, ["module-role-impact-not-bound"]
    paths = delta.get("attemptDelta", {}).get("changedPaths", [])
    checks = delta.get("validationSelection", {}).get("selectedCheckIds", [])
    roles = set()
    uncovered = set(paths)
    for scope in scopes:
        matched = {
            path
            for path in paths
            if any(path == prefix or path.startswith(prefix.rstrip("/") + "/") for prefix in scope["paths"])
        }
        if matched or set(scope["checkIds"]) & set(checks):
            roles.add(scope["role"])
            uncovered -= matched
    if uncovered or not roles:
        return "FULL_AUDIT_REQUIRED", all_roles, ["impact-has-unmapped-role"]
    return "DELTA_REVIEW_AVAILABLE", sorted(roles), []


def validate_remedy_native_chain(
    profile: dict[str, Any],
    synthesis: dict[str, Any],
    receipt: dict[str, Any],
    bundle: dict[str, Any],
    context: dict[str, Any],
    *,
    trusted_delta: dict[str, Any] | None = None,
) -> None:
    inputs = remedy_quorum_inputs(profile, synthesis, bundle)
    policy = profile["remedyProfile"]
    if receipt["remedy"]["evidenceBundle"] != bundle["reference"]:
        raise remedy_error("quorum evidence reference differs")
    if synthesis["subject"].get("remedyContext") != context:
        raise remedy_error("review does not bind the trusted current native context")
    rechecks = evidence_values(bundle, "recheck")
    mandatory_roles = sorted(scope["role"] for scope in policy["roleScopes"])
    if rechecks:
        mandatory_roles = sorted({role for value in rechecks for role in value["requiredRoles"]})
    if not set(mandatory_roles).issubset(inputs["roles"]):
        raise remedy_error("qualified mandatory reviewer roles are missing")
    if receipt["reviewerCount"] != len(inputs["results"]) or receipt["blockingFindingsUnresolved"]:
        raise remedy_error("quorum count or unresolved findings differ")
    expected = {
        "synthesisDigest": synthesis["synthesisDigest"],
        "policyDigest": policy["policyDigest"],
        "responseContractDigest": synthesis["remedy"]["responseContractDigest"],
        "decisionsDigest": synthesis["remedy"]["decisionsDigest"],
    }
    if any(receipt["remedy"].get(key) != item for key, item in expected.items()):
        raise remedy_error("quorum remedy identity differs")
    if sorted(value["recheckDigest"] for value in rechecks) != receipt["remedy"]["recheckDigests"]:
        raise remedy_error("recheck set differs")
    for recheck in rechecks:
        _validate_current_recheck(recheck, context, inputs, policy, trusted_delta)


def _validate_current_recheck(
    value: dict[str, Any],
    context: dict[str, Any],
    inputs: dict[str, Any],
    policy: dict[str, Any],
    delta: dict[str, Any] | None,
) -> None:
    require_recheck(value)
    if delta is None:
        raise remedy_error(
            "repair lineage needs a freshly recomputed native delta; obtain a full current review instead"
        )
    expected = {
        "runId": context.get("runId"),
        "taskId": context.get("taskId"),
        "currentAttempt": context.get("attempt"),
        "currentSubjectDigest": inputs["results"][0]["subject"]["subjectDigest"],
        "currentSourceRevision": context["sourceRevision"],
        "currentSourceLineageDigest": inputs["results"][0]["subject"]["sourceLineageDigest"],
        "policyDigest": policy["policyDigest"],
        "deltaReceiptDigest": delta["receiptDigest"],
    }
    if any(value[key] != item for key, item in expected.items()):
        raise remedy_error("recheck does not bind the current native attempt")
    _require_repair_epoch(value, context, inputs, delta)
    disposition, roles, _ = required_recheck_roles(policy, delta, phase=context["phase"])
    if value["disposition"] != disposition or value["requiredRoles"] != roles:
        raise remedy_error("recheck cannot narrow the trusted impact role union")
    actual = sorted(result["remedyQualification"]["participationDigest"] for result in inputs["results"])
    if not value["reviewEvidenceDigests"] or value["reviewEvidenceDigests"] != actual:
        raise remedy_error("pending or different review evidence cannot complete recheck")
    if value["selectedCheckIds"] != delta["validationSelection"]["selectedCheckIds"]:
        raise remedy_error("recheck checks differ from fresh native validation selection")
    _require_substitutions(value, inputs)


def _require_repair_epoch(
    value: dict[str, Any], context: dict[str, Any], inputs: dict[str, Any], delta: dict[str, Any]
) -> None:
    originals = inputs["originals"]
    previous = originals[0]["subject"]["remedyContext"]
    expected_previous = {
        **context,
        "attempt": value["previousAttempt"],
        "sourceSnapshotDigest": delta["attemptDelta"]["previousSnapshotHash"],
    }
    if previous != expected_previous or delta["attemptDelta"]["currentSnapshotHash"] != context["sourceSnapshotDigest"]:
        raise remedy_error("original/current native snapshots do not join the repair epochs")
    if value["previousAttempt"] != delta["previousAttempt"] or value["currentAttempt"] != delta["currentAttempt"]:
        raise remedy_error("recheck attempts differ from native history")
    if value["decisionsDigest"] != inputs["decisions"]["decisionsDigest"] or value["findingRefs"] != finding_origins(
        originals
    ):
        raise remedy_error("recheck replaced original decisions or finding origins")
    for field in ("runId", "taskId"):
        if delta[field] != context[field]:
            raise remedy_error("delta is from another native run/task")


def _require_substitutions(value: dict[str, Any], inputs: dict[str, Any]) -> None:
    current = {result["reviewer"]["id"]: result["reviewer"]["role"] for result in inputs["results"]}
    originals = {result["reviewer"]["id"]: result["reviewer"]["role"] for result in inputs["originals"]}
    replacements = value["substitutions"]
    seen = set()
    for item in replacements:
        original, replacement, role = item["originalReviewerId"], item["replacementReviewerId"], item["role"]
        if (
            originals.get(original) != role
            or current.get(replacement) != role
            or original in current
            or original in seen
        ):
            raise remedy_error("substitute reviewer lacks exact original/current qualified role binding")
        seen.add(original)
    missing = {
        reviewer for reviewer, role in originals.items() if role in value["requiredRoles"] and reviewer not in current
    }
    if seen != missing:
        raise remedy_error("every unavailable required reviewer needs one reasoned qualified substitute")


def current_remedy_results(bundle: dict[str, Any], decisions: dict[str, Any]) -> list[dict[str, Any]]:
    results = evidence_values(bundle, "result")
    rechecks = evidence_values(bundle, "recheck")
    if not rechecks:
        if sorted(item["resultDigest"] for item in results) != decisions["inputResultDigests"]:
            raise remedy_error("evidence contains an unrelated or missing result")
        return results
    if len(rechecks) != 1:
        raise remedy_error("one repair epoch requires one bounded recheck")
    expected = rechecks[0]["reviewEvidenceDigests"]
    current = [item for item in results if item.get("remedyQualification", {}).get("participationDigest") in expected]
    actual = sorted(item["remedyQualification"]["participationDigest"] for item in current)
    allowed = set(decisions["inputResultDigests"]) | {item["resultDigest"] for item in current}
    if actual != expected or {item["resultDigest"] for item in results} != allowed:
        raise remedy_error("repair evidence must contain exact separate original/current result sets")
    return current


def _require_terminal_output_binding(
    verdict: dict[str, Any], assignment: dict[str, Any], candidate: dict[str, Any]
) -> None:
    expected = {
        "assignmentDigest": assignment["assignmentDigest"],
        "profileDigest": assignment["profileDigest"],
        "responseContractDigest": assignment["subject"]["responseContract"]["contractDigest"],
        "rawOutputDigest": candidate["import"]["outputDigest"],
        "sanitizedOutputDigest": candidate["import"]["sanitizedOutputDigest"],
        "findingsDigest": canonical_digest(candidate["findings"]),
    }
    if verdict.get("reviewMeshBinding") != expected:
        raise remedy_error("actual terminal verdict must bind raw/sanitized output and normalized finding content")


def _participation_independence(
    independent: dict[str, Any], assignment: dict[str, Any], candidate: dict[str, Any]
) -> None:
    subject = assignment["subject"]
    requirement = assignment.get("independenceRequirement") or build_independence_requirement(
        prohibited_producer_classes=[subject.get("primaryProducerClass", "implementer")]
    )
    checked = validate_independent_evidence(
        independent,
        requirement=requirement,
        expected_source_revision=subject.get("sourceRevision"),
        expected_source_lineage_digest=subject.get("sourceLineageDigest"),
        primary_producer_class=subject.get("primaryProducerClass"),
        primary_implementation_digest=subject.get("primaryImplementationDigest"),
    )
    if checked["status"] != "PASS" or checked.get("independenceStatus") != "REQUIRED_PASS":
        raise remedy_error("required independent evidence did not pass")
    if independent.get("findings") != candidate["findings"]:
        raise remedy_error("independent finding set differs from the normalized review")
    if independent.get("producerIdentityHash") != assignment["reviewer"]["hostIdentityHash"]:
        raise remedy_error("independent producer does not match the reviewer")


def rejected_finding_digests(decisions: dict[str, Any], bundle: dict[str, Any]) -> set[str]:
    rejected: set[str] = set()
    available = {item["reference"]["digest"] for item in bundle["artifacts"]}
    for decision in decisions["decisions"]:
        if decision["dispositionDigest"] is None:
            continue
        disposition = evidence_value(bundle, "disposition", decision["dispositionDigest"])
        if disposition["disposition"] != "REJECTED" or disposition["reasonCode"] != "false-positive":
            continue
        evidence = set(disposition["evidenceDigests"])
        reviews = {ref["reviewEvidenceDigest"] for ref in decision["findingRefs"]}
        if not evidence or not evidence.issubset(available) or not reviews.issubset(evidence):
            raise remedy_error("rejection requires resolved independently qualified review evidence")
        rejected.update(ref["findingDigest"] for ref in decision["findingRefs"])
    return rejected


def _decision_proposals(
    decision: dict[str, Any], results: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[tuple[Any, ...], list[str]]]:
    proposals = []
    paths = {}
    for ref in decision["findingRefs"]:
        finding = next(item for item in results[ref["resultDigest"]]["findings"] if item["id"] == ref["findingId"])
        for proposal in finding["remedy"].get("proposals", []):
            proposals.append(_proposal_reference(ref["resultDigest"], ref["findingId"], proposal))
            paths[(ref["resultDigest"], ref["findingId"], proposal["proposalId"])] = proposal["paths"]
    first_id = sorted(ref["findingId"] for ref in decision["findingRefs"])[0]
    for item in decision["coordinatorProposals"]:
        proposal = item["proposal"]
        proposals.append(_proposal_reference(None, first_id, proposal))
        paths[(None, first_id, proposal["proposalId"])] = proposal["paths"]
    if len(paths) != len(proposals):
        raise remedy_error("proposal references must have unique attributable identities")
    return proposals, paths


def _proposal_reference(result_digest: str | None, finding_id: str, proposal: dict[str, Any]) -> dict[str, Any]:
    return {
        "resultDigest": result_digest,
        "findingId": finding_id,
        "proposalId": proposal["proposalId"],
        "proposalDigest": canonical_digest(proposal),
    }

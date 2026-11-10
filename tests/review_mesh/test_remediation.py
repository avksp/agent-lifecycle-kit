"""UNIT_ONLY typed joins. These fixtures do not prove live reviewer execution."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.external_job_schemas import (
    build_external_job_request,
    build_external_job_result,
    build_external_job_status,
)
from agent_lifecycle.contracts.independent_evidence_schemas import (
    build_independence_requirement,
    build_independent_evidence,
)
from agent_lifecycle.contracts.review_mesh_schemas import build_response_contract
from agent_lifecycle.contracts.review_remedy_schemas import (
    require_decisions,
    require_evidence_index,
    require_finding_remedies,
    require_recheck,
    require_remedy_policy,
)
from agent_lifecycle.contracts.review_round_schemas import build_review_round_participation
from agent_lifecycle.review_mesh.contracts import build_review_mesh_assignment, build_review_mesh_profile
from agent_lifecycle.review_mesh.quorum import build_quorum_from_synthesis
from agent_lifecycle.review_mesh.remediation import (
    finding_origins,
    load_remedy_evidence,
    qualify_remedy_candidate,
    required_recheck_roles,
)
from agent_lifecycle.review_mesh.results import import_review_mesh_result
from agent_lifecycle.review_mesh.synthesis import synthesize_review_mesh_results
from agent_lifecycle.workflow.review_mesh_gate import validate_review_mesh_quorum_gate
from tests.contracts.test_external_job_schemas import session_fixture


def seal(value: dict, field: str) -> dict:
    value[field] = canonical_digest({key: item for key, item in value.items() if key != field})
    return value


def policy(*, mode="required", phases=None, roles=None, cap=3) -> dict:
    return seal(
        {
            "schemaVersion": "agent-review-remedy-policy.v1",
            "mode": mode,
            "phases": phases or ["implementation-audit"],
            "maxProposalsPerFinding": cap,
            "roleScopes": roles or [{"role": "reviewer", "modules": [], "paths": ["src/a.py"], "checkIds": ["AC-1"]}],
        },
        "policyDigest",
    )


def config(selected=None) -> dict:
    selected = selected or policy()
    return {
        "required": True,
        "phases": selected["phases"],
        "remedyProfile": selected,
        "quorumPolicy": {"minReviewers": 1, "requiredRoles": [scope["role"] for scope in selected["roleScopes"]]},
    }


def finding(*, unavailable=False, severity="LOW", count=1) -> dict:
    remedy = {
        "schemaVersion": "agent-finding-remedy.v1",
        "availability": "UNAVAILABLE",
        "reason": "Need a bounded diagnostic.",
    }
    if not unavailable:
        remedy = {
            "schemaVersion": "agent-finding-remedy.v1",
            "availability": "AVAILABLE",
            "proposals": [
                {
                    "proposalId": f"P{number}",
                    "action": "Check the required key before reading it; quoted commands are inert.",
                    "paths": ["src/a.py"],
                    "rationale": "Preserve the required missing-key invariant.",
                    "risks": ["May affect callers."],
                    "checks": [{"checkId": "AC-1", "expectation": "Missing keys produce the documented refusal."}],
                }
                for number in range(1, count + 1)
            ],
        }
    return {
        "id": "F1",
        "severity": severity,
        "status": "open",
        "message": "Missing key is unchecked.",
        "remedy": remedy,
    }


def inputs(findings=None, *, selected=None, reviewer="independent-a", role="reviewer", context=None):
    selected = selected or policy()
    profile = build_review_mesh_profile(
        remedy_profile=selected,
        independence_required=False,
        budget_cap={"maxInvocations": 4, "maxInputTokens": 12000, "maxOutputTokens": 4000, "maxWallSeconds": 180},
    )
    contract = build_response_contract(
        {
            "remedy": {
                "schemaVersion": "agent-review-remedy-extension.v1",
                "policyDigest": selected["policyDigest"],
                "maxProposalsPerFinding": selected["maxProposalsPerFinding"],
            }
        },
        raw_version="reviewer-output.v2",
    )
    context = context or {
        "phase": "implementation-audit",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "1" * 64,
        "planLockDigest": "2" * 64,
        "sourceRevision": "b" * 40,
        "runId": "run",
        "taskId": "T",
        "attempt": 1,
        "sourceSnapshotDigest": "3" * 64,
        "sourceLineageDigest": "5" * 64,
    }
    subject = {
        "subjectDigest": "4" * 64,
        "sourceRevision": "b" * 40,
        "sourceLineageDigest": "5" * 64,
        "primaryProducerClass": "implementer",
        "primaryImplementationDigest": "6" * 64,
        "sessionDigest": "a" * 64,
        "hostIdentityHash": "7" * 64,
        "modelIdentityHash": "8" * 64,
        "reviewMeshRequired": True,
        "reviewMeshBlockingOptIn": True,
        "responseContract": contract,
        "reviewMeshProfile": profile,
        "remedyContext": context,
    }
    requirement = build_independence_requirement(prohibited_producer_classes=["implementer"])
    assignment = build_review_mesh_assignment(
        profile=profile,
        assignment_id="assignment-" + reviewer,
        subject=subject,
        phase="implementation-audit",
        reviewer={
            "id": reviewer,
            "role": role,
            "modelClass": "strong-reasoning",
            "producerClass": "independent-reviewer",
            "hostIdentityHash": canonical_digest(reviewer),
            "modelIdentityHash": "9" * 64,
        },
        blocking=True,
        independence_requirement=requirement,
    )
    receipt, _, proof = session_fixture()
    receipt.update(subjectDigest=canonical_digest(subject), assignmentDigest=assignment["assignmentDigest"])
    seal(receipt, "receiptDigest")
    proof.update(
        subjectDigest=receipt["subjectDigest"],
        assignmentDigest=receipt["assignmentDigest"],
        receiptDigest=receipt["receiptDigest"],
    )
    usage = {key: receipt["usage"][key] for key in ("invocations", "inputTokens", "outputTokens", "wallSeconds")}
    raw_status = (
        "FAIL"
        if any(item["severity"] in {"HIGH", "MEDIUM", "CRITICAL", "BLOCKER"} for item in findings or [])
        else "PASS"
    )
    raw = {
        "schemaVersion": "reviewer-output.v2",
        "status": raw_status,
        "findings": findings or [],
        "budgetUsage": usage,
        "contractDigest": contract["contractDigest"],
        "subjectDigest": subject["subjectDigest"],
        "assignmentDigest": assignment["assignmentDigest"],
    }
    return profile, assignment, raw, {"receipt": receipt, "qualification": proof, "previous": None}


def participation(_profile, assignment, raw, usage_context) -> dict:
    findings = raw["findings"]
    overall = (
        "REWORK"
        if any(item["severity"] in {"HIGH", "MEDIUM", "CRITICAL", "BLOCKER"} for item in findings)
        else "ACCEPTED"
    )
    verdict = {
        "schemaVersion": "agent-review-verdict.v1",
        "overall": overall,
        "dimensions": {
            name: {"status": "PASS", "reasonCode": "checked", "summary": "Independent fixture check."}
            for name in ("requirementFit", "implementationQuality", "evidenceQuality", "residualRisk")
        },
        "routing": {"nextAction": "accept" if overall == "ACCEPTED" else "fix-implementation", "target": None},
    }
    candidate = import_review_mesh_result(profile=_profile, assignment=assignment, reviewer_output=raw)
    verdict["reviewMeshBinding"] = {
        "assignmentDigest": assignment["assignmentDigest"],
        "profileDigest": assignment["profileDigest"],
        "responseContractDigest": assignment["subject"]["responseContract"]["contractDigest"],
        "rawOutputDigest": canonical_digest(raw),
        "sanitizedOutputDigest": candidate["import"]["sanitizedOutputDigest"],
        "findingsDigest": canonical_digest(candidate["findings"]),
    }
    context = assignment["subject"]["remedyContext"]
    request = build_external_job_request(
        job_id="job-" + assignment["reviewer"]["id"],
        attempt=1,
        adapter_id="unit-fixture",
        operation="independent-review",
        execution_kind="PROCESS",
        descriptor_digest=assignment["assignmentDigest"],
        plan_digest=context["planDigest"],
        plan_lock_digest=context["planLockDigest"],
        source_revision=context["sourceRevision"],
        source_snapshot_digest=context["sourceSnapshotDigest"],
        limits={
            "maxWallSeconds": 180,
            "maxAttempts": 2,
            "maxOutputBytes": 65536,
            "maxArtifactBytes": 65536,
            "maxArtifacts": 4,
            "maxCostMicros": 10000,
            "maxReportedTokens": 20000,
            "cancelGraceSeconds": 1,
        },
    )
    job_verdict = "PASS" if overall == "ACCEPTED" else "FAIL"
    observation = {
        "subjectDigest": canonical_digest(assignment["subject"]),
        "assignmentDigest": assignment["assignmentDigest"],
        "requestDigest": request["requestDigest"],
        "attempt": 1,
        "deliveryAttempt": 1,
        "semanticRound": 1,
        "remoteState": "TERMINAL",
        "localState": "COMPLETE",
        "semanticStatus": job_verdict,
        "responseDigest": canonical_digest(verdict),
        "sessionUsage": usage_context["receipt"],
    }
    status = build_external_job_status(
        request=request,
        state="SUCCEEDED",
        sequence=1,
        observed_at="2026-11-10T10:00:00Z",
        started_at="2026-11-10T09:59:00Z",
        ended_at="2026-11-10T10:00:00Z",
        process_cleanup_status="PASS",
        observation=observation,
    )
    result = build_external_job_result(
        result_id="result-" + assignment["reviewer"]["id"],
        request=request,
        status=status,
        verdict=job_verdict,
        complete=True,
        artifacts=[],
        output_digest=canonical_digest(verdict),
        output_bytes=len(canonical_bytes(verdict)),
    )
    joined = build_review_round_participation(
        reviewer_id=assignment["reviewer"]["id"],
        findings=findings,
        review_verdict=verdict,
        job_request=request,
        job_status=status,
        job_result=result,
    )
    independent = build_independent_evidence(
        evidence_id="EV-1",
        criterion_id="AC-1",
        requirement=assignment["independenceRequirement"],
        source_revision=assignment["subject"]["sourceRevision"],
        source_lineage_digest=assignment["subject"]["sourceLineageDigest"],
        method="deterministic-check",
        producer_class="independent-reviewer",
        producer_identity_hash=assignment["reviewer"]["hostIdentityHash"],
        implementation_digest="c" * 64,
        findings=findings,
    )
    return seal(
        {
            "schemaVersion": "agent-review-remedy-participation.v1",
            "assignmentDigest": assignment["assignmentDigest"],
            "rawOutputDigest": canonical_digest(raw),
            "participation": joined,
            "independentEvidence": independent,
            "sessionUsageContext": usage_context,
        },
        "qualificationDigest",
    )


def bundle(values) -> dict:
    field = {
        "assignment": "assignmentDigest",
        "result": "resultDigest",
        "participation": "qualificationDigest",
        "decision": "decisionsDigest",
        "recheck": "recheckDigest",
        "disposition": "dispositionDigest",
    }
    artifacts = []
    for number, (kind, value) in enumerate(values):
        raw = canonical_bytes(value) + b"\n"
        artifacts.append(
            {
                "reference": {
                    "kind": kind,
                    "path": f"evidence/{number}.json",
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "digest": value[field[kind]],
                },
                "value": value,
            }
        )
    artifacts.sort(key=lambda item: (item["reference"]["kind"], item["reference"]["digest"]))
    index = seal(
        {"schemaVersion": "agent-review-remedy-evidence.v1", "artifacts": [item["reference"] for item in artifacts]},
        "bundleDigest",
    )
    return {
        "artifacts": artifacts,
        "index": index,
        "reference": {
            "path": "evidence/index.json",
            "sha256": hashlib.sha256(canonical_bytes(index) + b"\n").hexdigest(),
            "digest": index["bundleDigest"],
        },
    }


def qualified(findings=None, **kwargs):
    profile, assignment, raw, usage = inputs(findings, **kwargs)
    candidate = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
    wrapper = participation(profile, assignment, raw, usage)
    proof = bundle([("assignment", assignment), ("participation", wrapper)])
    result = qualify_remedy_candidate(profile, assignment, candidate, proof)
    return profile, assignment, raw, candidate, wrapper, result


def decisions(profile, results) -> dict:
    subject = results[0]["subject"]
    refs = finding_origins(results)
    choices = []
    for ref in refs:
        item = next(result for result in results if result["resultDigest"] == ref["resultDigest"])
        finding = next(value for value in item["findings"] if value["id"] == ref["findingId"])
        proposals = finding["remedy"].get("proposals", [])
        if not proposals:
            continue
        proposal_refs = [
            {
                "resultDigest": ref["resultDigest"],
                "findingId": ref["findingId"],
                "proposalId": value["proposalId"],
                "proposalDigest": canonical_digest(value),
            }
            for value in proposals
        ]
        choices.append(
            {
                "findingRefs": [ref],
                "coordinatorProposals": [],
                "selected": proposal_refs[0],
                "rationale": "Smallest invariant-preserving repair.",
                "comparisons": [
                    {"proposalRef": value, "reason": "Wider change than needed."} for value in proposal_refs[1:]
                ],
                "executionPaths": proposals[0]["paths"],
                "dispositionDigest": None,
            }
        )
    return seal(
        {
            "schemaVersion": "agent-review-remedy-decisions.v1",
            "policyDigest": profile["remedyProfile"]["policyDigest"],
            "profileDigest": profile["profileDigest"],
            "responseContractDigest": subject["responseContract"]["contractDigest"],
            "subjectDigest": subject["subjectDigest"],
            "sourceRevision": subject["sourceRevision"],
            "sourceLineageDigest": subject["sourceLineageDigest"],
            "inputResultDigests": sorted(item["resultDigest"] for item in results),
            "coordinatorId": "coordinator",
            "decisions": choices,
            "authorityClaimed": False,
            "productionPromotionClaimed": False,
        },
        "decisionsDigest",
    )


def complete_chain(findings=None):
    profile, assignment, _raw, candidate, wrapper, result = qualified(findings)
    decision = decisions(profile, [result])
    proof = bundle([("assignment", assignment), ("participation", wrapper), ("result", result), ("decision", decision)])
    synthesis = synthesize_review_mesh_results(
        profile=profile, results=[result], remedy_decisions=decision, remedy_evidence=proof
    )
    receipt = build_quorum_from_synthesis(
        profile=profile,
        synthesis=synthesis,
        quorum_policy={"minReviewers": 1, "requiredRoles": ["reviewer"]},
        remedy_evidence=proof,
    )
    return profile, assignment, candidate, result, decision, proof, synthesis, receipt


class RemedyContractTests(unittest.TestCase):
    def test_evidence_loader_refuses_nonstring_lock_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for malformed in ([], {}):
                payload = {"schemaVersion": malformed}
                raw = canonical_bytes(payload) + b"\n"
                (root / "lock.json").write_bytes(raw)
                index = seal(
                    {
                        "schemaVersion": "agent-review-remedy-evidence.v1",
                        "artifacts": [
                            {
                                "kind": "lock",
                                "path": "lock.json",
                                "sha256": hashlib.sha256(raw).hexdigest(),
                                "digest": canonical_digest(payload),
                            }
                        ],
                    },
                    "bundleDigest",
                )
                (root / "index.json").write_bytes(canonical_bytes(index) + b"\n")
                with self.assertRaises(LifecycleError) as caught:
                    load_remedy_evidence(root, "index.json")
                self.assertEqual(caught.exception.code, "review-remedy-invalid")

    def test_one_proposal_is_sufficient_and_text_is_inert(self):
        item = finding()
        item["remedy"]["proposals"][0]["action"] = "$(touch forbidden); rm -rf / is quoted untrusted data"
        require_finding_remedies([item], policy(cap=1))
        require_remedy_policy(policy(cap=1))

    def test_shape_caps_paths_ids_and_unknown_fields_refuse(self):
        for mutate in [
            lambda x: x["remedy"].update(extra=True),
            lambda x: x.update(id="bad id"),
            lambda x: x["remedy"]["proposals"][0].update(paths=["../escape"]),
            lambda x: x["remedy"]["proposals"][0].update(action="x" * 2049),
            lambda x: x["remedy"]["proposals"][0].update(checks=[]),
        ]:
            value = finding()
            mutate(value)
            with self.assertRaises(LifecycleError):
                require_finding_remedies([value], policy())
        with self.assertRaises(LifecycleError):
            require_finding_remedies([finding(count=2)], policy(cap=1))
        with self.assertRaises(LifecycleError):
            require_finding_remedies([finding(), finding()], policy())

    def test_raw_candidate_remains_not_proven_and_cannot_synthesize(self):
        profile, assignment, raw, _ = inputs()
        candidate = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
        self.assertFalse(candidate["roundParticipation"]["eligible"])
        with self.assertRaises(LifecycleError):
            synthesize_review_mesh_results(
                profile=profile,
                results=[candidate],
                remedy_decisions=decisions(profile, [candidate]),
                remedy_evidence=bundle([]),
            )

    def test_real_contract_chain_preserves_candidate_and_accepts_empty_findings(self):
        profile, assignment, candidate, result, _, proof, synthesis, receipt = complete_chain()
        self.assertEqual(result["remedyQualification"]["candidate"], candidate)
        self.assertFalse(candidate["roundParticipation"]["eligible"])
        self.assertTrue(result["roundParticipation"]["eligible"])
        self.assertEqual(synthesis["remedy"]["originFindingRefs"], [])
        gate = validate_review_mesh_quorum_gate(
            phase="implementation-audit",
            config=config(profile["remedyProfile"]),
            receipt=receipt,
            trusted_context=assignment["subject"]["remedyContext"],
            remedy_evidence=proof,
        )
        self.assertEqual(gate["status"], "PASS", gate["blockers"])

    def test_choice_never_closes_open_blocking_finding(self):
        _, _, _, _, _, _, synthesis, receipt = complete_chain([finding(severity="HIGH")])
        self.assertTrue(synthesis["unresolvedFindings"])
        self.assertEqual(receipt["status"], "FAIL")

    def test_frozen_additional_role_needs_actual_qualified_reviewer(self):
        profile, assignment, _, result, _, proof, _, receipt = complete_chain()
        frozen = config(profile["remedyProfile"])
        frozen["quorumPolicy"]["requiredRoles"] = ["quality", "reviewer"]
        gate = validate_review_mesh_quorum_gate(
            phase="implementation-audit",
            config=frozen,
            receipt=receipt,
            trusted_context=assignment["subject"]["remedyContext"],
            remedy_evidence=proof,
        )
        self.assertEqual(gate["status"], "FAIL", gate)
        self.assertTrue(any("frozen required roles" in item.get("message", "") for item in gate["blockers"]))

        _, second, _, _, wrapper, second_result = qualified(reviewer="independent-quality", role="quality")
        values = [(item["reference"]["kind"], item["value"]) for item in proof["artifacts"]]
        results = [result, second_result]
        decision = decisions(profile, results)
        values = [(kind, value) for kind, value in values if kind != "decision"]
        values.extend(
            [("assignment", second), ("participation", wrapper), ("result", second_result), ("decision", decision)]
        )
        complete = bundle(values)
        synthesis = synthesize_review_mesh_results(
            profile=profile, results=results, remedy_decisions=decision, remedy_evidence=complete
        )
        quorum = build_quorum_from_synthesis(
            profile=profile,
            synthesis=synthesis,
            quorum_policy={"minReviewers": 1, "requiredRoles": ["reviewer"]},
            remedy_evidence=complete,
        )
        gate = validate_review_mesh_quorum_gate(
            phase="implementation-audit",
            config=frozen,
            receipt=quorum,
            trusted_context=assignment["subject"]["remedyContext"],
            remedy_evidence=complete,
        )
        self.assertEqual(gate["status"], "PASS", gate)

    def test_unknown_choice_missing_comparison_and_stale_source_refuse(self):
        profile, assignment, _raw, _candidate, wrapper, result = qualified([finding(count=2)])
        good = decisions(profile, [result])
        for mutate in [
            lambda x: x["decisions"][0]["selected"].update(proposalId="unknown"),
            lambda x: x["decisions"][0].update(comparisons=[]),
            lambda x: x.update(sourceRevision="c" * 40),
            lambda x: x.update(inputResultDigests=["f" * 64]),
        ]:
            value = deepcopy(good)
            mutate(value)
            seal(value, "decisionsDigest")
            proof = bundle([("assignment", assignment), ("participation", wrapper)])
            with self.assertRaises(LifecycleError):
                synthesize_review_mesh_results(
                    profile=profile, results=[result], remedy_decisions=value, remedy_evidence=proof
                )

    def test_qualification_rejects_wrong_terminal_producer_or_usage(self):
        profile, assignment, _raw, candidate, wrapper, _ = qualified()
        for mutate in [
            lambda x: x.update(rawOutputDigest="0" * 64),
            lambda x: x["independentEvidence"].update(producerClass="implementer"),
            lambda x: x["sessionUsageContext"]["qualification"].update(provenanceValidated=False),
            lambda x: x["participation"].update(participating=False),
        ]:
            value = deepcopy(wrapper)
            mutate(value)
            seal(value, "qualificationDigest")
            with self.assertRaises(LifecycleError):
                qualify_remedy_candidate(profile, assignment, candidate, bundle([("participation", value)]))

    def test_stale_native_context_and_legacy_quorum_are_rejected(self):
        profile, assignment, _, _, _, proof, _, receipt = complete_chain()
        for context in [
            None,
            {**assignment["subject"]["remedyContext"], "attempt": 2},
            {**assignment["subject"]["remedyContext"], "sourceSnapshotDigest": "f" * 64},
        ]:
            gate = validate_review_mesh_quorum_gate(
                phase="implementation-audit",
                config=config(profile["remedyProfile"]),
                receipt=receipt,
                trusted_context=context,
                remedy_evidence=proof,
            )
            self.assertEqual(gate["status"], "FAIL")
        legacy = deepcopy(receipt)
        legacy["schemaVersion"] = "agent-review-mesh-quorum-receipt.v1"
        legacy.pop("remedy")
        seal(legacy, "receiptDigest")
        self.assertEqual(
            validate_review_mesh_quorum_gate(phase="implementation-audit", config=config(), receipt=legacy)["status"],
            "FAIL",
        )

    def test_evidence_loader_rejects_tamper_wrong_kind_and_symlink(self):
        _, assignment, _, _, wrapper, result = qualified()
        proof = bundle([("assignment", assignment), ("participation", wrapper), ("result", result)])
        for malformed in ([], {}):
            with self.assertRaises(LifecycleError) as caught:
                require_remedy_policy(policy(mode=malformed))
            self.assertEqual(caught.exception.code, "review-remedy-invalid")
            index = deepcopy(proof["index"])
            index["artifacts"][0]["kind"] = malformed
            seal(index, "bundleDigest")
            with self.assertRaises(LifecycleError) as caught:
                require_evidence_index(index)
            self.assertEqual(caught.exception.code, "review-remedy-invalid")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "evidence").mkdir()
            for item in proof["artifacts"]:
                (root / item["reference"]["path"]).write_bytes(canonical_bytes(item["value"]) + b"\n")
            index = root / proof["reference"]["path"]
            index.write_bytes(canonical_bytes(proof["index"]) + b"\n")
            self.assertEqual(load_remedy_evidence(root, "evidence/index.json")["index"], proof["index"])
            target = root / proof["artifacts"][0]["reference"]["path"]
            original = target.read_bytes()
            target.write_bytes(b"{}")
            with self.assertRaises(LifecycleError):
                load_remedy_evidence(root, "evidence/index.json")
            target.unlink()
            elsewhere = root / "outside.json"
            elsewhere.write_bytes(original)
            target.symlink_to(elsewhere)
            with self.assertRaises(LifecycleError):
                load_remedy_evidence(root, "evidence/index.json")

    def test_missing_or_final_delta_forces_full_role_union(self):
        roles = [
            {"role": "a", "modules": [], "paths": ["src/a.py"], "checkIds": ["AC-1"]},
            {"role": "b", "modules": [], "paths": ["src/b.py"], "checkIds": ["AC-2"]},
        ]
        selected = policy(roles=roles)
        delta = {
            "disposition": "DELTA_REVIEW_AVAILABLE",
            "attemptDelta": {"changedPaths": ["src/a.py"]},
            "validationSelection": {"selectedCheckIds": ["AC-1"]},
        }
        self.assertEqual(
            required_recheck_roles(selected, delta, phase="implementation-audit")[:2], ("DELTA_REVIEW_AVAILABLE", ["a"])
        )
        delta["attemptDelta"]["changedPaths"].append("src/b.py")
        self.assertEqual(required_recheck_roles(selected, delta, phase="implementation-audit")[1], ["a", "b"])
        for missing, phase in [(None, "implementation-audit"), (delta, "final-audit")]:
            self.assertEqual(
                required_recheck_roles(selected, missing, phase=phase)[:2], ("FULL_AUDIT_REQUIRED", ["a", "b"])
            )

    def test_decisions_cannot_claim_execution_or_promotion(self):
        profile, _, _, _, _, result = qualified()
        value = decisions(profile, [result])
        value["authorityClaimed"] = True
        seal(value, "decisionsDigest")
        with self.assertRaises(LifecycleError):
            require_decisions(value)


class TrustedDeltaCompositionTests(unittest.TestCase):
    def context(self, *, repair=True, callback=None, selected_config=None, receipt=None):
        from unittest.mock import patch

        from agent_lifecycle.audit.implementation import _remedy_audit_context

        manifest = {"package": {"planArtifactRoot": "plans"}}
        values = [manifest, {}, {"remedy": {"evidenceBundle": {"path": "proof/index.json"}}}]
        if receipt is not None:
            values[-1] = receipt
        proof = {
            "artifacts": [
                {"reference": {"kind": kind, "path": path}, "value": {}}
                for kind, path in [
                    ("dependency", "proof/dependencies.json"),
                    ("validation-selection", "proof/selection.json"),
                    ("finding-binding", "proof/binding.json"),
                    ("finding-evidence", "proof/evidence.json"),
                ]
            ]
        }
        with (
            patch("agent_lifecycle.audit.implementation.read_json_object", side_effect=values),
            patch("agent_lifecycle.audit.implementation.native_remedy_context", return_value={"runId": "run"}),
            patch("agent_lifecycle.audit.implementation.load_remedy_evidence", return_value=proof),
            patch("agent_lifecycle.audit.implementation.evidence_values", return_value=[{}] if repair else []),
        ):
            return _remedy_audit_context(
                Path("/owned"),
                Path("/owned/state.json"),
                {"manifestPath": "plans/manifest.json"},
                {"id": "T"},
                config() if selected_config is None else selected_config,
                "proof/quorum.json",
                callback,
            )

    def test_repair_invokes_trusted_callable_with_current_native_inputs(self):
        from unittest.mock import Mock

        builder = Mock(return_value={"receiptDigest": "a" * 64})
        context, delta = self.context(callback=builder)
        self.assertEqual(context, {"runId": "run"})
        self.assertEqual(delta, {"receiptDigest": "a" * 64})
        builder.assert_called_once_with(
            manifest_path=Path("/owned/plans/manifest.json"),
            lock_path=Path("/owned/plans/plan.lock.json"),
            state_path=Path("/owned/state.json"),
            task_id="T",
            dependency_report_path=Path("/owned/proof/dependencies.json"),
            validation_selection_path=Path("/owned/proof/selection.json"),
            finding_check_binding_paths=[Path("/owned/proof/binding.json")],
            finding_check_evidence_paths=[Path("/owned/proof/evidence.json")],
        )

    def test_missing_callback_and_json_callback_claim_refuse_repair(self):
        for builder in (None, {"module": "hostile", "function": "pretend_delta"}):
            with self.assertRaises(LifecycleError):
                self.context(callback=builder)

    def test_malformed_quorum_sections_use_typed_refusal(self):
        for receipt in [
            {"remedy": "invalid"},
            {"remedy": None},
            {"remedy": {"evidenceBundle": []}},
            {"remedy": {"evidenceBundle": 3}},
        ]:
            with self.assertRaises(LifecycleError) as caught:
                self.context(receipt=receipt)
            self.assertEqual(caught.exception.code, "review-remedy-invalid")

    def test_off_and_fresh_full_paths_do_not_invoke_delta(self):
        from unittest.mock import Mock

        builder = Mock(side_effect=AssertionError("must not run"))
        self.assertEqual(self.context(callback=builder, selected_config={}), (None, None))
        self.assertEqual(self.context(callback=builder, repair=False), ({"runId": "run"}, None))
        builder.assert_not_called()


class ExtendedRemedyRegressionTests(unittest.TestCase):
    def evidence(self, assignment, wrapper, result, decision, extra=()):
        return bundle(
            [("assignment", assignment), ("participation", wrapper), ("result", result), ("decision", decision), *extra]
        )

    def test_unavailable_is_retained_as_unresolved_with_existing_disposition(self):
        from agent_lifecycle.contracts.review_round_schemas import build_finding_disposition

        profile, assignment, _, _, wrapper, result = qualified([finding(unavailable=True)])
        disposition = build_finding_disposition(
            finding=result["findings"][0],
            disposition="CONFIRMED",
            reason_code="diagnostic-needed",
            evidence_digests=[wrapper["qualificationDigest"]],
            operation_id="confirm-unavailable",
        )
        decision = decisions(profile, [result])
        decision["decisions"] = [
            {
                "findingRefs": finding_origins([result]),
                "coordinatorProposals": [],
                "selected": None,
                "rationale": "No safe repair has yet been established.",
                "comparisons": [],
                "executionPaths": [],
                "dispositionDigest": disposition["dispositionDigest"],
            }
        ]
        seal(decision, "decisionsDigest")
        proof = self.evidence(assignment, wrapper, result, decision, [("disposition", disposition)])
        synthesis = synthesize_review_mesh_results(
            profile=profile, results=[result], remedy_decisions=decision, remedy_evidence=proof
        )
        self.assertEqual(synthesis["unresolvedFindings"], result["findings"])

    def test_coordinator_alternative_is_optional_but_exact_and_bounded(self):
        profile, assignment, _, _, wrapper, result = qualified([finding()])
        decision = decisions(profile, [result])
        choice = decision["decisions"][0]
        original = choice["selected"]
        proposal = deepcopy(result["findings"][0]["remedy"]["proposals"][0])
        proposal.update(proposalId="COORD", action="Use the same invariant at the smallest caller.")
        choice["coordinatorProposals"] = [{"proposal": proposal, "findingRefs": choice["findingRefs"]}]
        choice["selected"] = {
            "resultDigest": None,
            "findingId": "F1",
            "proposalId": "COORD",
            "proposalDigest": canonical_digest(proposal),
        }
        choice["comparisons"] = [{"proposalRef": original, "reason": "Caller change has a smaller public surface."}]
        seal(decision, "decisionsDigest")
        proof = self.evidence(assignment, wrapper, result, decision)
        self.assertEqual(
            synthesize_review_mesh_results(
                profile=profile, results=[result], remedy_decisions=decision, remedy_evidence=proof
            )["status"],
            "PASS",
        )
        choice["executionPaths"] = ["src/unrelated.py"]
        seal(decision, "decisionsDigest")
        with self.assertRaises(LifecycleError):
            synthesize_review_mesh_results(
                profile=profile, results=[result], remedy_decisions=decision, remedy_evidence=proof
            )

    def test_duplicate_finding_ids_keep_each_independent_origin(self):
        first = qualified([finding()], reviewer="one")
        second = qualified([finding()], reviewer="two")
        profile = first[0]
        results = [first[5], second[5]]
        decision = decisions(profile, results)
        proof = bundle(
            [
                ("assignment", first[1]),
                ("participation", first[4]),
                ("result", first[5]),
                ("assignment", second[1]),
                ("participation", second[4]),
                ("result", second[5]),
                ("decision", decision),
            ]
        )
        synthesis = synthesize_review_mesh_results(
            profile=profile, results=results, remedy_decisions=decision, remedy_evidence=proof
        )
        self.assertEqual(len(synthesis["remedy"]["originFindingRefs"]), 2)
        self.assertNotEqual(
            synthesis["remedy"]["originFindingRefs"][0]["resultDigest"],
            synthesis["remedy"]["originFindingRefs"][1]["resultDigest"],
        )

    def test_redaction_cannot_change_bound_ids_and_unrelated_terminal_output_refuses(self):
        item = finding()
        item["id"] = "".join(("s", "k", "-")) + "".join(chr(value) for value in range(97, 119))
        profile, assignment, raw, _ = inputs([item])
        with self.assertRaises(LifecycleError):
            import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
        profile, assignment, _, candidate, wrapper, _ = qualified()
        # Directly remove the complete collector binding. The terminal and wrapper hashes alone cannot qualify it.
        wrapper["participation"]["reviewVerdict"].pop("reviewMeshBinding")
        from agent_lifecycle.review_mesh.remediation import _require_terminal_output_binding

        with self.assertRaises(LifecycleError):
            _require_terminal_output_binding(wrapper["participation"]["reviewVerdict"], assignment, candidate)

    def test_source_lineage_and_phase_cannot_differ_from_prepared_contract(self):
        profile, assignment, _, _ = inputs()
        for field, value in [("sourceLineageDigest", "e" * 64), ("sourceRevision", "c" * 40)]:
            subject = deepcopy(assignment["subject"])
            subject[field] = value
            with self.assertRaises(LifecycleError):
                build_review_mesh_assignment(
                    profile=profile,
                    assignment_id="bad",
                    subject=subject,
                    reviewer=assignment["reviewer"],
                    phase="implementation-audit",
                    blocking=True,
                )
        with self.assertRaises(LifecycleError):
            build_review_mesh_assignment(
                profile=profile,
                assignment_id="bad",
                subject=assignment["subject"],
                reviewer=assignment["reviewer"],
                phase="final-audit",
                blocking=True,
            )

    def test_recheck_binds_separate_native_epochs_and_rejects_missing_or_stale_delta(self):
        from agent_lifecycle.review_mesh.remediation import validate_remedy_native_chain

        original = qualified([finding()])
        profile, original_assignment, _, _, original_wrapper, original_result = original
        decision = decisions(profile, [original_result])
        context = {**original_assignment["subject"]["remedyContext"], "attempt": 2, "sourceSnapshotDigest": "f" * 64}
        current = qualified(context=context)
        assignment, wrapper, result = current[1], current[4], current[5]
        delta = {
            "receiptDigest": "d" * 64,
            "disposition": "DELTA_REVIEW_AVAILABLE",
            "runId": "run",
            "taskId": "T",
            "previousAttempt": 1,
            "currentAttempt": 2,
            "attemptDelta": {
                "previousSnapshotHash": "3" * 64,
                "currentSnapshotHash": "f" * 64,
                "changedPaths": ["src/a.py"],
            },
            "validationSelection": {"selectedCheckIds": ["AC-1"]},
        }
        recheck = seal(
            {
                "schemaVersion": "agent-review-remedy-recheck.v1",
                "policyDigest": profile["remedyProfile"]["policyDigest"],
                "decisionsDigest": decision["decisionsDigest"],
                "findingRefs": finding_origins([original_result]),
                "runId": "run",
                "taskId": "T",
                "previousAttempt": 1,
                "currentAttempt": 2,
                "currentSubjectDigest": result["subject"]["subjectDigest"],
                "currentSourceRevision": "b" * 40,
                "currentSourceLineageDigest": "5" * 64,
                "deltaReceiptDigest": delta["receiptDigest"],
                "disposition": "DELTA_REVIEW_AVAILABLE",
                "requiredRoles": ["reviewer"],
                "selectedCheckIds": ["AC-1"],
                "reviewEvidenceDigests": [wrapper["qualificationDigest"]],
                "substitutions": [],
                "reasons": [],
                "authorityClaimed": False,
                "productionPromotionClaimed": False,
            },
            "recheckDigest",
        )
        for malformed in ([], {}):
            invalid = deepcopy(recheck)
            invalid["disposition"] = malformed
            seal(invalid, "recheckDigest")
            with self.assertRaises(LifecycleError) as caught:
                require_recheck(invalid)
            self.assertEqual(caught.exception.code, "review-remedy-invalid")
        proof = bundle(
            [
                ("assignment", original_assignment),
                ("participation", original_wrapper),
                ("result", original_result),
                ("assignment", assignment),
                ("participation", wrapper),
                ("result", result),
                ("decision", decision),
                ("recheck", recheck),
            ]
        )
        synthesis = synthesize_review_mesh_results(
            profile=profile, results=[result], remedy_decisions=decision, remedy_evidence=proof
        )
        receipt = build_quorum_from_synthesis(
            profile=profile,
            synthesis=synthesis,
            quorum_policy={"minReviewers": 1, "requiredRoles": ["reviewer"]},
            remedy_evidence=proof,
        )
        validate_remedy_native_chain(profile, synthesis, receipt, proof, context, trusted_delta=delta)
        for invalid in [None, {**delta, "receiptDigest": "0" * 64}, {**delta, "previousAttempt": 0}]:
            with self.assertRaises(LifecycleError):
                validate_remedy_native_chain(profile, synthesis, receipt, proof, context, trusted_delta=invalid)

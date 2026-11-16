from __future__ import annotations

from copy import deepcopy
import unittest

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.review_mesh.contracts import (
    build_review_mesh_assignment,
    build_review_mesh_profile,
    validate_review_mesh_result,
)
from agent_lifecycle.review_mesh.remediation import qualified_results
from agent_lifecycle.review_mesh.results import import_review_mesh_result
from agent_lifecycle.workflow.review_mesh_gate import validate_review_mesh_quorum_gate
from tests.review_mesh.test_remediation import bundle, complete_chain, config, finding, qualified, seal
from tests.review_mesh.test_result_import import _profile_and_assignment, _raw_output


class ImportedIndependenceQualificationTests(unittest.TestCase):
    def test_standalone_qualification_presence_never_proves_import_independence(self):
        profile, _, _, _, _, result = qualified()
        for name, proof in (("absent", None), ("null", None), ("empty", {}), ("forged", {"claim": True})):
            with self.subTest(qualification=name):
                candidate = deepcopy(result)
                candidate["independence"]["status"] = "INDEPENDENT"
                candidate["crossCheckReceipt"]["independence"]["status"] = "INDEPENDENT"
                seal(candidate["crossCheckReceipt"], "receiptDigest")
                candidate.pop("remedyQualification")
                if name != "absent":
                    candidate["remedyQualification"] = proof
                seal(candidate, "resultDigest")
                check = validate_review_mesh_result(candidate, profile=profile)
                self.assertEqual(check["status"], "FAIL")
                self.assertIn(
                    "review-mesh-result-import-independence-not-proven",
                    {item["code"] for item in check["blockers"]},
                )

    def test_raw_legacy_ignores_qualification_and_v2_refuses_unknown_extension(self):
        profile = build_review_mesh_profile(independence_required=True)
        assignment = build_review_mesh_assignment(
            profile=profile,
            assignment_id="RM-import-qualification",
            subject={
                "taskId": "TASK-1",
                "reviewMeshBlockingOptIn": True,
                "hostIdentityHash": "a" * 64,
                "modelIdentityHash": "b" * 64,
            },
            reviewer={
                "role": "reviewer",
                "modelClass": "strong-reasoning",
                "hostIdentityHash": "c" * 64,
                "modelIdentityHash": "d" * 64,
            },
            blocking=True,
        )
        raw = _raw_output()
        raw["remedyQualification"] = {"participationDigest": "f" * 64}
        before = deepcopy(raw)
        imported = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
        self.assertEqual(imported["independence"]["status"], "NOT_PROVEN")
        self.assertNotIn("remedyQualification", imported)
        self.assertEqual(raw, before)
        profile, assignment, raw, _, _, _ = qualified()
        raw["remedyQualification"] = {}
        with self.assertRaises(LifecycleError):
            import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)

    def test_legacy_result_refuses_qualification_extension(self):
        profile, assignment = _profile_and_assignment()
        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=_raw_output())
        result["remedyQualification"] = {}
        seal(result, "resultDigest")
        check = validate_review_mesh_result(result, profile=profile)
        self.assertIn("review-remedy-version-mismatch", {item["code"] for item in check["blockers"]})

    def test_exact_v2_reconstruction_accepts_and_tampered_bindings_refuse(self):
        profile, _, _, result, _, proof, _, _ = complete_chain()
        before = deepcopy(proof)
        self.assertEqual(qualified_results(profile, [result], proof), [result])
        edits = [
            ("assignment", lambda value: value.update(assignmentId="other")),
            ("raw", lambda value: value["import"].update(outputDigest="0" * 64)),
            ("sanitized", lambda value: value["import"].update(sanitizedOutputDigest="0" * 64)),
            ("findings", lambda value: value.update(findings=[finding()])),
            ("producer", lambda value: value["reviewer"].update(hostIdentityHash="0" * 64)),
            ("session", lambda value: value["subject"].update(sessionDigest="0" * 64)),
            ("participation", lambda value: value["roundParticipation"].update(eligible=False)),
        ]
        for name, change in edits:
            with self.subTest(binding=name):
                tampered = deepcopy(result)
                change(tampered)
                seal(tampered, "resultDigest")
                with self.assertRaises(LifecycleError):
                    qualified_results(profile, [tampered], proof)
        self.assertEqual(proof, before)

    def test_required_native_gate_refusal_preserves_authority_and_usage_objects(self):
        profile, assignment, _, result, decision, original_proof, _, receipt = complete_chain()
        tampered = deepcopy(result)
        tampered["import"]["sanitizedOutputDigest"] = "0" * 64
        seal(tampered, "resultDigest")
        # The original exact wrapper remains bound to the original result.
        wrapper = next(item["value"] for item in original_proof["artifacts"] if "qualificationDigest" in item["value"])
        proof = bundle(
            [
                ("assignment", assignment),
                ("participation", wrapper),
                ("result", tampered),
                ("decision", decision),
            ]
        )
        context = deepcopy(assignment["subject"]["remedyContext"])
        objects = [profile, assignment, receipt, context, proof, original_proof]
        before = canonical_digest(objects)
        gate = validate_review_mesh_quorum_gate(
            phase="implementation-audit",
            config=config(profile["remedyProfile"]),
            receipt=receipt,
            trusted_context=context,
            remedy_evidence=proof,
        )
        self.assertEqual(gate["status"], "FAIL")
        self.assertEqual(canonical_digest(objects), before)
        self.assertEqual(result["budgetUsage"], tampered["budgetUsage"])


if __name__ == "__main__":
    unittest.main()

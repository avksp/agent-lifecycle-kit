from __future__ import annotations

import hashlib
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import jsonschema

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.review_mesh_schemas import build_response_contract, require_response_contract
from agent_lifecycle.contracts.schemas import get_schema, list_schemas
from agent_lifecycle.review_mesh.results import import_review_mesh_result


class ReviewMeshSchemaTests(unittest.TestCase):
    def test_generated_raw_contract_and_collector_agree_on_typed_coverage(self):
        from tests.review_mesh.test_operator_templates import _handoff_fixture, _prepare_handoff

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, inventory = _handoff_fixture(root)
            prepared = _prepare_handoff(root, manifest, inventory)
            packet = prepared["assignmentPackets"][0]
            response_format = packet["reviewerTask"]["responseFormat"]
            contract, valid = response_format["contract"], response_format["example"]
            jsonschema.Draft202012Validator.check_schema(contract["schema"])
            jsonschema.validate(valid, contract["schema"])
            mutations = [
                {"coverage": "all"},
                {"coverage": []},
                {"coverage": [7]},
                {"coverage": valid["coverage"] + [valid["coverage"][0]]},
                {"coverage": valid["coverage"] + ["extra.py"]},
                {"schemaVersion": "reviewer-output.v2"},
                {"contractDigest": "bad"},
                {"subjectDigest": False},
                {"assignmentDigest": None},
                {"findings": "none"},
            ]
            cases = [{**deepcopy(valid), **mutation} for mutation in mutations]
            missing = deepcopy(valid)
            del missing["coverage"]
            cases.append(missing)
            for raw in cases:
                with self.subTest(raw=raw):
                    with self.assertRaises(jsonschema.ValidationError):
                        jsonschema.validate(raw, contract["schema"])
                    with self.assertRaises(LifecycleError):
                        import_review_mesh_result(
                            profile=prepared["profile"], assignment=packet["assignment"], reviewer_output=raw
                        )
            failed = {**valid, "status": "FAIL", "findings": [{"id": "F-1", "severity": "HIGH", "status": "open"}]}
            result = import_review_mesh_result(
                profile=prepared["profile"], assignment=packet["assignment"], reviewer_output=failed
            )
            self.assertEqual(result["findings"][0]["id"], "F-1")
            self.assertEqual(result["status"], "FAIL")
            self.assertNotEqual(result["schemaVersion"], valid["schemaVersion"])
            self.assertTrue(all(value is None for value in result["budgetUsage"].values()))

    def test_unsupported_extensions_and_requested_contract_drift_refuse(self):
        for extension in [
            {"x": {}},
            {"coverage": {"type": "string", "paths": []}},
            {"coverage": {"type": "array", "paths": ["x", "x"]}},
            {"coverage": {"type": "array", "paths": ["x"], "enum": ["x"]}},
        ]:
            with self.subTest(extension=extension), self.assertRaises(LifecycleError):
                build_response_contract(extension)
        valid = build_response_contract({"coverage": {"type": "array", "paths": ["x"]}})
        self.assertEqual(require_response_contract(valid), valid)
        for mutation in [{"contractDigest": "f" * 64}, {"rawSchemaVersion": "unknown"}, {"extra": True}]:
            with self.subTest(mutation=mutation), self.assertRaises(LifecycleError):
                require_response_contract({**valid, **mutation})

    def test_core_plan_review_schema_negative_fixtures_match_real_freeze_consumer(self):
        from agent_lifecycle.freeze.package_integrity import build_reviewed_plan_lock_v2
        from tests.freeze.test_plan_package_integrity import _fixture_payload, _temporary_fixture

        schema = get_schema("agent-plan-review.v1")
        with _temporary_fixture() as (root, package):
            manifest, _ = _fixture_payload(root=root, package=package)
            relative = (package / "review.json").relative_to(root).as_posix()
            manifest["planFiles"].append(relative)
            manifest["planReview"] = {
                "required": True,
                "report": relative,
                "reviewedRevision": manifest["planRevision"],
                "verdict": "READY_TO_FREEZE",
            }
            (package / "plan.manifest.json").write_bytes(canonical_bytes(manifest) + b"\n")
            valid = {
                "schemaVersion": "agent-plan-review.v1",
                "reviewId": "review",
                "packageId": manifest["package"]["id"],
                "planRevision": manifest["planRevision"],
                "reviewedPlanHash": canonical_digest(manifest),
                "fullReview": True,
                "verdict": "READY_TO_FREEZE",
                "findings": [],
                "reviewer": {"id": "reviewer", "runId": "separate-run", "surface": "fixture", "independent": True},
            }
            mutations = [
                {"schemaVersion": "unknown"},
                {"fullReview": False},
                {"verdict": "CHANGES_REQUIRED"},
                {"reviewedPlanHash": "bad"},
                {"reviewId": ""},
                {"reviewer": {}},
            ]
            for value in [valid, *[{**valid, **mutation} for mutation in mutations]]:
                raw = canonical_bytes(value) + b"\n"
                (root / relative).write_bytes(raw)

                def consume(value=value, raw=raw):
                    return build_reviewed_plan_lock_v2(
                        manifest,
                        value,
                        review_path=relative,
                        review_sha256=hashlib.sha256(raw).hexdigest(),
                        repository_root=root,
                    )

                if value == valid:
                    jsonschema.validate(value, schema)
                    self.assertEqual(consume()["schemaVersion"], "agent-plan-lock.v2")
                else:
                    with self.assertRaises(jsonschema.ValidationError):
                        jsonschema.validate(value, schema)
                    with self.assertRaises(LifecycleError):
                        consume()

    def test_review_mesh_schemas_are_registered(self) -> None:
        schema_ids = {item["id"] for item in list_schemas()["schemas"]}

        for schema_id in (
            "agent-review-mesh-profile.v1",
            "agent-review-mesh-assignment.v1",
            "agent-review-mesh-result.v1",
            "agent-review-mesh-synthesis.v1",
            "agent-review-mesh-quorum-receipt.v1",
            "agent-review-mesh-quorum-validation.v1",
        ):
            with self.subTest(schema_id=schema_id):
                self.assertIn(schema_id, schema_ids)

    def test_profile_schema_is_optional_and_resource_budgeted(self) -> None:
        schema = get_schema("agent-review-mesh-profile.v1")

        self.assertEqual(schema["properties"]["enabledByDefault"], {"const": False})
        self.assertEqual(schema["properties"]["activationMode"], {"const": "opt-in"})
        self.assertEqual(schema["properties"]["budgetUnits"], {"const": "tokens-and-resources"})
        self.assertEqual(schema["properties"]["concreteProviderModelNamesInPortableContract"], {"const": False})
        self.assertEqual(schema["properties"]["productionPromotionClaimed"], {"const": False})
        self.assertIn("crossCheckProfile", schema["required"])

    def test_assignment_schema_uses_canonical_mode_enum(self) -> None:
        schema = get_schema("agent-review-mesh-assignment.v1")
        mode_enum = set(schema["properties"]["mode"]["enum"])

        self.assertEqual(
            mode_enum,
            {
                "leader-draft-multi-review",
                "parallel-research-synthesis",
                "implementation-audit-panel",
            },
        )

    def test_quorum_validation_schema_is_public(self) -> None:
        schema = get_schema("agent-review-mesh-quorum-validation.v1")

        self.assertIn("quorumSatisfied", schema["required"])
        self.assertEqual(schema["properties"]["status"], {"enum": ["PASS", "FAIL"]})


if __name__ == "__main__":
    unittest.main()

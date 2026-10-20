from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, canonical_bytes
from agent_lifecycle.contracts.review_mesh_schemas import build_response_contract
from agent_lifecycle.review_mesh.assignments import source_from_manifest
from agent_lifecycle.review_mesh.operator_templates import (
    REVIEW_MESH_OPERATOR_TEMPLATE_IDS,
    get_review_mesh_operator_template,
    iter_reading_ranges,
    list_review_mesh_operator_templates,
    parse_reviewer_spec,
    prepare_review_mesh_operator_packets,
    validate_review_mesh_operator_template,
)
from agent_lifecycle.review_mesh.results import import_review_mesh_result


class ReviewMeshOperatorTemplateTests(unittest.TestCase):
    def test_index_round_trip_preserves_long_json_and_relocates_without_source_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            manifest, inventory = _handoff_fixture(root)
            receipt = _prepare_handoff(root, manifest, inventory)
            index = json.loads((root / "prepared/reading-index.json").read_bytes())
            chunks = list(iter_reading_ranges(root, index))
            rebuilt = {}
            for identity, _offset, content in chunks:
                self.assertLessEqual(len(content), 8192)
                rebuilt[identity] = rebuilt.get(identity, b"") + content
            for item in inventory["inputs"]:
                self.assertEqual(rebuilt[item["id"]], (root / item["path"]).read_bytes())
            self.assertGreater(len([item for item in chunks if item[0] == "EV-01"]), 1)
            self.assertNotIn("long-input-" * 100, json.dumps(receipt))
            self.assertFalse(index["remoteDeliveryObserved"])
            self.assertFalse(index["authorityClaimed"])
            relocated = Path(tmp) / "relocated"
            shutil.copytree(root, relocated)
            self.assertEqual(list(iter_reading_ranges(relocated, index)), chunks)
            (relocated / "evidence.json").write_text("stale", encoding="utf-8")
            with self.assertRaises(LifecycleError):
                list(iter_reading_ranges(relocated, index))

    def test_reviewer_reassignment_keeps_subject_but_changes_assignment_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, inventory = _handoff_fixture(root)
            first = _prepare_handoff(root, manifest, inventory)
            reviewers = [parse_reviewer_spec("new-a"), parse_reviewer_spec("new-b")]
            second = _prepare_handoff(root, manifest, inventory, directory="second", reviewers=reviewers)
            a, b = first["assignmentPackets"][0], second["assignmentPackets"][0]
            self.assertEqual(a["assignment"]["subject"], b["assignment"]["subject"])
            self.assertNotEqual(a["assignment"]["assignmentDigest"], b["assignment"]["assignmentDigest"])
            example = a["reviewerTask"]["responseFormat"]["example"]
            result = import_review_mesh_result(
                profile=first["profile"],
                assignment=a["assignment"],
                reviewer_output=example,
            )
            self.assertEqual(result["status"], "SKIPPED")
            self.assertFalse(result["roundParticipation"]["eligible"])
            self.assertTrue(all(value is None for value in result["budgetUsage"].values()))
            with self.assertRaises(LifecycleError):
                import_review_mesh_result(
                    profile=second["profile"], assignment=b["assignment"], reviewer_output=example
                )

    def test_complete_inventory_refuses_drift_and_invalid_scopes_before_mkdir(self):
        mutations = [
            lambda x: x.update(sourceRevision="f" * 40),
            lambda x: x.update(phase="implementation-audit"),
            lambda x: x["scope"].update(changedPaths=[]),
            lambda x: x["scope"].update(evidenceIds=[]),
            lambda x: x["inputs"][0].update(sha256="0" * 64),
            lambda x: x["inputs"][0].update(bytes=True),
            lambda x: x["inputs"][0].update(path="../outside"),
            lambda x: x["inputs"].append(deepcopy(x["inputs"][0])),
            lambda x: x["inputs"].pop(),
            lambda x: x.update(authorityRefs=["MISSING"]),
            lambda x: x["reviewChain"][0].update(roleSlots=0),
            lambda x: x["reviewChain"][0].update(remediationSlots=True),
            lambda x: x.update(responseExtensions={"coverage": {"type": "string", "paths": []}}),
            lambda x: x.update(responseExtensions={"unknown": {}}),
            lambda x: x.update(responseExtensions={"coverage": {"type": "array", "paths": ["other.py"]}}),
            lambda x: x.update(previousFindings=[{"id": "same"}, {"id": "same"}]),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest, inventory = _handoff_fixture(root)
                before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                mutation(inventory)
                with self.assertRaises(LifecycleError):
                    _prepare_handoff(root, manifest, inventory)
                self.assertFalse((root / "prepared").exists())
                self.assertFalse((root / "prepared.reservation.json").exists())
                self.assertEqual(
                    before, {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                )

    def test_range_and_contract_limits_refuse_before_writing(self):
        mutations = [
            lambda x: x["inputs"][0].update(ranges=[{"start": 2, "end": 1}]),
            lambda x: x["inputs"][0].update(ranges=[{"start": 0, "end": 99999999}]),
            lambda x: x["inputs"][0].update(ranges=[{"start": 0, "end": 1}, {"start": 0, "end": 1}]),
            lambda x: x.update(inputs=x["inputs"] * 65),
            lambda x: x.update(responseContract={"rawSchemaVersion": "reviewer-output.v2"}),
            lambda x: x.update(
                responseContract=build_response_contract({"coverage": {"type": "array", "paths": ["other.py"]}})
            ),
            lambda x: x.update(previousFindings=[{"id": "secret", "message": "Bearer private-token-value"}]),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest, inventory = _handoff_fixture(root)
                mutation(inventory)
                with self.assertRaises(LifecycleError):
                    _prepare_handoff(root, manifest, inventory)
                self.assertFalse((root / "prepared").exists())

    def test_output_authority_links_and_repeated_creation_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, inventory = _handoff_fixture(root)
            original = (root / "plan/plan.manifest.json").read_bytes()
            for destination in ["plan", "plan/new", "evidence.json", "forbidden/new"]:
                with self.subTest(destination=destination), self.assertRaises(LifecycleError):
                    _prepare_handoff(root, manifest, inventory, directory=destination)
            self.assertFalse((root / "forbidden").exists())
            self.assertEqual((root / "plan/plan.manifest.json").read_bytes(), original)
            _prepare_handoff(root, manifest, inventory)
            with self.assertRaises(LifecycleError):
                _prepare_handoff(root, manifest, inventory)
            try:
                (root / "alias").symlink_to(root / "plan", target_is_directory=True)
            except OSError:
                self.skipTest("Symlink creation unavailable")
            inventory["inputs"][0]["path"] = "alias/plan.manifest.json"
            with self.assertRaises(LifecycleError):
                _prepare_handoff(root, manifest, inventory, directory="linked")
            self.assertFalse((root / "linked").exists())

    def test_git_clone_availability_names_local_only_and_modified_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            source = root / "src/example.py"
            source.write_text("original = True\n", encoding="utf-8")
            for command in [
                ["git", "init", "-q"],
                ["git", "add", "src/example.py"],
                ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "base"],
            ]:
                subprocess.run(command, cwd=root, check=True, capture_output=True)
            revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            manifest, inventory = _handoff_fixture(root, revision=revision)
            inventory["inputs"].append(_input_entry(root, "SOURCE", "src/example.py"))
            receipt = _prepare_handoff(root, manifest, inventory)
            self.assertEqual(
                receipt["reviewHandoff"]["subjectDigest"],
                receipt["assignmentPackets"][0]["assignment"]["subject"]["subjectDigest"],
            )
            index = json.loads((root / "prepared/reading-index.json").read_bytes())
            availability = {item["id"]: item["cloneAvailability"] for item in index["subject"]["inputs"]}
            self.assertEqual(availability["SOURCE"], "SOURCE_REVISION_MATCH")
            self.assertEqual(availability["EV-01"], "LOCAL_ONLY")
            source.write_text("original = False\n", encoding="utf-8")
            inventory["inputs"][-1] = _input_entry(root, "SOURCE", "src/example.py")
            inventory["scope"].update(kind="TASK_CHANGESET", changedPaths=["src/example.py"])
            _prepare_handoff(root, manifest, inventory, directory="changeset")
            index = json.loads((root / "changeset/reading-index.json").read_bytes())
            self.assertEqual(index["subject"]["scope"]["changedPaths"], ["src/example.py"])
            self.assertEqual(index["subject"]["inputs"][-1]["cloneAvailability"], "LOCAL_CHANGES_REQUIRED")

    def test_oversized_required_file_refuses_without_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, inventory = _handoff_fixture(root)
            (root / "oversized.txt").write_bytes(b"x" * (8_388_608 + 1))
            inventory["inputs"].append(_input_entry(root, "OVERSIZED", "oversized.txt"))
            with self.assertRaises(LifecycleError):
                _prepare_handoff(root, manifest, inventory)
            self.assertFalse((root / "prepared").exists())
            self.assertFalse((root / "prepared.reservation.json").exists())

    def test_built_in_templates_are_valid_and_provider_neutral(self) -> None:
        library = list_review_mesh_operator_templates()

        self.assertEqual(library["schemaVersion"], "agent-review-mesh-operator-template-library.v1")
        self.assertEqual(tuple(library["templateIds"]), REVIEW_MESH_OPERATOR_TEMPLATE_IDS)
        for template in library["templates"]:
            self.assertEqual(validate_review_mesh_operator_template(template)["status"], "PASS")
            self.assertFalse(template["hostExecutionStarted"])
            self.assertFalse(template["modelCallsStarted"])
            self.assertFalse(template["providerBrokerStarted"])
            reviewer_ids = {reviewer["id"] for reviewer in template["defaultReviewers"]}
            self.assertNotIn("codex", " ".join(sorted(reviewer_ids)))
            self.assertNotIn("claude", " ".join(sorted(reviewer_ids)))

    def test_prepare_writes_local_packets_without_host_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = prepare_review_mesh_operator_packets(
                source=_source(review_mesh_required=True),
                template_id="parallel-research-synthesis",
                reviewers=[
                    parse_reviewer_spec("codex-example:architecture-reviewer:strong-reasoning"),
                    parse_reviewer_spec("claude-example:risk-reviewer:strong-reasoning"),
                    parse_reviewer_spec("opencode-glm-example:local-reviewer:local-strong-review"),
                ],
                out_dir=root / "mesh",
                evidence_ids=["EV-PLAN"],
            )

            self.assertEqual(receipt["schemaVersion"], "agent-review-mesh-prepare-receipt.v1")
            self.assertEqual(receipt["status"], "PASS")
            self.assertEqual(receipt["mode"], "parallel-research-synthesis")
            self.assertEqual(receipt["reviewerCount"], 3)
            self.assertFalse(receipt["hostExecutionStarted"])
            self.assertFalse(receipt["modelCallsStarted"])
            self.assertFalse(receipt["providerBrokerStarted"])
            self.assertTrue((root / "mesh" / "profile.json").is_file())
            self.assertEqual(len(list((root / "mesh" / "assignments").glob("*.json"))), 3)
            self.assertEqual({artifact["role"] for artifact in receipt["artifacts"]}, {"profile", "assignment-packet"})

    def test_prepare_rejects_blocking_without_frozen_plan_opt_in(self) -> None:
        with self.assertRaises(LifecycleError) as raised:
            prepare_review_mesh_operator_packets(
                source=_source(review_mesh_required=False),
                template_id="leader-draft-review",
                blocking=True,
            )

        self.assertEqual(raised.exception.code, "review-mesh-prepare-blocking-without-plan-opt-in")

    def test_template_files_match_built_in_template_ids(self) -> None:
        root = Path(__file__).resolve().parents[2]
        template_dir = root / "templates" / "review-mesh"
        file_ids = {json.loads(path.read_text(encoding="utf-8"))["templateId"] for path in template_dir.glob("*.json")}

        self.assertEqual(file_ids, set(REVIEW_MESH_OPERATOR_TEMPLATE_IDS))
        for template_id in file_ids:
            self.assertEqual(get_review_mesh_operator_template(template_id)["templateId"], template_id)


def _source(*, review_mesh_required: bool) -> dict[str, object]:
    return {
        "kind": "PLAN_MANIFEST",
        "label": "release-x",
        "digest": "a" * 64,
        "status": "FROZEN",
        "reviewMesh": {"required": review_mesh_required},
    }


def _handoff_fixture(root: Path, *, revision: str = "a" * 40):
    from tests.cli.test_artifact_authoring_commands import _write_draft

    path, manifest = _write_draft(root)
    manifest["baseRevision"] = {"sha": revision}
    manifest["workstreams"][0]["acceptanceIds"] = ["AC-01"]
    manifest["forbiddenWrites"] = ["forbidden"]
    path.write_bytes(canonical_bytes(manifest) + b"\n")
    (root / "evidence.json").write_bytes(canonical_bytes({"note": "long-input-" * 1800}) + b"\n")
    (root / "budget.json").write_bytes(canonical_bytes({"maxReviewSlots": 4}) + b"\n")
    entries = []
    for identity, name in [
        ("AUTH", "plan/plan.manifest.json"),
        ("AC", "plan/acceptance-criteria.md"),
        ("BUDGET", "budget.json"),
        ("EV-01", "evidence.json"),
    ]:
        raw = (root / name).read_bytes()
        entries.append({"id": identity, "path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    inventory = {
        "schemaVersion": "agent-review-input-inventory.v1",
        "sourceRevision": revision,
        "phase": "plan-review",
        "scope": {
            "kind": "PLAN_PACKAGE",
            "taskIds": ["WS-01"],
            "changedPaths": manifest["planFiles"],
            "acceptanceIds": ["AC-01"],
            "evidenceIds": ["EV-01"],
        },
        "inputs": entries,
        "previousFindings": [{"id": "F-PRIOR", "status": "open"}],
        "reviewChain": [
            {"stage": stage, "roleSlots": 1, "remediationSlots": 1} for stage in ["area", "integration", "final"]
        ],
        "authorityRefs": ["AUTH"],
        "budgetRefs": ["BUDGET"],
    }
    return manifest, inventory


def _prepare_handoff(root, manifest, inventory, *, directory="prepared", **kwargs):
    return prepare_review_mesh_operator_packets(
        source=source_from_manifest(manifest),
        template_id="leader-draft-review",
        review_input=inventory,
        authority_manifest=manifest,
        repository_root=root,
        out_dir=Path(directory),
        **kwargs,
    )


def _input_entry(root: Path, identity: str, path: str):
    raw = (root / path).read_bytes()
    return {"id": identity, "path": path, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


if __name__ == "__main__":
    unittest.main()

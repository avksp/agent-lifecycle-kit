"""Authority text discrimination across tokens, prose and production consumers."""

from __future__ import annotations

import copy
import unittest
from collections.abc import Callable
from functools import partial

from agent_lifecycle.audit.implementation import (
    validate_final_implementation_audit,
    validate_implementation_audit_report,
)
from agent_lifecycle.audit.package import validate_package_audit
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.authority_text import require_authority_text, require_manifest_text, require_review_text
from agent_lifecycle.contracts.review_verdict import open_blocking_finding_ids, validate_review_verdict
from agent_lifecycle.planning.manifest_contract import validate_plan_manifest_contract
from agent_lifecycle.review.validation import validate_independent_review
from agent_lifecycle.review_mesh.contracts import validate_review_mesh_result
from agent_lifecycle.workflow.reviews import open_finding_ids, validate_task_outcome_review, validate_task_review

_CONTROLS = (
    [chr(code) for code in range(32)]
    + [chr(code) for code in range(127, 160)]
    + ["\u061c", "\u200b", "\u200c", "\u200d", "\u200e", "\u200f", "\u2060", "\ufeff", "\u2028", "\u2029"]
    + [chr(code) for code in range(0x202A, 0x202F)]
    + [chr(code) for code in range(0x2066, 0x206A)]
    + ["\ud800", "\udfff"]
)


class AuthorityTextTests(unittest.TestCase):
    def assert_control_rejected(self, operation: Callable[[], object]) -> None:
        with self.assertRaises(LifecycleError) as raised:
            operation()
        self.assertEqual(raised.exception.code, "authority-text-control")
        self.assertEqual(raised.exception.details, {})
        self.assertNotIn("UNTRUSTED", raised.exception.message)

    def test_token_and_prose_control_inventory(self) -> None:
        for character in _CONTROLS:
            with self.subTest(code=ord(character)):
                self.assert_control_rejected(partial(require_authority_text, f"UNTRUSTED{character}"))
                if character in "\t\n\r\u200c\u200d":
                    require_authority_text(f"text{character}text", prose=True)
                else:
                    self.assert_control_rejected(partial(require_authority_text, f"UNTRUSTED{character}", prose=True))

    def test_ordinary_scripts_and_nonprohibited_format_characters_are_preserved(self) -> None:
        for text in (
            "\u041f\u043b\u0430\u043d",
            "\u65e5\u672c\u8a9e",
            "\u0645\u0631\u062d\u0628\u0627",
            "caf\u00e9",
            "a\u00adb",
        ):
            require_authority_text(text)
            require_authority_text(text, prose=True)

    def test_closed_manifest_inventory_checks_each_present_field(self) -> None:
        examples = [
            {"package": {key: "bad\u202e"}}
            for key in ("id", "artifactRoot", "planArtifactRoot", "workspaceRoot", "root", "title")
        ] + [
            {"author": "bad\u202e"},
            {"author": {"surface": "bad\u202e"}},
            {"baseRevision": {"sha": "bad\u202e"}},
            {"releaseTarget": {"targetTag": "bad\u202e"}},
            {"orchestration": {"eventLog": "bad\u202e"}},
            {"planReview": {"report": "bad\u202e"}},
            {"planFiles": ["bad\u202e"]},
            {"readOnly": ["bad\u202e"]},
            {"forbiddenWrites": ["bad\u202e"]},
            {"leadOwned": [{"reason": "bad\u202e"}]},
            {"workstreams": [{"owner": "bad\u202e"}]},
            {"workstreams": [{"dependsOn": ["bad\u202e"]}]},
            {"workstreams": [{"readOnly": ["bad\u202e"]}]},
            {"specification": {"requirements": [{"description": "bad\u202e"}]}},
            {"acceptance": {"criteria": [{"requirementIds": ["bad\u202e"]}]}},
            {"validation": {"commands": ["command\nother"]}},
            {"validation": {"extraEvidence": ["bad\u202e"]}},
            {"finalAuditGates": ["bad\u202e"]},
        ]
        for manifest in examples:
            with self.subTest(manifest=repr(manifest)):
                self.assert_control_rejected(partial(require_manifest_text, manifest))
                self.assert_control_rejected(partial(validate_plan_manifest_contract, manifest))
        safe = {"package": {"title": "line\nnext"}, "extensions": {"uninterpreted": "\u202e"}}
        original = copy.deepcopy(safe)
        require_manifest_text(safe)
        self.assertEqual(safe, original)

    def test_all_finding_fields_rejected_before_severity_filtering(self) -> None:
        for key in (
            "id",
            "code",
            "severity",
            "status",
            "category",
            "path",
            "title",
            "summary",
            "message",
            "description",
            "recommendation",
        ):
            finding = {"id": "F-1", "status": "open", "severity": "HIGH", key: "UNTRUSTED\u200b"}
            review = {"reviewId": "R-1", "findings": [finding]}
            for operation in (
                partial(require_review_text, review),
                partial(open_blocking_finding_ids, [finding]),
                partial(validate_review_verdict, {}, findings=[finding]),
                partial(validate_package_audit, review),
                partial(validate_implementation_audit_report, review),
                partial(validate_final_implementation_audit, review),
                partial(validate_independent_review, review),
                partial(validate_review_mesh_result, review),
                partial(validate_task_review, {}, {}, review),
                partial(validate_task_outcome_review, {}, {}, review, result={}),
                partial(open_finding_ids, review),
            ):
                with self.subTest(field=key):
                    self.assert_control_rejected(operation)

    def test_optional_finding_ids_and_prose_do_not_add_required_fields(self) -> None:
        require_review_text({})
        require_review_text({"findings": [{"summary": "line\nnext\tpart\u200d"}]})
        for key in ("findingIds", "openFindingIds"):
            self.assert_control_rejected(partial(require_review_text, {key: ["F\u200b1"]}))

    def test_gate_prose_newlines_do_not_permit_control_characters_in_linked_ids(self) -> None:
        require_manifest_text({"finalAuditGates": ["[AC-1|EV-1] First line\nnext line"]})
        for gate in ("[AC-\t1|EV-1] prose", "[AC-1|EV-\n1] prose"):
            self.assert_control_rejected(partial(require_manifest_text, {"finalAuditGates": [gate]}))


if __name__ == "__main__":
    unittest.main()


class FrozenFieldEntryPointMatrixTests(unittest.TestCase):
    def test_every_frozen_manifest_field_rejects_controls_without_mutation(self) -> None:
        import json
        from pathlib import Path

        fixture = Path(__file__).resolve().parents[1] / "planning/fixtures/canonical-plan-manifest.v1.json"
        base = json.loads(fixture.read_text(encoding="utf-8"))
        paths = (
            "package.id",
            "package.artifactRoot",
            "package.planArtifactRoot",
            "package.workspaceRoot",
            "package.root",
            "package.title",
            "author",
            "author.id",
            "author.surface",
            "author.runId",
            "baseRevision.ref",
            "baseRevision.sha",
            "releaseTarget.targetVersion",
            "releaseTarget.targetTag",
            "orchestration.stateFile",
            "orchestration.eventLog",
            "planReview.report",
            "planFiles.0",
            "readOnly.0",
            "forbiddenWrites.0",
            "leadOwned.0.path",
            "leadOwned.0.reason",
            "workstreams.0.id",
            "workstreams.0.owner",
            "workstreams.0.title",
            "workstreams.0.dependsOn.0",
            "workstreams.0.acceptanceIds.0",
            "workstreams.0.evidenceIds.0",
            "workstreams.0.writes.0",
            "workstreams.0.readOnly.0",
            "workstreams.0.forbiddenWrites.0",
            "workstreams.0.leadOwned.0.path",
            "workstreams.0.leadOwned.0.reason",
            "specification.requirements.0.id",
            "specification.requirements.0.title",
            "specification.requirements.0.description",
            "acceptance.criteria.0.id",
            "acceptance.criteria.0.title",
            "acceptance.criteria.0.description",
            "acceptance.criteria.0.requirementIds.0",
            "acceptance.criteria.0.evidenceIds.0",
            "validation.commands.0",
            "validation.extraEvidence.0",
            "finalAuditGates.0",
        )
        for field in paths:
            with self.subTest(field=field):
                value = copy.deepcopy(base)
                _set_frozen_field(value, field, "UNTRUSTED\u202e")
                before = copy.deepcopy(value)
                with self.assertRaises(LifecycleError) as raised:
                    validate_plan_manifest_contract(value)
                self.assertEqual(raised.exception.code, "authority-text-control")
                self.assertEqual(raised.exception.details, {})
                self.assertNotIn("UNTRUSTED", raised.exception.message)
                self.assertEqual(value, before)

    def test_multilingual_prose_is_accepted_by_valid_manifest_and_review_entrypoints(self) -> None:
        import json
        from pathlib import Path

        from agent_lifecycle.review_mesh.contracts import (
            build_review_mesh_assignment,
            build_review_mesh_profile,
            build_review_mesh_result,
        )

        base = json.loads(
            (Path(__file__).resolve().parents[1] / "planning/fixtures/canonical-plan-manifest.v1.json").read_text(
                encoding="utf-8"
            )
        )
        for prose in (
            "English line\n\u0420\u0443\u0441\u0441\u043a\u0430\u044f \u0441\u0442\u0440\u043e\u043a\u0430\t\u041f\u0440\u0438\u043d\u044f\u0442\u043e\r\n",
            "\u0641\u0627\u0631\u0633\u06cc\u200c\u0645\u062a\u0646 \u0939\u093f\u0928\u094d\u0926\u0940\u200d\u092a\u093e\u0920",
        ):
            with self.subTest(prose=prose):
                manifest = copy.deepcopy(base)
                for field in (
                    "package.title",
                    "workstreams.0.title",
                    "specification.requirements.0.title",
                    "specification.requirements.0.description",
                    "acceptance.criteria.0.title",
                    "acceptance.criteria.0.description",
                    "leadOwned.0.reason",
                ):
                    _set_frozen_field(manifest, field, prose)
                _set_frozen_field(manifest, "leadOwned.0.path", "controller")
                before = copy.deepcopy(manifest)
                self.assertEqual(validate_plan_manifest_contract(manifest)["status"], "PASS")
                self.assertEqual(manifest, before)
                finding = {
                    "id": "F-TEXT",
                    "severity": "LOW",
                    "status": "closed",
                    "code": "TEXT",
                    "category": "quality",
                    "path": "src/example.py",
                    **{key: prose for key in ("title", "summary", "message", "description", "recommendation")},
                }
                review = {"reviewer": {"independent": True}, "verdict": "ACCEPTED", "findings": [finding]}
                before = copy.deepcopy(review)
                self.assertEqual(validate_independent_review(review)["verdict"], "ACCEPTED")
                self.assertEqual(review, before)
                profile = build_review_mesh_profile(independence_required=False)
                assignment = build_review_mesh_assignment(
                    profile=profile,
                    assignment_id="RM-TEXT",
                    subject={"taskId": "TASK-1", "reviewMeshBlockingOptIn": True},
                    reviewer={"role": "plan-reviewer", "modelClass": "local-strong-review"},
                    blocking=True,
                )
                result = build_review_mesh_result(
                    profile=profile,
                    assignment=assignment,
                    budget_usage={"invocations": 1, "inputTokens": 2000, "outputTokens": 400, "wallSeconds": 60},
                    findings=[finding],
                )
                before = copy.deepcopy(result)
                self.assertEqual(validate_review_mesh_result(result, profile=profile)["status"], "PASS")
                self.assertEqual(result, before)
                for key in finding:
                    for entrypoint, original in (
                        (validate_independent_review, review),
                        (validate_review_mesh_result, result),
                    ):
                        bad = copy.deepcopy(original)
                        bad["findings"][0][key] = "UNTRUSTED\u202e"
                        snapshot = copy.deepcopy(bad)
                        with self.assertRaises(LifecycleError) as raised:
                            entrypoint(bad)
                        self.assertEqual(raised.exception.code, "authority-text-control")
                        self.assertEqual(raised.exception.details, {})
                        self.assertNotIn("UNTRUSTED", raised.exception.message)
                        self.assertEqual(bad, snapshot)


def _set_frozen_field(value, path, content):
    parts = path.split(".")
    for index, part in enumerate(parts[:-1]):
        key = int(part) if isinstance(value, list) else part
        child = [] if parts[index + 1].isdigit() else {}
        if isinstance(value, list):
            while len(value) <= key:
                value.append(copy.deepcopy(child))
        if key not in value if isinstance(value, dict) else value[key] is None:
            value[key] = child
        if not isinstance(value[key], (dict, list)):
            value[key] = child
        value = value[key]
    key = int(parts[-1]) if isinstance(value, list) else parts[-1]
    if isinstance(value, list):
        while len(value) <= key:
            value.append(None)
    value[key] = content

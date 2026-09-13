from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError, authority_io, canonical_bytes, canonical_digest
from agent_lifecycle.workflow import plan_adoption
from agent_lifecycle.workflow.plan_adoption import (
    _build_tasks,
    _last_plan_review,
    _raw_file_identity,
    _replace_plan_state,
    _task_contract_compatible,
    adopt_plan,
)
from tests.workflow.helpers import _write_state
from tests.workflow.plan_helpers import _write_plan_bundle
from tests.workflow.test_plan_adoption import (
    _adopt_authority_bundle,
    _assert_authority_rejection,
    _write_authority_bundle,
)


class PlanAdoptionRuntimeContractTests(unittest.TestCase):
    def test_review_identity_hashes_consumed_raw_bytes_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / "review.json"
            review = {
                "reviewId": "review-original",
                "reviewer": {"id": "reviewer", "runId": "review-run", "surface": "test"},
                "verdict": "READY_TO_FREEZE",
            }
            data = json.dumps(review, indent=4).encode() + b"\n\n"
            path.write_bytes(data)
            expected = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            self.assertNotEqual(expected["sha256"], canonical_digest(review))
            original_open = authority_io._Directory.open_child
            opened = []

            def observe(parent, name):
                opened.append(name)
                return original_open(parent, name)

            with patch.object(authority_io._Directory, "open_child", observe):
                self.assertEqual(_raw_file_identity(path), expected)
                result = _last_plan_review(root, {"planReview": {"report": path.name}})
            self.assertEqual(opened, [path.name, path.name])
            self.assertEqual({key: result[key] for key in expected}, expected)
            self.assertEqual(result["reviewId"], review["reviewId"])
            self.assertEqual(result["reviewerRunId"], "review-run")

    def test_review_parser_consumes_the_bytes_used_for_raw_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / "review.json"
            data = b'{ "reviewId": "original", "reviewer": {"id": "reviewer"} }\n'
            changed = data.replace(b"original", b"replaced")
            path.write_bytes(data)
            original_parse = plan_adoption.load_json_object
            consumed = []

            def replace_before_parse(raw, *, label):
                consumed.append(raw)
                path.write_bytes(changed)
                return original_parse(raw, label=label)

            with patch.object(plan_adoption, "load_json_object", replace_before_parse):
                result = _last_plan_review(root, {"planReview": {"report": path.name}})
            self.assertEqual(consumed, [data])
            self.assertEqual(result["reviewId"], "original")
            self.assertEqual(result["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(result["bytes"], len(data))
            self.assertEqual(path.read_bytes(), changed)

    def test_raw_review_consumers_reject_same_size_replacement_and_symlinks(self) -> None:
        for consumer in ("raw", "review"):
            for change in ("replace", "leaf-link", "parent-link"):
                with self.subTest(consumer=consumer, change=change), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp).resolve()
                    folder = root / "reports"
                    folder.mkdir()
                    path = folder / "review.json"
                    data = b'{"reviewId":"original","reviewer":{}}\n'
                    changed = data.replace(b"original", b"replaced")
                    path.write_bytes(data)
                    replacement = folder / "replacement.json"
                    replacement.write_bytes(changed)
                    original_open = authority_io._Directory.open_child
                    touched = []
                    if change == "leaf-link":
                        path.unlink()
                        path.symlink_to(replacement)
                    elif change == "parent-link":
                        link = root / "linked"
                        link.symlink_to(folder, target_is_directory=True)
                        path = link / path.name

                    def substitute(
                        parent,
                        name,
                        *,
                        change=change,
                        path=path,
                        replacement=replacement,
                        touched=touched,
                        original_open=original_open,
                    ):
                        if change == "replace" and name == path.name:
                            parent.replace_child(replacement.name, name)
                            touched.append(name)
                        return original_open(parent, name)

                    with (
                        patch.object(authority_io._Directory, "open_child", substitute),
                        self.assertRaises(LifecycleError) as raised,
                    ):
                        if consumer == "raw":
                            _raw_file_identity(path)
                        else:
                            _last_plan_review(root, {"planReview": {"report": path.relative_to(root).as_posix()}})
                    if change == "replace":
                        self.assertEqual(raised.exception.code, "authority-input-changed")
                        self.assertEqual(touched, [path.name])

    def test_review_rejection_preserves_adoption_state_and_journal(self) -> None:
        for change in ("replace", "symlink", "lineage"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                state_path = _write_state(root, phase="READY")
                manifest_path = _write_authority_bundle(root)
                manifest = json.loads(manifest_path.read_bytes())
                review_path = root / manifest["planReview"]["report"]
                data = review_path.read_bytes()
                changed = data.replace(b"plan-review-r01", b"plan-review-r99")
                self.assertNotEqual(changed, data)
                self.assertEqual(len(changed), len(data))
                replacement = review_path.with_name("replacement.json")
                replacement.write_bytes(changed)
                if change == "symlink":
                    review_path.unlink()
                    review_path.symlink_to(replacement)
                elif change == "lineage":
                    lock_path = root / manifest["package"]["planArtifactRoot"] / "plan.lock.json"
                    lock = json.loads(lock_path.read_bytes())
                    lock["manifestHash"] = "f" * 64
                    lock_path.write_bytes(canonical_bytes(lock) + b"\n")
                journal = root / "events.jsonl"
                journal.write_bytes(b'{"stateRevision":1}\n')
                before = (state_path.read_bytes(), journal.read_bytes())
                original_open = authority_io._Directory.open_child
                touched = []

                def substitute(
                    parent,
                    name,
                    *,
                    change=change,
                    review_path=review_path,
                    replacement=replacement,
                    touched=touched,
                    original_open=original_open,
                ):
                    if change == "replace" and name == review_path.name:
                        parent.replace_child(replacement.name, name)
                        touched.append(name)
                    return original_open(parent, name)

                with (
                    patch.object(authority_io._Directory, "open_child", substitute),
                    patch.object(plan_adoption, "commit_state", wraps=plan_adoption.commit_state) as commit,
                    self.assertRaises(LifecycleError) as raised,
                ):
                    _adopt_authority_bundle(state_path, manifest_path)
                commit.assert_not_called()
                self.assertEqual((state_path.read_bytes(), journal.read_bytes()), before)
                if change == "replace":
                    self.assertEqual(raised.exception.code, "authority-input-changed")
                    self.assertEqual(touched, [review_path.name])

    def test_adoption_declarations_use_state_root_when_cwd_differs(self) -> None:
        for kind in ("legacy", "integrity"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as cwd:
                root = Path(tmp).resolve()
                (root / "Protected").mkdir()
                aliases = (root / "protected").exists()
                if not aliases:
                    (root / "protected").mkdir()
                state_path = _write_state(root, phase="READY")
                manifest_path = _write_authority_bundle(
                    root,
                    kind=kind,
                    global_fields={"readOnly": ["Protected"]},
                    task_fields={"writes": ["protected/output"]},
                )
                previous_cwd = Path.cwd()
                try:
                    os.chdir(cwd)
                    # No case names exist in cwd: using it would fail with unknown policy.
                    if aliases:
                        _assert_authority_rejection(
                            self,
                            root,
                            state_path,
                            manifest_path,
                            "ambiguous-authority-path",
                        )
                    else:
                        self.assertEqual(_adopt_authority_bundle(state_path, manifest_path)["phase"], "READY")
                finally:
                    os.chdir(previous_cwd)

    def test_adoption_unknown_state_root_case_policy_does_not_use_cwd(self) -> None:
        for kind in ("legacy", "integrity"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as cwd:
                root = Path(tmp).resolve()
                (Path(cwd) / "Protected").mkdir()
                state_path = _write_state(root, phase="READY")
                manifest_path = _write_authority_bundle(
                    root,
                    kind=kind,
                    global_fields={"readOnly": ["Protected"]},
                    task_fields={"writes": ["protected/output"]},
                )
                previous_cwd = Path.cwd()
                try:
                    os.chdir(cwd)
                    error = _assert_authority_rejection(
                        self,
                        root,
                        state_path,
                        manifest_path,
                        "filesystem-policy-unavailable",
                    )
                    self.assertEqual(error.message, "missing names have unknown alias semantics")
                finally:
                    os.chdir(previous_cwd)

    def test_runtime_tasks_copy_manifest_acceptance_ids(self) -> None:
        manifest = {
            "package": {"artifactRoot": "tasks/package"},
            "workstreams": [
                {
                    "id": "WS-01",
                    "title": "Task",
                    "owner": "worker",
                    "dependsOn": [],
                    "writes": ["src/example.py"],
                    "acceptanceIds": ["AC-01", "AC-02"],
                    "evidenceIds": ["EV-01"],
                }
            ],
        }

        tasks = _build_tasks(manifest, {})

        self.assertEqual(tasks[0]["acceptanceIds"], ["AC-01", "AC-02"])

    def test_runtime_tasks_copy_optional_security_policy(self) -> None:
        manifest = {
            "package": {"artifactRoot": "tasks/package"},
            "extensions": {
                "securityAnalysis": {
                    "profileId": "security-analysis.v1",
                    "activation": "read-only-by-default",
                    "implementationAudit": {"required": True, "independentVerificationRequired": True},
                }
            },
            "workstreams": [{"id": "WS-01", "owner": "worker", "writes": [], "dependsOn": []}],
        }
        task = _build_tasks(manifest, {})[0]
        self.assertEqual(task["securityAnalysis"]["profileId"], "security-analysis.v1")
        self.assertTrue(task["implementationAudit"]["required"])

    def test_missing_legacy_acceptance_ids_match_an_empty_contract(self) -> None:
        current = {
            "id": "WS-01",
            "title": "Task",
            "owner": "worker",
            "dependsOn": [],
            "writes": [],
            "reviewer": None,
            "launchGate": None,
            "capabilityHints": [],
            "requiredTools": [],
            "contextRefs": [],
            "acceptanceIds": [],
            "evidenceIds": [],
            "executionPolicy": {},
            "modelRoute": None,
            "reviewMesh": None,
            "artifactPaths": {},
            "required": True,
        }
        previous = {key: value for key, value in current.items() if key != "acceptanceIds"}

        self.assertTrue(_task_contract_compatible(previous, current))

    def test_adopted_manifest_path_is_repository_relative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(
                root,
                phase="BLOCKED",
                blocker={"code": "plan-drift", "reason": "x", "resumePhase": "RUNNING"},
            )
            _write_plan_bundle(root)
            manifest_path = root / "plans/package/plan.manifest.json"

            adopt_plan(
                state_path,
                manifest_path=manifest_path,
                operation_id="adopt-runtime-contract",
                expected_revision=1,
                source_revision="source-2",
                reset_tasks=True,
                start_mode="auto-after-freeze",
                authorized_by="tester",
            )
            stored = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(stored["manifestPath"], "plans/package/plan.manifest.json")
        self.assertNotIn("..", stored["manifestPath"].split("/"))

    def test_adopted_manifest_path_outside_package_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as external:
            root = Path(tmp)
            with self.assertRaises(LifecycleError) as caught:
                _replace_plan_state(
                    {},
                    state_path=root / "run.state.json",
                    manifest_path=Path(external) / "plan.manifest.json",
                    manifest={},
                    digest="0" * 64,
                    revision=2,
                    root=root,
                    source_revision="source-2",
                    start_mode="auto-after-freeze",
                    authorized_by="tester",
                    packet_set={},
                    tasks=[],
                )

        self.assertEqual(caught.exception.code, "manifest-path-outside-package-root")


if __name__ == "__main__":
    unittest.main()

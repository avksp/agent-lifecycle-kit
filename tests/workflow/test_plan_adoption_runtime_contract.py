from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.workflow.plan_adoption import (
    _build_tasks,
    _replace_plan_state,
    _task_contract_compatible,
    adopt_plan,
)
from agent_lifecycle.contracts import LifecycleError
from tests.workflow.helpers import _write_state
from tests.workflow.plan_helpers import _write_plan_bundle


class PlanAdoptionRuntimeContractTests(unittest.TestCase):
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
            ]
        }

        tasks = _build_tasks(manifest, {})

        self.assertEqual(tasks[0]["acceptanceIds"], ["AC-01", "AC-02"])

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

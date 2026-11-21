from __future__ import annotations

import json
import os
import subprocess
import unittest
from contextlib import chdir
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest, write_json_create
from agent_lifecycle.workflow import package_archive as archive
from agent_lifecycle.workflow.finalization import finalize_run
from tests.cli.helpers import _run_cli
from tests.workflow.helpers import _final_audit, _write_state


def seed_completed_project(root: Path) -> tuple[dict, dict]:
    """Use the actual finalization writer on a disposable workflow fixture."""
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    (root / ".gitignore").write_text("/tasks/\n/work/\n", encoding="utf-8")
    (root / "work/frozen-package").mkdir(parents=True)
    (root / "tasks").mkdir()
    (root / "work/package").mkdir(parents=True)
    plan_path = "work/frozen-package/plan.manifest.json"
    manifest = {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "package", "planArtifactRoot": "work/frozen-package", "artifactRoot": "work/package"},
        "planFiles": [plan_path],
    }
    write_json_create(root / plan_path, manifest)
    path = _write_state(root, phase="FINAL_AUDIT")
    state = json.loads(path.read_bytes())
    state["packageRoot"] = "../.."
    state["eventLog"] = "work/package/events.jsonl"
    state["planDigest"] = canonical_digest(manifest)
    state["tasks"][0].update(status="ACCEPTED", attempt=1, review={"sha256": "1" * 64})
    path.unlink()
    state_path = "work/package/run.state.json"
    write_json_create(root / state_path, state)
    audit = _final_audit()
    audit["planDigest"] = state["planDigest"]
    audit["completionSignal"]["planDigest"] = state["planDigest"]
    final_audit = "work/package/final-audit.json"
    proof = "work/package/final-proof.json"
    write_json_create(root / final_audit, audit)
    with chdir(root):
        final = finalize_run(
            root / state_path,
            operation_id="fixture-finalize",
            expected_revision=1,
            source_revision="source",
            final_audit_path=final_audit,
            proof_path=proof,
            reason="Terminal fixture",
        )
    assert final["phase"] == "COMPLETE"
    catalogue = {
        "schemaVersion": archive.CATALOGUE_SCHEMA,
        "scope": "test-project",
        "complete": True,
        "packages": [
            {
                "id": "package",
                "manifest": plan_path,
                "predecessorIds": [],
                "state": state_path,
                "proof": proof,
            }
        ],
    }
    return catalogue, state


class ArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        workspace = TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        parent = Path(workspace.name).resolve()
        self.root = parent / "repo"
        self.target = parent / "archives"
        self.target.mkdir()
        self.catalogue, self.before_final = seed_completed_project(self.root)
        self.output = self.target / "package.zip"

    def _snapshot(self) -> dict:
        files = {}
        for parent in (self.root / "tasks", self.root / "work", self.target):
            for entry in parent.rglob("*"):
                name = str(entry.relative_to(parent.parent))
                if entry.is_symlink():
                    files[name] = str(entry.readlink())
                elif entry.is_file():
                    files[name] = sha256(entry.read_bytes()).hexdigest()
                else:
                    files[name] = None
        return files

    def _args(self, command: str) -> list[str]:
        data = canonical_bytes(self.catalogue) + b"\n"
        (self.root / "work/catalogue.json").write_bytes(data)
        return [
            "project",
            "archive",
            command,
            "--project-root",
            str(self.root),
            "--catalogue",
            "work/catalogue.json",
            "--catalogue-sha256",
            sha256(data).hexdigest(),
        ]

    def _select(self) -> dict:
        code, record = _run_cli(self._args("inventory"))
        self.assertEqual(code, 0, record)
        return record

    def _create(self, digest: str) -> tuple[int, dict]:
        return _run_cli(
            [*self._args("create"), "--inventory-digest", digest, "--package", "package", "--out", str(self.output)]
        )

    def _assert_refusal(self, inventory: dict, code: str, reason: str | None = None) -> None:
        before = self._snapshot()
        status, result = self._create(inventory["inventoryDigest"])
        self.assertEqual((status, result["code"]), (2, code), result)
        if reason:
            self.assertEqual(result["details"]["reason"], reason)
        self.assertEqual(self._snapshot(), before)

    def test_completed_snapshot_and_existing_target_refusal(self) -> None:
        inventory = self._select()
        self.assertTrue(inventory["packages"][0]["closureEligible"], inventory)
        before = self._snapshot()
        code, saved = self._create(inventory["inventoryDigest"])
        self.assertEqual(code, 0, saved)
        self.assertEqual(saved["archiveSha256"], sha256(self.output.read_bytes()).hexdigest())
        self.assertEqual(saved["sourceBytesReclaimed"], 0)
        self.assertFalse(saved["authorityClaimed"])
        with ZipFile(self.output) as zipped:
            manifest = json.loads(zipped.read("archive-manifest.json"))
            self.assertEqual(set(zipped.namelist()), {*manifest["members"], "archive-manifest.json"})
            selected = inventory["packages"][0]
            for kind, name in (
                ("manifest", "plan/plan.manifest.json"),
                ("state", "work/run.state.json"),
                ("proof", "work/final-proof.json"),
            ):
                self.assertEqual(manifest["members"][name]["sha256"], selected[f"{kind}Sha256"])
            for name, member in manifest["members"].items():
                kind, _, relative = name.partition("/")
                folder = "work/frozen-package" if kind == "plan" else "work/package"
                source = (self.root / folder / relative).read_bytes()
                self.assertEqual(zipped.read(name), source)
                self.assertEqual(member, {"bytes": len(source), "sha256": sha256(source).hexdigest()})
        self.assertEqual({k: v for k, v in self._snapshot().items() if not k.startswith("archives/")}, before)
        self._assert_refusal(inventory, "archive-target-exists")

    def test_running_and_missing_proof_refuse(self) -> None:
        state = self.before_final
        state["phase"] = "RUNNING"
        (self.root / "work/package/run.state.json").write_bytes(canonical_bytes(state) + b"\n")
        self.catalogue["packages"][0].pop("proof")
        self._assert_refusal(self._select(), "archive-package-ineligible", "NO_BOUND_COMPLETION")
        self.catalogue["packages"][0].pop("state")
        self._assert_refusal(self._select(), "archive-package-ineligible", "NO_WORKFLOW_STATE")

    def test_invalid_closure_refuses_and_invalidates_prior_inventory(self) -> None:
        valid = self._select()
        proof = self.root / "work/package/final-proof.json"
        doc = json.loads(proof.read_bytes())
        doc["sourceRevision"] = "stale"
        proof.write_bytes(canonical_bytes(doc) + b"\n")
        self._assert_refusal(valid, "archive-inventory-drift")
        self._assert_refusal(self._select(), "archive-package-ineligible", "COMPLETION_UNAVAILABLE")

    def test_active_catalogue_entry_can_pin_predecessor(self) -> None:
        target = self.root / "tasks/active"
        target.mkdir()
        write_json_create(
            target / "plan.manifest.json",
            {
                "status": "DRAFT",
                "package": {"id": "active", "planArtifactRoot": "tasks/active", "artifactRoot": "work/active"},
            },
        )
        self.catalogue["packages"].append(
            {"id": "active", "manifest": "tasks/active/plan.manifest.json", "predecessorIds": ["package"]}
        )
        self._assert_refusal(self._select(), "archive-package-ineligible", "REFERENCED_PREDECESSOR")

    def test_catalogue_requires_asserted_complete_scope_and_no_dangling_edges(self) -> None:
        for complete, predecessors, error in (
            (False, [], "archive-catalogue-incomplete"),
            (True, ["absent"], "archive-catalogue-dangling"),
        ):
            with self.subTest(complete=complete, predecessors=predecessors):
                self.catalogue["complete"] = complete
                self.catalogue["packages"][0]["predecessorIds"] = predecessors
                args = self._args("inventory")
                before = self._snapshot()
                code, result = _run_cli(args)
                self.assertEqual((code, result["code"]), (2, error))
                self.assertEqual(self._snapshot(), before)

    def test_tracked_and_linked_members_refuse(self) -> None:
        member = self.root / "work/package/extra.txt"
        member.write_text("additional", encoding="utf-8")
        subprocess.run(["git", "add", "--force", str(member)], cwd=self.root, check=True, capture_output=True)
        self._assert_refusal(self._select(), "archive-member-tracked-or-unignored")
        member.unlink()
        proof = self.root / "work/package/final-proof.json"
        os.link(proof, self.root / "work/package/aliased.json")
        self._assert_refusal(self._select(), "archive-member-unsafe")

    def test_output_overlap_and_oversized_members_refuse(self) -> None:
        inventory = self._select()
        outside = self.output
        self.output = self.root / "nested.zip"
        self._assert_refusal(inventory, "archive-target-overlap")
        self.output = outside
        member = self.root / "work/package/oversized.bin"
        with member.open("wb") as stream:
            stream.truncate(archive.MAX_MEMBER_BYTES + 1)
        self._assert_refusal(inventory, "archive-size-limit")

    def test_inventory_change_detected_before_publication(self) -> None:
        old_inventory = self._select()
        original = archive._archive_bytes

        def copy_then_add_member(*args):
            snapshot = original(*args)
            (self.root / "work/package/concurrent.txt").write_text("changed", encoding="utf-8")
            return snapshot

        with patch.object(archive, "_archive_bytes", side_effect=copy_then_add_member):
            code, result = self._create(old_inventory["inventoryDigest"])
        self.assertEqual((code, result["code"]), (2, "archive-source-drift"))
        self.assertFalse(self.output.exists())

    def test_archive_guard_rejects_inconsistent_copied_closure(self) -> None:
        inventory = self._select()
        original = archive._archive_bytes
        for kind, member in (("missing", "work/run.state.json"), ("different", "work/final-proof.json")):

            def inconsistent_metadata(*args, mismatch=kind, name=member):
                payload, manifest = original(*args)
                if mismatch == "missing":
                    manifest["members"].pop(name)
                else:
                    manifest["members"][name]["sha256"] = "0" * 64
                return payload, manifest

            with self.subTest(kind=kind), patch.object(archive, "_archive_bytes", side_effect=inconsistent_metadata):
                self._assert_refusal(inventory, "archive-source-drift")

    def test_archive_guard_checks_directory_identity(self) -> None:
        with patch.object(Path, "samefile", return_value=True), self.assertRaises(LifecycleError) as denied:
            archive._destination(self.root, self.output)
        self.assertEqual(denied.exception.code, "archive-target-overlap")
        self.assertFalse(self.output.exists())

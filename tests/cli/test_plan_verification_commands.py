from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import canonical_digest  # noqa: E402
from tests.cli.helpers import _run_cli  # noqa: E402


class CliPlanVerificationTests(unittest.TestCase):
    def test_plan_verify_writes_bounded_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, lock_path, acceptance_path = _write_inputs(root)
            out_path = root / "verification.json"

            code, payload = _run_cli(
                [
                    "plan",
                    "verify",
                    "--manifest",
                    str(manifest_path),
                    "--lock",
                    str(lock_path),
                    "--acceptance",
                    str(acceptance_path),
                    "--repository-root",
                    str(root),
                    "--out",
                    str(out_path),
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-plan-verification-receipt.v1")
            self.assertEqual(payload["status"], "PASS")
            self.assertFalse(payload["executedCommands"])
            self.assertEqual(
                json.loads(out_path.read_text(encoding="utf-8"))["verificationDigest"], payload["verificationDigest"]
            )

    def test_plan_verify_returns_nonzero_for_missing_frozen_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, lock_path, acceptance_path = _write_inputs(root)
            lock_path.unlink()
            out_path = root / "failed-verification.json"

            code, payload = _run_cli(
                [
                    "plan",
                    "verify",
                    "--manifest",
                    str(manifest_path),
                    "--acceptance",
                    str(acceptance_path),
                    "--repository-root",
                    str(root),
                    "--out",
                    str(out_path),
                ]
            )

            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "plan-verification-failed")
            receipt = payload["details"]["verification"]
            self.assertEqual(receipt["status"], "FAIL")
            self.assertIn("plan-lock-required", {item["code"] for item in receipt["blockers"]})
            self.assertEqual(json.loads(out_path.read_text(encoding="utf-8"))["status"], "FAIL")


def _write_inputs(root: Path) -> tuple[Path, Path, Path]:
    manifest = {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "cli-verification-fixture"},
        "specification": {"tier": "S1", "requirements": [{"id": "REQ-01", "description": "verify"}]},
        "releaseTarget": {"targetVersion": "1.0.0"},
        "acceptance": {"criteria": [{"id": "AC-01", "requirementIds": ["REQ-01"], "evidenceIds": ["EV-01"]}]},
        "workstreams": [{"id": "WS-01", "dependsOn": [], "writes": ["src/example.py"], "evidenceIds": ["EV-01"]}],
        "validation": {"commands": ["python -m unittest"], "extraEvidence": []},
    }
    package = root / "plan"
    package.mkdir()
    manifest_path = package / "plan.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    lock_path = package / "plan.lock.json"
    lock_path.write_text(
        json.dumps(
            {"schemaVersion": "agent-plan-lock.v1", "planRevision": 1, "manifestHash": canonical_digest(manifest)}
        ),
        encoding="utf-8",
    )
    acceptance_path = package / "acceptance-criteria.md"
    acceptance_path.write_text(
        "| ID | Requirements | Evidence | Statement |\n| --- | --- | --- | --- |\n| `AC-01` | `REQ-01` | `EV-01` | Verify. |\n",
        encoding="utf-8",
    )
    return manifest_path, lock_path, acceptance_path


if __name__ == "__main__":
    unittest.main()


class CompilerOutputEntryPointMatrixTests(unittest.TestCase):
    def test_explicit_packet_and_index_conflicts_reject_at_api_and_cli_without_writes(self) -> None:
        from tests.compiler.test_task_packets import _write_bundle

        for small in (False, True):
            for destination in ("plans/p/.agent-plan/p", "plans/p/.agent-plan/p/new", "plans/p/plan.manifest.json"):
                with self.subTest(small=small, destination=destination), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    path = _write_bundle(root)
                    self._state_and_event_sentinels(root)
                    self._assert_rejected_output(root, path, destination, "plan-output-conflict", small)

    def test_default_manifest_verify_api_cli_conflict_matrix(self) -> None:
        from contextlib import chdir

        from agent_lifecycle.planning.manifest_contract import validate_plan_manifest_contract
        from agent_lifecycle.planning.verification import build_plan_verification
        from tests.compiler.test_task_packets import _manifest, _write_bundle

        for runtime in ("plans/p/.agent-plan/p", "plans/p/.agent-plan/p/nested"):
            with self.subTest(runtime=runtime), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = _manifest()
                manifest["package"]["artifactRoot"] = runtime
                path = _write_bundle(root, manifest=manifest)
                self._state_and_event_sentinels(root)
                before = self._tree_state(root)
                contract = validate_plan_manifest_contract(manifest)
                self.assertEqual(contract["status"], "FAIL")
                self.assertIn("plan-output-conflict", json.dumps(contract))
                result = build_plan_verification(manifest, manifest_path=path, repository_root=root)
                self.assertEqual(result["status"], "FAIL")
                self.assertIn("plan-output-conflict", json.dumps(result))
                for small in (False, True):
                    self._assert_rejected_output(root, path, None, "plan-output-conflict", small)
                with chdir(root):
                    code, payload = _run_cli(
                        ["plan", "verify", "--manifest", str(path), "--repository-root", str(root)]
                    )
                self.assertEqual(code, 2)
                self.assertEqual(payload["code"], "plan-verification-failed")
                self.assertIn(
                    "plan-output-conflict", {item["code"] for item in payload["details"]["verification"]["blockers"]}
                )
                self.assertEqual(self._tree_state(root), before)

    @staticmethod
    def _tree_state(root: Path) -> dict:
        inventory = {}
        for path in root.rglob("*"):
            name = path.relative_to(root).as_posix()
            if path.is_symlink():
                inventory[name] = ("link", str(path.readlink()))
            elif path.is_dir():
                inventory[name] = ("directory",)
            else:
                inventory[name] = ("file", path.read_bytes())
        return inventory

    @staticmethod
    def _state_and_event_sentinels(root: Path) -> None:
        (root / "run.state.json").write_text('{"secret":"private-output-payload"}', encoding="utf-8")
        (root / "workflow-events.jsonl").write_text('{"secret":"private-event-payload"}\n', encoding="utf-8")

    def _assert_rejected_output(
        self, root: Path, manifest: Path, destination: str | None, expected: str, small: bool
    ) -> None:
        from contextlib import chdir

        from agent_lifecycle.compiler import compile_small_model_packets, compile_task_packets
        from agent_lifecycle.contracts import LifecycleError

        before = self._tree_state(root)
        with chdir(root):
            with self.assertRaises(LifecycleError) as raised:
                if small:
                    compile_small_model_packets(
                        manifest,
                        context_profile_path=ROOT / "profiles/small-context-profile.v1.json",
                        out_dir=Path(destination) if destination is not None else None,
                        write=True,
                    )
                else:
                    compile_task_packets(
                        manifest, out_dir=Path(destination) if destination is not None else None, write=True
                    )
            self.assertEqual(raised.exception.code, expected)
            self.assertEqual(self._tree_state(root), before)
            args = ["task", "compile-small" if small else "compile", "--manifest", str(manifest), "--write"]
            if destination is not None:
                args += ["--out-dir", destination]
            if small:
                args += ["--context-profile", str(ROOT / "profiles/small-context-profile.v1.json")]
            code, payload = _run_cli(args)
            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], expected)
            diagnostic = json.dumps(payload, ensure_ascii=False)
            for private in (root.name, "private-output-payload", "private-event-payload", destination):
                if private is not None:
                    self.assertNotIn(private, diagnostic)
            self.assertEqual(self._tree_state(root), before)

    def test_output_cli_lexical_alias_matrix_has_redacted_errors_and_no_mutation(self) -> None:
        import os

        from tests.compiler.test_task_packets import _write_bundle

        cases = [
            ("plans//p/./.agent-plan/p", "plan-output-conflict"),
            ("plans/p/other/../.agent-plan/p", "invalid-repo-path"),
            (r"plans\p\.agent-plan\p", "plan-output-conflict" if os.name == "nt" else "invalid-repo-path"),
            (r"C:\outside\private-output", "authority-path-outside-root" if os.name == "nt" else "invalid-repo-path"),
            ("//private-server/private-share/output", "authority-path-outside-root"),
            ("plans/p/.agent-plan/p/e\u0301", "noncanonical-authority-path"),
        ]
        for small in (False, True):
            for destination, expected in cases:
                with self.subTest(small=small, destination=destination), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    path = _write_bundle(root)
                    self._state_and_event_sentinels(root)
                    self._assert_rejected_output(root, path, destination, expected, small)

    def test_output_cli_existing_case_alias_uses_actual_filesystem_identity(self) -> None:
        from contextlib import chdir

        from tests.compiler.test_task_packets import _write_bundle

        for small in (False, True):
            with self.subTest(small=small), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = _write_bundle(root)
                self._state_and_event_sentinels(root)
                alias = root / "plans/p/.agent-plan/P"
                protected = root / "plans/p/.agent-plan/p"
                if alias.exists() and alias.samefile(protected):
                    self._assert_rejected_output(root, path, "plans/p/.agent-plan/P/new", "plan-output-conflict", small)
                else:
                    # Distinct names on a sensitive filesystem retain ordinary write authority.
                    before = self._tree_state(protected)
                    with chdir(root):
                        args = [
                            "task",
                            "compile-small" if small else "compile",
                            "--manifest",
                            str(path),
                            "--out-dir",
                            "plans/p/.agent-plan/P/new",
                            "--write",
                        ]
                        if small:
                            args += ["--context-profile", str(ROOT / "profiles/small-context-profile.v1.json")]
                        code, _ = _run_cli(args)
                        self.assertEqual(code, 0)
                    self.assertEqual(self._tree_state(protected), before)
                    self.assertTrue((alias / "new/index.json").is_file())

    def test_output_cli_parent_and_final_symlinks_reject_without_directory_creation(self) -> None:
        from tests.compiler.test_task_packets import _write_bundle

        for small in (False, True):
            for tail in ("", "/missing/child"):
                with self.subTest(small=small, tail=tail), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    path = _write_bundle(root)
                    self._state_and_event_sentinels(root)
                    (root / "output-link").symlink_to(root / "plans/p/.agent-plan/p", target_is_directory=True)
                    self._assert_rejected_output(root, path, "output-link" + tail, "authority-input-symlink", small)

    def test_output_cli_unknown_case_semantics_fail_before_creating_output(self) -> None:
        from tests.compiler.test_task_packets import _manifest, _write_bundle

        for small in (False, True):
            with self.subTest(small=small), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                value = _manifest()
                value["planFiles"] = ["unknown/Protected/index.json"]
                path = _write_bundle(root, manifest=value)
                self._state_and_event_sentinels(root)
                self._assert_rejected_output(root, path, "unknown/protected", "filesystem-policy-unavailable", small)

    def test_output_cli_unicode_authority_file_aliases_are_checked_before_writes(self) -> None:
        from tests.compiler.test_task_packets import _manifest, _write_bundle

        for small in (False, True):
            for spelling, expected in (
                ("caf\u00e9.json", "plan-output-conflict"),
                ("cafe\u0301.json", "noncanonical-authority-path"),
            ):
                with self.subTest(small=small, spelling=spelling), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    value = _manifest()
                    value["planFiles"] = ["plans/p/caf\u00e9.json"]
                    path = _write_bundle(root, manifest=value)
                    (root / "plans/p/caf\u00e9.json").write_text("private-output-payload", encoding="utf-8")
                    self._state_and_event_sentinels(root)
                    self._assert_rejected_output(root, path, "plans/p/" + spelling, expected, small)

    def test_output_cli_ancestor_swap_cannot_redirect_creation_into_plan(self) -> None:
        from contextlib import chdir
        from unittest.mock import patch

        from agent_lifecycle.contracts.authority_io import create_authority_bytes
        from tests.compiler.test_task_packets import _write_bundle

        for small in (False, True):
            with self.subTest(small=small), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = _write_bundle(root)
                self._state_and_event_sentinels(root)
                runtime = root / "runtime"
                runtime.mkdir()
                protected = root / "plans/p/.agent-plan/p"
                protected_before = self._tree_state(protected)
                after_attacker = {}

                def swap_before_create(output, data, **kwargs):
                    runtime.rmdir()
                    runtime.symlink_to(protected, target_is_directory=True)
                    after_attacker.update(self._tree_state(root))
                    return create_authority_bytes(output, data, **kwargs)

                with (
                    chdir(root),
                    patch(
                        "agent_lifecycle.compiler.task_packets.create_authority_bytes", side_effect=swap_before_create
                    ),
                ):
                    args = [
                        "task",
                        "compile-small" if small else "compile",
                        "--manifest",
                        str(path),
                        "--out-dir",
                        "runtime/new",
                        "--write",
                    ]
                    if small:
                        args += ["--context-profile", str(ROOT / "profiles/small-context-profile.v1.json")]
                    code, payload = _run_cli(args)
                self.assertEqual(code, 2)
                self.assertEqual(payload["code"], "authority-input-symlink")
                self.assertTrue(after_attacker)
                self.assertEqual(self._tree_state(root), after_attacker)
                self.assertEqual(self._tree_state(protected), protected_before)
                diagnostic = json.dumps(payload)
                for private in (root.name, "private-output-payload", "private-event-payload", "runtime/new"):
                    self.assertNotIn(private, diagnostic)

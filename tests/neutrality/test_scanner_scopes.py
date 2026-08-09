from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.neutrality.errors import NeutralityError
from agent_lifecycle.neutrality.gate import _claims as build_gate_claims
from agent_lifecycle.neutrality.paths import StableReadRaceError, StableReadResult
from agent_lifecycle.neutrality.policy import load_policy
from agent_lifecycle.neutrality.receipt import build_claims, require_zero_completeness_counters
from agent_lifecycle.neutrality.scanner import (
    _parse_git_tracked_entries,
    _walk_local_artifacts,
    scan_repository,
)


class NeutralityScopeTests(unittest.TestCase):
    def test_tracked_release_ignores_untracked_files_and_binds_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repository(root)
            (root / "tracked.txt").write_text("portable", encoding="utf-8")
            self._git(root, "add", "tracked.txt")
            self._git(root, "commit", "-m", "fixture")
            (root / "untracked.txt").write_text("forbidden-marker", encoding="utf-8")

            report = self._scan(root, scope="tracked-release", deny_literals=["forbidden-marker"])
            payload = report.to_json({"operationId": "op"})

            self.assertEqual(report.findings, [])
            self.assertEqual(payload["scopeBinding"]["sourceRevision"], self._git(root, "rev-parse", "HEAD"))
            self.assertEqual(payload["scopeBinding"]["sourceClass"], "git-index")
            self.assertFalse(payload["scopeBinding"]["deprecatedScope"])
            self.assertEqual(payload["scanned"]["trackedFiles"], 1)

    @unittest.skipIf(os.name == "nt", "symlink fixture requires POSIX semantics")
    def test_tracked_symlink_scans_payload_without_following_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            self._init_repository(root)
            target = Path(outside) / "secret.txt"
            target.write_text("forbidden-target-content", encoding="utf-8")
            (root / "link").symlink_to(target)
            self._git(root, "add", "link")
            self._git(root, "commit", "-m", "symlink")

            report = self._scan(root, scope="tracked-release", deny_literals=["forbidden-target-content"])

            self.assertEqual(report.findings, [])
            self.assertEqual(report.scanned_tracked_files, 1)

    def test_missing_tracked_file_fails_required_completeness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repository(root)
            path = root / "tracked.txt"
            path.write_text("portable", encoding="utf-8")
            self._git(root, "add", "tracked.txt")
            self._git(root, "commit", "-m", "fixture")
            path.unlink()

            payload = self._scan(root, scope="tracked-release").to_json({"operationId": "op"})

            self.assertEqual(payload["counters"]["skippedInputs"], 1)
            self.assertGreaterEqual(payload["counters"]["incompleteScans"], 1)
            with self.assertRaises(NeutralityError):
                require_zero_completeness_counters(payload)

    def test_tracked_symlink_payload_regular_file_checkout_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repository(root)
            (root / "link").write_text("relative/target", encoding="utf-8")
            self._git(root, "add", "link")
            self._git(root, "commit", "-m", "fixture")
            with patch(
                "agent_lifecycle.neutrality.scanner._git_tracked_entries",
                return_value=[{"path": "link", "mode": "120000", "objectId": "a" * 40, "stage": 0}],
            ):
                report = self._scan(root, scope="tracked-release", deny_literals=["relative/target"])
            self.assertEqual(report.findings[0].source, "link")
            self.assertEqual(report.incomplete_scans, 0)

    def test_local_artifacts_require_explicit_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repository(root)
            (root / "tracked.txt").write_text("portable", encoding="utf-8")
            self._git(root, "add", "tracked.txt")
            self._git(root, "commit", "-m", "fixture")
            (root / "work").mkdir()
            (root / "work/local.txt").write_text("local-marker", encoding="utf-8")

            default_report = self._scan(root, scope="tracked-release", deny_literals=["local-marker"])
            included_report = self._scan(
                root,
                scope="tracked-release",
                deny_literals=["local-marker"],
                include_local_artifacts=True,
            )

            self.assertEqual(default_report.findings, [])
            self.assertEqual(included_report.findings[0].source, "work/local.txt")
            payload = included_report.to_json({"operationId": "op"})
            self.assertTrue(payload["scopeBinding"]["includeLocalArtifacts"])
            self.assertEqual(payload["scopeBinding"]["localArtifactRoots"], ["work"])
            self.assertEqual(payload["scanned"]["localArtifacts"], 1)

    def test_tracked_file_in_local_root_is_not_scanned_twice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repository(root)
            (root / "work").mkdir()
            (root / "work/tracked.txt").write_text("portable", encoding="utf-8")
            self._git(root, "add", "work/tracked.txt")
            self._git(root, "commit", "-m", "fixture")

            payload = self._scan(
                root,
                scope="tracked-release",
                include_local_artifacts=True,
            ).to_json({"operationId": "op"})

            self.assertEqual(payload["scanned"]["trackedFiles"], 1)
            self.assertEqual(payload["scanned"]["localArtifacts"], 0)
            self.assertEqual(payload["scanned"]["files"], 1)

    def test_local_artifact_opt_in_requires_declared_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repository(root)
            policy_path = root / "empty-policy.json"
            policy_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-lifecycle-neutrality-policy.v1",
                        "scan": {},
                        "archives": {},
                        "pathExcludes": [],
                        "denyLiterals": [],
                        "denyRegexes": [],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(NeutralityError):
                scan_repository(
                    workspace_root=root,
                    policy=load_policy(policy_path),
                    deny_literals=[],
                    deny_regexes=[],
                    scope="tracked-release",
                    output_paths=[],
                    include_local_artifacts=True,
                )

    def test_missing_declared_local_artifact_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repository(root)
            (root / "tracked.txt").write_text("portable", encoding="utf-8")
            self._git(root, "add", "tracked.txt")
            self._git(root, "commit", "-m", "fixture")

            payload = self._scan(
                root,
                scope="tracked-release",
                include_local_artifacts=True,
            ).to_json({"operationId": "op"})

            self.assertEqual(payload["counters"]["skippedInputs"], 1)
            self.assertEqual(payload["counters"]["incompleteScans"], 1)

    def test_local_artifact_file_budget_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repository(root)
            (root / "tracked.txt").write_text("portable", encoding="utf-8")
            self._git(root, "add", "tracked.txt")
            self._git(root, "commit", "-m", "fixture")
            (root / "work").mkdir()
            (root / "work/one.txt").write_text("one", encoding="utf-8")
            (root / "work/two.txt").write_text("two", encoding="utf-8")
            policy = replace(self._policy(root), max_local_artifact_files=1)

            payload = scan_repository(
                workspace_root=root,
                policy=policy,
                deny_literals=[],
                deny_regexes=[],
                scope="tracked-release",
                output_paths=[],
                include_local_artifacts=True,
            ).to_json({"operationId": "op"})

            self.assertEqual(payload["scanned"]["localArtifacts"], 1)
            self.assertEqual(payload["counters"]["archiveLimitBreaches"], 1)
            self.assertEqual(payload["counters"]["incompleteScans"], 1)

    def test_local_artifact_byte_budget_excludes_overflow_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repository(root)
            (root / "tracked.txt").write_text("portable", encoding="utf-8")
            self._git(root, "add", "tracked.txt")
            self._git(root, "commit", "-m", "fixture")
            (root / "work").mkdir()
            (root / "work/local.txt").write_text("too-large", encoding="utf-8")
            policy = replace(self._policy(root), max_local_artifact_bytes=1)

            payload = scan_repository(
                workspace_root=root,
                policy=policy,
                deny_literals=[],
                deny_regexes=[],
                scope="tracked-release",
                output_paths=[],
                include_local_artifacts=True,
            ).to_json({"operationId": "op"})

            self.assertEqual(payload["scanned"]["localArtifacts"], 0)
            self.assertEqual(payload["counters"]["archiveLimitBreaches"], 1)
            self.assertEqual(payload["counters"]["incompleteScans"], 1)

    def test_local_artifact_enumeration_is_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "work/nested").mkdir(parents=True)
            (root / "work/z.txt").write_text("z", encoding="utf-8")
            (root / "work/a.txt").write_text("a", encoding="utf-8")
            (root / "work/nested/b.txt").write_text("b", encoding="utf-8")

            paths = list(_walk_local_artifacts(root, root / "work"))

            self.assertEqual(paths, ["work/a.txt", "work/z.txt", "work/nested/b.txt"])

    def test_nested_git_metadata_in_local_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repository(root)
            (root / "tracked.txt").write_text("portable", encoding="utf-8")
            self._git(root, "add", "tracked.txt")
            self._git(root, "commit", "-m", "fixture")
            (root / "work/nested/.git/objects").mkdir(parents=True)
            (root / "work/nested/.git/config").write_text("private", encoding="utf-8")

            payload = self._scan(
                root,
                scope="tracked-release",
                include_local_artifacts=True,
            ).to_json({"operationId": "op"})

            self.assertEqual(payload["counters"]["skippedInputs"], 1)
            self.assertEqual(payload["counters"]["incompleteScans"], 1)

    @unittest.skipIf(os.name == "nt", "symlink fixture requires POSIX semantics")
    def test_local_artifact_symlink_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            self._init_repository(root)
            (root / "tracked.txt").write_text("portable", encoding="utf-8")
            self._git(root, "add", "tracked.txt")
            self._git(root, "commit", "-m", "fixture")
            (root / "work").mkdir()
            (root / "work/link").symlink_to(Path(outside))

            payload = self._scan(
                root,
                scope="tracked-release",
                include_local_artifacts=True,
            ).to_json({"operationId": "op"})

            self.assertEqual(payload["counters"]["skippedInputs"], 1)
            self.assertEqual(payload["counters"]["incompleteScans"], 1)

    def test_recovered_race_is_informational_and_signed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "file.txt").write_text("portable", encoding="utf-8")
            with patch(
                "agent_lifecycle.neutrality.scanner.stable_read_bytes_with_retry",
                return_value=StableReadResult(b"portable", True),
            ):
                payload = self._scan(root, scope="current-tree-complete").to_json({"operationId": "op"})

            self.assertEqual(payload["counters"]["recoveredReadRaces"], 1)
            require_zero_completeness_counters(payload)
            claims = self._detached_claims(payload)
            self.assertEqual(claims["subjectDigest"], payload["digests"]["subjectDigest"])

    def test_second_race_is_incomplete_and_excludes_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "file.txt").write_text("portable", encoding="utf-8")
            with patch(
                "agent_lifecycle.neutrality.scanner.stable_read_bytes_with_retry",
                side_effect=StableReadRaceError("stable read identity changed: fixture"),
            ):
                report = self._scan(root, scope="current-tree-complete")

            self.assertEqual(report.read_races, 1)
            self.assertEqual(report.incomplete_scans, 1)
            self.assertEqual(report.scanned_files, 0)

    def test_legacy_scopes_are_deprecated_in_both_claim_builders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "file.txt").write_text("portable", encoding="utf-8")
            payload = self._scan(root, scope="current-tree-complete").to_json({"operationId": "op"})

            detached = self._detached_claims(payload)
            gate = build_gate_claims(self._gate_args(), payload, "a" * 64, "2026-01-01T00:00:00Z")

            self.assertTrue(detached["deprecatedScope"])
            self.assertTrue(gate["deprecatedScope"])
            mutated = json.loads(json.dumps(payload))
            mutated["scopeBinding"]["deprecatedScope"] = False
            self.assertNotEqual(
                self._detached_claims(mutated)["scopeBindingDigest"],
                detached["scopeBindingDigest"],
            )
            self.assertNotEqual(
                build_gate_claims(self._gate_args(), mutated, "a" * 64, "2026-01-01T00:00:00Z")["scopeDigest"],
                gate["scopeDigest"],
            )

    def test_local_binding_changes_both_claim_builders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repository(root)
            (root / "tracked.txt").write_text("portable", encoding="utf-8")
            self._git(root, "add", "tracked.txt")
            self._git(root, "commit", "-m", "fixture")
            (root / "work").mkdir()
            (root / "work/local.txt").write_text("local", encoding="utf-8")
            payload = self._scan(
                root,
                scope="tracked-release",
                include_local_artifacts=True,
            ).to_json({"operationId": "op"})
            detached = self._detached_claims(payload)
            gate = build_gate_claims(self._gate_args(), payload, "a" * 64, "2026-01-01T00:00:00Z")

            mutated = json.loads(json.dumps(payload))
            mutated["scopeBinding"]["localArtifactRootsDigest"] = "f" * 64

            self.assertNotEqual(self._detached_claims(mutated)["scopeBindingDigest"], detached["scopeBindingDigest"])
            self.assertNotEqual(
                build_gate_claims(self._gate_args(), mutated, "a" * 64, "2026-01-01T00:00:00Z")["scopeDigest"],
                gate["scopeDigest"],
            )

    def test_nonzero_index_stage_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repository(root)
            with patch(
                "agent_lifecycle.neutrality.scanner._git_tracked_entries",
                return_value=[{"path": "file.txt", "mode": "100644", "objectId": "a" * 40, "stage": 2}],
            ):
                payload = self._scan(root, scope="tracked-release").to_json({"operationId": "op"})
            self.assertGreaterEqual(payload["counters"]["incompleteScans"], 1)

    def test_malformed_index_bytes_are_rejected_by_parser(self) -> None:
        malformed_records = (
            b"10064x " + b"a" * 40 + b" 0\tfile.txt\0",
            b"100644 not-an-object 0\tfile.txt\0",
            b"100644 " + b"a" * 40 + b" 0\tbad-\xff\0",
            b"missing-tab\0",
        )
        for raw in malformed_records:
            with self.subTest(raw=raw), self.assertRaises(NeutralityError):
                _parse_git_tracked_entries(raw)

    def _scan(
        self,
        root: Path,
        *,
        scope: str,
        deny_literals: list[str] | None = None,
        include_local_artifacts: bool = False,
    ):
        return scan_repository(
            workspace_root=root,
            policy=self._policy(root),
            deny_literals=deny_literals or [],
            deny_regexes=[],
            scope=scope,
            output_paths=[],
            include_local_artifacts=include_local_artifacts,
        )

    @staticmethod
    def _policy(root: Path):
        path = root / "policy.json"
        path.write_text(
            json.dumps(
                {
                    "schemaVersion": "agent-lifecycle-neutrality-policy.v1",
                    "scan": {"maxFileBytes": 1_000_000, "maxObjectBytes": 1_000_000},
                    "archives": {},
                    "pathExcludes": ["^policy\\.json$", "^\\.git/"],
                    "localArtifactRoots": ["work"],
                    "denyLiterals": [],
                    "denyRegexes": [],
                }
            ),
            encoding="utf-8",
        )
        return load_policy(path)

    @staticmethod
    def _init_repository(root: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=root, check=True)

    @staticmethod
    def _git(root: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()

    @staticmethod
    def _detached_claims(report: dict):
        return build_claims(
            operation={"operationId": "op"},
            report=report,
            authority_digest="a" * 64,
            primary_path="out/report.json",
            receipt_path="out/receipt.json",
            policy={"archives": {}},
            profile={},
        )

    @staticmethod
    def _gate_args() -> argparse.Namespace:
        return argparse.Namespace(
            gate_id="gate",
            run_id="run",
            package_id="package",
            task_id="task",
            attempt=1,
            phase="validation",
            operation_id="operation",
            plan_digest="p" * 64,
            source_revision="source",
            receipt="out/receipt.json",
        )


if __name__ == "__main__":
    unittest.main()

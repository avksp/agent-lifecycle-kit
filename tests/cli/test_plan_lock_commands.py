from __future__ import annotations

import contextlib
import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest, write_json_create

try:
    from .helpers import _run_cli
except ImportError:
    from helpers import _run_cli


class PlanLockCommandTests(unittest.TestCase):
    def test_lock_create_writes_only_canonical_verified_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, review_path = _write_reviewed_package(root)
            manifest_before = (root / manifest_path).read_bytes()
            review_before = (root / review_path).read_bytes()

            with contextlib.chdir(root):
                code, payload = _run_cli(
                    [
                        "plan",
                        "lock-create",
                        "--manifest",
                        manifest_path,
                        "--review",
                        review_path,
                    ]
                )
                check_code, check = _run_cli(
                    ["plan", "check", "--manifest", manifest_path, "--lock", payload["lockPath"]]
                )
                verify_code, verification = _run_cli(
                    [
                        "plan",
                        "verify",
                        "--manifest",
                        manifest_path,
                        "--lock",
                        payload["lockPath"],
                        "--package-root",
                        "plans/release-test",
                        "--repository-root",
                        ".",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-plan-lock-creation-receipt.v1")
            self.assertEqual(payload["status"], "PASS")
            self.assertTrue(payload["filesystemVerified"])
            self.assertEqual(payload["lockPath"], "plans/release-test/plan.lock.json")
            self.assertTrue((root / payload["lockPath"]).is_file())
            self.assertEqual(check_code, 0, check)
            self.assertEqual(verify_code, 0, verification)
            self.assertTrue(verification["checks"]["lock"]["result"]["filesystemVerified"])
            self.assertEqual((root / manifest_path).read_bytes(), manifest_before)
            self.assertEqual((root / review_path).read_bytes(), review_before)

    def test_lock_create_is_no_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, review_path = _write_reviewed_package(root)
            args = ["plan", "lock-create", "--manifest", manifest_path, "--review", review_path]

            with contextlib.chdir(root):
                first_code, _first = _run_cli(args)
                second_code, second = _run_cli(args)

            self.assertEqual(first_code, 0)
            self.assertEqual(second_code, 2)
            self.assertEqual(second["code"], "plan-lock-exists")

    def test_lock_create_rejects_non_independent_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, review_path = _write_reviewed_package(root, independent=False)

            with contextlib.chdir(root):
                code, payload = _run_cli(["plan", "lock-create", "--manifest", manifest_path, "--review", review_path])

            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "review-not-independent")
            self.assertFalse((root / "plans/release-test/plan.lock.json").exists())

    def test_lock_create_rejects_stale_review_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, review_path = _write_reviewed_package(root, reviewed_plan_hash="0" * 64)

            with contextlib.chdir(root):
                code, payload = _run_cli(["plan", "lock-create", "--manifest", manifest_path, "--review", review_path])

            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "plan-review-digest-mismatch")
            self.assertFalse((root / "plans/release-test/plan.lock.json").exists())

    def test_lock_create_rejects_case_and_whitespace_normalized_open_findings(self) -> None:
        findings = [
            {"id": "F-0", "severity": "BLOCKER", "status": "open"},
            {"id": "F-C", "severity": "CRITICAL", "status": "open"},
            {"id": "F-1", "severity": "Medium", "status": "Open"},
            {"id": "F-2", "severity": " medium ", "status": " open "},
            {"id": "F-3", "severity": "\tHIGH\n", "status": "OPEN"},
        ]
        for finding in findings:
            with self.subTest(finding=finding), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest_path, review_path = _write_reviewed_package(root, findings=[finding])

                code, payload = _run_lock_create(root, manifest_path, review_path)

                self.assertEqual(code, 2)
                self.assertEqual(payload["code"], "review-open-findings")
                self.assertFalse(_lock_path(root).exists())

    def test_lock_create_rejects_review_and_manifest_mutations_without_writing(self) -> None:
        cases = (
            ("draft", {"status": "DRAFT"}, {}, "plan-not-frozen"),
            ("reopened", {"status": "REOPENED"}, {}, "plan-not-frozen"),
            ("non-independent", {}, {"reviewer.independent": False}, "review-not-independent"),
            ("non-ready", {}, {"verdict": "CHANGES_REQUIRED"}, "plan-review-verdict-invalid"),
            ("package", {}, {"packageId": "other"}, "plan-review-package-mismatch"),
            ("revision", {}, {"planRevision": 2}, "plan-review-revision-mismatch"),
            ("incomplete", {}, {"fullReview": False}, "plan-review-incomplete"),
        )
        for name, manifest_updates, review_updates, expected_code in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest_path, review_path = _write_reviewed_package(root)
                _update_json(root / manifest_path, manifest_updates)
                _update_json(root / review_path, review_updates)

                code, payload = _run_lock_create(root, manifest_path, review_path)

                self.assertEqual(code, 2)
                self.assertEqual(payload["code"], expected_code)
                self.assertFalse(_lock_path(root).exists())

    def test_lock_create_rejects_unbound_or_changed_inputs_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, review_path = _write_reviewed_package(root)
            manifest = _read_json(root / manifest_path)
            manifest["planFiles"].remove(review_path)
            _write_json(root / manifest_path, manifest)

            code, payload = _run_lock_create(root, manifest_path, review_path)

            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "plan-review-unbound")
            self.assertFalse(_lock_path(root).exists())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, review_path = _write_reviewed_package(root)
            _update_json(root / manifest_path, {"operatorNote": "changed after review"})

            code, payload = _run_lock_create(root, manifest_path, review_path)

            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "plan-review-digest-mismatch")
            self.assertFalse(_lock_path(root).exists())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, _review_path = _write_reviewed_package(root)

            code, payload = _run_lock_create(root, manifest_path, "plans/release-test/missing-review.json")

            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "repository-file-missing")
            self.assertFalse(_lock_path(root).exists())

    def test_lock_create_rejects_undeclared_entries_before_writing(self) -> None:
        cases = ("file", "directory", "symlink")
        for kind in cases:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest_path, review_path = _write_reviewed_package(root)
                package = root / "plans/release-test"
                if kind == "file":
                    (package / "undeclared.txt").write_text("unexpected\n", encoding="utf-8")
                    expected_code = "plan-file-undeclared"
                elif kind == "directory":
                    (package / "undeclared").mkdir()
                    expected_code = "plan-directory-undeclared"
                else:
                    target = root / "outside.txt"
                    target.write_text("outside\n", encoding="utf-8")
                    (package / "undeclared-link").symlink_to(target)
                    expected_code = "plan-file-symlink"

                code, payload = _run_lock_create(root, manifest_path, review_path)

                self.assertEqual(code, 2)
                self.assertEqual(payload["code"], expected_code)
                self.assertFalse(_lock_path(root).exists())

    def test_lock_create_rejects_noncanonical_manifest_and_symlink_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _manifest_path, review_path = _write_reviewed_package(root)

            code, payload = _run_lock_create(
                root,
                "plans/release-test/../release-test/plan.manifest.json",
                review_path,
            )

            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "invalid-repo-path")
            self.assertFalse(_lock_path(root).exists())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, review_path = _write_reviewed_package(root)
            target = root / "outside-lock.json"
            _lock_path(root).symlink_to(target)

            code, payload = _run_lock_create(root, manifest_path, review_path)

            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "plan-file-symlink")
            self.assertFalse(target.exists())


def _run_lock_create(root: Path, manifest_path: str, review_path: str) -> tuple[int, dict]:
    with contextlib.chdir(root):
        return _run_cli(["plan", "lock-create", "--manifest", manifest_path, "--review", review_path])


def _lock_path(root: Path) -> Path:
    return root / "plans/release-test/plan.lock.json"


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _update_json(path: Path, updates: dict[str, object]) -> None:
    value = _read_json(path)
    for key, replacement in updates.items():
        target = value
        parts = key.split(".")
        for part in parts[:-1]:
            nested = target.get(part)
            if not isinstance(nested, dict):
                raise AssertionError(f"expected nested object for {key}")
            target = nested
        target[parts[-1]] = replacement
    _write_json(path, value)


def _write_reviewed_package(
    root: Path,
    *,
    independent: bool = True,
    reviewed_plan_hash: str | None = None,
    findings: list[dict] | None = None,
) -> tuple[str, str]:
    package = root / "plans/release-test"
    package.mkdir(parents=True)
    manifest_rel = "plans/release-test/plan.manifest.json"
    review_rel = "plans/release-test/plan-review.json"
    plan_rel = "plans/release-test/plan.md"
    manifest = {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "FROZEN",
        "planRevision": 3,
        "package": {
            "id": "release-test",
            "artifactRoot": "work/release-test",
            "planArtifactRoot": "plans/release-test",
        },
        "planFiles": sorted([manifest_rel, review_rel, plan_rel]),
        "packageIntegrity": {
            "required": True,
            "lockSchemaVersion": "agent-plan-lock.v2",
            "allowedUnlistedFiles": ["plan.lock.json"],
        },
        "planReview": {
            "required": True,
            "verdict": "READY_TO_FREEZE",
            "reviewedRevision": 3,
            "report": review_rel,
        },
        "workstreams": [{"id": "WS-01", "owner": "worker", "dependsOn": [], "writes": ["src/example.py"]}],
    }
    review = {
        "schemaVersion": "agent-plan-review.v1",
        "reviewId": "review-test",
        "packageId": "release-test",
        "planRevision": 3,
        "reviewedPlanHash": reviewed_plan_hash or canonical_digest(manifest),
        "reviewer": {
            "id": "independent-reviewer",
            "independent": independent,
            "runId": "review-run",
            "surface": "test",
        },
        "fullReview": True,
        "verdict": "READY_TO_FREEZE",
        "findings": list(findings or []),
    }
    write_json_create(root / manifest_rel, manifest)
    write_json_create(root / review_rel, review)
    (root / plan_rel).write_text("# Plan\n", encoding="utf-8")
    return manifest_rel, review_rel


if __name__ == "__main__":
    unittest.main()

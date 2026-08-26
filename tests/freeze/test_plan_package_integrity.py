from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.freeze import build_plan_lock_v2, verify_plan_package_integrity

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/freeze/fixtures/canonical-v2-plan-package"


class PlanPackageIntegrityTests(unittest.TestCase):
    def test_intact_fixture_passes_and_exposes_every_entry(self) -> None:
        manifest, lock = _fixture_payload()

        result = verify_plan_package_integrity(manifest, lock, repository_root=ROOT)

        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["filesystemVerified"])
        self.assertEqual(len(result["entries"]), 2)

    def test_same_size_mutation_is_rejected(self) -> None:
        with _temporary_fixture() as (root, package):
            manifest, lock = _fixture_payload(root=root, package=package)
            path = package / "plan.md"
            original = path.read_text(encoding="utf-8")
            path.write_text("X" + original[1:], encoding="utf-8")

            with self.assertRaises(LifecycleError) as raised:
                verify_plan_package_integrity(manifest, lock, repository_root=root)

        self.assertEqual(raised.exception.code, "plan-package-files-mismatch")

    def test_missing_file_is_rejected(self) -> None:
        with _temporary_fixture() as (root, package):
            manifest, lock = _fixture_payload(root=root, package=package)
            (package / "plan.md").unlink()

            with self.assertRaises(LifecycleError) as raised:
                verify_plan_package_integrity(manifest, lock, repository_root=root)

        self.assertIn(raised.exception.code, {"repository-file-missing", "plan-package-files-mismatch"})

    def test_undeclared_top_level_file_is_rejected(self) -> None:
        with _temporary_fixture() as (root, package):
            manifest, lock = _fixture_payload(root=root, package=package)
            (package / "extra.md").write_text("undeclared", encoding="utf-8")

            with self.assertRaises(LifecycleError) as raised:
                verify_plan_package_integrity(manifest, lock, repository_root=root)

        self.assertEqual(raised.exception.code, "plan-file-undeclared")

    def test_undeclared_top_level_directory_is_rejected(self) -> None:
        with _temporary_fixture() as (root, package):
            manifest, lock = _fixture_payload(root=root, package=package)
            (package / "workflow/task-packets").mkdir(parents=True)

            with self.assertRaises(LifecycleError) as raised:
                verify_plan_package_integrity(manifest, lock, repository_root=root)

        self.assertEqual(raised.exception.code, "plan-directory-undeclared")

    def test_duplicate_manifest_path_is_rejected(self) -> None:
        manifest, _lock = _fixture_payload()
        manifest["planFiles"].append(manifest["planFiles"][-1])

        with self.assertRaises(LifecycleError) as raised:
            build_plan_lock_v2(manifest, repository_root=ROOT)

        self.assertEqual(raised.exception.code, "plan-file-duplicate")

    def test_escaping_manifest_path_is_rejected(self) -> None:
        manifest, _lock = _fixture_payload()
        manifest["planFiles"][0] = "tests/freeze/fixtures/canonical-v2-plan-package/../outside.md"

        with self.assertRaises(LifecycleError) as raised:
            build_plan_lock_v2(manifest, repository_root=ROOT)

        self.assertEqual(raised.exception.code, "invalid-repo-path")

    def test_symlinked_declared_file_is_rejected(self) -> None:
        with _temporary_fixture() as (root, package):
            manifest, lock = _fixture_payload(root=root, package=package)
            target = package / "plan.md"
            target.unlink()
            target.symlink_to(root / "outside.md")
            (root / "outside.md").write_text("outside", encoding="utf-8")

            with self.assertRaises(LifecycleError) as raised:
                verify_plan_package_integrity(manifest, lock, repository_root=root)

        self.assertEqual(raised.exception.code, "repository-input-symlink")


def _fixture_payload(*, root: Path = ROOT, package: Path = FIXTURE) -> tuple[dict, dict]:
    manifest = json.loads((package / "plan.manifest.json").read_text(encoding="utf-8"))
    lock = build_plan_lock_v2(manifest, repository_root=root)
    return manifest, lock


class _temporary_fixture:
    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        destination = self.root / "tests/freeze/fixtures/canonical-v2-plan-package"
        destination.parent.mkdir(parents=True)
        shutil.copytree(FIXTURE, destination)
        return self.root, destination

    def __exit__(self, exc_type, exc_value, traceback):
        self.temp.cleanup()


if __name__ == "__main__":
    unittest.main()

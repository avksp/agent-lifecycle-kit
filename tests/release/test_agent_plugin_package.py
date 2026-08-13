from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.release.agent_plugin_package import (
    EXPECTED_SKILLS,
    SCHEMA_ID,
    build_package,
    provenance_for_schema,
    validate_archive,
    validate_manifest,
    validate_package,
    validate_skill_source,
)


ROOT = Path(__file__).resolve().parents[2]


class AgentPluginPackageTests(unittest.TestCase):
    def test_builds_exact_portable_package_and_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "package"
            archive = root / "package.zip"
            result = build_package(root=ROOT, version="1.67.0", output=package, archive=archive)

            self.assertEqual(result["status"], "PASS")
            self.assertEqual(validate_package(package, expected_version="1.67.0")["status"], "PASS")
            self.assertEqual(validate_archive(archive, package_root=package, expected_version="1.67.0")["status"], "PASS")
            self.assertEqual(sorted(path.name for path in (package / "skills").iterdir()), list(EXPECTED_SKILLS))
            self.assertTrue((package / "plugin.json").is_file())
            self.assertFalse((package / "mcp.json").exists())
            with zipfile.ZipFile(archive) as handle:
                self.assertEqual(sorted(handle.namelist()), sorted(_package_files(package)))

    def test_archive_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = build_package(root=ROOT, version="1.67.0", output=root / "one", archive=root / "one.zip")
            second = build_package(root=ROOT, version="1.67.0", output=root / "two", archive=root / "two.zip")
            self.assertEqual(first["status"], "PASS")
            self.assertEqual(second["status"], "PASS")
            self.assertEqual((root / "one.zip").read_bytes(), (root / "two.zip").read_bytes())

    def test_schema_provenance_is_pinned_locally(self) -> None:
        result = provenance_for_schema(ROOT)
        self.assertEqual(result["status"], "PASS", result)
        provenance = json.loads((ROOT / "schemas/agent-plugins/1.0.0/provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance["sourceDigest"], result["schemaDigest"])
        self.assertEqual(provenance["localSchemaDigest"], result["schemaDigest"])

    def test_manifest_rejects_unknown_fields_and_wrong_schema(self) -> None:
        manifest = {"$schema": SCHEMA_ID, "name": "agent-lifecycle-kit", "unexpected": True}
        result = validate_manifest(manifest)
        codes = {item["code"] for item in result["blockers"]}
        self.assertIn("manifest-unknown-fields", codes)

        manifest["$schema"] = "https://example.invalid/schema.json"
        result = validate_manifest(manifest)
        self.assertIn("manifest-schema-mismatch", {item["code"] for item in result["blockers"]})

    def test_package_rejects_mcp_and_unexpected_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "package"
            build_package(root=ROOT, version="1.67.0", output=package)
            (package / "mcp.json").write_text("{}\n", encoding="utf-8")
            result = validate_package(package, expected_version="1.67.0")
            codes = {item["code"] for item in result["blockers"]}
            self.assertIn("portable-root-mismatch", codes)
            self.assertIn("forbidden-component-rejected", codes)

    def test_source_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "skills"
            shutil.copytree(ROOT / "skills", source, symlinks=True)
            link = source / EXPECTED_SKILLS[0] / "SKILL.md"
            original = link.read_bytes()
            link.unlink()
            try:
                link.symlink_to(source / EXPECTED_SKILLS[1] / "SKILL.md")
            except OSError as exc:
                self.skipTest(f"symlink unavailable: {exc}")
            result = validate_skill_source(source)
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("symlink-rejected", {item["code"] for item in result["blockers"]})
            link.unlink()
            link.write_bytes(original)

    def test_archive_rejects_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("../escape.txt", "unsafe")
            result = validate_archive(archive)
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("archive-path-invalid", {item["code"] for item in result["blockers"]})


def _package_files(package: Path) -> list[str]:
    return sorted(path.relative_to(package).as_posix() for path in package.rglob("*") if path.is_file())


if __name__ == "__main__":
    unittest.main()

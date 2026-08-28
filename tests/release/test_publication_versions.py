from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS_RELEASE = ROOT / "tools" / "release"
sys.path.insert(0, str(TOOLS_RELEASE))

from publication_contract import build_publication_manifest, validate_publication_tree  # noqa: E402

TARGET_VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
TARGET_REF = f"v{TARGET_VERSION}"


class PublicationVersionTests(unittest.TestCase):
    def test_publication_manifest_records_field_shapes_and_last_policy(self) -> None:
        manifest = build_publication_manifest(target_version=TARGET_VERSION, target_ref=TARGET_REF)
        self.assertEqual(manifest["schemaVersion"], "agent-publication-manifest.v1")
        self.assertFalse(manifest["productionPromotionClaimed"])
        field_forms = {entry["fieldForm"] for entry in manifest["entries"]}
        self.assertEqual(
            field_forms,
            {"version", "source.ref", "package.pin", "changelog.version", "docs.version"},
        )
        self.assertFalse(manifest["lastChannelPolicy"]["pluginVersionMayBeFloating"])
        self.assertEqual(manifest["lastChannelPolicy"]["allowedFloatingRef"], "source-ref-only")

    def test_publication_manifest_exposes_optional_domain_language(self) -> None:
        manifest = build_publication_manifest(target_version=TARGET_VERSION, target_ref=TARGET_REF)
        features = {item["id"]: item for item in manifest["documentedFeatures"]}
        self.assertEqual(features["optional-project-domain-language"]["status"], "OPTIONAL")
        self.assertFalse(features["optional-project-domain-language"]["automaticRename"])

    def test_publication_manifest_exposes_optional_multi_run_view(self) -> None:
        manifest = build_publication_manifest(target_version=TARGET_VERSION, target_ref=TARGET_REF)
        features = {item["id"]: item for item in manifest["documentedFeatures"]}
        self.assertTrue(features["optional-multi-run-attention-view"]["readOnly"])
        self.assertFalse(features["optional-multi-run-attention-view"]["automaticOverlapResolution"])

    def test_publication_manifest_exposes_security_analysis_boundaries(self) -> None:
        manifest = build_publication_manifest(target_version=TARGET_VERSION, target_ref=TARGET_REF)
        feature = {item["id"]: item for item in manifest["documentedFeatures"]}["optional-security-analysis-profile"]
        self.assertEqual(feature["status"], "OPTIONAL")
        self.assertTrue(feature["readOnlyByDefault"])
        self.assertTrue(feature["independentHighSeverityVerification"])
        self.assertFalse(feature["automaticExecution"])

    def test_publication_manifest_exposes_workflow_evidence_boundaries(self) -> None:
        manifest = build_publication_manifest(target_version=TARGET_VERSION, target_ref=TARGET_REF)
        feature = {item["id"]: item for item in manifest["documentedFeatures"]}["workflow-evidence-validation"]
        self.assertEqual(feature["status"], "REQUIRED")
        self.assertTrue(feature["workerIdentityRequired"])
        self.assertTrue(feature["reviewIdRequired"])
        self.assertFalse(feature["historicalEvidenceRewritten"])

    def test_publication_manifest_exposes_bounded_external_tool_jobs(self) -> None:
        manifest = build_publication_manifest(target_version=TARGET_VERSION, target_ref=TARGET_REF)
        feature = {item["id"]: item for item in manifest["documentedFeatures"]}["optional-bounded-external-tool-jobs"]
        self.assertEqual(feature["status"], "OPTIONAL")
        self.assertTrue(feature["adapterOwned"])
        self.assertTrue(feature["immutableAttempts"])
        self.assertFalse(feature["coreNetworkCalls"])
        self.assertFalse(feature["ordinaryWorkflowStateAllocated"])
        self.assertFalse(feature["lifecycleAuthority"])

    def test_publication_manifest_exposes_release_accounting_boundaries(self) -> None:
        manifest = build_publication_manifest(target_version=TARGET_VERSION, target_ref=TARGET_REF)
        feature = {item["id"]: item for item in manifest["documentedFeatures"]}[
            "release-accounting-and-session-handoff"
        ]

        self.assertEqual(feature["status"], "ADVISORY")
        self.assertFalse(feature["missingTelemetryIsZero"])
        self.assertFalse(feature["workflowAuthority"])
        self.assertFalse(feature["rawTranscriptRequired"])

    def test_publication_manifest_exposes_review_efficiency_boundaries(self) -> None:
        manifest = build_publication_manifest(target_version=TARGET_VERSION, target_ref=TARGET_REF)
        feature = {item["id"]: item for item in manifest["documentedFeatures"]}[
            "review-efficiency-and-evidence-independence"
        ]

        self.assertEqual(feature["status"], "ADVISORY")
        self.assertTrue(feature["qualityFloorPreserved"])
        self.assertFalse(feature["missingTelemetryIsZero"])
        self.assertFalse(feature["automaticApply"])
        self.assertFalse(feature["reviewerTextExecutable"])

    def test_publication_manifest_records_successor_adoption_boundary(self) -> None:
        manifest = build_publication_manifest(target_version=TARGET_VERSION, target_ref=TARGET_REF)

        self.assertEqual(manifest["successorAdoption"]["packageId"], "release-2-7")
        self.assertEqual(manifest["successorAdoption"]["requiredPredecessor"], "release-2-6")
        self.assertFalse(manifest["successorAdoption"]["sourceTracked"])
        self.assertTrue(manifest["successorAdoption"]["acceptedMergeRevisionRequiredBeforeFreeze"])

    def test_current_tree_publication_versions_match_target(self) -> None:
        result = validate_publication_tree(root=ROOT, target_version=TARGET_VERSION, target_ref=TARGET_REF)
        self.assertEqual(result["status"], "PASS", result["blockers"])
        self.assertEqual(result["targetVersion"], TARGET_VERSION)
        self.assertFalse(result["productionPromotionClaimed"])

    def test_stale_plugin_version_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_publication_fixture(root, version=TARGET_VERSION, ref=TARGET_REF)
            _write_json(root / ".codex-plugin/plugin.json", {"name": "agent-lifecycle-kit", "version": "1.29.1"})
            result = validate_publication_tree(root=root, target_version=TARGET_VERSION, target_ref=TARGET_REF)
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("codex-root-plugin", {item["entryId"] for item in result["blockers"]})

    def test_stale_marketplace_ref_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_publication_fixture(root, version=TARGET_VERSION, ref=TARGET_REF)
            _write_json(
                root / ".agents/plugins/marketplace.json",
                {
                    "name": "agent-lifecycle-kit",
                    "plugins": [
                        {
                            "name": "agent-lifecycle-kit",
                            "source": {
                                "source": "url",
                                "url": "https://github.com/avksp/agent-lifecycle-kit.git",
                                "ref": "v1.29.1",
                            },
                        }
                    ],
                },
            )
            result = validate_publication_tree(root=root, target_version=TARGET_VERSION, target_ref=TARGET_REF)
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("codex-marketplace-source-ref", {item["entryId"] for item in result["blockers"]})

    def test_stale_install_guide_package_pin_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_publication_fixture(root, version=TARGET_VERSION, ref=TARGET_REF)
            (root / "docs/guides/install-and-first-run.md").write_text(
                "python -m pip install agent-lifecycle-kit==1.29.1\n",
                encoding="utf-8",
            )
            result = validate_publication_tree(root=root, target_version=TARGET_VERSION, target_ref=TARGET_REF)
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("install-guide-package-pin", {item["entryId"] for item in result["blockers"]})

    def test_secondary_stale_package_pin_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_publication_fixture(root, version=TARGET_VERSION, ref=TARGET_REF)
            path = root / "docs/guides/install-and-first-run.md"
            path.write_text(
                path.read_text(encoding="utf-8") + "agent-lifecycle-kit==1.29.1\n",
                encoding="utf-8",
            )

            result = validate_publication_tree(root=root, target_version=TARGET_VERSION, target_ref=TARGET_REF)

            self.assertEqual(result["status"], "FAIL")
            self.assertIn("install-guide-package-pin", {item["entryId"] for item in result["blockers"]})

    def test_stale_changelog_release_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_publication_fixture(root, version=TARGET_VERSION, ref=TARGET_REF)
            (root / "CHANGELOG.md").write_text("## 1.29.1 - 2026-01-01\n", encoding="utf-8")

            result = validate_publication_tree(root=root, target_version=TARGET_VERSION, target_ref=TARGET_REF)

            self.assertEqual(result["status"], "FAIL")
            self.assertIn("changelog-release-version", {item["entryId"] for item in result["blockers"]})

    def test_stale_russian_docs_prose_version_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_publication_fixture(root, version=TARGET_VERSION, ref=TARGET_REF)
            path = root / "docs/ru/README.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    f"**Версия:** {TARGET_VERSION}",
                    "**Версия:** 1.29.1",
                ),
                encoding="utf-8",
            )

            result = validate_publication_tree(root=root, target_version=TARGET_VERSION, target_ref=TARGET_REF)

            self.assertEqual(result["status"], "FAIL")
            self.assertIn("docs-index-ru-prose-version", {item["entryId"] for item in result["blockers"]})

    def test_publication_manifest_tracks_every_exact_package_pin(self) -> None:
        manifest = build_publication_manifest(target_version=TARGET_VERSION, target_ref=TARGET_REF)
        pin_paths = {entry["path"] for entry in manifest["entries"] if entry["fieldForm"] == "package.pin"}
        self.assertEqual(
            pin_paths,
            {
                "README.md",
                "docs/README.md",
                "docs/ru/README.md",
                "docs/guides/install-and-first-run.md",
                "docs/ru/guides/install-and-first-run.md",
                "docs/reference/cli.md",
                "docs/ru/reference/cli.md",
            },
        )

    def test_cli_writes_fail_evidence_and_nonzero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_publication_fixture(root, version=TARGET_VERSION, ref="v1.29.1")
            evidence = root / "evidence.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(TOOLS_RELEASE / "validate_publication_versions.py"),
                    "--root",
                    str(root),
                    "--target-version",
                    TARGET_VERSION,
                    "--target-ref",
                    TARGET_REF,
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["schemaVersion"], "agent-publication-version-validation.v1")
            self.assertEqual(payload["status"], "FAIL")


def _write_publication_fixture(root: Path, *, version: str, ref: str) -> None:
    (root / "src/agent_lifecycle").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "agent-lifecycle-kit"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        f'version = 1\n\n[[package]]\nname = "agent-lifecycle-kit"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (root / "src/agent_lifecycle/_version.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    (root / "CHANGELOG.md").write_text(f"## {version} - 2026-01-01\n", encoding="utf-8")
    for path in (
        ".codex-plugin/plugin.json",
        ".claude-plugin/plugin.json",
        ".cursor-plugin/plugin.json",
        "adapters/claude/.claude-plugin/plugin.json",
        "adapters/codex/.codex-plugin/plugin.json",
        "adapters/cursor/.cursor-plugin/plugin.json",
    ):
        _write_json(root / path, {"name": "agent-lifecycle-kit", "version": version})
    _write_json(
        root / ".agents/plugins/marketplace.json",
        {
            "name": "agent-lifecycle-kit",
            "plugins": [
                {
                    "name": "agent-lifecycle-kit",
                    "source": {
                        "source": "url",
                        "url": "https://github.com/avksp/agent-lifecycle-kit.git",
                        "ref": ref,
                    },
                }
            ],
        },
    )
    _write_json(
        root / ".claude-plugin/marketplace.json",
        {
            "name": "agent-lifecycle-kit",
            "plugins": [
                {
                    "name": "agent-lifecycle-kit",
                    "source": {"source": "github", "repo": "avksp/agent-lifecycle-kit", "ref": ref},
                    "version": version,
                }
            ],
        },
    )
    _write_json(
        root / ".cursor-plugin/marketplace.json",
        {
            "name": "agent-lifecycle-kit",
            "metadata": {"version": version},
            "plugins": [{"name": "agent-lifecycle-kit", "source": ".", "version": version}],
        },
    )
    for path in (
        "README.md",
        "docs/README.md",
        "docs/ru/README.md",
        "docs/guides/install-and-first-run.md",
        "docs/ru/guides/install-and-first-run.md",
        "docs/reference/cli.md",
        "docs/ru/reference/cli.md",
    ):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"python -m pip install agent-lifecycle-kit=={version}\n", encoding="utf-8")
    russian_index = root / "docs/ru/README.md"
    russian_index.write_text(
        russian_index.read_text(encoding="utf-8") + f"**Версия:** {version}\n",
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

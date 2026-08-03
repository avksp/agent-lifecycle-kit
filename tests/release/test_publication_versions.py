from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS_RELEASE = ROOT / "tools" / "release"
sys.path.insert(0, str(TOOLS_RELEASE))

from publication_contract import build_publication_manifest, validate_publication_tree  # noqa: E402


TARGET_VERSION = "1.32.0"
TARGET_REF = "v1.32.0"


class PublicationVersionTests(unittest.TestCase):
    def test_publication_manifest_records_field_shapes_and_last_policy(self) -> None:
        manifest = build_publication_manifest(target_version=TARGET_VERSION, target_ref=TARGET_REF)
        self.assertEqual(manifest["schemaVersion"], "agent-publication-manifest.v1")
        self.assertFalse(manifest["productionPromotionClaimed"])
        field_forms = {entry["fieldForm"] for entry in manifest["entries"]}
        self.assertEqual(field_forms, {"version", "source.ref"})
        self.assertFalse(manifest["lastChannelPolicy"]["pluginVersionMayBeFloating"])
        self.assertEqual(manifest["lastChannelPolicy"]["allowedFloatingRef"], "source-ref-only")

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


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

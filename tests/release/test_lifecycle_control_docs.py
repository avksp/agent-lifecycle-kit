from __future__ import annotations

import json
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "release"))

from publication_contract import build_publication_manifest  # noqa: E402


ADAPTER_IDS = (
    "claude",
    "codex",
    "cursor",
    "gemini-cli",
    "goose",
    "grok-build",
    "hermes",
    "kimi-code",
    "opencode",
    "openinterpreter",
    "pi",
    "qwen-code",
)


class LifecycleControlDocumentationTests(unittest.TestCase):
    def test_central_reference_documents_the_optional_contract(self) -> None:
        for relative_path in (
            "docs/adapters/lifecycle-control.md",
            "docs/ru/adapters/lifecycle-control.md",
        ):
            text = (ROOT / relative_path).read_text(encoding="utf-8")
            for marker in (
                "GUIDANCE_ONLY",
                "OBSERVED",
                "ENFORCED",
                "declaredLevel",
                "supportedLevel",
                "qualifiedLevel",
                "qualificationStatus",
                "file-edit",
                "shell-command",
                "task-accept",
                "run-finalize",
                "agent-lifecycle-control-request.v1",
                "agent-lifecycle-control-qualification.v1",
                "NO_RECOMMENDATION",
                "WRAPPER_ONLY",
            ):
                self.assertIn(marker, text, f"{marker} missing from {relative_path}")

    def test_each_adapter_page_matches_its_descriptor(self) -> None:
        for adapter_id in ADAPTER_IDS:
            descriptor = _load_json(f"adapters/{adapter_id}/adapter.descriptor.json")
            operation_names = {item["name"] for item in descriptor["operations"]}
            expected_levels = {
                field: {item[field] for item in descriptor["operations"]}
                for field in (
                    "declaredLevel",
                    "supportedLevel",
                    "qualifiedLevel",
                    "qualificationStatus",
                )
            }
            managed_status = descriptor["managedLaunch"]["status"]

            for relative_path in (
                f"docs/adapters/{adapter_id}.md",
                f"docs/ru/adapters/{adapter_id}.md",
            ):
                text = (ROOT / relative_path).read_text(encoding="utf-8")
                for operation_name in operation_names:
                    self.assertIn(f"`{operation_name}`", text, f"{operation_name} missing from {relative_path}")
                for field, values in expected_levels.items():
                    for value in values:
                        self.assertIn(f"`{field}: {value}`", text, f"{field}={value} missing from {relative_path}")
                self.assertIn(f"`{managed_status}`", text, f"managed launch missing from {relative_path}")
                self.assertIn("lifecycle-control.md", text)
                self.assertIn("usage-modes.md", text)

    def test_support_indexes_link_every_adapter_and_publish_current_status(self) -> None:
        for relative_path in (
            "docs/adapters/support-matrix.md",
            "docs/ru/adapters/support-matrix.md",
        ):
            text = (ROOT / relative_path).read_text(encoding="utf-8")
            for adapter_id in ADAPTER_IDS:
                self.assertIn(f"({adapter_id}.md)", text, f"{adapter_id} missing from {relative_path}")
            for marker in ("GUIDANCE_ONLY", "NO_RECOMMENDATION", "WRAPPER_ONLY", "lifecycle-control.md"):
                self.assertIn(marker, text, f"{marker} missing from {relative_path}")

    def test_indexes_and_publication_manifest_expose_the_feature(self) -> None:
        for relative_path in ("README.md", "docs/README.md", "docs/ru/README.md"):
            text = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn("lifecycle-control.md", text, f"feature link missing from {relative_path}")

        version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        manifest = build_publication_manifest(target_version=version, target_ref=f"v{version}")
        self.assertIn(
            {
                "id": "optional-adapter-lifecycle-control",
                "status": "OPTIONAL",
                "englishPath": "docs/adapters/lifecycle-control.md",
                "russianPath": "docs/ru/adapters/lifecycle-control.md",
                "bundledAdapterLevel": "GUIDANCE_ONLY",
                "bundledQualificationStatus": "NO_RECOMMENDATION",
            },
            manifest["documentedFeatures"],
        )
        self.assertIn(
            {
                "id": "optional-project-domain-language",
                "status": "OPTIONAL",
                "englishPath": "docs/reference/project-domain-language.md",
                "russianPath": "docs/ru/reference/project-domain-language.md",
                "activatedContexts": ["qualification"],
                "automaticRename": False,
            },
            manifest["documentedFeatures"],
        )


def _load_json(relative_path: str) -> dict[str, object]:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

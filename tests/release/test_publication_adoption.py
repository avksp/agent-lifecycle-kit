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

from validate_publication_adoption import validate_publication_adoption  # noqa: E402


TARGET_VERSION = "1.43.0"


class PublicationAdoptionTests(unittest.TestCase):
    def test_current_docs_pass_adoption_validation(self) -> None:
        result = validate_publication_adoption(root=ROOT, target_version=TARGET_VERSION)

        self.assertEqual(result["schemaVersion"], "agent-publication-adoption-validation.v1")
        self.assertEqual(result["status"], "PASS", result["blockers"])
        self.assertFalse(result["productionPromotionClaimed"])

    def test_missing_project_comparison_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimum_docs(root, target_version=TARGET_VERSION)
            (root / "docs/reference/project-comparison.md").unlink()

            result = validate_publication_adoption(root=root, target_version=TARGET_VERSION)

            self.assertEqual(result["status"], "FAIL")
            self.assertIn("docs/reference/project-comparison.md", {item["path"] for item in result["blockers"]})

    def test_false_publication_claim_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimum_docs(root, target_version=TARGET_VERSION)
            path = root / "docs/guides/quickstart.md"
            path.write_text(path.read_text(encoding="utf-8") + "\nPyPI publication is claimed.\n", encoding="utf-8")

            result = validate_publication_adoption(root=root, target_version=TARGET_VERSION)

            self.assertEqual(result["status"], "FAIL")
            self.assertIn("publication-adoption-false-claim", {item["code"] for item in result["blockers"]})

    def test_cli_writes_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimum_docs(root, target_version=TARGET_VERSION)
            evidence = root / "evidence.json"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(TOOLS_RELEASE / "validate_publication_adoption.py"),
                    "--root",
                    str(root),
                    "--target-version",
                    TARGET_VERSION,
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["schemaVersion"], "agent-publication-adoption-validation.v1")
            self.assertEqual(payload["status"], "PASS")


def _write_minimum_docs(root: Path, *, target_version: str) -> None:
    _write_text(
        root / "README.md",
        "docs/guides/quickstart.md\ndocs/reference/project-comparison.md\npython -m pip install -e .\n",
    )
    _write_text(
        root / "docs/README.md",
        "Project comparison\nreference/project-comparison.md\nManaged adapter session support\n",
    )
    _write_text(
        root / "docs/ru/README.md",
        "сравнение проекта\nreference/project-comparison.md\nуправляемые сессии адаптеров\n",
    )
    _write_text(
        root / "docs/guides/quickstart.md",
        f"Install from source\nInstall from package\nWhen the package is available\nagent-lifecycle-kit=={target_version}\n",
    )
    _write_text(
        root / "docs/ru/quickstart.md",
        f"Установка из исходников\nУстановка из пакета\nЕсли пакет опубликован\nagent-lifecycle-kit=={target_version}\n",
    )
    _write_text(
        root / "docs/adapters/support-matrix.md",
        "Managed launch\n`WRAPPER_ONLY`\nmanaged-session-support.md\n",
    )
    _write_text(
        root / "docs/ru/adapters/support-matrix.md",
        "Управляемый запуск\n`WRAPPER_ONLY`\nmanaged-session-support.md\n",
    )
    _write_text(
        root / "docs/reference/project-comparison.md",
        "lifecycle controller\nnot a runtime\nnot a model broker\nSource of truth remains the frozen ALK plan\n",
    )
    _write_text(
        root / "docs/ru/reference/project-comparison.md",
        "не кодовый агент\nне платформа запуска моделей\nИсточником правды остаётся зафиксированный план ALK\n",
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

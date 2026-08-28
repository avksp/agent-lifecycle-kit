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

from validate_publication_adoption import validate_publication_adoption  # noqa: E402

TARGET_VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


class PublicationAdoptionTests(unittest.TestCase):
    def test_current_docs_pass_adoption_validation(self) -> None:
        result = validate_publication_adoption(root=ROOT, target_version=TARGET_VERSION)

        self.assertEqual(result["schemaVersion"], "agent-publication-adoption-validation.v1")
        self.assertEqual(result["status"], "PASS", result["blockers"])
        self.assertFalse(result["productionPromotionClaimed"])

    def test_security_analysis_documentation_is_present_and_bounded(self) -> None:
        english = (ROOT / "docs/reference/security-analysis-profile.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/reference/security-analysis-profile.md").read_text(encoding="utf-8")
        for text in (english, russian):
            self.assertIn("trusted: false", text)
            self.assertIn("authorityClaimed: false", text)
            self.assertIn("security-analysis-verification-required", text)

    def test_workflow_evidence_validation_is_documented_fail_closed(self) -> None:
        english = (ROOT / "docs/reference/cli.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/reference/cli.md").read_text(encoding="utf-8")
        for text in (english, russian):
            for marker in ("actorRunId", "reviewId", "task-review-invalid", "task-review-self-certification"):
                self.assertIn(marker, text)

    def test_workflow_continuation_is_documented_as_one_guarded_transition(self) -> None:
        english = (ROOT / "docs/reference/workflow-continuation.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/reference/workflow-continuation.md").read_text(encoding="utf-8")
        skill = (ROOT / "skills/agent-workflow-orchestrator/SKILL.md").read_text(encoding="utf-8")

        for text in (english, russian):
            for marker in (
                "workflow continue",
                "--projected-state-revision",
                "--projected-action-digest",
            ):
                self.assertIn(marker, text)
        self.assertIn("exactly one revision", english)
        self.assertIn("увеличивает ревизию состояния ровно на", russian)
        self.assertIn("workflow continue", skill)
        self.assertIn("projected revision and action", skill)
        self.assertIn("replaces no validator or transition", skill)

    def test_external_tool_jobs_are_documented_as_optional_adapter_work(self) -> None:
        english = (ROOT / "docs/reference/external-tool-jobs.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/reference/external-tool-jobs.md").read_text(encoding="utf-8")
        for text in (english, russian):
            for marker in (
                "agent-external-job-request.v1",
                "adapter external-job run",
                ".alk/external-jobs",
                "NO_FINAL_VERDICT",
                "authorityClaimed: false",
                "productionPromotionClaimed: false",
            ):
                self.assertIn(marker, text)
        self.assertIn("ALK core contains no provider client", english)
        self.assertIn(  # noqa: RUF001 - exact Russian documentation marker
            "В ядре ALK нет клиента провайдера",
            russian,
        )

    def test_release_accounting_and_handoff_are_documented_without_authority(self) -> None:
        accounting = (
            (ROOT / "docs/reference/release-accounting.md").read_text(encoding="utf-8"),
            (ROOT / "docs/ru/reference/release-accounting.md").read_text(encoding="utf-8"),
        )
        handoff = (
            (ROOT / "docs/guides/phase-session-handoff.md").read_text(encoding="utf-8"),
            (ROOT / "docs/ru/guides/phase-session-handoff.md").read_text(encoding="utf-8"),
        )
        for text in accounting:
            for marker in (
                "agent-phase-resource-input.v1",
                "agent-release-accounting.v1",
                "UNAVAILABLE",
                "elapsedWallMs",
                "computeMs",
                "ATTESTED",
            ):
                self.assertIn(marker, text)

        for text in handoff:
            for marker in (
                "plan snapshot",
                "plan handoff",
                "context checkpoint",
                "context restore",
                "workflow task-snapshot",
                "workflow task-result",
                "implementationAuthorized: false",
                "proofAuthority",
            ):
                self.assertIn(marker, text)

        cli = (
            (ROOT / "docs/reference/cli.md").read_text(encoding="utf-8"),
            (ROOT / "docs/ru/reference/cli.md").read_text(encoding="utf-8"),
        )
        for text in cli:
            for marker in (
                "agent-lifecycle plan lock-create",
                "--manifest",
                "--review",
                "--repository-root",
                "agent-plan-lock.v2",
                "plan.lock.json",
            ):
                self.assertIn(marker, text)

    def test_review_efficiency_and_independence_are_documented_fail_closed(self) -> None:
        efficiency = (
            (ROOT / "docs/reference/review-efficiency.md").read_text(encoding="utf-8"),
            (ROOT / "docs/ru/reference/review-efficiency.md").read_text(encoding="utf-8"),
        )
        independence = (
            (ROOT / "docs/reference/evidence-independence.md").read_text(encoding="utf-8"),
            (ROOT / "docs/ru/reference/evidence-independence.md").read_text(encoding="utf-8"),
        )
        for text in efficiency:
            for marker in (
                "metrics audit-efficiency",
                "agent-audit-efficiency-input.v1",
                "agent-audit-efficiency-report.v1",
                "qualityFloorPreserved: true",
                "advisoryOnly: true",
                "autoApply: false",
                "UNAVAILABLE",
                "NO_COMPARISON",
            ):
                self.assertIn(marker, text)
        for text in independence:
            for marker in (
                "agent-statistical-evidence-requirement.v1",
                "agent-statistical-evidence-set.v1",
                "agent-statistical-evidence-validation.v1",
                "statistical-check",
                "150",
                "300",
                "10,000" if "# Evidence independence" in text else "10 000",
            ):
                self.assertIn(marker, text)

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
            path = root / "docs/guides/install-and-first-run.md"
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
        "docs/guides/quickstart.md\ndocs/guides/install-and-first-run.md\n"
        "docs/guides/commands-by-task.md\ndocs/reference/project-comparison.md\n"
        "python -m pip install -e .\n",
    )
    _write_text(
        root / "docs/README.md",
        "Project comparison\nreference/project-comparison.md\nManaged adapter session support\n"
        "guides/install-and-first-run.md\nguides/commands-by-task.md\n",
    )
    _write_text(
        root / "docs/ru/README.md",
        "сравнение проекта\nreference/project-comparison.md\nуправляемые сессии адаптеров\n"
        "guides/install-and-first-run.md\nguides/commands-by-task.md\n",
    )
    _write_text(
        root / "docs/guides/quickstart.md",
        "Install ALK and make the first run\n",
    )
    _write_text(
        root / "docs/ru/quickstart.md",
        "Быстрый старт\n",
    )
    _write_text(
        root / "docs/guides/install-and-first-run.md",
        f"Install from a GitHub checkout\nInstall the published package\nagent-lifecycle-kit=={target_version}\nagent-lifecycle version\n",
    )
    _write_text(
        root / "docs/ru/guides/install-and-first-run.md",
        f"Установка из GitHub\nУстановка опубликованного пакета\nagent-lifecycle-kit=={target_version}\nagent-lifecycle version\n",
    )
    _write_text(
        root / "docs/guides/commands-by-task.md",
        "Commands by task\n",
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
        root / "docs/reference/project-domain-language.md",
        "agent-project-domain-language.v1\nproject language check\nproject language audit\nread-only\nqualification\n",
    )
    _write_text(
        root / "docs/ru/reference/project-domain-language.md",
        "agent-project-domain-language.v1\nproject language check\nproject language audit\nтолько для чтения\nqualification\n",
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

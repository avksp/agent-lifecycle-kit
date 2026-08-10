from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET_VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


class ReleaseDocumentationGateTests(unittest.TestCase):
    def test_frozen_release_candidate_rejects_empty_unreleased_changelog(self) -> None:
        # NEG-R03-13 Changelog Or Architecture Drift
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = _section(changelog, "## Unreleased")
        current_release = _section(changelog, "## 1.3.0 - 2026-07-30")
        self.assertNotIn("- No changes yet.", current_release)
        self.assertTrue(
            any(line.startswith("- ") for line in unreleased.splitlines())
            or any(line.startswith("- ") for line in current_release.splitlines())
        )

    def test_root_readmes_are_compact_and_delegate_reference_detail(self) -> None:
        english = (ROOT / "README.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/README.md").read_text(encoding="utf-8")

        self.assertLessEqual(len(english.splitlines()), 180)
        self.assertLessEqual(len(russian.splitlines()), 190)
        for required in (
            "docs/guides/quickstart.md",
            "docs/adapters/install.md",
            "docs/reference/cli.md",
            "docs/reference/project-comparison.md",
            "docs/reference/source-of-truth.md",
        ):
            self.assertIn(required, english)
        self.assertIn("quickstart.md", russian)
        self.assertIn("reference/project-comparison.md", russian)
        self.assertIn("reference/cli.md", russian)
        for adapter in ("Goose", "Grok Build", "OpenInterpreter", "Pi"):
            self.assertIn(adapter, english)
            self.assertIn(adapter, russian)

    def test_release_entry_docs_have_resolving_links(self) -> None:
        for relative in (
            "README.md",
            "docs/README.md",
            "docs/guides/code-review-workflows.md",
            "docs/guides/lifecycle-cookbook.md",
            "docs/guides/bug-forensics-workflows.md",
            "docs/guides/production-resource-security.md",
            "docs/guides/reference-task-evaluation.md",
            "docs/guides/README.ru.md",
            "docs/guides/quickstart.md",
            "docs/guides/quickstart.ru.md",
            "docs/ru/README.md",
            "docs/ru/architecture/system-architecture.md",
            "docs/ru/code-review-workflows.md",
            "docs/ru/lifecycle-cookbook.md",
            "docs/ru/guides/bug-forensics-workflows.md",
            "docs/ru/quickstart.md",
            "docs/ru/guides/production-resource-security.md",
            "docs/ru/guides/reference-task-evaluation.md",
            "docs/ru/adapters/install.md",
            "docs/ru/adapters/progress-bridge-matrix.md",
            "docs/ru/adapters/support-matrix.md",
            "docs/ru/reference/automatic-progress-bridge.md",
            "docs/ru/reference/cli.md",
            "docs/ru/reference/execution-strategy.md",
            "docs/ru/reference/external-memory.md",
            "docs/ru/reference/import-mappers.md",
            "docs/ru/reference/episode-retrieval.md",
            "docs/ru/reference/project-comparison.md",
            "docs/ru/reference/source-of-truth.md",
            "docs/ru/reference/public-contracts.md",
            "docs/ru/reference/adaptive-lifecycle-policy.md",
            "docs/ru/reference/small-model-packets.md",
            "docs/ru/reference/quality-cost-learning.md",
            "docs/ru/reference/readiness-diagnostics.md",
            "docs/ru/reference/reference-task-evaluation.md",
            "docs/ru/reference/lifecycle-cost.md",
            "docs/ru/reference/local-host-launch.md",
            "docs/ru/reference/planning-only-launch.md",
            "docs/ru/reference/qualified-host-launch.md",
            "docs/ru/reference/model-routing.md",
            "docs/ru/reference/risk-aware-execution.md",
            "docs/ru/security/release-security.md",
            "docs/adapters/install.md",
            "docs/adapters/progress-bridge-matrix.md",
            "docs/architecture/system-architecture.md",
            "docs/reference/automatic-progress-bridge.md",
            "docs/reference/cli.md",
            "docs/reference/execution-strategy.md",
            "docs/reference/external-memory.md",
            "docs/reference/import-mappers.md",
            "docs/reference/episode-retrieval.md",
            "docs/reference/project-comparison.md",
            "docs/reference/source-of-truth.md",
            "docs/reference/adaptive-lifecycle-policy.md",
            "docs/reference/model-routing.md",
            "docs/reference/risk-aware-execution.md",
            "docs/reference/small-model-packets.md",
            "docs/reference/local-host-launch.md",
            "docs/reference/planning-only-launch.md",
            "docs/reference/qualified-host-launch.md",
            "docs/reference/readiness-diagnostics.md",
            "docs/reference/reference-task-evaluation.md",
        ):
            with self.subTest(path=relative):
                _assert_links_resolve(ROOT / relative)

    def test_adapter_evidence_index_covers_current_descriptors(self) -> None:
        descriptor_ids = {
            json.loads(path.read_text(encoding="utf-8"))["adapterId"]
            for path in sorted((ROOT / "adapters").glob("*/adapter.descriptor.json"))
        }
        index = json.loads((ROOT / "docs/adapters/evidence/adapter-evidence-summary.v1.json").read_text(encoding="utf-8"))
        indexed_ids = {item["adapterId"] for item in index["adapters"]}

        self.assertEqual(indexed_ids, descriptor_ids)
        for item in index["adapters"]:
            with self.subTest(adapter=item["adapterId"]):
                self.assertTrue((ROOT / item["summaryPath"]).is_file())
                self.assertFalse(item["productionPromotionClaimed"])
                self.assertFalse(item["publicDirectoryApprovalClaimed"])

    def test_quickstart_and_adapter_docs_cover_bounded_commands(self) -> None:
        quickstart = (ROOT / "docs/guides/quickstart.md").read_text(encoding="utf-8")
        quickstart_ru = (ROOT / "docs/ru/quickstart.md").read_text(encoding="utf-8")
        install = (ROOT / "docs/adapters/install.md").read_text(encoding="utf-8")

        for text in (quickstart, quickstart_ru):
            self.assertIn("```bash", text)
            self.assertIn("agent-lifecycle diagnose --no-install-plans", text)
            self.assertIn("agent-lifecycle adapter install-plan", text)
            self.assertIn("agent-lifecycle plan check", text)
            self.assertIn("agent-lifecycle import plan", text)
            self.assertIn("agent-lifecycle context check", text)
            self.assertIn("agent-lifecycle start --adapter codex", text)
            self.assertIn("--mode research", text)
            self.assertIn("--mode implement", text)
            self.assertIn("--resume <session-id>", text)
            self.assertIn("--risk auto", text)
            self.assertIn("risk-aware-execution.md", text)
        self.assertIn("lifecycle-cookbook.md", quickstart)
        self.assertIn("lifecycle-cookbook.md", quickstart_ru)
        for command in (
            "agent-lifecycle adapter validate",
            "agent-lifecycle adapter inspect",
            "agent-lifecycle adapter install-plan",
            "codex plugin",
            "claude plugin",
            "qwen --version",
            "gemini --version",
            "goose --help",
            "kimi --version",
        ):
            self.assertIn(command, install)

    def test_risk_aware_execution_docs_cover_profile_handoff_and_usage(self) -> None:
        for relative_path in (
            "docs/reference/risk-aware-execution.md",
            "docs/ru/reference/risk-aware-execution.md",
        ):
            with self.subTest(path=relative_path):
                text = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn("--risk-profile-out", text)
                self.assertIn("workflow task-start", text)
                self.assertIn("--risk-profile", text)
                self.assertIn("usage.invocations", text)
                self.assertIn("agent-risk-execution-profile.v1", text)

    def test_reference_task_docs_cover_command_metrics_and_boundaries(self) -> None:
        for relative_path in (
            "docs/reference/reference-task-evaluation.md",
            "docs/ru/reference/reference-task-evaluation.md",
            "docs/guides/reference-task-evaluation.md",
            "docs/ru/guides/reference-task-evaluation.md",
        ):
            with self.subTest(path=relative_path):
                text = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn("agent-lifecycle benchmark evaluate", text)
                self.assertIn("falseAcceptanceCount", text)
                self.assertIn("benchmarks/reference-tasks/manifest.json", text)

        english = (ROOT / "docs/reference/reference-task-evaluation.md").read_text(encoding="utf-8")
        self.assertIn("`ATTESTED`, `ESTIMATED`, and `MISSING`", english)
        self.assertIn("does not call a model", english)

        russian = (ROOT / "docs/ru/reference/reference-task-evaluation.md").read_text(encoding="utf-8")
        self.assertIn("`ATTESTED`, `ESTIMATED` и `MISSING`", russian)
        self.assertIn("не вызывает модель", russian)

        for text in (english, russian):
            self.assertIn("agent-lifecycle benchmark compare", text)
            self.assertIn("agent-reference-task-comparison.v1", text)

    def test_execution_strategy_docs_cover_simple_and_advanced_paths(self) -> None:
        for relative_path in (
            "docs/reference/execution-strategy.md",
            "docs/ru/reference/execution-strategy.md",
        ):
            with self.subTest(path=relative_path):
                text = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn("agent-lifecycle start --adapter codex", text)
                self.assertIn("agent-lifecycle strategy resolve", text)
                self.assertIn("agent-lifecycle task compile-small", text)
                self.assertIn("agent-lifecycle benchmark compare", text)
                self.assertIn("DEFERRED_UNTIL_FREEZE", text)
                self.assertIn("agent-execution-strategy.v1", text)

    def test_python_package_guidance_is_synchronized(self) -> None:
        package_url = "https://pypi.org/project/agent-lifecycle-kit/"
        package_pins: list[str] = []
        for relative_path in (
            "README.md",
            "docs/README.md",
            "docs/ru/README.md",
            "docs/guides/quickstart.md",
            "docs/ru/quickstart.md",
            "docs/reference/cli.md",
            "docs/ru/reference/cli.md",
        ):
            with self.subTest(path=relative_path):
                text = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn(package_url, text)
                self.assertIn("Python 3.11-3.14", text)
                match = re.search(r"python -m pip install agent-lifecycle-kit==([0-9]+\.[0-9]+\.[0-9]+)", text)
                self.assertIsNotNone(match)
                package_pins.append(match.group(1))
        self.assertEqual(len(set(package_pins)), 1)

    def test_security_docs_describe_blocked_launch_and_fail_closed_receipts(self) -> None:
        managed_sessions = [
            ROOT / "docs/reference/managed-adapter-sessions.md",
            ROOT / "docs/ru/reference/managed-adapter-sessions.md",
        ]
        for path in managed_sessions:
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                self.assertIn("adapter-generic-launch-disabled", text)
                self.assertIn("WRAPPER_ONLY", text)
                self.assertIn("шаблоны" if "/docs/ru/" in path.as_posix() else "wildcard", text)

        for path in (
            ROOT / "docs/security/neutrality-contract.md",
            ROOT / "docs/ru/security/neutrality-contract.md",
        ):
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                self.assertIn("readRaces", text)
                self.assertIn("pathAliasConflicts", text)

        readiness = (ROOT / "docs/reference/readiness-diagnostics.md").read_text(encoding="utf-8")
        self.assertIn("schema-validated installation facts", readiness)

    def test_russian_docs_link_to_russian_docs(self) -> None:
        for path in sorted((ROOT / "docs/ru").rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text):
                target = match.group(1).strip()
                if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                    continue
                target_path = target.split("#", 1)[0]
                if not target_path:
                    continue
                resolved = (path.parent / target_path).resolve()
                self.assertTrue(
                    resolved.is_relative_to((ROOT / "docs/ru").resolve()),
                    f"{path.relative_to(ROOT)} links outside Russian locale: {target}",
                )

    def test_docs_compat_evidence_passes_current_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "docs-compat.json"

            _run("tools/release/validate_docs_compat.py", "--evidence", str(evidence))

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "PASS")
            self.assertFalse(payload["productionPromotionClaimed"])

    def test_docs_compat_rejects_unsupported_verified_current_maturity_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_min_docs(root, unsupported_verified_row=True)
            evidence = root / "docs-compat.json"

            result = _run_no_check(
                "tools/release/validate_docs_compat.py",
                "--root",
                str(root),
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("docs-compat-verified-row", {item["code"] for item in payload["blockers"]})

    def test_docs_compat_accepts_verified_row_backed_by_live_evidence_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_min_docs(root, unsupported_verified_row=False)
            support_matrix = root / "docs/adapters/support-matrix.md"
            support_matrix.write_text(
                support_matrix.read_text(encoding="utf-8") + "| Goose | Projection | VERIFIED | Claim |\n",
                encoding="utf-8",
            )
            _write_text(root / "docs/adapters/evidence/goose-live.md", "Goose live evidence.\n")
            _write_text(
                root / "docs/adapters/evidence/adapter-evidence-summary.v1.json",
                json.dumps(
                    {
                        "schemaVersion": "agent-adapter-evidence-summary-index.v1",
                        "status": "PASS",
                        "productionPromotionClaimed": False,
                        "maturityChangesClaimed": True,
                        "adapters": [
                            {
                                "adapterId": "goose",
                                "host": "goose",
                                "maturity": "VERIFIED",
                                "testedHostRange": "1.45.0",
                                "summaryPath": "docs/adapters/evidence/goose-live.md",
                                "rawEvidenceLocalOnly": True,
                                "evidenceKinds": [
                                    "live-host-conformance",
                                    "live-usage-calibration",
                                    "lifecycle-final-proof",
                                ],
                                "productionPromotionClaimed": False,
                                "publicDirectoryApprovalClaimed": False,
                            }
                        ],
                    }
                ),
            )
            _write_text(root / "adapters/goose/adapter.descriptor.json", '{"adapterId":"goose","host":"goose"}\n')
            evidence = root / "docs-compat.json"

            _run("tools/release/validate_docs_compat.py", "--root", str(root), "--evidence", str(evidence))

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "PASS")

    def test_docs_compat_rejects_missing_public_contract_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_min_docs(root, unsupported_verified_row=False)
            public_contracts = root / "docs/reference/public-contracts.md"
            public_contracts.write_text(
                public_contracts.read_text(encoding="utf-8").replace(
                    "`agent-risk-execution-profile.v1`.\n",
                    "",
                ),
                encoding="utf-8",
            )
            evidence = root / "docs-compat.json"

            result = _run_no_check(
                "tools/release/validate_docs_compat.py",
                "--root",
                str(root),
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            blockers = [item for item in payload["blockers"] if item["code"] == "docs-compat-required-text-missing"]
            self.assertTrue(any("agent-risk-execution-profile.v1" in item["message"] for item in blockers))

    def test_docs_compat_rejects_versioned_feature_prose(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_min_docs(root, unsupported_verified_row=False)
            _write_text(root / "docs/reference/feature.md", "Release 0.16 adds a runtime feature.\n")
            evidence = root / "docs-compat.json"

            result = _run_no_check(
                "tools/release/validate_docs_compat.py",
                "--root",
                str(root),
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("docs-compat-versioned-feature-prose", {item["code"] for item in payload["blockers"]})


def _section(text: str, heading: str) -> str:
    lines = text.splitlines()
    try:
        start = lines.index(heading) + 1
    except ValueError:
        return ""
    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return "\n".join(lines[start:end]).strip()


def _run(script: str, *args: str) -> None:
    subprocess.run([sys.executable, script, *args], cwd=ROOT, check=True)


def _run_no_check(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, script, *args], cwd=ROOT, check=False, text=True, capture_output=True)


def _assert_links_resolve(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    missing = []
    for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text):
        target = match.group(1).strip()
        if not target or target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        target_path = target.split("#", 1)[0]
        if not target_path:
            continue
        if not (path.parent / target_path).resolve().exists():
            missing.append(target)
    if missing:
        raise AssertionError(f"{path.relative_to(ROOT).as_posix()} has missing links: {missing}")


def _write_min_docs(root: Path, *, unsupported_verified_row: bool) -> None:
    _write_text(
        root / "README.md",
        "`VERIFIED` for Codex CLI 0.145.0. `VERIFIED` for Claude Code 2.1.220. `VERIFIED` for OpenCode CLI 1.18.9. `VERIFIED` for Hermes Agent v0.19.0. `VERIFIED` for Qwen Code 0.21.0. `EXPERIMENTAL` means bounded live host conformance and usage/resource calibration are required. Public contracts live in docs/reference/public-contracts.md. https://pypi.org/project/agent-lifecycle-kit/ supports Python 3.11-3.14. agent-lifecycle start --adapter codex. `completionCheck` requires `agent-completion-check-receipt.v1`. `agent-goal-record.v1` produces `agent-objective-snapshot.v1`. `agent-runner-state.v1` produces `agent-runner-snapshot.v1`. `agent-follow-up-register.v1` produces `agent-follow-up-summary.v1`. `agent-worktree-isolation-policy.v1` validates `agent-worktree-attempt-receipt.v1`. `agent-adapter-event-stream-receipt.v1` validates `agent-adapter-event-capture-validation.v1`. `agent-review-verdict.v1` produces `agent-review-routing-summary.v1`. `agent-optional-quality-pack.v1`. `agent-behavior-check-run.v1`. `agent-diagnostic-bundle.v1`. `agent-readonly-status-view.v1`. `agent-workflow-event-feed.v1`. `agent-lifecycle-progress-view.v1`.\n",
    )
    _write_text(
        root / "docs/ru/README.md",
        "`VERIFIED` для Codex CLI 0.145.0. `VERIFIED` для Claude Code 2.1.220. `VERIFIED` для OpenCode CLI 1.18.9. `VERIFIED` для Hermes Agent v0.19.0. `VERIFIED` для Qwen Code 0.21.0. `EXPERIMENTAL` означает, что без калибровки расхода продвижение запрещено. Список в Публичных контрактах: reference/public-contracts.md. https://pypi.org/project/agent-lifecycle-kit/ поддерживает Python 3.11-3.14. agent-lifecycle start --adapter codex. `completionCheck` требует `agent-completion-check-receipt.v1`. `agent-goal-record.v1` создаёт `agent-objective-snapshot.v1`. `agent-runner-state.v1` создаёт `agent-runner-snapshot.v1`. `agent-follow-up-register.v1` создаёт `agent-follow-up-summary.v1`. `agent-worktree-isolation-policy.v1` проверяет `agent-worktree-attempt-receipt.v1`. `agent-adapter-event-stream-receipt.v1` проверяет `agent-adapter-event-capture-validation.v1`. `agent-review-verdict.v1` создаёт `agent-review-routing-summary.v1`. `agent-optional-quality-pack.v1`. `agent-behavior-check-run.v1`. `agent-diagnostic-bundle.v1`. `agent-readonly-status-view.v1`. `agent-workflow-event-feed.v1`. `agent-lifecycle-progress-view.v1`.\n",
    )
    public_contracts = (
        "`completionCheck`.\n"
        "`agent-completion-check-receipt.v1`.\n"
        "`agent-completion-gate-receipt.v1`.\n"
        "`agent-completion-gate-validation.v1`.\n"
        "`agent-goal-record.v1`.\n"
        "`agent-objective-snapshot.v1`.\n"
        "`agent-runner-state.v1`.\n"
        "`agent-runner-snapshot.v1`.\n"
        "`agent-managed-lifecycle-next-action.v1`.\n"
        "`agent-managed-lifecycle-runner-receipt.v1`.\n"
        "`agent-lifecycle-start-receipt.v1`.\n"
        "`agent-adapter-session-receipt.v1`.\n"
        "`agent-managed-adapter-launch-receipt.v1`.\n"
        "`agent-adapter-session-resume-receipt.v1`.\n"
        "`agent-no-model-call-scan.v1`.\n"
        "`agent-plan-completeness-profile.v1`.\n"
        "`agent-plan-completeness-validation.v1`.\n"
        "`agent-implementation-audit-report.v1`.\n"
        "`agent-final-implementation-audit.v1`.\n"
        "`agent-follow-up-register.v1`.\n"
        "`agent-follow-up-summary.v1`.\n"
        "`agent-worktree-isolation-policy.v1`.\n"
        "`agent-worktree-attempt-receipt.v1`.\n"
        "`agent-adapter-event-stream-receipt.v1`.\n"
        "`agent-adapter-event-capture-validation.v1`.\n"
        "`agent-review-verdict.v1`.\n"
        "`agent-review-routing-summary.v1`.\n"
        "`agent-optional-quality-pack.v1`.\n"
        "`agent-behavior-check-run.v1`.\n"
        "`agent-diagnostic-bundle.v1`.\n"
        "`agent-readonly-status-view.v1`.\n"
        "`agent-workflow-event-feed.v1`.\n"
        "`agent-lifecycle-progress-view.v1`.\n"
        "`agent-lifecycle-progress-watch.v1`.\n"
        "`agent-change-summary-receipt.v1`.\n"
        "`agent-progress-bridge-config.v1`.\n"
        "`agent-progress-bridge-receipt.v1`.\n"
        "`agent-progress-hook-policy.v1`.\n"
        "`agent-progress-hook-receipt.v1`.\n"
        "`agent-risk-execution-policy.v1`.\n"
        "`agent-risk-execution-profile.v1`.\n"
        "`agent-execution-strategy.v1`.\n"
        "`agent-execution-strategy-validation.v1`.\n"
        "`agent-lifecycle-quality-floor-decision.v1`.\n"
        "`agent-lifecycle-policy-proposal.v1`.\n"
        "`agent-adaptive-lifecycle-policy-request.v1`.\n"
        "`agent-adaptive-lifecycle-policy-decision.v1`.\n"
        "`agent-adaptive-lifecycle-policy-decision-validation.v1`.\n"
        "`agent-small-model-task-packet.v1`.\n"
        "`agent-small-model-output-contract.v1`.\n"
        "`agent-small-model-output-validation.v1`.\n"
        "`agent-small-model-packet-compile-result.v1`.\n"
        "`agent-task-outcome-index.v1`.\n"
        "`agent-quality-cost-signals.v1`.\n"
        "`agent-quality-cost-signals-summary.v1`.\n"
        "`agent-reference-task-comparison.v1`.\n"
        "`agent-reference-task-comparison-validation.v1`.\n"
        "`agent-failure-classification-receipt.v1`.\n"
        "`agent-failure-classification-validation.v1`.\n"
        "`agent-external-context-import-receipt.v1`.\n"
        "`agent-external-context-import-validation.v1`.\n"
        "Quality-cost learning avoids provider/model leaderboards.\n"
    )
    _write_text(root / "docs/reference/public-contracts.md", public_contracts)
    _write_text(
        root / "docs/ru/reference/public-contracts.md",
        public_contracts
        + "Локальная статистика качества и расхода избегает рейтинги провайдеров.\n",
    )
    _write_text(
        root / "docs/reference/project-comparison.md",
        "lifecycle controller. not a runtime. not a model broker. Source of truth remains the frozen ALK plan.\n",
    )
    _write_text(
        root / "docs/ru/reference/project-comparison.md",
        "не кодовый агент. не платформа запуска моделей. Источником правды остаётся зафиксированный план ALK.\n",
    )
    cli = (
        "import plan --source <file-or-folder>.\n"
        "openspec|spec-kit|bmad|spec-kitty.\n"
        "import plan/check.\n"
        "docs/guides/lifecycle-cookbook.md.\n"
        "docs/ru/lifecycle-cookbook.md.\n"
        "adapter session start/status/resume/promote.\n"
        "adapter run.\n"
        "agent-lifecycle start --adapter <id>.\n"
        "`agent-lifecycle-start-receipt.v1`.\n"
        "`WAITING_FOR_TASK`.\n"
        "`agent-adapter-session-receipt.v1`.\n"
        "https://pypi.org/project/agent-lifecycle-kit/.\n"
        f"python -m pip install agent-lifecycle-kit=={TARGET_VERSION}.\n"
    )
    _write_text(root / "docs/reference/cli.md", cli)
    _write_text(root / "docs/ru/reference/cli.md", cli)
    neutrality = (
        "`tracked-release`.\n"
        "git ls-files -z --stage --cached.\n"
        "--include-local-artifacts.\n"
        "`localArtifactRoots`.\n"
        "`recoveredReadRaces`.\n"
        "`deprecatedScope: true`.\n"
        "without following.\n"
        "без перехода к цели.\n"
    )
    _write_text(root / "docs/reference/neutrality.md", neutrality)
    _write_text(root / "docs/ru/reference/neutrality.md", neutrality)
    _write_text(
        root / "docs/ru/guides/release-candidate.md",
        "`tracked-release`. `--include-local-artifacts`. `localArtifactRoots`. не заменяет.\n",
    )
    cookbook = (
        "Research and planning only.\n"
        "Review a Markdown plan folder.\n"
        "Review code changes.\n"
        "Audit implementation evidence.\n"
        "Coordinate cross-review.\n"
        "Run a risk-aware task.\n"
        "Исследование и планирование.\n"
        "Проверка папки с Markdown-планом.\n"
        "Проверка изменений кода.\n"
        "Аудит подтверждений реализации.\n"
        "Согласованная перепроверка.\n"
        "Запуск с учётом риска.\n"
        "agent-lifecycle start.\n"
        "agent-lifecycle import plan.\n"
        "review-mesh recommend.\n"
        "review-mesh prepare.\n"
        "--risk-profile-out.\n"
        "workflow task-start.\n"
    )
    _write_text(root / "docs/guides/lifecycle-cookbook.md", cookbook)
    _write_text(root / "docs/ru/lifecycle-cookbook.md", cookbook)
    import_mappers = (
        "`openspec-planning`.\n"
        "`github-spec-kit-planning`.\n"
        "`bmad-method-planning`.\n"
        "`spec-kitty-planning`.\n"
        "agent-markdown-source-collection.v1.\n"
        "--dialect openspec.\n"
        "--dialect spec-kit.\n"
    )
    _write_text(root / "docs/reference/import-mappers.md", import_mappers)
    _write_text(root / "docs/ru/reference/import-mappers.md", import_mappers)
    external_memory = (
        "`agent-external-context-import-receipt.v1`.\n"
        "`sourceOfTruth: false`.\n"
        "`rawContentStored: false`.\n"
        "`modelCallsStarted: false`.\n"
        "`networkCallsStarted: false`.\n"
        "`providerApiCallsStarted: false`.\n"
        "agent-lifecycle context external-import.\n"
        "agent-lifecycle context episode-retrieve.\n"
        "cannot satisfy evidence, review or final proof requirements.\n"
        "не закрывает требования по доказательствам.\n"
    )
    _write_text(root / "docs/reference/external-memory.md", external_memory)
    _write_text(root / "docs/ru/reference/external-memory.md", external_memory)
    install = (
        "`agent-lifecycle adapter session start/status/resume/promote`.\n"
        "`agent-lifecycle adapter run`.\n"
        "`agent-adapter-session-receipt.v1`.\n"
        "`managedLaunch.status: WRAPPER_ONLY`.\n"
        "docs/adapters/managed-session-support.md.\n"
        "docs/ru/adapters/managed-session-support.md.\n"
    )
    _write_text(root / "docs/adapters/install.md", install)
    _write_text(root / "docs/ru/adapters/install.md", install)
    implementation_audit = (
        "`agent-implementation-audit-report.v1`.\n"
        "`agent-final-implementation-audit.v1`.\n"
        "agent-lifecycle audit implementation.\n"
        "agent-lifecycle audit final-implementation.\n"
        "`workflow task-accept`.\n"
        "`workflow finalize`.\n"
    )
    _write_text(root / "docs/reference/implementation-audit.md", implementation_audit)
    _write_text(root / "docs/ru/reference/implementation-audit.md", implementation_audit)
    plan_completeness = (
        "`agent-plan-completeness-profile.v1`.\n"
        "`agent-plan-completeness-validation.v1`.\n"
        "agent-lifecycle plan completeness-check.\n"
        "--require-completeness.\n"
        "missing-evidence-route.\n"
        "missing-budget-policy.\n"
    )
    _write_text(root / "docs/reference/plan-completeness.md", plan_completeness)
    _write_text(root / "docs/ru/reference/plan-completeness.md", plan_completeness)
    adaptive_policy = (
        "`agent-lifecycle-quality-floor-decision.v1`.\n"
        "`agent-adaptive-lifecycle-policy-decision.v1`.\n"
        "agent-lifecycle policy adaptive-decision.\n"
        "agent-lifecycle policy adaptive-check.\n"
        "tokens-and-resources.\n"
        "`monetaryFieldsUsed` is always `false`.\n"
        "`monetaryFieldsUsed: false`.\n"
        "quality floor.\n"
        "quality-cost learning.\n"
        "Failure signals.\n"
    )
    _write_text(root / "docs/reference/adaptive-lifecycle-policy.md", adaptive_policy)
    _write_text(root / "docs/ru/reference/adaptive-lifecycle-policy.md", adaptive_policy)
    _write_text(
        root / "docs/reference/model-routing.md",
        "failureSignals.\n"
        "no-model -> local-small-packet -> standard-implementation -> stronger-review -> optional-cross-check.\n"
        "optionalCrossCheckRecommended.\n"
        "downgradeBlocked.\n"
        "providerModelNamesInCore: false.\n"
        "`usage.invocations`.\n"
        "workflow task-start --risk-profile.\n",
    )
    _write_text(
        root / "docs/ru/reference/model-routing.md",
        "`agent-lifecycle-model-usage-receipt.v1`.\n"
        "`usage.invocations`.\n"
        "workflow task-start --risk-profile.\n"
        "risk-aware-execution.md.\n",
    )
    risk_aware = (
        "agent-risk-execution-profile.v1.\n"
        "--risk-profile-out.\n"
        "workflow task-start.\n"
        "--risk-profile.\n"
        "usage.invocations.\n"
        "advisory only.\n"
        "does not call a model or launch an adapter host.\n"
        "рекомендацией.\n"
        "не вызывает модель.\n"
        "не запускает внешний инструмент.\n"
    )
    _write_text(root / "docs/reference/risk-aware-execution.md", risk_aware)
    _write_text(root / "docs/ru/reference/risk-aware-execution.md", risk_aware)
    execution_strategy = (
        "agent-lifecycle start --adapter codex.\n"
        "agent-lifecycle strategy resolve.\n"
        "`agent-execution-strategy.v1`.\n"
        "DEFERRED_UNTIL_FREEZE.\n"
        "agent-lifecycle task compile-small.\n"
        "agent-lifecycle benchmark compare.\n"
        "Automatic adoption eligibility requires no measurement gaps.\n"
        "Пригодность для автоматического принятия требует отсутствия пробелов в измерениях.\n"
    )
    _write_text(root / "docs/reference/execution-strategy.md", execution_strategy)
    _write_text(root / "docs/ru/reference/execution-strategy.md", execution_strategy)
    _write_text(
        root / "docs/reference/quality-cost-learning.md",
        "`agent-task-outcome-index.v1`.\n"
        "`agent-quality-cost-signals.v1`.\n"
        "`agent-lifecycle-recommendation.v1`.\n"
        "agent-lifecycle metrics outcome-index.\n"
        "agent-lifecycle metrics quality-signals.\n"
        "agent-lifecycle metrics learn-recommend.\n"
        "`autoApply: false`.\n"
        "provider/model leaderboards.\n",
    )
    _write_text(
        root / "docs/ru/reference/quality-cost-learning.md",
        "`agent-task-outcome-index.v1`.\n"
        "`agent-quality-cost-signals.v1`.\n"
        "`agent-lifecycle-recommendation.v1`.\n"
        "agent-lifecycle metrics outcome-index.\n"
        "agent-lifecycle metrics quality-signals.\n"
        "agent-lifecycle metrics learn-recommend.\n"
        "`autoApply: false`.\n"
        "provider/model leaderboards.\n",
    )
    reference_task = (
        "agent-lifecycle benchmark evaluate.\n"
        "`agent-reference-task-evaluation.v1`.\n"
        "`agent-reference-task-submission.v1`.\n"
        "`ATTESTED`, `ESTIMATED`, and `MISSING`.\n"
        "`ATTESTED`, `ESTIMATED` и `MISSING`.\n"
        "falseAcceptanceCount.\n"
        "does not call a model. не вызывает модель.\n"
        "cannot satisfy production evidence.\n"
        "не заменяет промышленные подтверждения.\n"
        "agent-lifecycle benchmark compare.\n"
        "`agent-reference-task-comparison.v1`.\n"
        "remediation loops. циклов исправления.\n"
        "benchmarks/reference-tasks/manifest.json.\n"
        "accepted-pass.json. accepted-false.json.\n"
        "No model account or external CLI is required.\n"
        "Учётная запись модели и внешний инструмент не требуются.\n"
    )
    _write_text(root / "docs/reference/reference-task-evaluation.md", reference_task)
    _write_text(root / "docs/ru/reference/reference-task-evaluation.md", reference_task)
    _write_text(root / "docs/guides/reference-task-evaluation.md", reference_task)
    _write_text(root / "docs/ru/guides/reference-task-evaluation.md", reference_task)
    _write_text(
        root / "docs/reference/lifecycle-cost.md",
        "agent-lifecycle metrics outcome-index.\n"
        "agent-lifecycle metrics quality-signals.\n"
        "agent-lifecycle metrics learn-recommend.\n"
        "`agent-task-outcome-index.v1`.\n"
        "`agent-quality-cost-signals.v1`.\n"
        "does not require USD fields.\n",
    )
    small_model_packets = (
        "`agent-small-model-task-packet.v1`.\n"
        "`agent-small-model-output-contract.v1`.\n"
        "`agent-small-model-task-result.v1`.\n"
        "`agent-small-model-output-validation.v1`.\n"
        "agent-lifecycle task compile-small.\n"
        "quality floor.\n"
        "write scope.\n"
    )
    _write_text(root / "docs/reference/small-model-packets.md", small_model_packets)
    _write_text(root / "docs/ru/reference/small-model-packets.md", small_model_packets)
    cursor_maturity = "VERIFIED" if unsupported_verified_row else "EXPERIMENTAL"
    _write_text(
        root / "docs/adapters/support-matrix.md",
        "This matrix is the authoritative source-tree support claim.\n"
        "Codex CLI 0.6.0 live evidence.\n"
        "Claude Code 0.5.0 live evidence.\n"
        "OpenCode Host-Local Live Evidence.\n"
        "Hermes Host-Local Live Evidence.\n"
        "Qwen Code Host-Local Live Evidence.\n"
        "Cursor. Gemini CLI. Goose. Grok Build. Kimi Code. OpenInterpreter. Pi.\n"
        "`adapter-event-stream`.\n"
        "`agent-adapter-event-stream-receipt.v1`.\n"
        "| Codex | Projection | VERIFIED | Claim |\n"
        "| Claude Code | Projection | VERIFIED | Claim |\n"
        "| OpenCode | Projection | VERIFIED | Claim |\n"
        "| Hermes | Projection | VERIFIED | Claim |\n"
        "| Qwen Code | Projection | VERIFIED | Claim |\n"
        f"| Cursor | Projection | {cursor_maturity} | Claim |\n",
    )
    _write_text(
        root / "release/notes/v0.19.0.md",
        "Status: source release.\n"
        "Updated package metadata to `0.19.0`.\n"
        "`agent-optional-quality-pack.v1`.\n"
        "`agent-behavior-check-run.v1`.\n"
        "`agent-diagnostic-bundle.v1`.\n"
        "`agent-readonly-status-view.v1`.\n"
        "`agent-workflow-event-feed.v1`.\n"
        "`agent-lifecycle-progress-view.v1`.\n"
        "`agent-lifecycle quality pack-check`.\n"
        "`agent-lifecycle diagnostics bundle`.\n"
        "`agent-lifecycle report status-view`.\n"
        "productionPromotionClaimed.\n",
    )
    _write_text(
        root / "docs/adapters/live-promotion-runbook.md",
        "Source release.\n"
        "Host-specific `VERIFIED`.\n"
        "Public directory approval.\n"
        "Production promotion.\n"
        "validate_adapter_conformance.py.\n"
        "validate_live_host_conformance.py.\n"
        "validate_live_calibration.py.\n"
        "validate_host_env_hygiene.py.\n"
        "validate_support_matrix.py.\n",
    )
    _write_text(
        root / "docs/guides/verified-adapter-release-checklist.md",
        "remote tag.\n"
        "GitHub Release object.\n"
        "CI status.\n"
        "Binary assets are intentionally omitted for a source release.\n"
        "validate_adapter_conformance.py.\n"
        "validate_docs_compat.py.\n"
        "validate_support_matrix.py.\n",
    )
    _write_text(
        root / "docs/reference/completion-check.md",
        "`completionCheck`.\n"
        "`agent-completion-check-receipt.v1`.\n"
        "`agent-completion-gate-receipt.v1`.\n"
        "agent-lifecycle specification completion-gate.\n"
        "`agent-external-action-receipt.v1`.\n"
        "fails closed.\n",
    )
    _write_text(
        root / "docs/reference/goal-continuity.md",
        "`agent-goal-record.v1`.\n"
        "`agent-objective-snapshot.v1`.\n"
        "fails closed.\n"
        "`workflow finalize`.\n",
    )
    _write_text(
        root / "docs/reference/runner.md",
        "`agent-runner-policy.v1`.\n"
        "`agent-runner-transition-request.v1`.\n"
        "`agent-runner-snapshot.v1`.\n"
        "fails closed.\n",
    )
    _write_text(
        root / "docs/reference/follow-up-register.md",
        "`agent-follow-up-register.v1`.\n"
        "`agent-follow-up-summary.v1`.\n"
        "fails closed.\n"
        "`workflow finalize`.\n",
    )
    _write_text(
        root / "docs/reference/worktree-isolation.md",
        "`agent-worktree-isolation-policy.v1`.\n"
        "`agent-worktree-attempt-receipt.v1`.\n"
        "preserved unless.\n"
        "`runner transition`.\n",
    )
    _write_text(
        root / "docs/reference/adapter-event-capture.md",
        "`adapter-event-stream`.\n"
        "`agent-adapter-event.v1`.\n"
        "`agent-adapter-event-stream-receipt.v1`.\n"
        "`agent-adapter-event-capture-validation.v1`.\n"
        "`adapter-owned`.\n"
        "No automatic hook installation.\n"
        "Adapter event capture matrix.\n"
        "fails closed.\n",
    )
    _write_text(
        root / "docs/ru/reference/adapter-event-capture.md",
        "`adapter-event-stream`.\n"
        "`agent-adapter-event.v1`.\n"
        "`agent-adapter-event-stream-receipt.v1`.\n"
        "`adapter-owned`.\n"
        "Автоматическая установка: нет.\n"
        "матрице захвата событий адаптеров.\n",
    )
    event_matrix = (
        "`agent-adapter-event.v1`.\n"
        "`agent-adapter-event-stream-receipt.v1`.\n"
        "No automatic hook installation.\n"
        "`adapter-owned`.\n"
        "conformance/adapters/codex/event-stream-receipt.json.\n"
        "conformance/adapters/qwen-code/event-stream-receipt.json.\n"
    )
    _write_text(root / "docs/adapters/event-capture-matrix.md", event_matrix)
    _write_text(
        root / "docs/ru/adapters/event-capture-matrix.md",
        event_matrix.replace("No automatic hook installation", "Автоматическая установка: нет"),
    )
    _write_text(
        root / "docs/reference/review-verdict.md",
        "`agent-review-verdict.v1`.\n"
        "`agent-review-verdict-validation.v1`.\n"
        "`agent-review-routing-summary.v1`.\n"
        "fails closed.\n"
        "`agent-lifecycle audit review-check`.\n",
    )
    _write_text(
        root / "docs/reference/optional-quality-packs.md",
        "`agent-optional-quality-pack.v1`.\n"
        "`agent-optional-quality-pack-validation.v1`.\n"
        "`agent-behavior-check-fixture.v1`.\n"
        "`agent-behavior-check-run.v1`.\n"
        "resource caps.\n"
        "agent-lifecycle quality pack-check.\n"
        "agent-lifecycle quality behavior-check.\n",
    )
    _write_text(
        root / "docs/reference/diagnostic-bundles.md",
        "`agent-diagnostic-bundle.v1`.\n"
        "redacted.\n"
        "source of truth.\n"
        "artifact count.\n"
        "agent-lifecycle diagnostics bundle.\n",
    )
    _write_text(
        root / "docs/reference/read-only-status-view.md",
        "`agent-readonly-status-view.v1`.\n"
        "`agent-workflow-event-feed.v1`.\n"
        "`agent-lifecycle-progress-view.v1`.\n"
        "`agent-lifecycle-progress-watch.v1`.\n"
        "`agent-change-summary-receipt.v1`.\n"
        "`agent-progress-bridge-receipt.v1`.\n"
        "not source of truth.\n"
        "small local model.\n"
        "agent-lifecycle report status-view.\n"
        "agent-lifecycle report event-feed.\n"
        "agent-lifecycle report progress.\n"
        "agent-lifecycle report progress-bridge.\n"
        "agent-lifecycle report change-summary.\n"
        "--watch.\n"
        "--terminal.\n"
        "host-specific telemetry.\n",
    )
    _write_text(
        root / "docs/ru/reference/read-only-status-view.md",
        "`agent-readonly-status-view.v1`.\n"
        "`agent-workflow-event-feed.v1`.\n"
        "`agent-lifecycle-progress-view.v1`.\n"
        "`agent-lifecycle-progress-watch.v1`.\n"
        "`agent-change-summary-receipt.v1`.\n"
        "`agent-progress-bridge-receipt.v1`.\n"
        "не является источником правды.\n"
        "agent-lifecycle report progress-bridge.\n"
        "--watch.\n"
        "--terminal.\n"
        "телеметрию конкретного хоста.\n",
    )
    _write_text(
        root / "docs/reference/automatic-progress-bridge.md",
        "`agent-progress-bridge-receipt.v1`.\n"
        "`agent-progress-bridge-config.v1`.\n"
        "readOnly: true.\n"
        "modelCallsStarted: false.\n"
        "tokenSpendForProgress: false.\n"
        "hostTelemetryParsedInCore: false.\n"
        "agent-lifecycle report progress-bridge.\n"
        "does not infer missing counts.\n"
        "Host adapters remain responsible.\n",
    )
    _write_text(
        root / "docs/ru/reference/automatic-progress-bridge.md",
        "`agent-progress-bridge-receipt.v1`.\n"
        "`agent-progress-bridge-config.v1`.\n"
        "readOnly: true.\n"
        "modelCallsStarted: false.\n"
        "tokenSpendForProgress: false.\n"
        "hostTelemetryParsedInCore: false.\n"
        "agent-lifecycle report progress-bridge.\n"
        "не вычисляет токены.\n"
        "Адаптеры хостов отвечают.\n",
    )
    _write_text(
        root / "docs/reference/managed-adapter-sessions.md",
        "`agent-adapter-session-receipt.v1`.\n"
        "`agent-managed-adapter-launch-receipt.v1`.\n"
        "`agent-adapter-session-resume-receipt.v1`.\n"
        "adapter session start.\n"
        "adapter session resume.\n"
        "adapter run.\n"
        "agent-lifecycle start.\n"
        "`agent-lifecycle-start-receipt.v1`.\n"
        "`WRAPPER_ONLY`.\n"
        "shell: false.\n"
        "adapter-generic-launch-disabled.\n"
        "wildcard.\n"
        "plugin installation alone.\n"
        "risk-aware-execution.md.\n"
        "--risk-profile-out.\n"
        "local-host-launch.md.\n",
    )
    _write_text(
        root / "docs/ru/reference/managed-adapter-sessions.md",
        "`agent-adapter-session-receipt.v1`.\n"
        "`agent-managed-adapter-launch-receipt.v1`.\n"
        "`agent-adapter-session-resume-receipt.v1`.\n"
        "adapter session start.\n"
        "adapter session resume.\n"
        "adapter run.\n"
        "agent-lifecycle start.\n"
        "`agent-lifecycle-start-receipt.v1`.\n"
        "`WRAPPER_ONLY`.\n"
        "shell: false.\n"
        "adapter-generic-launch-disabled.\n"
        "шаблоны.\n"
        "установка плагина.\n"
        "risk-aware-execution.md.\n"
        "--risk-profile-out.\n"
        "local-host-launch.md.\n",
    )
    local_launch = (
        "`agent-local-host-launch-profile.v1`.\n"
        ".alk/host-launch/.\n"
        "host-launch inspect.\n"
        "host-launch preflight.\n"
        "--launch.\n"
        "--host-launch-profile.\n"
        "launch_from_local_profile.\n"
        "adapter session start --launch.\n"
        "`WRAPPER_ONLY`.\n"
        "Raw task text.\n"
        "Текст задачи.\n"
    )
    _write_text(root / "docs/reference/local-host-launch.md", local_launch)
    _write_text(root / "docs/ru/reference/local-host-launch.md", local_launch)
    qualified_launch = (
        "agent-host-launch-qualification-receipt.v1.\n"
        "adapter launch-profile.\n"
        "0.147.0.\n"
        "2.1.226.\n"
        "1.18.15.\n"
        "WRAPPER_ONLY.\n"
        "FIXTURE_ONLY.\n"
        "acceptedForS1S2: false.\n"
    )
    _write_text(root / "docs/reference/qualified-host-launch.md", qualified_launch)
    _write_text(root / "docs/ru/reference/qualified-host-launch.md", qualified_launch)
    planning_launch = (
        "agent-lifecycle start.\n"
        "--mode plan.\n"
        "--launch.\n"
        "PLANNING_ONLY_QUALIFIED.\n"
        "PLANNING_ONLY_UNSUPPORTED.\n"
        "agent-planning-session-state.v1.\n"
        "agent-planning-launch-receipt.v1.\n"
        "implementationAuthorized: false.\n"
        ".alk/planning-sessions.\n"
        "DRAFT_PLAN_REVIEW.\n"
        "modelCallsStarted.\n"
        "2026.07.23.\n"
        "0.46.0.\n"
        "1.45.0.\n"
        "0.2.118.\n"
        "0.19.0.\n"
        "0.30.0.\n"
        "0.0.34.\n"
        "0.83.0.\n"
        "0.21.8.\n"
    )
    _write_text(root / "docs/reference/planning-only-launch.md", planning_launch)
    _write_text(root / "docs/ru/reference/planning-only-launch.md", planning_launch)
    _write_text(
        root / "docs/reference/readiness-diagnostics.md",
        "`agent-adapter-install-plan.v1`.\n"
        "schema-validated installation facts.\n"
        "argv arrays.\n"
        "Diagnostics never interpret the argv arrays as a shell command.\n",
    )
    _write_text(
        root / "docs/ru/reference/readiness-diagnostics.md",
        "`agent-adapter-install-plan.v1`.\n"
        "argv-массивы.\n"
        "Диагностика не трактует argv-массивы как строку shell.\n",
    )
    _write_text(
        root / "docs/security/neutrality-contract.md",
        "Completeness counters.\n"
        "`readRaces`.\n"
        "`pathAliasConflicts`.\n"
        "fail closed.\n",
    )
    _write_text(
        root / "docs/ru/security/neutrality-contract.md",
        "Счётчики полноты.\n"
        "`readRaces`.\n"
        "`pathAliasConflicts`.\n"
        "ненулевое значение приводит к отказу.\n",
    )
    _write_text(
        root / "docs/adapters/progress-bridge-matrix.md",
        "Progress support is documented separately from adapter maturity.\n"
        "`AUTO`. `WATCH`. `MANUAL`. `UNSUPPORTED`.\n"
        "agent-lifecycle report progress-bridge.\n"
        "No adapter claims unsupported native hooks.\n",
    )
    _write_text(
        root / "docs/ru/adapters/progress-bridge-matrix.md",
        "Поддержка прогресса описывается отдельно от зрелости адаптера.\n"
        "`AUTO`. `WATCH`. `MANUAL`. `UNSUPPORTED`.\n"
        "agent-lifecycle report progress-bridge.\n"
        "не заявляет неподтверждённые прямые hooks хоста.\n",
    )
    _write_text(
        root / "docs/adapters/managed-session-support.md",
        "Managed session support is separate from adapter maturity.\n"
        "`WRAPPER_ONLY`.\n"
        "agent-lifecycle adapter run.\n"
        "does not claim safe native argv launch.\n"
        "plugin installation.\n",
    )
    _write_text(
        root / "docs/ru/adapters/managed-session-support.md",
        "Поддержка управляемых сессий отделена от зрелости адаптера.\n"
        "`WRAPPER_ONLY`.\n"
        "agent-lifecycle adapter run.\n"
        "не заявляет безопасный прямой запуск CLI.\n"
        "подтверждением жизненного цикла.\n",
    )
    for host in (
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
    ):
        _write_text(
            root / f"docs/adapters/{host}.md",
            (
                "This adapter is `VERIFIED` for Codex CLI 0.145.0; live conformance exists and it does not claim public approval.\n"
                if host == "codex"
                else "This adapter is `VERIFIED` for Claude Code 2.1.220; live conformance exists and it does not claim official approval.\n"
                if host == "claude"
                else "This adapter is `VERIFIED` for Goose `1.45.0`; live conformance exists and it does not claim public approval.\n"
                if host == "goose"
                else "This adapter is `VERIFIED` for OpenCode CLI `1.18.9`; live conformance exists and it does not claim npm publication.\n"
                if host == "opencode"
                else "This adapter is `VERIFIED` for Hermes Agent `v0.19.0`; live conformance exists and it does not claim public approval.\n"
                if host == "hermes"
                else "This adapter is `VERIFIED` for Qwen Code `0.21.0`; live conformance exists and it does not claim public approval.\n"
                if host == "qwen-code"
                else "This adapter remains `EXPERIMENTAL`; probe and live conformance evidence are required before promotion.\n"
                if host == "grok-build"
                else "This adapter remains `EXPERIMENTAL` until live conformance evidence exists.\n"
            ),
        )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


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
            "docs/reference/source-of-truth.md",
        ):
            self.assertIn(required, english)
        self.assertIn("quickstart.md", russian)
        self.assertIn("reference/cli.md", russian)
        for adapter in ("Goose", "Grok Build", "OpenInterpreter", "Pi"):
            self.assertIn(adapter, english)
            self.assertIn(adapter, russian)

    def test_release_entry_docs_have_resolving_links(self) -> None:
        for relative in (
            "README.md",
            "docs/README.md",
            "docs/guides/README.ru.md",
            "docs/guides/quickstart.md",
            "docs/guides/quickstart.ru.md",
            "docs/ru/README.md",
            "docs/ru/quickstart.md",
            "docs/ru/adapters/install.md",
            "docs/ru/adapters/support-matrix.md",
            "docs/ru/reference/cli.md",
            "docs/ru/reference/source-of-truth.md",
            "docs/ru/reference/public-contracts.md",
            "docs/ru/reference/adaptive-lifecycle-policy.md",
            "docs/ru/reference/small-model-packets.md",
            "docs/ru/reference/quality-cost-learning.md",
            "docs/ru/reference/readiness-diagnostics.md",
            "docs/ru/reference/lifecycle-cost.md",
            "docs/ru/security/release-security.md",
            "docs/adapters/install.md",
            "docs/reference/cli.md",
            "docs/reference/source-of-truth.md",
            "docs/reference/adaptive-lifecycle-policy.md",
            "docs/reference/model-routing.md",
            "docs/reference/small-model-packets.md",
            "docs/reference/readiness-diagnostics.md",
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
            self.assertIn("agent-lifecycle context check", text)
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
        "`VERIFIED` for Codex CLI 0.145.0. `VERIFIED` for Claude Code 2.1.220. `VERIFIED` for OpenCode CLI 1.18.9. `VERIFIED` for Hermes Agent v0.19.0. `VERIFIED` for Qwen Code 0.21.0. `EXPERIMENTAL` means bounded live host conformance and usage/resource calibration are required. Public contracts live in docs/reference/public-contracts.md. `completionCheck` requires `agent-completion-check-receipt.v1`. `agent-goal-record.v1` produces `agent-objective-snapshot.v1`. `agent-runner-state.v1` produces `agent-runner-snapshot.v1`. `agent-follow-up-register.v1` produces `agent-follow-up-summary.v1`. `agent-worktree-isolation-policy.v1` validates `agent-worktree-attempt-receipt.v1`. `agent-adapter-event-stream-receipt.v1` validates `agent-adapter-event-capture-validation.v1`. `agent-review-verdict.v1` produces `agent-review-routing-summary.v1`. `agent-optional-quality-pack.v1`. `agent-behavior-check-run.v1`. `agent-diagnostic-bundle.v1`. `agent-readonly-status-view.v1`. `agent-workflow-event-feed.v1`. `agent-lifecycle-progress-view.v1`.\n",
    )
    _write_text(
        root / "docs/ru/README.md",
        "`VERIFIED` для Codex CLI 0.145.0. `VERIFIED` для Claude Code 2.1.220. `VERIFIED` для OpenCode CLI 1.18.9. `VERIFIED` для Hermes Agent v0.19.0. `VERIFIED` для Qwen Code 0.21.0. `EXPERIMENTAL` означает, что без калибровки расхода продвижение запрещено. Список в Публичных контрактах: reference/public-contracts.md. `completionCheck` требует `agent-completion-check-receipt.v1`. `agent-goal-record.v1` создаёт `agent-objective-snapshot.v1`. `agent-runner-state.v1` создаёт `agent-runner-snapshot.v1`. `agent-follow-up-register.v1` создаёт `agent-follow-up-summary.v1`. `agent-worktree-isolation-policy.v1` проверяет `agent-worktree-attempt-receipt.v1`. `agent-adapter-event-stream-receipt.v1` проверяет `agent-adapter-event-capture-validation.v1`. `agent-review-verdict.v1` создаёт `agent-review-routing-summary.v1`. `agent-optional-quality-pack.v1`. `agent-behavior-check-run.v1`. `agent-diagnostic-bundle.v1`. `agent-readonly-status-view.v1`. `agent-workflow-event-feed.v1`. `agent-lifecycle-progress-view.v1`.\n",
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
        "`agent-no-model-call-scan.v1`.\n"
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
        "`agent-lifecycle-quality-floor-decision.v1`.\n"
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
        "`agent-failure-classification-receipt.v1`.\n"
        "`agent-failure-classification-validation.v1`.\n"
        "Quality-cost learning avoids provider/model leaderboards.\n"
    )
    _write_text(root / "docs/reference/public-contracts.md", public_contracts)
    _write_text(root / "docs/ru/reference/public-contracts.md", public_contracts)
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
        "providerModelNamesInCore: false.\n",
    )
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
        "fails closed.\n",
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
        "not source of truth.\n"
        "small local model.\n"
        "agent-lifecycle report status-view.\n"
        "agent-lifecycle report event-feed.\n"
        "agent-lifecycle report progress.\n",
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

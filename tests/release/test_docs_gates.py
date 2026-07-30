from __future__ import annotations

import json
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
        current_release = _section(changelog, "## 0.18.0 - 2026-07-30")
        self.assertNotIn("- No changes yet.", current_release)
        self.assertTrue(
            any(line.startswith("- ") for line in unreleased.splitlines())
            or any(line.startswith("- ") for line in current_release.splitlines())
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


def _write_min_docs(root: Path, *, unsupported_verified_row: bool) -> None:
    _write_text(
        root / "README.md",
        "`VERIFIED` for Codex CLI 0.145.0. `VERIFIED` for Claude Code 2.1.220. `VERIFIED` for OpenCode CLI 1.18.9. `VERIFIED` for Hermes Agent v0.19.0. `VERIFIED` for Qwen Code 0.21.0. `EXPERIMENTAL` means bounded live host conformance and usage/cost calibration are required. `completionCheck` requires `agent-completion-check-receipt.v1`. `agent-goal-record.v1` produces `agent-objective-snapshot.v1`. `agent-runner-state.v1` produces `agent-runner-snapshot.v1`. `agent-follow-up-register.v1` produces `agent-follow-up-summary.v1`. `agent-worktree-isolation-policy.v1` validates `agent-worktree-attempt-receipt.v1`. `agent-adapter-event-stream-receipt.v1` validates `agent-adapter-event-capture-validation.v1`. `agent-review-verdict.v1` produces `agent-review-routing-summary.v1`.\n",
    )
    _write_text(
        root / "docs/guides/README.ru.md",
        "`VERIFIED` для Codex CLI 0.145.0. `VERIFIED` для Claude Code 2.1.220. `VERIFIED` для OpenCode CLI 1.18.9. `VERIFIED` для Hermes Agent v0.19.0. `VERIFIED` для Qwen Code 0.21.0. `EXPERIMENTAL` означает, что без калибровки расхода продвижение запрещено. `completionCheck` требует `agent-completion-check-receipt.v1`. `agent-goal-record.v1` создаёт `agent-objective-snapshot.v1`. `agent-runner-state.v1` создаёт `agent-runner-snapshot.v1`. `agent-follow-up-register.v1` создаёт `agent-follow-up-summary.v1`. `agent-worktree-isolation-policy.v1` проверяет `agent-worktree-attempt-receipt.v1`. `agent-adapter-event-stream-receipt.v1` проверяет `agent-adapter-event-capture-validation.v1`. `agent-review-verdict.v1` создаёт `agent-review-routing-summary.v1`.\n",
    )
    cursor_maturity = "VERIFIED" if unsupported_verified_row else "EXPERIMENTAL"
    _write_text(
        root / "docs/adapters/support-matrix.md",
        "This matrix is the authoritative source-tree support claim.\n"
        "Codex CLI 0.6.0 live evidence.\n"
        "Claude Code 0.5.0 live evidence.\n"
        "OpenCode GLM 5.2 live evidence.\n"
        "Hermes GLM 5.2 live evidence.\n"
        "Qwen Code GLM 5.2 live evidence.\n"
        "Cursor, Gemini CLI, and Kimi Code remain `EXPERIMENTAL`.\n"
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
        root / "release/notes/v0.18.0.md",
        "Status: source release.\n"
        "Updated package metadata to `0.18.0`.\n"
        "`agent-adapter-event-stream-receipt.v1`.\n"
        "`agent-adapter-event-capture-validation.v1`.\n"
        "`agent-review-verdict.v1`.\n"
        "`agent-review-verdict-validation.v1`.\n"
        "`agent-lifecycle adapter event-capture-check`.\n"
        "`agent-lifecycle audit review-check`.\n"
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
    for host in ("claude", "codex", "cursor", "gemini-cli", "hermes", "kimi-code", "opencode", "qwen-code"):
        _write_text(
            root / f"docs/adapters/{host}.md",
            (
                "This adapter is `VERIFIED` for Codex CLI 0.145.0; live conformance exists and it does not claim public approval.\n"
                if host == "codex"
                else "This adapter is `VERIFIED` for Claude Code 2.1.220; live conformance exists and it does not claim official approval.\n"
                if host == "claude"
                else "This adapter is `VERIFIED` for OpenCode CLI `1.18.9`; live conformance exists and it does not claim npm publication.\n"
                if host == "opencode"
                else "This adapter is `VERIFIED` for Hermes Agent `v0.19.0`; live conformance exists and it does not claim public approval.\n"
                if host == "hermes"
                else "This adapter is `VERIFIED` for Qwen Code `0.21.0`; live conformance exists and it does not claim public approval.\n"
                if host == "qwen-code"
                else "This adapter remains `EXPERIMENTAL` until live conformance evidence exists.\n"
            ),
        )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

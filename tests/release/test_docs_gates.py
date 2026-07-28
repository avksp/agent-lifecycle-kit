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
        current_release = _section(changelog, "## 0.4.0 - 2026-07-28")
        self.assertNotIn("- No changes yet.", unreleased)
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

    def test_docs_compat_rejects_verified_current_maturity_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_min_docs(root, verified_row=True)
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


def _write_min_docs(root: Path, *, verified_row: bool) -> None:
    _write_text(
        root / "README.md",
        "The adapters are still `EXPERIMENTAL` and not `VERIFIED`; production-promotion evidence is required.\n",
    )
    _write_text(
        root / "docs/guides/README.ru.md",
        "Адаптеры пока имеют статус `EXPERIMENTAL`, статуса `VERIFIED` нет; production-promotion evidence нужен.\n",
    )
    maturity = "VERIFIED" if verified_row else "EXPERIMENTAL"
    _write_text(
        root / "docs/adapters/support-matrix.md",
        "This matrix is the authoritative current source-release support claim.\n"
        "`VERIFIED` is reserved.\n"
        "All current adapters remain `EXPERIMENTAL`.\n"
        f"| Codex | Projection | {maturity} | Claim |\n",
    )
    _write_text(
        root / "release/notes/v0.4.0.md",
        "Status: source release.\n"
        "Bundled adapters remain `EXPERIMENTAL`.\n"
        "Budget caps stop runaway execution.\n",
    )
    for host in ("claude", "codex", "cursor", "hermes", "opencode"):
        _write_text(
            root / f"docs/adapters/{host}.md",
            "This adapter remains `EXPERIMENTAL` until live conformance evidence exists.\n",
        )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import re
import shlex
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.cli.parsers import build_parser
from tests.cli.helpers import _run_cli

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = (
    "security/release-security.md",
    "architecture/system-architecture.md",
    "reference/security-analysis-profile.md",
)


class SecurityDocumentationTests(unittest.TestCase):
    def test_release_175_security_contract_is_historical_in_both_languages(self) -> None:
        english = (ROOT / "docs/security/release-security.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/security/release-security.md").read_text(encoding="utf-8")
        for content, current, historical in (
            (english, "## Current control map", "## Historical release 1.75"),
            (russian, "## Текущая карта контроля", "## Исторические контракты релиза 1.75"),
        ):
            self.assertLess(content.index(current), content.index(historical))
            for term in ("PyPI Trusted Publisher", "Ed25519", "lock", "neutrality-contract.md"):
                self.assertIn(term, content)
        self.assertIn("claims, operation and primary artifact", english)
        self.assertIn("утверждения \u0441 операцией и", russian)

    def test_current_maps_link_existing_owners_checks_and_limits_in_both_languages(self) -> None:
        for name in DOCUMENTS:
            documents = [ROOT / prefix / name for prefix in ("docs", "docs/ru")]
            tables = []
            for path in documents:
                content = path.read_text(encoding="utf-8")
                if name.startswith("architecture/"):
                    content = content.split("## C0:")[0]
                links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", content)
                for link in links:
                    if "://" not in link and not link.startswith("#"):
                        with self.subTest(path=path, link=link):
                            self.assertTrue((path.parent / link.split("#")[0]).exists())
                rows = [line for line in content.splitlines() if line.startswith("| ")][2:]
                self.assertTrue(rows, path)
                owner_checks = set()
                for row in rows:
                    cells = row.strip("|").split("|")
                    self.assertEqual(len(cells), 4, path)
                    self.assertTrue(all(cell.strip() for cell in cells), row)
                    for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", row):
                        target = (path.parent / link).resolve().relative_to(ROOT).as_posix()
                        if target.startswith(("src/", "tests/", "tools/", "policy/", ".github/")):
                            owner_checks.add(target)
                tables.append((owner_checks, set(re.findall(r"`([^`]+)`", "\n".join(rows)))))
            self.assertTrue(tables[0][0], name)
            self.assertEqual(tables[0], tables[1], name)

    def test_security_maps_keep_runtime_ci_optional_and_host_boundaries(self) -> None:
        for prefix in ("docs", "docs/ru"):
            content = (ROOT / prefix / DOCUMENTS[0]).read_text(encoding="utf-8")
            for term in (
                "import-sensitive-content",
                "maxFiles + 1",
                "security-analysis-import-too-large",
                "validate_adapter_launcher_security.py",
                "OPTIONAL",
                "GUIDANCE_ONLY",
                "ORDINARY_LIMITED",
            ):
                self.assertIn(term, content)
            architecture = (ROOT / prefix / DOCUMENTS[1]).read_text(encoding="utf-8")
            for term in (
                "require_condition",
                "closing_instant",
                "financial_transactions.py",
                "_JournalStoragePort",
                "JournalHandle",
                "--check-untyped-defs",
                "declared-ledger-route-unsupported",
                "UNIT_ONLY",
            ):
                self.assertIn(term, architecture)

    def test_documented_analysis_commands_parse_and_run_without_promoting_trust(self) -> None:
        examples = []
        for prefix in ("docs", "docs/ru"):
            content = (ROOT / prefix / DOCUMENTS[2]).read_text(encoding="utf-8")
            blocks = re.findall(r"```bash\n(.*?)```", content, re.S)
            self.assertEqual(len(blocks), 1)
            lines = blocks[0].replace("\\\n", "").strip().splitlines()
            examples.append([shlex.split(line)[1:] for line in lines])
        self.assertEqual(examples[0], examples[1])
        self.assertEqual(len(examples[0]), 4)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "work").mkdir()
            source = {
                "version": "2.1.0",
                "runs": [
                    {
                        "results": [
                            {
                                "ruleId": "SEC-DOCS",
                                "level": "note",
                                "message": {"text": "Review input handling"},
                            }
                        ]
                    }
                ],
            }
            (root / "findings.sarif").write_text(json.dumps(source), encoding="utf-8")
            for command in examples[0]:
                args = [
                    str(root / item) if item == "findings.sarif" or item.startswith("work/") else item
                    for item in command
                ]
                parsed = build_parser(args).parse_args(args)
                code, payload = _run_cli(args)
                self.assertEqual(code, 0, payload)
                self.assertEqual(json.loads(Path(parsed.out).read_text(encoding="utf-8")), payload)
                if "trusted" in payload:
                    self.assertFalse(payload["trusted"])
                    self.assertFalse(payload["authorityClaimed"])
                    self.assertFalse(payload["productionPromotionClaimed"])
                if parsed.command == "report":
                    self.assertEqual(payload["status"], "PASS")
                    self.assertEqual(payload["findings"][0]["findingId"], "SEC-DOCS")
                    self.assertFalse(payload["profile"]["enabledByDefault"])

    def test_security_contract_pages_cover_receipt_binding(self) -> None:
        english = (ROOT / "docs/security/neutrality-contract.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/security/neutrality-contract.md").read_text(encoding="utf-8")
        self.assertIn("claims, operation and the", english)
        self.assertIn("primary artifact identity", english)
        expected_russian = (
            "\u0443\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0438\u044f,"
            " \u043e\u043f\u0435\u0440\u0430\u0446\u0438\u044f \u0438\n"
            "\u0438\u0434\u0435\u043d\u0442\u0438\u0447\u043d\u043e\u0441\u0442\u044c"
            " \u043e\u0441\u043d\u043e\u0432\u043d\u043e\u0433\u043e \u0430"
            "\u0440\u0442\u0435\u0444\u0430\u043a\u0442\u0430"
        )
        self.assertIn(expected_russian, russian)


if __name__ == "__main__":
    unittest.main()

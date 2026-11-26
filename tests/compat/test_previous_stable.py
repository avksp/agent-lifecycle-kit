from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from tools.release.release_common import canonical_bytes, digest_value, write_json
from tools.release.run_compat_suite import FIXTURES, materialize_table, tested_version_table


def fixture_receipt(*, development: bool = False) -> dict:
    import json

    cases = json.loads(FIXTURES.read_bytes())["cases"]
    counts = dict(
        zip(
            (
                "readonly-projection",
                "guarded-action",
                "stale-guards",
                "missing-input",
                "unattested-usage",
                "critical-route",
                "lost-reply",
                "incompatible-contract",
            ),
            (2, 3, 4, 3, 2, 2, 4, 4),
            strict=True,
        )
    )
    call = {"exitCode": 0, "outcome": "RECEIVED", "stdoutSha256": "0" * 64}
    rows = [
        {"caseId": row["id"], "status": "PASS", "calls": [dict(call) for _ in range(counts[row["id"]])]}
        for row in cases
    ]
    body = {
        "schemaVersion": "agent-installed-compatibility-receipt.v1",
        "status": "PASS",
        "developmentCandidate": development,
        "baseline": {"identity": {"version": "2.52.0"}, "cases": rows},
        "candidate": {"identity": {"version": "2.52.0" if development else "2.53.0"}, "cases": copy.deepcopy(rows)},
    }
    return {**body, "receiptDigest": digest_value(body)}


class CompatibilityReceiptTests(unittest.TestCase):
    def test_table_names_only_observed_versions_and_cases(self) -> None:
        table = tested_version_table(fixture_receipt())
        self.assertEqual(table["testedVersions"], ["2.52.0", "2.53.0"])
        self.assertEqual(len(table["cases"]), 8)
        self.assertEqual(tested_version_table(fixture_receipt(development=True))["testedVersions"], [])

    def test_one_deliberate_exit_regression_refuses_even_with_updated_digest(self) -> None:
        receipt = fixture_receipt()
        receipt["candidate"]["cases"][0]["calls"][0]["exitCode"] = 2
        del receipt["receiptDigest"]
        receipt["receiptDigest"] = digest_value(receipt)
        with self.assertRaisesRegex(ValueError, "outcomes differ"):
            tested_version_table(receipt)

    def test_mismatched_table_and_development_table_cannot_be_materialized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "receipt.json"
            table = root / "table.json"
            out = root / "published.json"
            value = fixture_receipt()
            write_json(receipt, value)
            table.write_bytes(b"{}\n")
            with self.assertRaises(ValueError):
                materialize_table(receipt, table, out)
            self.assertFalse(out.exists())
            table.write_bytes(canonical_bytes(tested_version_table(value)) + b"\n")
            materialize_table(receipt, table, out)
            self.assertEqual(out.read_bytes(), table.read_bytes())
            value = fixture_receipt(development=True)
            write_json(receipt, value)
            table.write_bytes(canonical_bytes(tested_version_table(value)) + b"\n")
            with self.assertRaises(ValueError):
                materialize_table(receipt, table, root / "development.json")

    def test_invalid_or_incomplete_case_observations_prevent_materialization(self) -> None:
        for defect in ("failed", "empty", "duplicate", "missing-command", "invalid-command"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                receipt = fixture_receipt()
                table = root / "table.json"
                table.write_bytes(canonical_bytes(tested_version_table(receipt)) + b"\n")
                for side in ("baseline", "candidate"):
                    rows = receipt[side]["cases"]
                    if defect == "failed":
                        rows[0]["status"] = "FAIL"
                    elif defect == "empty":
                        rows[0]["calls"] = []
                    elif defect == "duplicate":
                        rows.append(copy.deepcopy(rows[0]))
                    elif defect == "missing-command":
                        rows[0]["calls"].pop()
                    else:
                        rows[0]["calls"][0]["stdoutSha256"] = ""
                del receipt["receiptDigest"]
                receipt["receiptDigest"] = digest_value(receipt)
                inp = root / "receipt.json"
                write_json(inp, receipt)
                out = root / "published.json"
                with self.assertRaises(ValueError):
                    materialize_table(inp, table, out)
                self.assertFalse(out.exists())

    def test_development_guides_do_not_claim_a_released_version(self) -> None:
        table = tested_version_table(fixture_receipt(development=True))
        self.assertEqual(table["testedVersions"], [])
        root = Path(__file__).resolve().parents[2]
        for relative in (
            "docs/guides/compatibility-and-release-channels.md",
            "docs/ru/guides/compatibility-and-release-channels.md",
        ):
            with self.subTest(relative=relative):
                guide = (root / relative).read_text(encoding="utf-8")
                self.assertNotRegex(guide, r"\b(?:ALK\s+\d+\.\d+|\d+\.\d+\.\d+)\b")

    def test_plan_help_marks_the_individual_preflight_command_as_preview(self) -> None:
        from agent_lifecycle.cli.parsers import build_parser

        parser = build_parser(["plan", "--help"])
        import argparse

        def child(parent, name):
            subparsers = next(a for a in parent._actions if isinstance(a, argparse._SubParsersAction))
            return subparsers.choices[name]

        plan = child(parser, "plan")
        self.assertRegex(plan.format_help(), r"review-preflight\s+\[Preview\]")
        self.assertIn("Preview interface.", child(plan, "review-preflight").format_help())

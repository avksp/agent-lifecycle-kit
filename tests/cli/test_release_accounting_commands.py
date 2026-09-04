from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import write_json_create
from agent_lifecycle.metrics import build_release_accounting, build_release_accounting_source

try:
    from .helpers import _run_cli
except ImportError:
    from helpers import _run_cli


class ReleaseAccountingCommandTests(unittest.TestCase):
    def test_cli_matches_api_and_writes_once(self) -> None:
        source = build_release_accounting_source(
            "2.6.0",
            [_entry()],
            provenance={"coreVersion": "2.6.0", "runAlkVersion": "1.80.0"},
        )
        declared = {"coreVersion": "2.6.0", "runAlkVersion": "2.6.0"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json_create(root / "source.json", source)
            write_json_create(root / "provenance.json", declared)
            expected = build_release_accounting(
                "2.6.0",
                [Path("source.json")],
                project_root=root,
                declared_provenance=declared,
            )

            args = [
                "metrics",
                "release-accounting",
                "--release-id",
                "2.6.0",
                "--project-root",
                str(root),
                "--artifact",
                "source.json",
                "--provenance",
                str(root / "provenance.json"),
                "--out",
                str(root / "release-accounting.json"),
            ]
            code, receipt = _run_cli(args)
            output = json.loads((root / "release-accounting.json").read_bytes())
            second_code, second = _run_cli(args)

        self.assertEqual(code, 0)
        self.assertEqual(output, expected)
        self.assertEqual(receipt["accountingDigest"], expected["accountingDigest"])
        self.assertEqual(receipt["validation"]["status"], "PASS")
        self.assertEqual(second_code, 2)
        self.assertEqual(second["code"], "cli-io-error")

    def test_cli_rejects_artifact_outside_project_root(self) -> None:
        source = build_release_accounting_source("2.6.0", [_entry()])
        with tempfile.TemporaryDirectory() as project_tmp, tempfile.TemporaryDirectory() as outside_tmp:
            root = Path(project_tmp)
            outside = Path(outside_tmp) / "source.json"
            write_json_create(outside, source)
            code, payload = _run_cli(
                [
                    "metrics",
                    "release-accounting",
                    "--release-id",
                    "2.6.0",
                    "--project-root",
                    str(root),
                    "--artifact",
                    str(outside),
                    "--out",
                    str(root / "out.json"),
                ]
            )

        self.assertEqual(code, 2)
        self.assertEqual(payload["code"], "release-accounting-artifact-outside-root")

    def test_cli_rejects_duplicate_artifact_before_writing(self) -> None:
        source = build_release_accounting_source("2.6.0", [_entry()])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json_create(root / "source.json", source)
            output = root / "out.json"
            code, payload = _run_cli(
                [
                    "metrics",
                    "release-accounting",
                    "--release-id",
                    "2.6.0",
                    "--project-root",
                    str(root),
                    "--artifact",
                    "source.json",
                    "--artifact",
                    "source.json",
                    "--out",
                    str(output),
                ]
            )

        self.assertEqual(code, 2)
        self.assertEqual(payload["code"], "release-accounting-source-artifact-duplicate")
        self.assertFalse(output.exists())

    def test_workflow_compare_consumes_exact_predeclared_pair(self) -> None:
        fixtures = Path(__file__).resolve().parents[1] / "metrics" / "fixtures"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "comparison.json"
            code, payload = _run_cli(
                [
                    "metrics",
                    "workflow-compare",
                    "--before",
                    str(fixtures / "release-2-8-continuation-baseline.json"),
                    "--after",
                    str(fixtures / "release-2-10-continuation-baseline.json"),
                    "--comparison-pair",
                    str(fixtures / "release-2-10-continuation-comparison-pair.json"),
                    "--out",
                    str(output),
                ]
            )
            written = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertEqual(payload, written)
        self.assertEqual(payload["implementationStatus"], "PREDECLARED_PAIR")
        self.assertEqual(payload["status"], "MIXED")
        self.assertFalse(payload["authorityClaimed"])

    def test_workflow_recommend_is_advisory_and_create_only(self) -> None:
        fixtures = Path(__file__).resolve().parents[1] / "metrics" / "fixtures"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            comparison_path = root / "comparison.json"
            recommendation_path = root / "recommendation.json"
            compare_code, _ = _run_cli(
                [
                    "metrics",
                    "workflow-compare",
                    "--before",
                    str(fixtures / "release-2-8-continuation-baseline.json"),
                    "--after",
                    str(fixtures / "release-2-10-continuation-baseline.json"),
                    "--comparison-pair",
                    str(fixtures / "release-2-10-continuation-comparison-pair.json"),
                    "--out",
                    str(comparison_path),
                ]
            )
            code, payload = _run_cli(
                [
                    "metrics",
                    "workflow-recommend",
                    "--comparison",
                    str(comparison_path),
                    "--task-shape",
                    "release",
                    "--current-mode",
                    "release",
                    "--required-mode",
                    "release",
                    "--protected-work",
                    "--out",
                    str(recommendation_path),
                ]
            )
            second_code, second = _run_cli(
                [
                    "metrics",
                    "workflow-recommend",
                    "--comparison",
                    str(comparison_path),
                    "--current-mode",
                    "release",
                    "--required-mode",
                    "release",
                    "--out",
                    str(recommendation_path),
                ]
            )

        self.assertEqual(compare_code, 0)
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "PASS")
        self.assertTrue(payload["advisoryOnly"])
        self.assertFalse(payload["autoApply"])
        self.assertFalse(payload["authorityClaimed"])
        self.assertFalse(payload["policyMutationAllowed"])
        self.assertFalse(payload["workflowMutationAllowed"])
        self.assertEqual(second_code, 2)
        self.assertEqual(second["code"], "cli-io-error")


def _entry() -> dict:
    return {
        "entryId": "audit-panel",
        "view": "audit",
        "costCategory": "productValidation",
        "scope": {"kind": "release", "id": "2.6.0", "additive": True},
        "metrics": {
            "tokens": _metric("MEASURED", 100),
            "steps": _metric("MEASURED", 2),
            "elapsedWallMs": _metric("MEASURED", 10),
            "computeMs": _metric("MEASURED", 20),
        },
    }


def _metric(status: str, value: int | None, *, additive: bool = True) -> dict:
    return {"status": status, "value": value, "additive": additive}


if __name__ == "__main__":
    unittest.main()

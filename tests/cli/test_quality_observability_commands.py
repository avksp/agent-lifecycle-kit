from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import _run_cli  # noqa: F401,E402
except ImportError:
    from helpers import _run_cli  # noqa: F401,E402


class CliQualityObservabilityCommandTests(unittest.TestCase):
    def test_quality_pack_and_behavior_check_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "fixture.json"
            fixture.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-behavior-check-fixture.v1",
                        "fixtureId": "false-done",
                        "expectedOutcome": "FAIL",
                        "signals": {"completion": {"status": "FAIL"}},
                    }
                ),
                encoding="utf-8",
            )

            code, pack = _run_cli(["quality", "pack-check"])
            self.assertEqual(code, 0)
            self.assertEqual(pack["schemaVersion"], "agent-optional-quality-pack-validation.v1")
            self.assertEqual(pack["status"], "PASS")

            code, result = _run_cli(["quality", "behavior-check", "--fixture", str(fixture)])
            self.assertEqual(code, 0)
            self.assertEqual(result["schemaVersion"], "agent-behavior-check-run.v1")
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["checks"][0]["actualOutcome"], "FAIL")

    def test_quality_template_and_bug_recipe_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template_out = root / "out/templates.json"
            template_check_out = root / "out/template-check.json"
            recipe_out = root / "out/recipes.json"
            recipe_check_out = root / "out/recipe-check.json"

            code, templates = _run_cli(["quality", "template-list", "--out", str(template_out)])
            self.assertEqual(code, 0)
            self.assertEqual(templates["schemaVersion"], "agent-task-template-library.v1")
            self.assertFalse(templates["enabledByDefault"])
            self.assertTrue(template_out.is_file())

            code, template_check = _run_cli(
                ["quality", "template-check", "--template-id", "bugfix", "--out", str(template_check_out)]
            )
            self.assertEqual(code, 0)
            self.assertEqual(template_check["schemaVersion"], "agent-task-template-library-validation.v1")
            self.assertEqual(template_check["status"], "PASS")
            self.assertEqual(template_check["templateIds"], ["bugfix"])

            code, recipes = _run_cli(["quality", "bug-recipe-list", "--out", str(recipe_out)])
            self.assertEqual(code, 0)
            self.assertEqual(recipes["schemaVersion"], "agent-bug-forensics-recipe-library.v1")
            self.assertTrue(recipes["reusesExistingReceiptSchemas"])
            self.assertEqual(recipes["competingReceiptSchemas"], [])

            code, recipe_check = _run_cli(
                ["quality", "bug-recipe-check", "--recipe-id", "reproduction", "--out", str(recipe_check_out)]
            )
            self.assertEqual(code, 0)
            self.assertEqual(recipe_check["schemaVersion"], "agent-bug-forensics-recipe-validation.v1")
            self.assertEqual(recipe_check["recipeIds"], ["reproduction"])
            self.assertTrue(recipe_check_out.is_file())

    def test_diagnostics_bundle_and_status_view_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "evidence/result.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(json.dumps({"schemaVersion": "artifact.v1", "status": "PASS"}), encoding="utf-8")
            bundle_out = root / "out/bundle.json"
            view_out = root / "out/view.json"

            code, bundle = _run_cli(
                [
                    "diagnostics",
                    "bundle",
                    "--project-root",
                    str(root),
                    "--artifact",
                    "evidence/result.json",
                    "--out",
                    str(bundle_out),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(bundle["schemaVersion"], "agent-diagnostic-bundle.v1")
            self.assertTrue(bundle_out.is_file())

            code, view = _run_cli(
                [
                    "report",
                    "status-view",
                    "--project-root",
                    str(root),
                    "--artifact",
                    "evidence/result.json",
                    "--target-window",
                    "4k-strict",
                    "--out",
                    str(view_out),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(view["schemaVersion"], "agent-readonly-status-view.v1")
            self.assertTrue(view_out.is_file())
            self.assertFalse(view["sourceOfTruth"])

    def test_report_event_feed_and_progress_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state.json"
            usage = root / "usage.json"
            changes = root / "changes.json"
            feed_out = root / "out/feed.json"
            progress_out = root / "out/progress.json"
            state.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-workflow-state.v3",
                        "runId": "run-1",
                        "packageId": "package",
                        "planRevision": 1,
                        "planDigest": "0" * 64,
                        "sourceRevision": "main",
                        "stateRevision": 2,
                        "phase": "COMPLETE",
                        "authorization": {"mode": "approval-required"},
                        "budgets": {},
                        "tasks": [{"id": "WS-01", "status": "ACCEPTED", "attempt": 1, "required": True}],
                        "lifecycleProgressSteps": [
                            {"name": "review", "status": "DONE", "durationSeconds": 3661, "taskIds": ["WS-01"]}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            usage.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-lifecycle-model-usage-receipt.v1",
                        "operationId": "op-1",
                        "host": "codex",
                        "modelClass": "balanced",
                        "providerModelHash": "1" * 64,
                        "taskId": "WS-01",
                        "usage": {
                            "inputTokens": 1100,
                            "outputTokens": 200,
                            "billableTokens": 1300,
                            "cumulativeContextBytes": 0,
                            "toolCalls": 0,
                            "wallSeconds": 3661,
                        },
                        "attestation": {"source": "host", "status": "ATTESTED"},
                    }
                ),
                encoding="utf-8",
            )
            changes.write_text(
                json.dumps(
                    {
                        "filesChanged": 7,
                        "insertions": 432,
                        "deletions": 118,
                        "modified": 5,
                        "added": 1,
                        "deleted": 1,
                    }
                ),
                encoding="utf-8",
            )

            code, feed = _run_cli(["report", "event-feed", "--state", str(state), "--out", str(feed_out)])
            self.assertEqual(code, 0)
            self.assertEqual(feed["schemaVersion"], "agent-workflow-event-feed.v1")
            self.assertTrue(feed_out.is_file())
            self.assertTrue(feed["readOnly"])

            code, progress = _run_cli(
                [
                    "report",
                    "progress",
                    "--state",
                    str(state),
                    "--usage-receipt",
                    str(usage),
                    "--change-summary",
                    str(changes),
                    "--out",
                    str(progress_out),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(progress["schemaVersion"], "agent-lifecycle-progress-view.v1")
            self.assertTrue(progress_out.is_file())
            self.assertIn("01:01:01", progress["lines"][0])
            self.assertIn("↑0.2k/↓1.1k tok", progress["lines"][0])


if __name__ == "__main__":
    unittest.main()

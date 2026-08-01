from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import _run_cli  # noqa: F401,E402
except ImportError:
    from helpers import _run_cli  # noqa: F401,E402


class CliEvidenceImportCommandTests(unittest.TestCase):
    def test_evidence_index_and_search_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "evidence/final.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(json.dumps({"schemaVersion": "artifact.v1", "status": "PASS"}), encoding="utf-8")
            index_out = root / "out/index.json"
            summary_out = root / "out/summary.json"

            code, index = _run_cli(
                [
                    "evidence",
                    "index",
                    "--project-root",
                    str(root),
                    "--artifact",
                    "evidence/final.json",
                    "--out",
                    str(index_out),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(index["schemaVersion"], "agent-evidence-index.v1")
            self.assertTrue(index_out.is_file())

            code, summary = _run_cli(
                [
                    "evidence",
                    "search",
                    "--index",
                    str(index_out),
                    "--query",
                    "artifact",
                    "--out",
                    str(summary_out),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(summary["schemaVersion"], "agent-evidence-search-summary.v1")
            self.assertTrue(summary_out.is_file())
            self.assertFalse(summary["sourceOfTruth"])

    def test_import_plan_check_and_proposal_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "incoming.md"
            source.write_text("# Imported work\n\n- Validate before freeze.\n", encoding="utf-8")
            result_out = root / "out/import.json"
            proposal = root / "proposal.json"
            proposal.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-skill-improvement-proposal.v1",
                        "proposalId": "proposal-1",
                        "affectedSkill": "agent-workflow-orchestrator",
                        "status": "PROPOSED",
                        "rationale": "Reduce duplicate context.",
                        "expectedBehavior": "Keep compact summaries reviewable.",
                        "requiredTests": ["skill proposal validation"],
                        "requiresReview": True,
                        "autoApply": False,
                        "applied": False,
                    }
                ),
                encoding="utf-8",
            )

            code, imported = _run_cli(["import", "plan", "--source", str(source), "--out", str(result_out)])
            self.assertEqual(code, 0)
            self.assertEqual(imported["schemaVersion"], "agent-planning-import-result.v1")
            self.assertEqual(imported["candidatePlan"]["status"], "DRAFT")
            self.assertTrue(result_out.is_file())

            code, validation = _run_cli(["import", "check", "--candidate", str(result_out)])
            self.assertEqual(code, 0)
            self.assertEqual(validation["schemaVersion"], "agent-planning-import-validation.v1")
            self.assertTrue(validation["freezeBlocked"])

            code, proposal_validation = _run_cli(["import", "proposal-check", "--proposal", str(proposal)])
            self.assertEqual(code, 0)
            self.assertEqual(proposal_validation["schemaVersion"], "agent-skill-improvement-proposal-validation.v1")
            self.assertFalse(proposal_validation["autoApply"])

    def test_external_import_profile_list_and_check_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "workflow.yaml"
            source.write_text(
                "name: External workflow\n"
                "steps:\n"
                "  - inspect request\n"
                "  - validate evidence\n",
                encoding="utf-8",
            )
            registry_out = root / "out/registry.json"
            import_out = root / "out/import.json"

            code, registry = _run_cli(["import", "profile-list", "--out", str(registry_out)])
            self.assertEqual(code, 0)
            self.assertEqual(registry["schemaVersion"], "agent-external-dialect-profile-registry.v1")
            self.assertIn("workflow", registry["families"])
            self.assertTrue(registry_out.is_file())

            code, imported = _run_cli(
                [
                    "import",
                    "external",
                    "--source",
                    str(source),
                    "--family",
                    "workflow",
                    "--package-id",
                    "external-workflow",
                    "--out",
                    str(import_out),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(imported["schemaVersion"], "agent-planning-import-result.v1")
            self.assertEqual(imported["externalDialect"]["family"], "workflow")
            self.assertFalse(imported["externalDialect"]["executesInput"])

            code, validation = _run_cli(["import", "external-check", "--candidate", str(import_out)])
            self.assertEqual(code, 0)
            self.assertEqual(validation["schemaVersion"], "agent-external-dialect-import-validation.v1")
            self.assertTrue(validation["freezeBlocked"])


if __name__ == "__main__":
    unittest.main()

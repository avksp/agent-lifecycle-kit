from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.evidence_index import (
    build_evidence_index,
    require_evidence_index_pass,
    search_evidence_index,
    validate_evidence_index,
)


class EvidenceIndexTests(unittest.TestCase):
    def test_index_is_optional_rebuildable_and_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "evidence/final.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-final-proof.v1",
                        "status": "PASS",
                        "taskId": "T-1",
                        "hostLocalPath": "/" + "Users/local/private",
                    }
                ),
                encoding="utf-8",
            )

            index = build_evidence_index(root, ["evidence/final.json"], target_tokens=1024)
            validation = validate_evidence_index(index)
            summary = search_evidence_index(index, query="final", target_tokens=1024)

            self.assertEqual(index["schemaVersion"], "agent-evidence-index.v1")
            self.assertEqual(require_evidence_index_pass(validation)["status"], "PASS")
            self.assertFalse(index["sourceOfTruth"])
            self.assertTrue(index["rebuildable"])
            self.assertFalse(index["enabledByDefault"])
            self.assertEqual(index["entries"][0]["artifactRecognition"], "UNKNOWN")
            self.assertEqual(index["entries"][0]["validationStatus"], "UNVALIDATED")
            self.assertFalse(index["entries"][0]["validatedArtifact"])
            self.assertEqual(index["entries"][0]["redactionStatus"], "REDACTED")
            self.assertNotIn("private", json.dumps(summary, sort_keys=True))
            self.assertEqual(summary["status"], "PASS")
            self.assertLessEqual(summary["estimatedTokens"], 1024)

    def test_index_rejects_invalid_paths_and_unvalidated_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "notes.txt"
            artifact.write_text("plain text", encoding="utf-8")

            index = build_evidence_index(root, ["/absolute.json", "notes.txt"])

            self.assertEqual(index["status"], "FAIL")
            codes = {item["code"] for item in index["blockers"]}
            self.assertIn("evidence-index-artifact-path-invalid", codes)
            self.assertNotIn("evidence-index-artifact-not-validated", codes)
            self.assertEqual(validate_evidence_index(index)["status"], "FAIL")

    def test_search_rejects_summary_over_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "evidence/result.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(json.dumps({"schemaVersion": "artifact.v1", "status": "PASS"}), encoding="utf-8")
            index = build_evidence_index(root, ["evidence/result.json"])

            summary = search_evidence_index(index, target_tokens=1)

            self.assertEqual(summary["status"], "FAIL")
            self.assertIn("evidence-search-target-tokens-exceeded", {item["code"] for item in summary["blockers"]})

    def test_index_fails_closed_before_reading_over_input_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "evidence/large.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(json.dumps({"schemaVersion": "artifact.v1", "status": "PASS", "body": "x" * 1024}), encoding="utf-8")

            index = build_evidence_index(root, ["evidence/large.json"], max_input_bytes=64)

            self.assertEqual(index["status"], "FAIL")
            self.assertEqual(index["artifactCount"], 0)
            self.assertIn("evidence-index-input-cap-exceeded", {item["code"] for item in index["blockers"]})

    @unittest.skipIf(os.name == "nt", "symlink fixture requires POSIX semantics")
    def test_index_rejects_symlinked_inputs_inside_and_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside_tmp:
            root = Path(tmp)
            outside = Path(outside_tmp) / "outside.json"
            outside.write_text(json.dumps({"schemaVersion": "agent-change-summary-receipt.v1"}), encoding="utf-8")
            inside = root / "inside.json"
            inside.write_text(json.dumps({"schemaVersion": "agent-change-summary-receipt.v1"}), encoding="utf-8")
            evidence = root / "evidence"
            evidence.mkdir()
            links = (evidence / "outside.json", evidence / "inside.json")
            try:
                links[0].symlink_to(outside)
                links[1].symlink_to(inside)
            except OSError as exc:
                self.skipTest(f"symlink unavailable: {exc}")

            index = build_evidence_index(root, ["evidence/outside.json", "evidence/inside.json"])

            self.assertEqual(index["status"], "FAIL")
            self.assertEqual(index["artifactCount"], 0)
            self.assertEqual(
                {item["code"] for item in index["blockers"]},
                {"evidence-index-artifact-symlink"},
            )


if __name__ == "__main__":
    unittest.main()

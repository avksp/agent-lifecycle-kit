from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.diagnostics import build_diagnostic_bundle


class DiagnosticBundleTests(unittest.TestCase):
    def test_bundle_is_redacted_compact_and_not_source_of_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "evidence/result.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-test-artifact.v1",
                        "status": "PASS",
                        "apiKey": "secret-value",
                        "path": str(root / "private"),
                        "productionPromotionClaimed": False,
                    }
                ),
                encoding="utf-8",
            )

            bundle = build_diagnostic_bundle(project_root=root, artifact_paths=[Path("evidence/result.json")])

        rendered = json.dumps(bundle, sort_keys=True)
        self.assertEqual(bundle["schemaVersion"], "agent-diagnostic-bundle.v1")
        self.assertEqual(bundle["status"], "PASS")
        self.assertFalse(bundle["sourceOfTruth"])
        self.assertTrue(bundle["redacted"])
        self.assertFalse(bundle["productionPromotionClaimed"])
        self.assertNotIn(str(root), rendered)
        self.assertNotIn("secret-value", rendered)
        self.assertEqual(bundle["artifacts"][0]["summary"]["blockerCount"], 0)

    def test_bundle_fails_on_missing_or_oversized_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "large.json"
            artifact.write_text(json.dumps({"schemaVersion": "artifact.v1", "status": "PASS", "data": "x" * 40}), encoding="utf-8")

            bundle = build_diagnostic_bundle(
                project_root=root,
                artifact_paths=[Path("large.json"), Path("missing.json")],
                max_input_bytes=20,
            )

        self.assertEqual(bundle["status"], "FAIL")
        codes = {item["code"] for item in bundle["blockers"]}
        self.assertIn("diagnostic-bundle-artifact-too-large", codes)
        self.assertIn("diagnostic-bundle-artifact-missing", codes)


if __name__ == "__main__":
    unittest.main()

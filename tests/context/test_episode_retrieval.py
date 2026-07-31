from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.context import build_episode_context


class EpisodeRetrievalContextTests(unittest.TestCase):
    def test_build_episode_context_returns_bounded_digest_linked_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "evidence/review.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-review-verdict.v1",
                        "status": "PASS",
                        "taskId": "WS-1",
                        "operationId": "review-1",
                    }
                ),
                encoding="utf-8",
            )

            context = build_episode_context(root, ["evidence/review.json"], query="review", max_results=1, target_tokens=2048)

            self.assertEqual(context["schemaVersion"], "agent-episode-retrieval.v1")
            self.assertEqual(context["status"], "PASS")
            self.assertFalse(context["sourceOfTruth"])
            self.assertEqual(context["resultCount"], 1)
            self.assertEqual(context["results"][0]["sourcePath"], "evidence/review.json")
            self.assertEqual(context["results"][0]["chainState"], "chainUnchecked")
            self.assertIn("retrievalDigest", context)


if __name__ == "__main__":
    unittest.main()

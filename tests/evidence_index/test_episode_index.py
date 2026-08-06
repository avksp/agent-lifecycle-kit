from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.audit.proof_integrity import build_receipt_hash_chain
from agent_lifecycle.evidence_index import (
    build_episode_index,
    require_episode_index_pass,
    require_episode_retrieval_pass,
    retrieve_episodes,
    validate_episode_index,
)


class EpisodeIndexTests(unittest.TestCase):
    def test_episode_index_marks_chain_verified_when_hash_chain_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_path = "evidence/final.json"
            artifact = root / artifact_path
            artifact.parent.mkdir(parents=True)
            payload = {"schemaVersion": "agent-final-proof.v1", "status": "PASS", "taskId": "T-1"}
            data = json.dumps(payload).encode("utf-8")
            artifact.write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            chain = build_receipt_hash_chain([{"path": artifact_path, "digest": digest}], chain_id="chain-1")

            index = build_episode_index(root, [artifact_path], hash_chain=chain, target_tokens=2048)
            validation = validate_episode_index(index)
            retrieval = retrieve_episodes(index, query="final", target_tokens=2048)

            self.assertEqual(require_episode_index_pass(validation)["status"], "PASS")
            self.assertEqual(require_episode_retrieval_pass(retrieval)["status"], "PASS")
            self.assertEqual(index["episodes"][0]["provenance"]["chainState"], "chainVerified")
            self.assertFalse(index["episodes"][0]["provenance"]["chainUnchecked"])
            self.assertEqual(retrieval["results"][0]["chainState"], "chainVerified")

    def test_episode_index_marks_chain_unchecked_without_hash_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "evidence/session.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(json.dumps({"schemaVersion": "agent-session-summary.v1", "status": "PASS"}), encoding="utf-8")

            index = build_episode_index(root, ["evidence/session.json"], target_tokens=2048)
            retrieval = retrieve_episodes(index, query="session", target_tokens=2048)

            self.assertEqual(index["status"], "PASS")
            self.assertEqual(index["episodes"][0]["provenance"]["chainState"], "chainUnchecked")
            self.assertTrue(index["episodes"][0]["provenance"]["chainUnchecked"])
            self.assertEqual(retrieval["chainStateCounts"]["chainUnchecked"], 1)

    def test_episode_retrieval_fails_closed_when_context_budget_is_too_small(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "evidence/result.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(json.dumps({"schemaVersion": "artifact.v1", "status": "PASS", "taskId": "T-1"}), encoding="utf-8")
            index = build_episode_index(root, ["evidence/result.json"], target_tokens=2048)

            retrieval = retrieve_episodes(index, target_tokens=1)

            self.assertEqual(retrieval["status"], "FAIL")
            self.assertIn("episode-retrieval-target-tokens-exceeded", {item["code"] for item in retrieval["blockers"]})

    def test_episode_retrieval_includes_external_context_as_non_proof_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "evidence/result.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(json.dumps({"schemaVersion": "artifact.v1", "status": "PASS", "taskId": "T-1"}), encoding="utf-8")
            index = build_episode_index(root, ["evidence/result.json"], target_tokens=2048)

            retrieval = retrieve_episodes(
                index,
                query="retry",
                target_tokens=2048,
                external_context_hints=[
                    {
                        "hintId": "hint-1",
                        "contextRole": "optional-external-context",
                        "sourceOfTruth": False,
                        "proof": False,
                        "citation": "operator memory export",
                        "sourceDigest": "a" * 64,
                        "redactionStatus": "PASS",
                        "text": "Retry logic needs idempotency validation.",
                    }
                ],
            )

            self.assertEqual(retrieval["status"], "PASS")
            self.assertFalse(retrieval["externalContextPolicy"]["sourceOfTruth"])
            self.assertFalse(retrieval["externalContextPolicy"]["proof"])
            self.assertEqual(retrieval["externalContextHintCount"], 1)
            self.assertFalse(retrieval["externalContextHints"][0]["proof"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError  # noqa: E402
from agent_lifecycle.policy import apply_policy_proposal, build_tuned_policy  # noqa: E402


class PolicyApplyTests(unittest.TestCase):
    def test_tuned_policy_binds_proposal_digest_and_rollback(self) -> None:
        policy = build_tuned_policy(_proposal())

        self.assertEqual(policy["schemaVersion"], "agent-lifecycle-tuned-policy.v1")
        self.assertEqual(policy["status"], "PASS")
        self.assertEqual(policy["changes"][0]["path"], "taskShapes.small-fix.defaultMode")
        self.assertTrue(policy["rollback"]["requiresReview"])
        self.assertFalse(policy["productionPromotionClaimed"])

    def test_write_path_is_create_no_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "policy.json"
            apply_policy_proposal(_proposal(), out)
            payload = json.loads(out.read_text(encoding="utf-8"))
            with self.assertRaises(FileExistsError):
                apply_policy_proposal(_proposal(), out)

        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-tuned-policy.v1")

    def test_tuned_policy_rejects_unapproved_proposal(self) -> None:
        proposal = _proposal()
        proposal["applyAllowed"] = False

        with self.assertRaises(LifecycleError):
            build_tuned_policy(proposal)


def _proposal() -> dict[str, object]:
    return {
        "schemaVersion": "agent-lifecycle-policy-proposal.v1",
        "status": "PASS",
        "proposalId": "p",
        "proposalDigest": "0" * 64,
        "applyAllowed": True,
        "candidateChanges": [
            {"path": "taskShapes.small-fix.defaultMode", "before": "strict", "after": "light", "applies": True}
        ],
        "rollback": {"strategy": "restore", "restore": [], "requiresReview": True},
        "qualityConstraints": {"qualityFloorPreserved": True},
        "productionPromotionClaimed": False,
    }


if __name__ == "__main__":
    unittest.main()

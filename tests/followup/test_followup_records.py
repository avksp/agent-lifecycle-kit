from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError, sha256_hex  # noqa: E402
from agent_lifecycle.followup import (  # noqa: E402
    build_followup_summary,
    close_followup_item,
    validate_followup_register,
)


class FollowUpRegisterTests(unittest.TestCase):
    def test_register_reports_finalization_blockers_and_compact_summary(self) -> None:
        register = _register([_item(current_scope_impact="completion-proof")])
        profile = json.loads((ROOT / "profiles/small-context-profile.v1.json").read_text(encoding="utf-8"))

        validation = validate_followup_register(register, state=_state())
        summary = build_followup_summary(register, state=_state(), profile=profile, window="4k-strict")

        self.assertEqual(validation["schemaVersion"], "agent-follow-up-register-validation.v1")
        self.assertEqual(validation["finalizationBlockers"][0]["id"], "FU-01")
        self.assertEqual(summary["schemaVersion"], "agent-follow-up-summary.v1")
        self.assertLessEqual(summary["estimatedTokens"], 450)

    def test_close_item_requires_current_evidence_and_artifact_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "evidence/fix.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text('{"status":"PASS"}\n', encoding="utf-8")
            register = _register([_item(required_artifacts=["evidence/fix.json"])])

            updated = close_followup_item(
                register,
                item_id="FU-01",
                evidence_ids=["EV-FOLLOWUP"],
                artifact_paths=["evidence/fix.json"],
                verifier="reviewer",
                reason="validated current artifact",
                root=root,
            )
            validation = validate_followup_register(updated, state=_state(), root=root)

            self.assertEqual(validation["openItemIds"], [])
            self.assertEqual(updated["items"][0]["status"], "CLOSED")
            self.assertEqual(updated["items"][0]["closure"]["artifacts"][0]["sha256"], sha256_hex(artifact.read_bytes()))

            artifact.write_text('{"status":"CHANGED"}\n', encoding="utf-8")
            with self.assertRaises(LifecycleError) as raised:
                validate_followup_register(updated, state=_state(), root=root)
            self.assertEqual(raised.exception.code, "follow-up-artifact-stale")

    def test_closed_item_fails_when_required_evidence_is_missing(self) -> None:
        register = _register(
            [
                {
                    **_item(),
                    "status": "CLOSED",
                    "closure": {
                        "status": "PASS",
                        "evidenceIds": [],
                        "artifacts": [],
                        "verifier": {"id": "reviewer"},
                        "reason": "missing required evidence",
                        "closedAt": "2026-07-30T09:30:00Z",
                    },
                }
            ]
        )

        with self.assertRaises(LifecycleError) as raised:
            validate_followup_register(register, state=_state())
        self.assertEqual(raised.exception.code, "follow-up-closure-invalid")


def _state() -> dict:
    return {
        "schemaVersion": "agent-workflow-state.v3",
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "stateRevision": 7,
        "phase": "FINAL_AUDIT",
    }


def _register(items: list[dict]) -> dict:
    return {
        "schemaVersion": "agent-follow-up-register.v1",
        "lineage": {
            "runId": "run",
            "packageId": "package",
            "planRevision": 1,
            "planDigest": "0" * 64,
            "sourceRevision": "source",
        },
        "items": items,
        "updatedAt": "2026-07-30T09:30:00Z",
    }


def _item(*, current_scope_impact: str = "none", required_artifacts: list[str] | None = None) -> dict:
    return {
        "id": "FU-01",
        "title": "Document out-of-scope follow-up",
        "owner": {"id": "release-lead"},
        "status": "SCHEDULED",
        "source": {
            "requirementIds": ["R-1"],
            "acceptanceIds": ["AC-1"],
            "outOfScopeReason": "Explicitly scheduled outside current release boundary.",
        },
        "targetRelease": "next",
        "currentScopeImpact": current_scope_impact,
        "closureEvidence": {
            "requiredEvidenceIds": ["EV-FOLLOWUP"],
            "requiredArtifacts": required_artifacts or [],
        },
        "reason": "tracked for later closure",
    }


if __name__ == "__main__":
    unittest.main()

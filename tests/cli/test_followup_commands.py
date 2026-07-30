from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
try:
    from .helpers import _run_cli  # noqa: E402
except ImportError:
    from helpers import _run_cli  # noqa: E402


class FollowUpCommandTests(unittest.TestCase):
    def test_followup_check_close_and_sweep_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root)
            register_path = _write_register(root, current_scope_impact="completion-proof")

            code, payload = _run_cli([
                "followup",
                "check",
                "--register",
                str(register_path),
                "--state",
                str(state_path),
                "--root",
                str(root),
                "--fail-on-finalization-blockers",
            ])
            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "follow-up-finalization-blocked")

            artifact = root / "evidence/follow-up.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text('{"status":"PASS"}\n', encoding="utf-8")

            code, payload = _run_cli([
                "followup",
                "close",
                "--register",
                str(register_path),
                "--item-id",
                "FU-01",
                "--evidence-id",
                "EV-FOLLOWUP",
                "--artifact",
                "evidence/follow-up.json",
                "--verifier",
                "reviewer",
                "--reason",
                "current evidence passed",
                "--root",
                str(root),
            ])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-follow-up-close-result.v1")

            code, payload = _run_cli([
                "followup",
                "sweep",
                "--register",
                str(register_path),
                "--state",
                str(state_path),
                "--profile",
                str(ROOT / "profiles/small-context-profile.v1.json"),
                "--target-window",
                "4k-strict",
            ])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-follow-up-summary.v1")
            self.assertEqual(payload["counts"]["open"], 0)
            self.assertLessEqual(payload["estimatedTokens"], 450)

    def test_followup_add_cli_rejects_duplicate_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            register_path = _write_register(root)
            item_path = root / "item.json"
            item_path.write_text(json.dumps(_item()), encoding="utf-8")

            code, payload = _run_cli(["followup", "add", "--register", str(register_path), "--item", str(item_path)])

            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "duplicate-follow-up-item")


def _write_state(root: Path) -> Path:
    path = root / "run.state.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "agent-workflow-state.v3",
                "runId": "run",
                "packageId": "package",
                "planRevision": 1,
                "planDigest": "0" * 64,
                "sourceRevision": "source",
                "stateRevision": 1,
                "phase": "FINAL_AUDIT",
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_register(root: Path, *, current_scope_impact: str = "none") -> Path:
    path = root / "follow-up-register.json"
    path.write_text(json.dumps(_register([_item(current_scope_impact=current_scope_impact)])), encoding="utf-8")
    return path


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


def _item(*, current_scope_impact: str = "none") -> dict:
    return {
        "id": "FU-01",
        "title": "Follow-up item",
        "owner": {"id": "release-lead"},
        "status": "SCHEDULED",
        "source": {
            "requirementIds": ["R-1"],
            "acceptanceIds": ["AC-1"],
            "outOfScopeReason": "Outside current release boundary.",
        },
        "targetRelease": "next",
        "currentScopeImpact": current_scope_impact,
        "closureEvidence": {
            "requiredEvidenceIds": ["EV-FOLLOWUP"],
            "requiredArtifacts": ["evidence/follow-up.json"],
        },
        "reason": "tracked for closure",
    }


if __name__ == "__main__":
    unittest.main()

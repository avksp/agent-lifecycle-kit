from __future__ import annotations

import argparse
from pathlib import Path

from release_common import digest_value, file_identity, load_json, require_contains, write_json


REQUIRED_HOSTS = ("Codex", "Claude Code", "Cursor", "Hermes", "OpenCode")
CLAUDE_LIVE_EVIDENCE = (
    "tasks/release-0-5/evidence/live-host-conformance-claude-code.json",
    "tasks/release-0-5/evidence/live-calibration-verification-claude-code.json",
    "tasks/release-0-5/evidence/0.5.1-claude-live-promotion/full-lifecycle/final/final-proof.json",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--support-matrix", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--operation-request")
    args = parser.parse_args()

    support_matrix = Path(args.support_matrix)
    profile = load_json(Path(args.profile))
    leg_ids = [item["id"] for item in profile.get("legProfiles", [])]
    require_contains(support_matrix, [*REQUIRED_HOSTS, *leg_ids, "EXPERIMENTAL"])
    text = support_matrix.read_text(encoding="utf-8")
    verified_rows = [line for line in text.splitlines() if "| VERIFIED |" in line]
    invalid_verified = [line for line in verified_rows if not line.startswith("| Claude Code |")]
    if invalid_verified:
        raise SystemExit("support matrix can only claim VERIFIED for evidence-bound host rows")
    if verified_rows and not all(marker in text for marker in CLAUDE_LIVE_EVIDENCE):
        raise SystemExit("Claude Code VERIFIED row requires live conformance, calibration, and lifecycle proof evidence")
    evidence = {
        "schemaVersion": "agent-support-matrix-contract-evidence.v1",
        "status": "PASS",
        "supportMatrix": file_identity(support_matrix),
        "profile": file_identity(Path(args.profile)),
        "profileDigest": digest_value(profile),
        "hostCount": len(REQUIRED_HOSTS),
        "legCount": len(leg_ids),
        "adapterMaturity": "HOST_SPECIFIC",
        "adapterMaturityByHost": {
            "Codex": "EXPERIMENTAL",
            "Claude Code": "VERIFIED" if verified_rows else "EXPERIMENTAL",
            "Cursor": "EXPERIMENTAL",
            "Hermes": "EXPERIMENTAL",
            "OpenCode": "EXPERIMENTAL",
        },
        "productionPromotionClaimed": False,
        "operationRequest": args.operation_request,
    }
    write_json(Path(args.evidence), evidence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

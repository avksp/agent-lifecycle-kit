from __future__ import annotations

import argparse
from pathlib import Path

from release_common import digest_value, file_identity, load_json, require_contains, write_json


REQUIRED_HOSTS = ("Codex", "Claude Code", "Cursor", "Hermes", "OpenCode")


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
    if any("| VERIFIED |" in line for line in text.splitlines()):
        raise SystemExit("offline support matrix must not claim VERIFIED maturity in a support row")
    evidence = {
        "schemaVersion": "agent-support-matrix-contract-evidence.v1",
        "status": "PASS",
        "supportMatrix": file_identity(support_matrix),
        "profile": file_identity(Path(args.profile)),
        "profileDigest": digest_value(profile),
        "hostCount": len(REQUIRED_HOSTS),
        "legCount": len(leg_ids),
        "adapterMaturity": "EXPERIMENTAL",
        "productionPromotionClaimed": False,
        "operationRequest": args.operation_request,
    }
    write_json(Path(args.evidence), evidence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

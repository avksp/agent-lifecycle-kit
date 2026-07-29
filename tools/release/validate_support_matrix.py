from __future__ import annotations

import argparse
from pathlib import Path

from release_common import digest_value, file_identity, load_json, require_contains, write_json


REQUIRED_HOSTS = ("Codex", "Claude Code", "Cursor", "Hermes", "OpenCode")
VERIFIED_EVIDENCE = {
    "Codex": (
        "docs/adapters/evidence/codex-cli-0.6.0.md",
        "tasks/release-0-6/evidence/codex-live-promotion/live-host-conformance-codex.json",
        "tasks/release-0-6/evidence/codex-live-promotion/live-calibration-verification-codex.json",
        "tasks/release-0-6/evidence/codex-live-promotion/full-lifecycle/final/final-proof.json",
    ),
    "Claude Code": (
        "docs/adapters/evidence/claude-code-0.5.0.md",
        "tasks/release-0-5/evidence/live-host-conformance-claude-code.json",
        "tasks/release-0-5/evidence/live-calibration-verification-claude-code.json",
        "tasks/release-0-5/evidence/0.5.1-claude-live-promotion/full-lifecycle/final/final-proof.json",
    ),
}


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
    maturity_by_host = _maturity_by_host(text)
    verified_hosts = [host for host, maturity in maturity_by_host.items() if maturity == "VERIFIED"]
    invalid_verified = [host for host in verified_hosts if host not in VERIFIED_EVIDENCE]
    if invalid_verified:
        raise SystemExit("support matrix can only claim VERIFIED for evidence-bound host rows")
    for host in verified_hosts:
        missing = [marker for marker in VERIFIED_EVIDENCE[host] if marker not in text]
        if missing:
            raise SystemExit(f"{host} VERIFIED row requires live conformance, calibration, and lifecycle proof evidence")
    evidence = {
        "schemaVersion": "agent-support-matrix-contract-evidence.v1",
        "status": "PASS",
        "supportMatrix": file_identity(support_matrix),
        "profile": file_identity(Path(args.profile)),
        "profileDigest": digest_value(profile),
        "hostCount": len(REQUIRED_HOSTS),
        "legCount": len(leg_ids),
        "adapterMaturity": "HOST_SPECIFIC",
        "adapterMaturityByHost": maturity_by_host,
        "verifiedHosts": verified_hosts,
        "productionPromotionClaimed": False,
        "operationRequest": args.operation_request,
    }
    write_json(Path(args.evidence), evidence)
    return 0


def _maturity_by_host(text: str) -> dict[str, str]:
    maturity = {host: "EXPERIMENTAL" for host in REQUIRED_HOSTS}
    for line in text.splitlines():
        if not line.startswith("|") or line.startswith("| ---"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        host, current = cells[0], cells[2]
        if host in maturity and current in {"EXPERIMENTAL", "VERIFIED"}:
            maturity[host] = current
    return maturity


if __name__ == "__main__":
    raise SystemExit(main())

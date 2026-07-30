from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from release_common import digest_value, file_identity, load_json, require_contains, write_json


REQUIRED_HOSTS = (
    "Codex",
    "Claude Code",
    "Cursor",
    "Gemini CLI",
    "Hermes",
    "Kimi Code",
    "OpenCode",
    "Qwen Code",
)
REQUIRED_LIVE_EVIDENCE_LABELS = (
    "Committed redacted evidence summary:",
    "Live host conformance receipt:",
    "Live host conformance validation:",
    "Live calibration receipt:",
    "Live calibration validation:",
    "ALK lifecycle final proof:",
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
    maturity_by_host = _maturity_by_host(text)
    verified_hosts = [host for host, maturity in maturity_by_host.items() if maturity == "VERIFIED"]
    descriptors = _adapter_descriptors(Path("."))
    verified_descriptor_claims: list[dict[str, Any]] = []
    for host in verified_hosts:
        descriptor = descriptors.get(_normalize_host(host))
        if descriptor is None:
            raise SystemExit(f"{host} VERIFIED row requires a matching adapter descriptor")
        descriptor_path = descriptor["path"]
        descriptor_payload = descriptor["payload"]
        _require_verified_descriptor(host, descriptor_payload)
        evidence_markers = tuple(descriptor_payload["liveTestedHostRange"]["evidence"])
        missing = [marker for marker in evidence_markers if marker not in text]
        if missing:
            raise SystemExit(f"{host} VERIFIED row requires descriptor evidence markers: {', '.join(missing)}")
        section = _live_evidence_section(text, host)
        missing_labels = [label for label in REQUIRED_LIVE_EVIDENCE_LABELS if label not in section]
        if missing_labels:
            raise SystemExit(f"{host} VERIFIED row requires live evidence section labels: {', '.join(missing_labels)}")
        verified_descriptor_claims.append(
            {
                "host": host,
                "descriptor": file_identity(descriptor_path),
                "evidenceMarkers": list(evidence_markers),
            }
        )
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
        "verifiedDescriptorClaims": verified_descriptor_claims,
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


def _adapter_descriptors(root: Path) -> dict[str, dict[str, Any]]:
    descriptors: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "adapters").glob("*/adapter.descriptor.json")):
        payload = load_json(path)
        keys = {
            _normalize_host(path.parent.name),
            _normalize_host(str(payload.get("adapterId", ""))),
            _normalize_host(str(payload.get("host", ""))),
        }
        for key in keys:
            if key:
                descriptors[key] = {"path": path, "payload": payload}
    return descriptors


def _require_verified_descriptor(host: str, descriptor: dict[str, Any]) -> None:
    if descriptor.get("maturity") != "VERIFIED":
        raise SystemExit(f"{host} VERIFIED row requires adapter descriptor maturity VERIFIED")
    live_range = descriptor.get("liveTestedHostRange")
    if not isinstance(live_range, dict):
        raise SystemExit(f"{host} VERIFIED row requires liveTestedHostRange in descriptor")
    evidence = live_range.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise SystemExit(f"{host} VERIFIED row requires descriptor evidence markers")
    if live_range.get("productionPromotionClaimed") is not False:
        raise SystemExit(f"{host} VERIFIED row must not claim production promotion")
    if live_range.get("publicDirectoryApprovalClaimed") is not False:
        raise SystemExit(f"{host} VERIFIED row must not claim public directory approval")
    model_routing = descriptor.get("modelRouting")
    if not isinstance(model_routing, dict) or model_routing.get("liveVerified") is not True:
        raise SystemExit(f"{host} VERIFIED row requires live-verified model routing descriptor state")


def _live_evidence_section(text: str, host: str) -> str:
    lines = text.splitlines()
    host_key = _normalize_host(host)
    for index, line in enumerate(lines):
        if not line.startswith("## "):
            continue
        title_key = _normalize_host(line.removeprefix("## ").strip())
        if host_key and host_key in title_key:
            end = len(lines)
            for next_index in range(index + 1, len(lines)):
                if lines[next_index].startswith("## "):
                    end = next_index
                    break
            return "\n".join(lines[index:end])
    return ""


def _normalize_host(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


if __name__ == "__main__":
    raise SystemExit(main())

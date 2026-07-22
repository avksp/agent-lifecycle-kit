from __future__ import annotations

import argparse
from pathlib import Path

from release_common import digest_value, file_identity, load_json, write_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--operation-request")
    args = parser.parse_args()

    inventory_path = Path(args.inventory)
    inventory = load_json(inventory_path)
    expected = inventory.get("candidatePayloadInventoryDigest")
    body = {k: v for k, v in inventory.items() if k != "candidatePayloadInventoryDigest"}
    actual = digest_value(body)
    if expected != actual:
        raise SystemExit("inventory digest mismatch")
    mismatches = []
    for item in inventory.get("files", []):
        path = Path(item["path"])
        if not path.is_file():
            mismatches.append({"path": item["path"], "reason": "missing"})
            continue
        current = file_identity(path)
        if current["sha256"] != item["sha256"] or current["bytes"] != item["bytes"]:
            mismatches.append({"path": item["path"], "reason": "identity-mismatch"})
    evidence = {
        "schemaVersion": "agent-release-verification-evidence.v1",
        "status": "PASS" if not mismatches else "FAIL",
        "mode": "offline-release-candidate",
        "inventory": file_identity(inventory_path),
        "candidatePayloadInventoryDigest": expected,
        "mismatches": mismatches,
        "productionPromotionClaimed": False,
        "operationRequest": args.operation_request,
    }
    write_json(Path(args.evidence), evidence)
    return 0 if not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())

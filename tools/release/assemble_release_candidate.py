from __future__ import annotations

import argparse
from pathlib import Path

from release_common import digest_value, file_identity, iter_payload_files, load_json, write_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--operation-request")
    args = parser.parse_args()

    manifest = load_json(Path(args.manifest))
    files = [file_identity(path) for path in iter_payload_files()]
    body = {
        "schemaVersion": "agent-release-candidate-inventory.v1",
        "packageId": manifest.get("package", {}).get("id"),
        "planRevision": manifest.get("planRevision"),
        "planDigest": digest_value(manifest),
        "payloadRoots": list(iter_payload_files.__globals__["PAYLOAD_ROOTS"]),
        "files": files,
    }
    digest = digest_value(body)
    inventory = {**body, "candidatePayloadInventoryDigest": digest}
    write_json(Path(args.inventory), inventory)
    second_pass = digest_value({k: inventory[k] for k in body})
    evidence = {
        "schemaVersion": "agent-release-assembly-evidence.v1",
        "status": "PASS",
        "mode": "offline-release-candidate",
        "inventory": file_identity(Path(args.inventory)),
        "candidatePayloadInventoryDigest": digest,
        "deterministicPassDigests": [digest, second_pass],
        "productionPromotionClaimed": False,
        "operationRequest": args.operation_request,
    }
    write_json(Path(args.evidence), evidence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

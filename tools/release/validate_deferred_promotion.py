from __future__ import annotations

import argparse
from pathlib import Path

from release_common import digest_value, file_identity, load_json, write_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--operation-request")
    args = parser.parse_args()

    profile_path = Path(args.profile)
    profile = load_json(profile_path)
    live = profile.get("liveCalibrationAuthority", {})
    required_env = [
        live.get("modelProfilePathEnvironment"),
        live.get("modelProfileTrustRootEnvironment"),
        live.get("expectedSignerFingerprintEnvironment"),
    ]
    if not all(isinstance(item, str) and item for item in required_env):
        raise SystemExit("live calibration profile is missing deferred environment names")
    evidence = {
        "schemaVersion": "agent-deferred-promotion-contract-evidence.v1",
        "status": "PASS",
        "profile": file_identity(profile_path),
        "profileDigest": digest_value(profile),
        "deferredProductionPromotion": True,
        "productionPromotionClaimed": False,
        "liveModelExecutionClaimed": False,
        "requiredEnvironmentNames": required_env,
        "operationRequest": args.operation_request,
    }
    write_json(Path(args.evidence), evidence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

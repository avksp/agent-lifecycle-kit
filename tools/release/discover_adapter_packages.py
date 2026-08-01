from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from release_common import digest_value, file_identity, load_json, write_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter-root", default="adapters")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    adapter_root = Path(args.adapter_root)
    packages = _discover(adapter_root)
    body = {
        "schemaVersion": "agent-adapter-package-discovery.v1",
        "status": "PASS",
        "adapterRoot": adapter_root.as_posix(),
        "advisoryOnly": True,
        "sourceTreeDescriptorsAuthoritative": True,
        "discoveryCanOverrideDescriptors": False,
        "packageCount": len(packages),
        "packages": packages,
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.out), {**body, "discoveryDigest": digest_value(body)})
    return 0


def _discover(adapter_root: Path) -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    for descriptor_path in sorted(adapter_root.glob("*/adapter.descriptor.json")):
        descriptor = load_json(descriptor_path)
        capabilities_path = descriptor_path.with_name("capabilities.manifest.json")
        item: dict[str, Any] = {
            "adapterId": descriptor.get("adapterId"),
            "host": descriptor.get("host"),
            "maturity": descriptor.get("maturity"),
            "descriptor": file_identity(descriptor_path),
            "descriptorDigest": digest_value(descriptor),
            "capabilityManifest": None,
            "capabilityManifestDigest": None,
            "missingCapabilities": True,
        }
        if capabilities_path.is_file():
            capabilities = load_json(capabilities_path)
            item["capabilityManifest"] = file_identity(capabilities_path)
            item["capabilityManifestDigest"] = digest_value(capabilities)
            item["missingCapabilities"] = False
        packages.append(item)
    return packages


if __name__ == "__main__":
    raise SystemExit(main())

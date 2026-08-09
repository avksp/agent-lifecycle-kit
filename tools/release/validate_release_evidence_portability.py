from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from release_common import ROOT, digest_value, file_identity, write_json

PRIVATE_PATH_PATTERNS = (
    re.compile(r"(?:^|\s)/(?:Users|Volumes|private|home|tmp|root|etc|opt|snap)/[^\s\"'`]+"),
    re.compile(r"(?:^|\s)/usr/local/[^\s\"'`]+"),
    re.compile(r"(?:^|\s)/var/folders/[^\s\"'`]+"),
    re.compile(r"[A-Za-z]:\\Users\\[^\s\"'`]+"),
    re.compile(r"file://[^\s\"'`]+", re.IGNORECASE),
)
CREDENTIAL_PATTERNS = (
    re.compile(r"\b[A-Z][A-Z0-9_]{2,}_(?:API_KEY|TOKEN|SECRET|PASSWORD)\s*=\s*\S+"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{12,}\b", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
)
RAW_OUTPUT_FIELDS = {"stdout", "stderr", "stdouttail", "stderrtail", "rawoutput", "processoutput"}
CREDENTIAL_FIELD_SUFFIXES = (
    "apikey",
    "authorization",
    "credential",
    "password",
    "privatekey",
    "secret",
    "token",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    evidence_dir = Path(args.evidence_dir)
    output_path = Path(args.evidence)
    blockers: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    if not evidence_dir.is_dir():
        blockers.append({"code": "release-evidence-directory-missing", "path": _portable_path(evidence_dir)})
        candidates: list[Path] = []
    else:
        output_resolved = output_path.resolve()
        candidates = sorted(
            (path for path in evidence_dir.rglob("*.json") if path.resolve() != output_resolved),
            key=lambda path: path.as_posix(),
        )

    for path in candidates:
        portable_artifact = _portable_artifact_path(path, evidence_dir=evidence_dir)
        identity = file_identity(path)
        identity["path"] = portable_artifact
        artifacts.append(identity)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            blockers.append(
                {
                    "code": "release-evidence-json-invalid",
                    "path": portable_artifact,
                    "error": type(exc).__name__,
                }
            )
            continue
        _scan_value(payload, artifact=portable_artifact, json_path="$", blockers=blockers)

    body = {
        "schemaVersion": "agent-release-evidence-portability-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "evidenceDir": _portable_path(evidence_dir),
        "artifactCount": len(artifacts),
        "artifacts": artifacts,
        "requiredInvariants": {
            "privateAbsolutePaths": False,
            "credentialLikeValues": False,
            "rawProcessOutput": False,
            "selfReceiptExcluded": True,
        },
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    write_json(output_path, {**body, "validationDigest": digest_value(body)})
    return 0 if not blockers else 1


def _scan_value(value: Any, *, artifact: str, json_path: str, blockers: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{json_path}.{key}"
            normalized_key = re.sub(r"[^a-z]", "", str(key).lower())
            if normalized_key in RAW_OUTPUT_FIELDS and item not in (None, "", [], {}):
                blockers.append(
                    {
                        "code": "release-evidence-raw-process-output",
                        "artifact": artifact,
                        "jsonPath": child_path,
                    }
                )
            if (
                _is_credential_field(normalized_key)
                and isinstance(item, str)
                and item.strip()
                and not any(pattern.search(item) for pattern in CREDENTIAL_PATTERNS)
            ):
                blockers.append(
                    {
                        "code": "release-evidence-credential-like-value",
                        "artifact": artifact,
                        "jsonPath": child_path,
                    }
                )
            _scan_value(item, artifact=artifact, json_path=child_path, blockers=blockers)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _scan_value(item, artifact=artifact, json_path=f"{json_path}[{index}]", blockers=blockers)
        return
    if not isinstance(value, str):
        return
    if any(pattern.search(value) for pattern in PRIVATE_PATH_PATTERNS):
        blockers.append(
            {
                "code": "release-evidence-private-absolute-path",
                "artifact": artifact,
                "jsonPath": json_path,
            }
        )
    if any(pattern.search(value) for pattern in CREDENTIAL_PATTERNS):
        blockers.append(
            {
                "code": "release-evidence-credential-like-value",
                "artifact": artifact,
                "jsonPath": json_path,
            }
        )


def _portable_path(path: Path) -> str:
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return "external-evidence"


def _portable_artifact_path(path: Path, *, evidence_dir: Path) -> str:
    if path.is_absolute():
        try:
            return path.resolve().relative_to(ROOT.resolve()).as_posix()
        except ValueError:
            pass
    try:
        relative = path.resolve().relative_to(evidence_dir.resolve()).as_posix()
    except ValueError:
        relative = path.name or "artifact.json"
    return f"external-evidence/{relative}"


def _is_credential_field(normalized_key: str) -> bool:
    return any(normalized_key.endswith(suffix) for suffix in CREDENTIAL_FIELD_SUFFIXES)


if __name__ == "__main__":
    raise SystemExit(main())

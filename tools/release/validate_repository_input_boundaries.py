from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

try:
    from release_common import digest_value, file_identity, write_json
except ModuleNotFoundError:  # pragma: no cover - supports package-style test imports
    from tools.release.release_common import digest_value, file_identity, write_json


BOUNDARY_SCHEMA = "agent-repository-input-boundary-validation.v1"

REQUIRED_FILES = {
    "paths": "contracts/paths.py",
    "git": "changesets/git.py",
    "changeSummary": "reporting/change_summary.py",
    "evidenceIndex": "evidence_index/core.py",
}

REQUIRED_MARKERS = {
    "paths": (
        "normalize_git_revision",
        "resolve_repository_file",
        "read_stable_repository_file",
        "_reject_symlink_components",
        "O_NOFOLLOW",
        "dir_fd",
        "st_mtime_ns",
        "repository-input-changed-during-read",
    ),
    "git": (
        "_resolve_revision",
        "rev-parse",
        "--end-of-options",
        "normalize_git_revision",
    ),
    "changeSummary": (
        "_resolve_revision",
        "rev-parse",
        "--end-of-options",
        "normalize_git_revision",
    ),
    "evidenceIndex": (
        "resolve_repository_file",
        "read_stable_repository_file",
        "artifactRecognition",
        "validationStatus",
        "get_schema",
    ),
}

TEST_FILES = (
    "tests/contracts/test_path_security.py",
    "tests/changesets/test_git.py",
    "tests/reporting/test_change_summary.py",
    "tests/evidence_index/test_evidence_index.py",
    "tests/release/test_repository_input_boundary_validator.py",
)


def validate_sources(package_root: Path) -> dict[str, Any]:
    """Validate the source-level repository input boundary contract."""

    root = package_root.resolve()
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    identities: list[dict[str, Any]] = []
    for label, relative in REQUIRED_FILES.items():
        path = root / relative
        if not path.is_file() or path.is_symlink():
            blockers.append({"code": "repository-boundary-source-missing", "label": label, "path": relative})
            continue
        text = path.read_text(encoding="utf-8")
        identities.append(file_identity(path))
        missing = [marker for marker in REQUIRED_MARKERS[label] if marker not in text]
        if missing:
            blockers.append({"code": "repository-boundary-marker-missing", "label": label, "path": relative, "markers": missing})
        checks.append({"id": f"source-{label}", "status": "PASS" if not missing else "FAIL", "path": relative, "markers": list(REQUIRED_MARKERS[label])})

    for relative in TEST_FILES:
        path = root.parents[1] / relative
        if not path.is_file() or path.is_symlink():
            blockers.append({"code": "repository-boundary-test-missing", "path": relative})
            continue
        identities.append(file_identity(path))
    checks.append({"id": "security-regression-tests", "status": "PASS" if not any(item.get("code") == "repository-boundary-test-missing" for item in blockers) else "FAIL", "files": list(TEST_FILES)})

    body = {
        "schemaVersion": BOUNDARY_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "packageRoot": root.as_posix(),
        "checks": checks,
        "files": identities,
        "requiredProperties": {
            "gitRevisionOptionBoundary": True,
            "stableRegularFileContainment": True,
            "symlinksRejected": True,
            "artifactRecognitionSeparateFromValidation": True,
        },
        "blockers": blockers,
        "modelCallsStarted": False,
        "networkCallsStarted": False,
        "hostProcessesStarted": False,
        "sourceWritesStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    payload = validate_sources(Path(args.package_root))
    write_json(Path(args.evidence), payload)
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

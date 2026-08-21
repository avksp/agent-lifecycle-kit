"""Verify that a semver release tag is an ancestor of the protected main ref."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from typing import Any

from release_common import digest_value, write_json


VALIDATION_SCHEMA = "agent-release-ref-validation.v1"
SEMVER_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def validate_release_ref(*, repository_root: Path, tag: str, main_ref: str) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    if not SEMVER_TAG_RE.fullmatch(tag):
        blockers.append({"code": "release-tag-not-immutable-semver", "tag": tag})
        checks.append({"id": "tag-format", "status": "FAIL"})
    else:
        checks.append({"id": "tag-format", "status": "PASS"})

    tag_commit, tag_error = _git_revision(repository_root, tag)
    main_commit, main_error = _git_revision(repository_root, main_ref)
    if tag_commit is None:
        blockers.append({"code": "release-tag-not-found", "error": tag_error})
    if main_commit is None:
        blockers.append({"code": "release-main-ref-not-found", "error": main_error})
    checks.append({"id": "tag-resolution", "status": "PASS" if tag_commit else "FAIL"})
    checks.append({"id": "main-resolution", "status": "PASS" if main_commit else "FAIL"})

    ancestry = "NOT_CHECKED"
    if tag_commit and main_commit:
        process = subprocess.run(
            ["git", "-C", str(repository_root), "merge-base", "--is-ancestor", tag_commit, main_commit],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        ancestry = "PASS" if process.returncode == 0 else "FAIL"
        if process.returncode not in {0, 1}:
            blockers.append({"code": "release-ancestry-check-failed", "error": process.stderr.strip() or "git merge-base failed"})
        elif process.returncode == 1:
            blockers.append({"code": "release-tag-not-ancestor-of-main", "tagCommit": tag_commit, "mainCommit": main_commit})
    checks.append({"id": "tag-ancestor-of-main", "status": ancestry})

    body = {
        "schemaVersion": VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "tag": tag,
        "mainRef": main_ref,
        "tagCommit": tag_commit,
        "mainCommit": main_commit,
        "checks": checks,
        "blockers": blockers,
        "privilegedPublicationAllowed": not blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def _git_revision(repository_root: Path, revision: str) -> tuple[str | None, str | None]:
    if not revision or revision.startswith("-") or "\x00" in revision:
        return None, "revision input is invalid"
    process = subprocess.run(
        ["git", "-C", str(repository_root), "rev-parse", "--verify", f"{revision}^{{commit}}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    value = process.stdout.strip()
    if process.returncode != 0 or not COMMIT_RE.fullmatch(value):
        return None, process.stderr.strip() or "revision could not be resolved"
    return value, None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--main-ref", default="origin/main")
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    payload = validate_release_ref(repository_root=Path(args.repository_root), tag=args.tag, main_ref=args.main_ref)
    write_json(Path(args.evidence), payload)
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

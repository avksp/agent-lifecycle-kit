"""Pure prerequisite declarations and stable local acceptance checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, sha256_hex
from agent_lifecycle.contracts.canonical import MAX_JSON_INPUT_BYTES, load_json_object
from agent_lifecycle.contracts.paths import (
    normalize_git_revision,
    normalize_repo_path,
    read_stable_repository_file,
)
from agent_lifecycle.review.validation import validate_independent_review


def prerequisite_dependencies(manifest: dict[str, Any]) -> list[dict[str, str]]:
    """Validate the opt-in shape without reading evidence or mutating inputs."""
    extensions = manifest.get("extensions", {})
    if not isinstance(extensions, dict) or "prerequisiteAcceptance" not in extensions:
        return []
    policy = extensions["prerequisiteAcceptance"]
    if not isinstance(policy, dict) or set(policy) != {"required", "dependencies"}:
        _fail("shape-invalid", "prerequisiteAcceptance requires only required and dependencies")
    if not isinstance(policy["required"], bool) or not isinstance(policy["dependencies"], list):
        _fail("shape-invalid", "required must be boolean and dependencies must be an array")
    declared = manifest.get("dependsOn", [])
    if not isinstance(declared, list) or any(not _text(item) for item in declared):
        _fail("declarations-invalid", "dependsOn must contain nonempty package IDs")
    if len(set(declared)) != len(declared):
        _fail("declarations-invalid", "dependsOn contains duplicate package IDs")
    dependencies: list[dict[str, str]] = []
    packages: set[str] = set()
    paths: set[str] = set()
    for entry in policy["dependencies"]:
        _require_dependency(entry)
        package, path = entry["packageId"], entry["evidencePath"]
        if package not in declared:
            _fail("undeclared", "prerequisite package must appear in dependsOn")
        if package in packages or path.casefold() in paths:
            _fail("duplicate", "prerequisite packages and evidence paths must be unique")
        packages.add(package)
        paths.add(path.casefold())
        dependencies.append(dict(entry))
    if policy["required"] and packages != set(declared):
        _fail("missing", "required acceptance must cover every declared prerequisite")
    return dependencies


def validate_prerequisite_acceptance(
    manifest: dict[str, Any],
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Check declared evidence bytes and independent ACCEPTED identity locally.

    This validates declared independent review, not host attestation, publication
    or release promotion. Callers must invoke it before their first mutation.
    """
    dependencies = prerequisite_dependencies(manifest)
    for entry in dependencies:
        raw = read_stable_repository_file(
            repository_root,
            entry["evidencePath"],
            max_bytes=MAX_JSON_INPUT_BYTES,
            label="prerequisite acceptance",
        )
        if sha256_hex(raw) != entry["sha256"]:
            _fail("hash-mismatch", "prerequisite acceptance byte hash differs")
        receipt = load_json_object(raw, label="prerequisite acceptance")
        if any(receipt.get(key) != entry[key] for key in ("packageId", "sourceRevision")):
            _fail("identity-mismatch", "prerequisite package or source revision differs")
        validation = validate_independent_review(receipt)
        if validation["verdict"] != "ACCEPTED":
            _fail("not-accepted", "prerequisite needs implementation acceptance")
    body = {
        "schemaVersion": "agent-prerequisite-acceptance-validation.v1",
        "status": "PASS",
        "dependencies": dependencies,
        "guarantee": "DECLARED",
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _require_dependency(entry: Any) -> None:
    fields = {"packageId", "sourceRevision", "evidencePath", "sha256"}
    if not isinstance(entry, dict) or set(entry) != fields or any(not _text(entry[k]) for k in fields):
        _fail("entry-invalid", "prerequisite entry requires four nonempty identity fields")
    digest = entry["sha256"]
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        _fail("entry-invalid", "prerequisite sha256 must be a lowercase byte digest")
    path = normalize_repo_path(entry["evidencePath"], label="prerequisite evidence")
    if path != entry["evidencePath"] or "{" in path or "}" in path:
        _fail("path-invalid", "prerequisite evidence must use a canonical concrete repository path")
    normalize_git_revision(entry["sourceRevision"], label="prerequisite source revision")


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _fail(reason: str, message: str) -> None:
    raise LifecycleError(f"prerequisite-acceptance-{reason}", message)

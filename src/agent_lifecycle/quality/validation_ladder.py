"""Deterministic validation selection without command execution authority."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object
from agent_lifecycle.contracts.ownership_paths import is_under_authority_path, normalize_authority_path
from agent_lifecycle.contracts.paths import normalize_repo_path, read_stable_repository_file
from agent_lifecycle.contracts.validation_ladder_schemas import (
    RELEASE_FULL_VALIDATION_RECEIPT_SCHEMA,
    VALIDATION_CHECK_CATALOG_SCHEMA,
    VALIDATION_LADDER_PROFILE_SCHEMA,
    VALIDATION_SELECTION_SCHEMA,
)

LEVELS = ("TASK_FAST", "TASK_ACCEPTANCE", "RELEASE_FULL")
LEVEL_RANK = {level: index for index, level in enumerate(LEVELS)}

BUILT_IN_PROTECTED_PATH_PREFIXES = (
    ".agents/plugins/marketplace.json",
    ".claude-plugin",
    ".codex-plugin/plugin.json",
    ".cursor-plugin",
    ".github/workflows",
    "CHANGELOG.md",
    "README.md",
    "adapters/claude/.claude-plugin/plugin.json",
    "adapters/codex/.codex-plugin/plugin.json",
    "adapters/cursor/.cursor-plugin/plugin.json",
    "docs",
    "policy",
    "profiles",
    "pyproject.toml",
    "schemas",
    "src/agent_lifecycle/_version.py",
    "src/agent_lifecycle/audit",
    "src/agent_lifecycle/cli",
    "src/agent_lifecycle/compiler",
    "src/agent_lifecycle/contracts",
    "src/agent_lifecycle/freeze",
    "src/agent_lifecycle/model_routing",
    "src/agent_lifecycle/neutrality",
    "src/agent_lifecycle/planning",
    "src/agent_lifecycle/quality",
    "src/agent_lifecycle/workflow",
    "tests/metrics/fixtures",
    "tests/release",
    "tests/security",
    "tools/release",
    "uv.lock",
)

_CATALOG_KEYS = {"schemaVersion", "checks", "catalogDigest"}
_CHECK_KEYS = {"id", "commandDigest"}
_PROFILE_KEYS = {"schemaVersion", "mappings", "additionalProtectedPathPrefixes", "profileDigest"}
_MAPPING_KEYS = {"id", "pathPrefix", "level", "checkIds"}
_PROFILE_REF_KEYS = {"path", "digest"}
_RECEIPT_KEYS = {
    "schemaVersion",
    "status",
    "sourceRevision",
    "currentTreeDigest",
    "planDigest",
    "planLockDigest",
    "catalogDigest",
    "requiredCheckIds",
    "passedCheckIds",
    "gateEvidenceDigests",
    "completedAt",
    "blockers",
    "productionPromotionClaimed",
    "receiptDigest",
}
_EMPTY_CATALOG_DIGEST = canonical_digest({"schemaVersion": VALIDATION_CHECK_CATALOG_SCHEMA, "checks": []})


def build_validation_check_catalog(commands_by_id: dict[str, str]) -> dict[str, Any]:
    """Build a canonical command-digest catalog from stable check IDs."""

    if not isinstance(commands_by_id, dict) or not commands_by_id:
        raise LifecycleError("validation-ladder-check-missing", "validation check catalog cannot be empty")
    checks = []
    for check_id, command in sorted(commands_by_id.items()):
        if not _non_empty_string(check_id) or not _non_empty_string(command):
            raise LifecycleError("validation-ladder-check-missing", "validation check IDs and commands are required")
        checks.append({"id": check_id, "commandDigest": canonical_digest(command)})
    body = {"schemaVersion": VALIDATION_CHECK_CATALOG_SCHEMA, "checks": checks}
    return {**body, "catalogDigest": canonical_digest(body)}


def validate_validation_check_catalog(catalog: dict[str, Any], commands: list[str]) -> dict[str, Any]:
    """Validate that every catalog record resolves to exactly one frozen command."""

    normalized = _normalize_catalog(catalog, commands)
    return normalized


def build_validation_ladder_profile(
    mappings: list[dict[str, Any]],
    *,
    additional_protected_path_prefixes: list[str] | None = None,
) -> dict[str, Any]:
    """Build a normalized command-free validation ladder profile."""

    body = _normalize_profile_body(
        {
            "schemaVersion": VALIDATION_LADDER_PROFILE_SCHEMA,
            "mappings": mappings,
            "additionalProtectedPathPrefixes": additional_protected_path_prefixes or [],
        }
    )
    return {**body, "profileDigest": canonical_digest(body)}


def validate_validation_ladder_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize one command-free ladder profile."""

    _require_exact_keys(profile, _PROFILE_KEYS, code="validation-ladder-profile-invalid")
    body = _normalize_profile_body({key: value for key, value in profile.items() if key != "profileDigest"})
    if not _is_digest(profile.get("profileDigest")) or profile.get("profileDigest") != canonical_digest(body):
        raise LifecycleError("validation-ladder-profile-invalid", "validation ladder profileDigest is invalid")
    return {**body, "profileDigest": profile["profileDigest"]}


def validation_ladder_manifest_blockers(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Return structural authority blockers without loading profile bytes."""

    validation = manifest.get("validation")
    if not isinstance(validation, dict):
        return []
    catalog = validation.get("checkCatalog")
    reference = validation.get("validationLadderProfile")
    if catalog is None and reference is None:
        return []
    blockers: list[dict[str, Any]] = []
    if catalog is None or reference is None:
        blockers.append(
            _blocker("validation-ladder-authority-missing-peer", "validation ladder fields are all-or-none")
        )
        return blockers
    commands = validation.get("commands")
    try:
        if not isinstance(commands, list):
            raise LifecycleError("validation-ladder-check-missing", "validation.commands must be an array")
        _normalize_catalog(catalog, commands)
    except LifecycleError as exc:
        blockers.append(_blocker(exc.code, exc.message, exc.details))
    try:
        _normalize_profile_reference(reference)
    except LifecycleError as exc:
        blockers.append(_blocker(exc.code, exc.message, exc.details))
    return blockers


def build_validation_selection(
    *,
    manifest: dict[str, Any],
    lock: dict[str, Any],
    state: dict[str, Any],
    snapshot: dict[str, Any],
    repository_root: Path,
) -> dict[str, Any]:
    """Select a validation level from frozen plain data without executing commands."""

    plan_digest = canonical_digest(manifest)
    plan_lock_digest = canonical_digest(lock)
    state_revision = state.get("stateRevision")
    source_revision = state.get("sourceRevision")
    current_tree_digest = snapshot.get("snapshotHash")
    _require_selection_lineage_shapes(state_revision, source_revision, current_tree_digest)
    state_revision = cast(int, state_revision)
    source_revision = cast(str, source_revision)
    current_tree_digest = cast(str, current_tree_digest)

    validation = manifest.get("validation")
    validation = validation if isinstance(validation, dict) else {}
    raw_catalog = validation.get("checkCatalog")
    raw_reference = validation.get("validationLadderProfile")
    catalog_digest = _catalog_digest_or_default(raw_catalog)
    profile_digest = _declared_profile_digest(
        raw_reference, opted_in=raw_catalog is not None or raw_reference is not None
    )

    if (raw_catalog is None) != (raw_reference is None):
        return _blocked_selection(
            code="validation-ladder-profile-invalid",
            message="validation ladder catalog and profile reference are all-or-none",
            plan_digest=plan_digest,
            plan_lock_digest=plan_lock_digest,
            state_revision=state_revision,
            source_revision=source_revision,
            current_tree_digest=current_tree_digest,
            profile_digest=profile_digest,
            catalog_digest=catalog_digest,
        )

    if raw_reference is None:
        return _selected(
            level="RELEASE_FULL",
            selected_check_ids=[],
            matched_mapping_ids=[],
            reasons=["LEGACY_PROFILE_ABSENT"],
            plan_digest=plan_digest,
            plan_lock_digest=plan_lock_digest,
            state_revision=state_revision,
            source_revision=source_revision,
            current_tree_digest=current_tree_digest,
            profile_digest=None,
            catalog_digest=_EMPTY_CATALOG_DIGEST,
        )

    profile: dict[str, Any]
    if raw_reference is not None:
        try:
            reference = _normalize_profile_reference(raw_reference)
        except LifecycleError as exc:
            return _blocked_from_error(
                exc,
                plan_digest,
                plan_lock_digest,
                state_revision,
                source_revision,
                current_tree_digest,
                profile_digest,
                catalog_digest,
            )
        profile_digest = reference["digest"]
        profile_path = repository_root / reference["path"]
        try:
            raw_bytes = read_stable_repository_file(
                repository_root,
                reference["path"],
                max_bytes=1_048_576,
                label="validation ladder profile",
            )
        except LifecycleError:
            return _blocked_selection(
                code="validation-ladder-profile-unreadable",
                message="validation ladder profile cannot be read",
                plan_digest=plan_digest,
                plan_lock_digest=plan_lock_digest,
                state_revision=state_revision,
                source_revision=source_revision,
                current_tree_digest=current_tree_digest,
                profile_digest=profile_digest,
                catalog_digest=catalog_digest,
                context={"path": str(profile_path.relative_to(repository_root))},
            )
        try:
            raw_profile = load_json_object(raw_bytes, label="validation ladder profile")
        except LifecycleError as exc:
            return _blocked_selection(
                code="validation-ladder-profile-invalid",
                message="validation ladder profile is not valid JSON",
                plan_digest=plan_digest,
                plan_lock_digest=plan_lock_digest,
                state_revision=state_revision,
                source_revision=source_revision,
                current_tree_digest=current_tree_digest,
                profile_digest=profile_digest,
                catalog_digest=catalog_digest,
                context={"cause": exc.code},
            )
        if canonical_digest(raw_profile) != profile_digest:
            return _blocked_selection(
                code="validation-ladder-profile-digest-mismatch",
                message="validation ladder profile digest does not match its manifest reference",
                plan_digest=plan_digest,
                plan_lock_digest=plan_lock_digest,
                state_revision=state_revision,
                source_revision=source_revision,
                current_tree_digest=current_tree_digest,
                profile_digest=profile_digest,
                catalog_digest=catalog_digest,
            )
        try:
            profile = validate_validation_ladder_profile(raw_profile)
        except LifecycleError as exc:
            return _blocked_from_error(
                exc,
                plan_digest,
                plan_lock_digest,
                state_revision,
                source_revision,
                current_tree_digest,
                profile_digest,
                catalog_digest,
            )

    if state.get("planDigest") != plan_digest or lock.get("manifestHash") != plan_digest:
        return _blocked_selection(
            code="validation-ladder-profile-stale",
            message="validation ladder lineage is stale",
            plan_digest=plan_digest,
            plan_lock_digest=plan_lock_digest,
            state_revision=state_revision,
            source_revision=source_revision,
            current_tree_digest=current_tree_digest,
            profile_digest=profile_digest,
            catalog_digest=catalog_digest,
        )

    try:
        commands = validation.get("commands")
        if not isinstance(commands, list):
            raise LifecycleError("validation-ladder-check-missing", "validation.commands must be an array")
        catalog = _normalize_catalog(raw_catalog, commands)
        catalog_digest = catalog["catalogDigest"]
        catalog_ids = {item["id"] for item in catalog["checks"]}
        for mapping in profile["mappings"]:
            missing = sorted(set(mapping["checkIds"]).difference(catalog_ids))
            if missing:
                raise LifecycleError(
                    "validation-ladder-check-missing",
                    "validation ladder mapping references unknown check IDs",
                    {"mappingId": mapping["id"], "checkIds": missing},
                )
    except LifecycleError as exc:
        return _blocked_from_error(
            exc,
            plan_digest,
            plan_lock_digest,
            state_revision,
            source_revision,
            current_tree_digest,
            profile_digest,
            catalog_digest,
        )

    try:
        changed_paths = _normalized_changed_paths(snapshot)
    except LifecycleError as exc:
        return _blocked_from_error(
            exc,
            plan_digest,
            plan_lock_digest,
            state_revision,
            source_revision,
            current_tree_digest,
            profile_digest,
            catalog_digest,
        )
    protected = [*BUILT_IN_PROTECTED_PATH_PREFIXES, *profile["additionalProtectedPathPrefixes"]]
    if any(is_under_authority_path(path, prefix) for path in changed_paths for prefix in protected):
        return _selected(
            level="RELEASE_FULL",
            selected_check_ids=sorted(catalog_ids),
            matched_mapping_ids=[],
            reasons=["PROTECTED_PATH"],
            plan_digest=plan_digest,
            plan_lock_digest=plan_lock_digest,
            state_revision=state_revision,
            source_revision=source_revision,
            current_tree_digest=current_tree_digest,
            profile_digest=profile_digest,
            catalog_digest=catalog_digest,
        )

    matches = [
        mapping
        for mapping in profile["mappings"]
        if any(is_under_authority_path(path, mapping["pathPrefix"]) for path in changed_paths)
    ]
    if not matches:
        return _selected(
            level="RELEASE_FULL",
            selected_check_ids=sorted(catalog_ids),
            matched_mapping_ids=[],
            reasons=["NO_MAPPING_MATCH"],
            plan_digest=plan_digest,
            plan_lock_digest=plan_lock_digest,
            state_revision=state_revision,
            source_revision=source_revision,
            current_tree_digest=current_tree_digest,
            profile_digest=profile_digest,
            catalog_digest=catalog_digest,
        )
    level = max((mapping["level"] for mapping in matches), key=LEVEL_RANK.__getitem__)
    selected_ids = (
        sorted(catalog_ids)
        if level == "RELEASE_FULL"
        else sorted({check_id for mapping in matches for check_id in mapping["checkIds"]})
    )
    return _selected(
        level=level,
        selected_check_ids=selected_ids,
        matched_mapping_ids=sorted(mapping["id"] for mapping in matches),
        reasons=["MAPPING_MATCH"],
        plan_digest=plan_digest,
        plan_lock_digest=plan_lock_digest,
        state_revision=state_revision,
        source_revision=source_revision,
        current_tree_digest=current_tree_digest,
        profile_digest=profile_digest,
        catalog_digest=catalog_digest,
    )


def validate_release_full_validation_receipt(
    receipt: dict[str, Any],
    *,
    source_revision: str,
    current_tree_digest: str,
    plan_digest: str,
    plan_lock_digest: str,
    catalog_digest: str,
    required_check_ids: list[str],
) -> dict[str, Any]:
    """Validate a fresh full-validation receipt against exact finalization lineage."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_KEYS:
        blockers.append(_blocker("release-full-validation-shape", "release-full receipt fields are not exact"))
    else:
        expected = {
            "schemaVersion": RELEASE_FULL_VALIDATION_RECEIPT_SCHEMA,
            "status": "PASS",
            "sourceRevision": source_revision,
            "currentTreeDigest": current_tree_digest,
            "planDigest": plan_digest,
            "planLockDigest": plan_lock_digest,
            "catalogDigest": catalog_digest,
            "productionPromotionClaimed": False,
        }
        for key, value in expected.items():
            if receipt.get(key) != value:
                blockers.append(
                    _blocker(
                        "release-full-validation-lineage",
                        f"release-full receipt {key} mismatch",
                        {"field": key},
                    )
                )
        required = _canonical_string_list(receipt.get("requiredCheckIds"), allow_empty=False)
        passed = _canonical_string_list(receipt.get("passedCheckIds"), allow_empty=False)
        expected_required = sorted(set(required_check_ids))
        if required != expected_required or passed != expected_required:
            blockers.append(
                _blocker(
                    "release-full-validation-checks",
                    "release-full required and passed check IDs must equal the frozen catalog",
                )
            )
        evidence = receipt.get("gateEvidenceDigests")
        if (
            not isinstance(evidence, list)
            or evidence != sorted(set(evidence))
            or len(evidence) != len(expected_required)
            or any(not _is_digest(item) for item in evidence)
        ):
            blockers.append(
                _blocker(
                    "release-full-validation-evidence",
                    "release-full receipt requires one canonical evidence digest per check",
                )
            )
        if receipt.get("blockers") != []:
            blockers.append(_blocker("release-full-validation-blockers", "release-full receipt has blockers"))
        if not _is_utc_timestamp(receipt.get("completedAt")):
            blockers.append(_blocker("release-full-validation-completed-at", "completedAt is required"))
        body = {key: value for key, value in receipt.items() if key != "receiptDigest"}
        if not _is_digest(receipt.get("receiptDigest")) or receipt.get("receiptDigest") != canonical_digest(body):
            blockers.append(_blocker("release-full-validation-digest", "release-full receiptDigest is invalid"))
    result = {
        "schemaVersion": "agent-release-full-validation-receipt-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**result, "validationDigest": canonical_digest(result)}


def require_release_full_validation_receipt(
    receipt: dict[str, Any],
    **expected: Any,
) -> dict[str, Any]:
    validation = validate_release_full_validation_receipt(receipt, **expected)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "release-full-validation-invalid",
            "release-full validation receipt failed validation",
            {"validation": validation},
        )
    return validation


def _normalize_catalog(catalog: Any, commands: list[str]) -> dict[str, Any]:
    if not isinstance(catalog, dict):
        raise LifecycleError("validation-ladder-check-missing", "validation check catalog must be an object")
    _require_exact_keys(catalog, _CATALOG_KEYS, code="validation-ladder-check-missing")
    if catalog.get("schemaVersion") != VALIDATION_CHECK_CATALOG_SCHEMA:
        raise LifecycleError("validation-ladder-check-missing", "validation check catalog schema is unsupported")
    if any(not _non_empty_string(command) for command in commands):
        raise LifecycleError("validation-ladder-check-missing", "validation commands must be non-empty strings")
    command_digests = [canonical_digest(command) for command in commands]
    digest_counts = Counter(command_digests)
    raw_checks = catalog.get("checks")
    if not isinstance(raw_checks, list) or not raw_checks:
        raise LifecycleError("validation-ladder-check-missing", "validation check catalog cannot be empty")
    by_id: dict[str, dict[str, str]] = {}
    for raw in raw_checks:
        if not isinstance(raw, dict):
            raise LifecycleError("validation-ladder-check-missing", "validation check record must be an object")
        _require_exact_keys(raw, _CHECK_KEYS, code="validation-ladder-check-missing")
        check_id = raw.get("id")
        digest = raw.get("commandDigest")
        if not _non_empty_string(check_id) or not _is_digest(digest):
            raise LifecycleError("validation-ladder-check-missing", "validation check record is invalid")
        normalized_id = cast(str, check_id)
        normalized_digest = cast(str, digest)
        record = {"id": normalized_id, "commandDigest": normalized_digest}
        previous = by_id.get(normalized_id)
        if previous is not None and previous != record:
            raise LifecycleError("validation-ladder-check-missing", "validation check ID is retargeted")
        by_id[normalized_id] = record
    checks = [by_id[check_id] for check_id in sorted(by_id)]
    if any(digest_counts[record["commandDigest"]] != 1 for record in checks):
        raise LifecycleError(
            "validation-ladder-check-missing",
            "every catalog command digest must resolve to exactly one validation command",
        )
    if set(command_digests) != {record["commandDigest"] for record in checks}:
        raise LifecycleError(
            "validation-ladder-check-missing",
            "every validation command must have exactly one catalog record",
        )
    body = {"schemaVersion": VALIDATION_CHECK_CATALOG_SCHEMA, "checks": checks}
    if not _is_digest(catalog.get("catalogDigest")) or catalog.get("catalogDigest") != canonical_digest(body):
        raise LifecycleError("validation-ladder-check-missing", "validation check catalogDigest is invalid")
    return {**body, "catalogDigest": catalog["catalogDigest"]}


def _normalize_profile_body(body: dict[str, Any]) -> dict[str, Any]:
    if set(body) != {"schemaVersion", "mappings", "additionalProtectedPathPrefixes"}:
        raise LifecycleError("validation-ladder-profile-invalid", "validation ladder profile fields are not exact")
    if body.get("schemaVersion") != VALIDATION_LADDER_PROFILE_SCHEMA:
        raise LifecycleError("validation-ladder-profile-invalid", "validation ladder profile schema is unsupported")
    raw_mappings = body.get("mappings")
    if not isinstance(raw_mappings, list):
        raise LifecycleError("validation-ladder-profile-invalid", "validation ladder mappings must be an array")
    by_id: dict[str, dict[str, Any]] = {}
    for raw in raw_mappings:
        if not isinstance(raw, dict):
            raise LifecycleError("validation-ladder-profile-invalid", "validation ladder mapping must be an object")
        _require_exact_keys(raw, _MAPPING_KEYS, code="validation-ladder-profile-invalid")
        mapping_id = raw.get("id")
        path_prefix = raw.get("pathPrefix")
        level = raw.get("level")
        if not _non_empty_string(mapping_id) or not isinstance(path_prefix, str) or level not in LEVEL_RANK:
            raise LifecycleError("validation-ladder-profile-invalid", "validation ladder mapping is invalid")
        normalized_id = cast(str, mapping_id)
        normalized_level = cast(str, level)
        try:
            normalized_prefix = normalize_authority_path(path_prefix, label="validation ladder path prefix")
        except LifecycleError as exc:
            raise LifecycleError(
                "validation-ladder-profile-invalid", "validation ladder path prefix is invalid"
            ) from exc
        check_ids = _canonical_string_list(raw.get("checkIds"), allow_empty=False)
        if check_ids is None:
            raise LifecycleError("validation-ladder-profile-invalid", "validation ladder checkIds are invalid")
        mapping = {
            "id": normalized_id,
            "pathPrefix": normalized_prefix,
            "level": normalized_level,
            "checkIds": check_ids,
        }
        previous = by_id.get(normalized_id)
        if previous is not None and previous != mapping:
            raise LifecycleError(
                "validation-ladder-duplicate-conflict",
                "validation ladder mapping ID has contradictory bodies",
                {"mappingId": normalized_id},
            )
        by_id[normalized_id] = mapping
    additions = _canonical_authority_paths(body.get("additionalProtectedPathPrefixes"))
    return {
        "schemaVersion": VALIDATION_LADDER_PROFILE_SCHEMA,
        "mappings": [by_id[mapping_id] for mapping_id in sorted(by_id)],
        "additionalProtectedPathPrefixes": additions,
    }


def _normalize_profile_reference(reference: Any) -> dict[str, str]:
    if not isinstance(reference, dict):
        raise LifecycleError("validation-ladder-profile-invalid", "validation ladder profile reference is invalid")
    _require_exact_keys(reference, _PROFILE_REF_KEYS, code="validation-ladder-profile-invalid")
    raw_path = reference.get("path")
    digest = reference.get("digest")
    if not isinstance(raw_path, str) or not _is_digest(digest):
        raise LifecycleError("validation-ladder-profile-invalid", "validation ladder profile reference is invalid")
    try:
        path = normalize_authority_path(raw_path, label="validation ladder profile path")
    except LifecycleError as exc:
        raise LifecycleError("validation-ladder-profile-invalid", "validation ladder profile path is invalid") from exc
    return {"path": path, "digest": cast(str, digest)}


def _selected(
    *,
    level: str,
    selected_check_ids: list[str],
    matched_mapping_ids: list[str],
    reasons: list[str],
    plan_digest: str,
    plan_lock_digest: str,
    state_revision: int,
    source_revision: str,
    current_tree_digest: str,
    profile_digest: str | None,
    catalog_digest: str,
) -> dict[str, Any]:
    body = {
        "schemaVersion": VALIDATION_SELECTION_SCHEMA,
        "status": "PASS",
        "disposition": "SELECTED",
        "level": level,
        "selectedCheckIds": sorted(set(selected_check_ids)),
        "matchedMappingIds": sorted(set(matched_mapping_ids)),
        "reasons": sorted(set(reasons)),
        "planDigest": plan_digest,
        "planLockDigest": plan_lock_digest,
        "stateRevision": state_revision,
        "sourceRevision": source_revision,
        "currentTreeDigest": current_tree_digest,
        "profileDigest": profile_digest,
        "catalogDigest": catalog_digest,
        "commandsExecuted": False,
        "stateWritten": False,
        "blockers": [],
    }
    return {**body, "selectionDigest": canonical_digest(body)}


def _blocked_selection(
    *,
    code: str,
    message: str,
    plan_digest: str,
    plan_lock_digest: str,
    state_revision: int,
    source_revision: str,
    current_tree_digest: str,
    profile_digest: str | None,
    catalog_digest: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = {
        "schemaVersion": VALIDATION_SELECTION_SCHEMA,
        "status": "FAIL",
        "disposition": "BLOCKED",
        "level": None,
        "selectedCheckIds": [],
        "matchedMappingIds": [],
        "reasons": [code],
        "planDigest": plan_digest,
        "planLockDigest": plan_lock_digest,
        "stateRevision": state_revision,
        "sourceRevision": source_revision,
        "currentTreeDigest": current_tree_digest,
        "profileDigest": profile_digest,
        "catalogDigest": catalog_digest,
        "commandsExecuted": False,
        "stateWritten": False,
        "blockers": [_blocker(code, message, context)],
    }
    return {**body, "selectionDigest": canonical_digest(body)}


def _blocked_from_error(
    exc: LifecycleError,
    plan_digest: str,
    plan_lock_digest: str,
    state_revision: int,
    source_revision: str,
    current_tree_digest: str,
    profile_digest: str | None,
    catalog_digest: str,
) -> dict[str, Any]:
    return _blocked_selection(
        code=exc.code,
        message=exc.message,
        plan_digest=plan_digest,
        plan_lock_digest=plan_lock_digest,
        state_revision=state_revision,
        source_revision=source_revision,
        current_tree_digest=current_tree_digest,
        profile_digest=profile_digest,
        catalog_digest=catalog_digest,
        context=exc.details,
    )


def _normalized_changed_paths(snapshot: dict[str, Any]) -> list[str]:
    changed = snapshot.get("changedFiles")
    if not isinstance(changed, list):
        raise LifecycleError("validation-ladder-profile-invalid", "validation snapshot changedFiles are required")
    try:
        return sorted({normalize_repo_path(path, label="validation changed path") for path in changed})
    except LifecycleError as exc:
        raise LifecycleError("validation-ladder-profile-invalid", "validation snapshot path is invalid") from exc


def _require_selection_lineage_shapes(state_revision: Any, source_revision: Any, tree_digest: Any) -> None:
    if not isinstance(state_revision, int) or isinstance(state_revision, bool) or state_revision < 1:
        raise LifecycleError("validation-ladder-profile-stale", "stateRevision is invalid")
    if not _non_empty_string(source_revision) or not _is_digest(tree_digest):
        raise LifecycleError("validation-ladder-profile-stale", "validation selection lineage is invalid")


def _catalog_digest_or_default(catalog: Any) -> str:
    if isinstance(catalog, dict) and _is_digest(catalog.get("catalogDigest")):
        return catalog["catalogDigest"]
    return _EMPTY_CATALOG_DIGEST


def _declared_profile_digest(reference: Any, *, opted_in: bool) -> str | None:
    if isinstance(reference, dict) and _is_digest(reference.get("digest")):
        return cast(str, reference["digest"])
    return "0" * 64 if opted_in else None


def _canonical_authority_paths(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise LifecycleError(
            "validation-ladder-profile-invalid",
            "additionalProtectedPathPrefixes must be an array",
        )
    try:
        paths = [normalize_authority_path(item, label="additional protected path") for item in value]
    except LifecycleError as exc:
        raise LifecycleError("validation-ladder-profile-invalid", "additional protected path is invalid") from exc
    if len(paths) != len(set(paths)):
        raise LifecycleError("validation-ladder-profile-invalid", "additional protected paths must not repeat")
    return sorted(paths)


def _canonical_string_list(value: Any, *, allow_empty: bool) -> list[str] | None:
    if not isinstance(value, list) or any(not _non_empty_string(item) for item in value):
        return None
    normalized = sorted(set(value))
    if len(normalized) != len(value) or (not allow_empty and not normalized):
        return None
    return normalized


def _require_exact_keys(payload: dict[str, Any], expected: set[str], *, code: str) -> None:
    if set(payload) != expected:
        raise LifecycleError(
            code, "contract fields are not exact", {"expected": sorted(expected), "actual": sorted(payload)}
        )


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _is_utc_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z") or "T" not in value:
        return False
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").tzinfo == UTC
    except ValueError:
        return False


def _blocker(code: str, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "context": context or {}}


__all__ = [
    "BUILT_IN_PROTECTED_PATH_PREFIXES",
    "LEVELS",
    "build_validation_check_catalog",
    "build_validation_ladder_profile",
    "build_validation_selection",
    "require_release_full_validation_receipt",
    "validate_release_full_validation_receipt",
    "validate_validation_check_catalog",
    "validate_validation_ladder_profile",
    "validation_ladder_manifest_blockers",
]

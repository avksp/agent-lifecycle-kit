"""Read-only update impact over explicit plans, using canonical integrity checks."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object, sha256_hex
from agent_lifecycle.contracts.paths import normalize_repo_path, read_stable_repository_file
from agent_lifecycle.contracts.plugin_update_schemas import UPDATE_DOMAINS
from agent_lifecycle.contracts.plugin_update_validation import (
    MAX_PLAN_INPUT_BYTES,
    MAX_UPDATE_BYTES,
    require_update,
    update_report,
    update_strings,
    validate_plan_inventory,
    validate_release_impact,
    validate_update_request,
)
from agent_lifecycle.planning.verification import build_plan_verification

_DYNAMIC_COMMAND = re.compile(r"[$`{};<>]|&&|\|\|")
_ACTIVE_PHASES = frozenset(
    {"RUNNING", "VERIFYING", "FINAL_AUDIT", "PAUSED", "BLOCKED", "READY", "AWAITING_AUTHORIZATION"}
)
_STATE_SCHEMAS = frozenset({"agent-workflow-state.v4", "agent-workflow-state.v5", "agent-workflow-state.v6"})
_SAFE_ASSESSMENT_REASONS = {
    "plugin-update-input-budget": "Explicit plan inputs exceed the supported byte or file budget",
    "plugin-update-state-identity": "Supplied state does not bind to this plan identity",
    "plugin-update-input-drift": "Explicit plan input bytes changed during assessment",
    "plugin-update-scoped-verification-unsupported": "Scoped verification needs a separate bounded evidence closure",
}


class _PlanInputs:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.bytes = 0
        self.read_bytes = 0
        self.identities: dict[str, tuple[int, str]] = {}

    def read(self, name: str) -> bytes:
        name = normalize_repo_path(name)
        try:
            data = read_stable_repository_file(self.root, name, max_bytes=MAX_UPDATE_BYTES)
        except LifecycleError as exc:
            if exc.code == "repository-input-too-large":
                raise LifecycleError("plugin-update-input-budget", "Explicit plan file exceeds256KiB") from None
            if exc.code == "repository-input-changed-during-read":
                raise LifecycleError("plugin-update-input-drift", "Explicit plan file changed during read") from None
            raise
        self.read_bytes += len(data)
        identity = (len(data), sha256_hex(data))
        if name in self.identities:
            require_update(
                self.identities[name] == identity, "plan changed during assessment", code="plugin-update-input-drift"
            )
        else:
            require_update(
                self.bytes + len(data) <= MAX_PLAN_INPUT_BYTES,
                "unique aggregate plan input cap8MiB",
                code="plugin-update-input-budget",
            )
            self.identities[name] = identity
            self.bytes += len(data)
        return data


def _plan_snapshots(reader: _PlanInputs, item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, bytes]]:
    name = item["manifest"]
    body = reader.read(name)
    manifest = load_json_object(body)
    files = update_strings(manifest.get("planFiles", []), 64)
    snapshot = {name: body}
    for path in files:
        normalize_repo_path(path)
        if path not in snapshot:
            require_update(
                len(snapshot) < 64,
                "total plan file cap64 including authority siblings",
                code="plugin-update-input-budget",
            )
            snapshot[path] = reader.read(path)
    siblings = {
        "acceptance": (Path(name).parent / "acceptance-criteria.md").as_posix(),
        "lock": (Path(name).parent / "plan.lock.json").as_posix(),
    }
    for key in ("lock", "state", "acceptance"):
        sibling_path = item.get(key, siblings.get(key))
        if sibling_path is None or sibling_path in snapshot:
            continue
        candidate = reader.root / sibling_path
        if key in item or candidate.exists() or candidate.is_symlink():
            require_update(
                len(snapshot) < 64,
                "total plan file cap64 including authority siblings",
                code="plugin-update-input-budget",
            )
            snapshot[sibling_path] = reader.read(sibling_path)
    return manifest, snapshot


def _bound_state(manifest: dict[str, Any], item: dict[str, Any], snapshot: dict[str, bytes]) -> dict[str, Any] | None:
    if "state" not in item:
        return None
    state = load_json_object(snapshot[item["state"]])
    package = manifest.get("package", {})
    require_update(
        state.get("schemaVersion") in _STATE_SCHEMAS,
        "unsupported workflow state schema",
        code="plugin-update-state-identity",
    )
    require_update(
        isinstance(package, dict)
        and state.get("packageId") == package.get("id")
        and state.get("planDigest") == canonical_digest(manifest)
        and type(state.get("planRevision")) is int
        and state.get("planRevision") == manifest.get("planRevision"),
        "state/plan identity mismatch",
        code="plugin-update-state-identity",
    )
    require_update(
        type(state.get("stateRevision")) is int and state["stateRevision"] >= 0,
        "state revision unavailable",
        code="plugin-update-state-identity",
    )
    require_update(
        isinstance(state.get("runId"), str) and bool(state["runId"]),
        "state run identity unavailable",
        code="plugin-update-state-identity",
    )
    require_update(
        isinstance(state.get("phase"), str) and bool(state["phase"]),
        "state phase unavailable",
        code="plugin-update-state-identity",
    )
    return state


def _integrity(
    manifest: dict[str, Any], item: dict[str, Any], snapshot: dict[str, bytes], state: dict[str, Any] | None, root: Path
) -> dict[str, Any]:
    name = item["manifest"]
    siblings = Path(name).parent
    lock_name = item.get("lock", (siblings / "plan.lock.json").as_posix())
    acceptance = (siblings / "acceptance-criteria.md").as_posix()
    lock = load_json_object(snapshot[lock_name]) if lock_name in snapshot else None
    _bounded_verifier_scope(manifest, lock)
    markdown = snapshot[acceptance].decode("utf-8") if acceptance in snapshot else ""
    return build_plan_verification(
        manifest,
        manifest_path=root / name,
        lock=lock,
        acceptance_markdown=markdown,
        workflow_state=state,
        repository_root=root,
        package_root=root / siblings,
    )


def _bounded_verifier_scope(manifest: dict[str, Any], lock: dict[str, Any] | None) -> None:
    extensions = manifest.get("extensions", {})
    require_update(isinstance(extensions, dict), "invalid plan extensions")
    scoped = extensions.get("reviewPolicy") is not None
    if lock is not None:
        scoped = scoped or lock.get("schemaVersion") not in ("agent-plan-lock.v1", "agent-plan-lock.v2")
        scoped = scoped or "reviewEvidence" in lock
    if scoped:
        raise LifecycleError(
            "plugin-update-scoped-verification-unsupported",
            "Preserve scoped authority; separately assess its complete bounded evidence closure",
        )


def _identifiers(manifest: dict[str, Any], state: dict[str, Any] | None, host: dict[str, Any]) -> dict[str, list[str]]:
    commands = manifest.get("validation", {}).get("commands", [])
    require_update(
        isinstance(commands, list) and all(isinstance(x, str) for x in commands), "unsupported command inventory"
    )
    paths = list(manifest.get("planFiles", []))
    paths.extend(x for x in manifest.get("readOnly", []) if isinstance(x, str))
    for task in manifest.get("workstreams", []):
        for key in ("contextRefs", "writes"):
            paths.extend(x for x in task.get(key, []) if isinstance(x, str))
    schemas = [manifest.get("schemaVersion", "UNKNOWN")]
    if state:
        schemas.append(state["schemaVersion"])
    return {
        "schema": schemas,
        "cli": commands,
        "path": sorted(set(paths)),
        "profile": sorted("extensions." + key for key in manifest.get("extensions", {})),
        "host": [
            host["adapterId"] + "@" + host["version"] if host.get("adapterId") and host.get("version") else "UNKNOWN"
        ],
        "quality": ["validation.commands", "securityGates"],
        "review": ["planReview", "orchestration.stepReviewRequired", "orchestration.finalAuditRequired"],
        "evidence": ["acceptance.criteria", "implementationAudit"],
        "authority": ["packageIntegrity", "orchestration.startMode", "orchestration"],
    }


def _coverage(
    manifest: dict[str, Any],
    state: dict[str, Any] | None,
    descriptor: dict[str, Any],
    current: str | None,
    host: dict[str, Any],
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    identifiers = _identifiers(manifest, state, host)
    gaps = []
    if current is None or current not in descriptor["baseVersions"]:
        gaps.append("Current ALK base identity is missing or outside descriptor coverage")
    domains = {}
    changes: list[dict[str, Any]] = []
    for name in UPDATE_DOMAINS:
        expected = set(identifiers[name])
        domain = descriptor["domains"].get(name)
        declared = set(domain["identifiers"]) if domain else set()
        missing = sorted(expected - declared)
        complete = _domain_complete(domain, expected, missing)
        domains[name] = {
            "identifiers": sorted(expected),
            "missingIdentifiers": missing,
            "comparison": "DECLARED_COVERAGE" if complete else "UNKNOWN",
            "publisherEvidenceRefs": domain["evidenceRefs"] if domain else [],
        }
        if not complete:
            gaps.append(name + ": missing coverage or semantic review")
        changes.extend(row for row in descriptor["changes"] if row["domain"] == name and row["identifier"] in expected)
    if any(_DYNAMIC_COMMAND.search(cmd) for cmd in identifiers["cli"]):
        gaps.append("Dynamic/shell command meaning requires affected independent review")
    if descriptor["exclusions"]:
        gaps.append("Descriptor declares exclusions; no complete semantic guarantee")
    if any(row["impact"] == "UNKNOWN" for row in changes):
        gaps.append("Descriptor has an unknown affected change")
    return domains, gaps, changes


def _domain_complete(domain: dict[str, Any] | None, expected: set[str], missing: list[str]) -> bool:
    return bool(
        domain
        and domain["semanticReview"] == "REVIEWED"
        and domain["evidenceRefs"]
        and domain["coverage"] == "COMPLETE"
        and not missing
        and "UNKNOWN" not in expected
    )


def _lifecycle(manifest: dict[str, Any], state: dict[str, Any] | None) -> dict[str, str]:
    if state is not None:
        phase = state["phase"]
        if phase == "COMPLETE":
            return {"stage": phase, "action": "PRESERVE_IMMUTABLE_HISTORY"}
        if phase in _ACTIVE_PHASES:
            return {"stage": phase, "action": "DEFER_ACTIVATION"}
        return {"stage": phase, "action": "UNKNOWN_STATE_DEFER_ACTIVATION"}
    status = manifest.get("status", "UNKNOWN")
    if status in ("DRAFT", "REOPENED"):
        return {"stage": status, "action": "PROPOSE_UNAPPLIED_EDITS_AND_REVIEW"}
    return {"stage": status, "action": "RETAIN_RUNTIME_OR_REVIEWED_AMENDMENT_EXECUTION_STATE_UNKNOWN"}


def _literal_proposals(
    changes: list[dict[str, Any]], snapshot: dict[str, bytes], lifecycle: dict[str, str]
) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    if lifecycle["action"] != "PROPOSE_UNAPPLIED_EDITS_AND_REVIEW":
        return proposals
    for row in changes:
        edit = row.get("proposedEdit")
        if edit is None or edit["path"] not in snapshot:
            continue
        try:
            value: Any = load_json_object(snapshot[edit["path"]])
            for part in edit["pointer"][1:].split("/"):
                key = part.replace("~1", "/").replace("~0", "~")
                value = value[int(key)] if isinstance(value, list) and key.isdigit() else value[key]
        except (LifecycleError, KeyError, IndexError, TypeError, ValueError):
            continue
        if type(value) is type(edit["expectedValue"]) and value == edit["expectedValue"]:
            proposals.append(
                {
                    **edit,
                    "beforeSHA256": sha256_hex(snapshot[edit["path"]]),
                    "applied": False,
                    "requiresIndependentReview": True,
                }
            )
    return proposals


def _assess_plan(
    reader: _PlanInputs,
    item: dict[str, Any],
    descriptor: dict[str, Any],
    current: str | None,
    host: dict[str, Any],
) -> dict[str, Any]:
    manifest, snapshot = _plan_snapshots(reader, item)
    state = _bound_state(manifest, item, snapshot)
    integrity = _integrity(manifest, item, snapshot, state, reader.root)
    if integrity["status"] == "PASS":
        domains, gaps, changes = _coverage(manifest, state, descriptor, current, host)
    else:
        domains, gaps, changes = {}, ["Canonical plan integrity did not pass"], []
    lifecycle = _lifecycle(manifest, state)
    if state is None:
        gaps.append("Runtime state not supplied; no active/global-scope qualification")
    if integrity["status"] != "PASS":
        gaps.append("Canonical plan integrity did not pass")
    changed = any(row["impact"] == "ADAPTATION_REQUIRED" for row in changes)
    semantic = "ADAPTATION_REQUIRED" if changed else ("UNKNOWN" if gaps else "NO_IMPACT_WITHIN_COVERAGE")
    hashes = {name: sha256_hex(body) for name, body in snapshot.items()}
    for name, digest in hashes.items():
        require_update(sha256_hex(reader.read(name)) == digest, "plan changed during assessment")
    return {
        "manifest": item["manifest"],
        "manifestDigest": canonical_digest(manifest),
        "inputSHA256": hashes,
        "stateRevision": state["stateRevision"] if state else None,
        "stateValidation": "BINDING_ONLY_NOT_NATIVE_ACCEPTANCE" if state else "UNAVAILABLE",
        "structuralResult": integrity["status"],
        "integrity": integrity,
        "semanticResult": semantic,
        "semanticEvidence": "DECLARED_METADATA_COMPARISON_NOT_INDEPENDENT_REVIEW",
        "domains": domains,
        "gaps": gaps,
        "affectedChanges": changes,
        "lifecycle": lifecycle,
        "proposedEdits": _literal_proposals(changes, snapshot, lifecycle),
        "installationEligibility": "UNQUALIFIED",
        "inputBasis": "DECLARED_LOCAL_INVENTORY",
    }


def assess_plugin_update(
    request: dict[str, Any], descriptor: dict[str, Any], inventory: dict[str, Any], *, repository_root: Path
) -> dict[str, Any]:
    """Read only explicit files; never launch validation commands or mutate plans."""
    validate_update_request(request)
    validate_release_impact(descriptor)
    validate_plan_inventory(inventory)
    require_update(
        request.get("targetVersion", descriptor["version"]) == descriptor["version"], "assessment target mismatch"
    )
    pin = request.get("pin")
    require_update(pin is None or pin == "v" + descriptor["version"], "descriptor differs from immutable pin")
    trusted = request.get("trustedTargetCommit")
    require_update(trusted is None or descriptor["sourceCommit"] in (None, trusted), "descriptor commit mismatch")
    reader = _PlanInputs(repository_root)
    plans = []
    for item in inventory["plans"]:
        try:
            plans.append(
                _assess_plan(reader, item, descriptor, inventory.get("currentVersion"), request.get("host", {}))
            )
        except (LifecycleError, OSError, UnicodeError, TypeError, KeyError, ValueError) as exc:
            reason = exc.code if isinstance(exc, LifecycleError) else "plugin-update-input-unavailable"
            return update_report(
                "assess",
                "UNKNOWN",
                request,
                {
                    "plans": plans,
                    "assessmentComplete": False,
                    "reason": reason,
                    "reasonMessage": _SAFE_ASSESSMENT_REASONS.get(
                        reason, "Explicit plan input could not be assessed safely"
                    ),
                    "inputBytes": reader.bytes,
                    "readBytes": reader.read_bytes,
                    "readBytesBasis": "CUMULATIVE_WRAPPER_READS_NOT_WHOLE_VERIFIER_IO",
                    "unassessedPlanCount": len(inventory["plans"]) - len(plans),
                    "failedManifest": item["manifest"],
                    "installationEligibility": "UNQUALIFIED",
                },
                {"releaseDigest": canonical_digest(descriptor), "inventoryDigest": canonical_digest(inventory)},
            )
    return update_report(
        "assess",
        "ASSESSED",
        request,
        {
            "plans": plans,
            "assessmentComplete": True,
            "inputBytes": reader.bytes,
            "readBytes": reader.read_bytes,
            "readBytesBasis": "CUMULATIVE_WRAPPER_READS_NOT_WHOLE_VERIFIER_IO",
            "target": {"version": descriptor["version"], "sourceCommit": descriptor["sourceCommit"]},
            "targetProvenance": "DECLARED_LOCAL_DESCRIPTOR",
            "installationEligibility": "UNQUALIFIED",
        },
        {"releaseDigest": canonical_digest(descriptor), "inventoryDigest": canonical_digest(inventory)},
    )

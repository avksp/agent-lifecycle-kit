from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from release_common import digest_value, load_json

PLUGIN_NAME = "agent-lifecycle-kit"

LIFECYCLE_CONTROL_DOCUMENTATION: dict[str, Any] = {
    "id": "optional-adapter-lifecycle-control",
    "status": "OPTIONAL",
    "englishPath": "docs/adapters/lifecycle-control.md",
    "russianPath": "docs/ru/adapters/lifecycle-control.md",
    "bundledAdapterLevel": "GUIDANCE_ONLY",
    "bundledQualificationStatus": "NO_RECOMMENDATION",
}

DOMAIN_LANGUAGE_DOCUMENTATION: dict[str, Any] = {
    "id": "optional-project-domain-language",
    "status": "OPTIONAL",
    "englishPath": "docs/reference/project-domain-language.md",
    "russianPath": "docs/ru/reference/project-domain-language.md",
    "activatedContexts": ["qualification"],
    "automaticRename": False,
}

MULTI_RUN_DOCUMENTATION: dict[str, Any] = {
    "id": "optional-multi-run-attention-view",
    "status": "OPTIONAL",
    "englishPath": "docs/reference/multi-run-attention-view.md",
    "russianPath": "docs/ru/reference/multi-run-attention-view.md",
    "readOnly": True,
    "automaticOverlapResolution": False,
}

SECURITY_ANALYSIS_DOCUMENTATION: dict[str, Any] = {
    "id": "optional-security-analysis-profile",
    "status": "OPTIONAL",
    "englishPath": "docs/reference/security-analysis-profile.md",
    "russianPath": "docs/ru/reference/security-analysis-profile.md",
    "readOnlyByDefault": True,
    "independentHighSeverityVerification": True,
    "automaticExecution": False,
}

WORKFLOW_EVIDENCE_DOCUMENTATION: dict[str, Any] = {
    "id": "workflow-evidence-validation",
    "status": "REQUIRED",
    "englishPath": "docs/reference/cli.md",
    "russianPath": "docs/ru/reference/cli.md",
    "workerIdentityRequired": True,
    "reviewIdRequired": True,
    "historicalEvidenceRewritten": False,
}

EXTERNAL_TOOL_JOBS_DOCUMENTATION: dict[str, Any] = {
    "id": "optional-bounded-external-tool-jobs",
    "status": "OPTIONAL",
    "englishPath": "docs/reference/external-tool-jobs.md",
    "russianPath": "docs/ru/reference/external-tool-jobs.md",
    "adapterOwned": True,
    "immutableAttempts": True,
    "coreNetworkCalls": False,
    "ordinaryWorkflowStateAllocated": False,
    "lifecycleAuthority": False,
}

RELEASE_ACCOUNTING_DOCUMENTATION: dict[str, Any] = {
    "id": "release-accounting-and-session-handoff",
    "status": "ADVISORY",
    "englishPath": "docs/reference/release-accounting.md",
    "russianPath": "docs/ru/reference/release-accounting.md",
    "englishHandoffPath": "docs/guides/phase-session-handoff.md",
    "russianHandoffPath": "docs/ru/guides/phase-session-handoff.md",
    "missingTelemetryIsZero": False,
    "workflowAuthority": False,
    "rawTranscriptRequired": False,
}

WORKFLOW_ECONOMICS_DOCUMENTATION: dict[str, Any] = {
    "id": "workflow-economics-and-regression-evidence",
    "status": "ADVISORY",
    "englishPath": "docs/reference/workflow-economics.md",
    "russianPath": "docs/ru/reference/workflow-economics.md",
    "stableWorkloadIdentityRequired": True,
    "predeclaredPairRequiredForImplementationChange": True,
    "missingTelemetryIsImprovement": False,
    "weakerAssuranceIsImprovement": False,
    "automaticApply": False,
    "workflowAuthority": False,
}

REVIEW_EFFICIENCY_DOCUMENTATION: dict[str, Any] = {
    "id": "review-efficiency-and-evidence-independence",
    "status": "ADVISORY",
    "englishPath": "docs/reference/review-efficiency.md",
    "russianPath": "docs/ru/reference/review-efficiency.md",
    "englishIndependencePath": "docs/reference/evidence-independence.md",
    "russianIndependencePath": "docs/ru/reference/evidence-independence.md",
    "qualityFloorPreserved": True,
    "missingTelemetryIsZero": False,
    "automaticApply": False,
    "reviewerTextExecutable": False,
}

DELTA_AUDIT_DOCUMENTATION: dict[str, Any] = {
    "id": "rework-delta-audit",
    "status": "OPTIONAL",
    "englishPath": "docs/reference/implementation-audit.md",
    "russianPath": "docs/ru/reference/implementation-audit.md",
    "commandsExecutedByBuilder": False,
    "independentAcceptanceRequired": True,
    "freshFinalAuditRequired": True,
    "conservativeFullAuditFallback": True,
}

PHASE_PACKET_VALIDATION_DOCUMENTATION: dict[str, Any] = {
    "id": "phase-packets-and-validation-ladder",
    "status": "OPTIONAL",
    "englishPacketPath": "docs/reference/phase-packets.md",
    "russianPacketPath": "docs/ru/reference/phase-packets.md",
    "englishValidationPath": "docs/reference/validation-ladder.md",
    "russianValidationPath": "docs/ru/reference/validation-ladder.md",
    "workflowAuthority": False,
    "commandsExecutedBySelector": False,
    "releaseFullFloorPreserved": True,
}

EXECUTION_STRATEGY_ADOPTION_DOCUMENTATION: dict[str, Any] = {
    "id": "execution-strategy-adoption",
    "status": "OPTIONAL",
    "englishPath": "docs/reference/execution-strategy.md",
    "russianPath": "docs/ru/reference/execution-strategy.md",
    "attemptBindingRequired": True,
    "modelCallsStarted": False,
    "qualityFloorMayBeLowered": False,
    "releaseFullMayBeReplaced": False,
    "workflowAuthority": False,
}

SUCCESSOR_ADOPTION: dict[str, Any] = {
    "packageId": "release-2-7",
    "requiredPredecessor": "release-2-6",
    "sourceTracked": False,
    "acceptedMergeRevisionRequiredBeforeFreeze": True,
}

PUBLICATION_ENTRIES: tuple[dict[str, Any], ...] = (
    {
        "id": "pyproject-version",
        "path": "pyproject.toml",
        "kind": "toml-project-version",
        "fieldForm": "version",
    },
    {
        "id": "uv-lock-package-version",
        "path": "uv.lock",
        "kind": "toml-uv-package-version",
        "fieldForm": "version",
    },
    {
        "id": "module-version",
        "path": "src/agent_lifecycle/_version.py",
        "kind": "python-version-assignment",
        "fieldForm": "version",
    },
    {
        "id": "changelog-release-version",
        "path": "CHANGELOG.md",
        "kind": "text-changelog-version",
        "fieldForm": "changelog.version",
    },
    {
        "id": "release-accounting-fixture",
        "path": "tests/metrics/fixtures/release-2-14-accounting.json",
        "kind": "json-field",
        "jsonPath": ["releaseId"],
        "fieldForm": "accounting.release",
    },
    {
        "id": "codex-root-plugin",
        "path": ".codex-plugin/plugin.json",
        "kind": "json-field",
        "jsonPath": ["version"],
        "fieldForm": "version",
    },
    {
        "id": "claude-root-plugin",
        "path": ".claude-plugin/plugin.json",
        "kind": "json-field",
        "jsonPath": ["version"],
        "fieldForm": "version",
    },
    {
        "id": "cursor-root-plugin",
        "path": ".cursor-plugin/plugin.json",
        "kind": "json-field",
        "jsonPath": ["version"],
        "fieldForm": "version",
    },
    {
        "id": "claude-adapter-plugin",
        "path": "adapters/claude/.claude-plugin/plugin.json",
        "kind": "json-field",
        "jsonPath": ["version"],
        "fieldForm": "version",
    },
    {
        "id": "codex-adapter-plugin",
        "path": "adapters/codex/.codex-plugin/plugin.json",
        "kind": "json-field",
        "jsonPath": ["version"],
        "fieldForm": "version",
    },
    {
        "id": "cursor-adapter-plugin",
        "path": "adapters/cursor/.cursor-plugin/plugin.json",
        "kind": "json-field",
        "jsonPath": ["version"],
        "fieldForm": "version",
    },
    {
        "id": "codex-marketplace-source-ref",
        "path": ".agents/plugins/marketplace.json",
        "kind": "json-field",
        "jsonPath": ["plugins", 0, "source", "ref"],
        "fieldForm": "source.ref",
    },
    {
        "id": "claude-marketplace-source-ref",
        "path": ".claude-plugin/marketplace.json",
        "kind": "json-field",
        "jsonPath": ["plugins", 0, "source", "ref"],
        "fieldForm": "source.ref",
    },
    {
        "id": "claude-marketplace-version",
        "path": ".claude-plugin/marketplace.json",
        "kind": "json-field",
        "jsonPath": ["plugins", 0, "version"],
        "fieldForm": "version",
    },
    {
        "id": "cursor-marketplace-metadata-version",
        "path": ".cursor-plugin/marketplace.json",
        "kind": "json-field",
        "jsonPath": ["metadata", "version"],
        "fieldForm": "version",
    },
    {
        "id": "cursor-marketplace-plugin-version",
        "path": ".cursor-plugin/marketplace.json",
        "kind": "json-field",
        "jsonPath": ["plugins", 0, "version"],
        "fieldForm": "version",
    },
    {
        "id": "install-guide-package-pin",
        "path": "docs/guides/install-and-first-run.md",
        "kind": "text-package-pin",
        "fieldForm": "package.pin",
    },
    {
        "id": "install-guide-ru-package-pin",
        "path": "docs/ru/guides/install-and-first-run.md",
        "kind": "text-package-pin",
        "fieldForm": "package.pin",
    },
    {
        "id": "root-readme-package-pin",
        "path": "README.md",
        "kind": "text-package-pin",
        "fieldForm": "package.pin",
    },
    {
        "id": "docs-index-package-pin",
        "path": "docs/README.md",
        "kind": "text-package-pin",
        "fieldForm": "package.pin",
    },
    {
        "id": "docs-index-ru-package-pin",
        "path": "docs/ru/README.md",
        "kind": "text-package-pin",
        "fieldForm": "package.pin",
    },
    {
        "id": "docs-index-ru-prose-version",
        "path": "docs/ru/README.md",
        "kind": "text-russian-version-line",
        "fieldForm": "docs.version",
    },
    {
        "id": "cli-reference-package-pin",
        "path": "docs/reference/cli.md",
        "kind": "text-package-pin",
        "fieldForm": "package.pin",
    },
    {
        "id": "cli-reference-ru-package-pin",
        "path": "docs/ru/reference/cli.md",
        "kind": "text-package-pin",
        "fieldForm": "package.pin",
    },
)


LAST_CHANNEL_POLICY: dict[str, Any] = {
    "status": "OPTIONAL",
    "defaultInstallChannel": "immutable-semver",
    "pluginVersionMayBeFloating": False,
    "allowedFloatingRef": "source-ref-only",
    "requiresAcceptedReleaseCommit": True,
}


def build_publication_manifest(*, target_version: str, target_ref: str) -> dict[str, Any]:
    entries = []
    for entry in PUBLICATION_ENTRIES:
        expected = _expected_value(entry=entry, target_version=target_version, target_ref=target_ref)
        entries.append(
            {
                "id": entry["id"],
                "path": entry["path"],
                "kind": entry["kind"],
                "fieldForm": entry["fieldForm"],
                "jsonPath": entry.get("jsonPath"),
                "expectedValue": expected,
            }
        )
    body = {
        "schemaVersion": "agent-publication-manifest.v1",
        "status": "PASS",
        "targetVersion": target_version,
        "targetRef": target_ref,
        "pluginName": PLUGIN_NAME,
        "entries": entries,
        "documentedFeatures": [
            LIFECYCLE_CONTROL_DOCUMENTATION,
            DOMAIN_LANGUAGE_DOCUMENTATION,
            MULTI_RUN_DOCUMENTATION,
            SECURITY_ANALYSIS_DOCUMENTATION,
            WORKFLOW_EVIDENCE_DOCUMENTATION,
            EXTERNAL_TOOL_JOBS_DOCUMENTATION,
            RELEASE_ACCOUNTING_DOCUMENTATION,
            WORKFLOW_ECONOMICS_DOCUMENTATION,
            REVIEW_EFFICIENCY_DOCUMENTATION,
            DELTA_AUDIT_DOCUMENTATION,
            PHASE_PACKET_VALIDATION_DOCUMENTATION,
            EXECUTION_STRATEGY_ADOPTION_DOCUMENTATION,
        ],
        "successorAdoption": SUCCESSOR_ADOPTION,
        "lastChannelPolicy": LAST_CHANNEL_POLICY,
        "productionPromotionClaimed": False,
    }
    return {**body, "publicationManifestDigest": digest_value(body)}


def validate_publication_tree(*, root: Path, target_version: str, target_ref: str) -> dict[str, Any]:
    publication_manifest = build_publication_manifest(target_version=target_version, target_ref=target_ref)
    checks: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for entry in publication_manifest["entries"]:
        check = _check_entry(root=root, entry=entry)
        checks.append(check)
        if check["status"] != "PASS":
            blockers.append(
                {
                    "code": "publication-version-mismatch",
                    "entryId": entry["id"],
                    "path": entry["path"],
                    "fieldForm": entry["fieldForm"],
                    "expected": entry["expectedValue"],
                    "actual": check.get("actualValue"),
                }
            )
    status = "PASS" if not blockers else "FAIL"
    body = {
        "schemaVersion": "agent-publication-version-validation.v1",
        "status": status,
        "targetVersion": target_version,
        "targetRef": target_ref,
        "publicationManifest": publication_manifest,
        "publicationManifestDigest": publication_manifest["publicationManifestDigest"],
        "checks": checks,
        "blockers": blockers,
        "lastChannelPolicy": LAST_CHANNEL_POLICY,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def _check_entry(*, root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    path = root / entry["path"]
    actual = _read_entry_value(path=path, entry=entry)
    status = "PASS" if actual == entry["expectedValue"] else "FAIL"
    return {
        "id": entry["id"],
        "status": status,
        "path": entry["path"],
        "fieldForm": entry["fieldForm"],
        "expectedValue": entry["expectedValue"],
        "actualValue": actual,
    }


def _read_entry_value(*, path: Path, entry: dict[str, Any]) -> str | None:
    if not path.is_file():
        return None
    kind = entry["kind"]
    if kind == "json-field":
        return _json_path(load_json(path), entry["jsonPath"])
    if kind == "toml-project-version":
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
        return _string((payload.get("project") or {}).get("version"))
    if kind == "toml-uv-package-version":
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
        for package in payload.get("package", []):
            if isinstance(package, dict) and package.get("name") == PLUGIN_NAME:
                return _string(package.get("version"))
        return None
    if kind == "python-version-assignment":
        match = re.search(r'^__version__\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8"), re.MULTILINE)
        return match.group(1) if match else None
    if kind == "text-package-pin":
        matches = re.findall(
            rf"{re.escape(PLUGIN_NAME)}==([0-9]+(?:\.[0-9]+){{2}})",
            path.read_text(encoding="utf-8"),
        )
        if not matches:
            return None
        pins = [f"{PLUGIN_NAME}=={version}" for version in matches]
        return pins[0] if len(set(pins)) == 1 else ";".join(pins)
    if kind == "text-changelog-version":
        match = re.search(
            r"^##\s+([0-9]+(?:\.[0-9]+){2})(?:\s+-|$)",
            path.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        return match.group(1) if match else None
    if kind == "text-russian-version-line":
        match = re.search(
            r"\*\*Версия:\*\*\s*([0-9]+(?:\.[0-9]+){2})",
            path.read_text(encoding="utf-8"),
        )
        return match.group(1) if match else None
    raise ValueError(f"unsupported publication entry kind: {kind}")


def _expected_value(*, entry: dict[str, Any], target_version: str, target_ref: str) -> str:
    if entry["fieldForm"] == "source.ref":
        return target_ref
    if entry["fieldForm"] == "package.pin":
        return f"{PLUGIN_NAME}=={target_version}"
    return target_version


def _json_path(payload: Any, path: list[Any]) -> str | None:
    current = payload
    for part in path:
        if isinstance(part, int):
            if not isinstance(current, list) or part >= len(current):
                return None
            current = current[part]
        else:
            if not isinstance(current, dict):
                return None
            current = current.get(part)
    return _string(current)


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) else None

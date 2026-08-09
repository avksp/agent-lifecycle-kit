from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from release_common import digest_value, load_json


PLUGIN_NAME = "agent-lifecycle-kit"

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
        "id": "quickstart-package-pin",
        "path": "docs/guides/quickstart.md",
        "kind": "text-package-pin",
        "fieldForm": "package.pin",
    },
    {
        "id": "quickstart-ru-package-pin",
        "path": "docs/ru/quickstart.md",
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
        return _string(((payload.get("project") or {}).get("version")))
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
        match = re.search(
            rf"{re.escape(PLUGIN_NAME)}==([0-9]+(?:\.[0-9]+){{2}})",
            path.read_text(encoding="utf-8"),
        )
        return match.group(0) if match else None
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

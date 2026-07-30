"""Opt-in quality pack contracts and fixture-based behavior checks."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest

QUALITY_PACK_SCHEMA = "agent-optional-quality-pack.v1"
QUALITY_PACK_VALIDATION_SCHEMA = "agent-optional-quality-pack-validation.v1"
BEHAVIOR_CHECK_RUN_SCHEMA = "agent-behavior-check-run.v1"
FIXTURE_SCHEMA = "agent-behavior-check-fixture.v1"
RESOURCE_CAP_KEYS = {
    "maxArtifacts",
    "maxInputBytes",
    "maxInputTokens",
    "maxInvocations",
    "maxOutputTokens",
    "maxWallSeconds",
}
SIGNAL_NAMES = (
    "completion",
    "goal",
    "budget",
    "eventCapture",
    "externalAction",
    "review",
)
NEGATIVE_STATUSES = {"FAIL", "BLOCKED"}


def build_default_quality_pack() -> dict[str, Any]:
    """Return the built-in optional quality pack manifest."""

    return {
        "schemaVersion": QUALITY_PACK_SCHEMA,
        "packId": "optional-quality-observability",
        "status": "OPTIONAL",
        "enabledByDefault": False,
        "activationMode": "opt-in",
        "canonicalLifecycleCommandsChanged": False,
        "providerSpecificCoreDependency": False,
        "productionPromotionClaimed": False,
        "defaultCommandFootprint": {
            "extraCommands": 0,
            "extraLiveCalls": 0,
            "extraRequiredArtifacts": 0,
        },
        "commands": [
            {
                "name": "quality pack-check",
                "purpose": "validate an optional quality pack manifest",
                "inputSchemas": [QUALITY_PACK_SCHEMA],
                "expectedEvidence": [QUALITY_PACK_VALIDATION_SCHEMA],
                "resourceCaps": {"maxInputBytes": 32768, "maxOutputTokens": 2048},
            },
            {
                "name": "quality behavior-check",
                "purpose": "check lifecycle outcome fixtures",
                "inputSchemas": [FIXTURE_SCHEMA],
                "expectedEvidence": [BEHAVIOR_CHECK_RUN_SCHEMA],
                "resourceCaps": {"maxArtifacts": 16, "maxInputBytes": 65536, "maxOutputTokens": 4096},
            },
        ],
    }


def validate_quality_pack(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate one optional quality pack without enabling it."""

    if not isinstance(manifest, dict):
        raise LifecycleError("invalid-quality-pack", "quality pack manifest must be an object")
    blockers: list[dict[str, Any]] = []
    if manifest.get("schemaVersion") != QUALITY_PACK_SCHEMA:
        blockers.append({"code": "quality-pack-schema-invalid", "message": "unsupported quality pack schemaVersion"})
    _required_string(manifest, "packId", blockers)
    if manifest.get("status") != "OPTIONAL":
        blockers.append({"code": "quality-pack-not-optional", "message": "quality pack status must be OPTIONAL"})
    if manifest.get("enabledByDefault") is not False:
        blockers.append({"code": "quality-pack-default-enabled", "message": "quality packs must be disabled by default"})
    if manifest.get("activationMode") != "opt-in":
        blockers.append({"code": "quality-pack-not-opt-in", "message": "quality pack activation must be opt-in"})
    if manifest.get("canonicalLifecycleCommandsChanged") is not False:
        blockers.append({"code": "quality-pack-command-drift", "message": "canonical lifecycle commands must remain unchanged"})
    if manifest.get("providerSpecificCoreDependency") is not False:
        blockers.append({"code": "quality-pack-provider-core-dependency", "message": "quality packs cannot add provider-specific core dependencies"})
    if manifest.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "quality-pack-promotion-overclaim", "message": "quality packs cannot claim production promotion"})
    _validate_default_footprint(manifest.get("defaultCommandFootprint"), blockers)
    commands = manifest.get("commands")
    if not isinstance(commands, list) or not commands:
        blockers.append({"code": "quality-pack-command-missing", "message": "quality pack must declare opt-in commands"})
        commands = []
    seen: set[str] = set()
    for index, command in enumerate(commands):
        _validate_command(command, index, blockers, seen)
    body = {
        "schemaVersion": QUALITY_PACK_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "packId": manifest.get("packId"),
        "commandCount": len(commands),
        "defaultEnabled": manifest.get("enabledByDefault"),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "packDigest": canonical_digest(manifest), "validationDigest": canonical_digest(body)}


def require_quality_pack_pass(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") == "FAIL":
        raise LifecycleError("quality-pack-validation-failed", "quality pack validation failed", {"validation": payload})
    return payload


def run_behavior_checks(pack_manifest: dict[str, Any], fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    """Run small, deterministic lifecycle outcome checks."""

    pack_validation = validate_quality_pack(pack_manifest)
    checks: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    if pack_validation["status"] == "FAIL":
        blockers.append({"code": "behavior-check-pack-invalid", "message": "quality pack validation failed"})
    if not fixtures:
        blockers.append({"code": "behavior-check-fixtures-missing", "message": "at least one fixture is required"})
    for index, fixture in enumerate(fixtures):
        checks.append(_evaluate_fixture(fixture, index, blockers))
    failed_expectations = [item for item in checks if item["expectationStatus"] == "FAIL"]
    if failed_expectations:
        blockers.append(
            {
                "code": "behavior-check-expectation-failed",
                "fixtureIds": [item["fixtureId"] for item in failed_expectations],
            }
        )
    body = {
        "schemaVersion": BEHAVIOR_CHECK_RUN_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "packId": pack_manifest.get("packId"),
        "packDigest": canonical_digest(pack_manifest),
        "fixtureCount": len(fixtures),
        "passedExpectationCount": len([item for item in checks if item["expectationStatus"] == "PASS"]),
        "failedExpectationCount": len(failed_expectations),
        "checks": checks,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "runDigest": canonical_digest(body)}


def require_behavior_checks_pass(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") == "FAIL":
        raise LifecycleError("behavior-check-failed", "behavior checks failed", {"validation": payload})
    return payload


def _validate_command(command: object, index: int, blockers: list[dict[str, Any]], seen: set[str]) -> None:
    if not isinstance(command, dict):
        blockers.append({"code": "quality-pack-command-invalid", "index": index, "message": "command must be an object"})
        return
    name = command.get("name")
    if not isinstance(name, str) or not name:
        blockers.append({"code": "quality-pack-command-name-missing", "index": index})
    elif name in seen:
        blockers.append({"code": "quality-pack-command-duplicate", "command": name})
    else:
        seen.add(name)
    _required_string(command, "purpose", blockers, index=index)
    _required_string_list(command.get("inputSchemas"), "inputSchemas", blockers, index=index)
    _required_string_list(command.get("expectedEvidence"), "expectedEvidence", blockers, index=index)
    _validate_resource_caps(command.get("resourceCaps"), blockers, index=index)


def _validate_default_footprint(value: object, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict):
        blockers.append({"code": "quality-pack-default-footprint-missing", "message": "default footprint is required"})
        return
    for key in ("extraCommands", "extraLiveCalls", "extraRequiredArtifacts"):
        if value.get(key) != 0:
            blockers.append({"code": "quality-pack-default-footprint-nonzero", "field": key})


def _validate_resource_caps(value: object, blockers: list[dict[str, Any]], *, index: int | None = None) -> None:
    if not isinstance(value, dict) or not value:
        blockers.append({"code": "quality-pack-resource-caps-missing", "index": index})
        return
    supported = [key for key in value if key in RESOURCE_CAP_KEYS]
    if not supported:
        blockers.append({"code": "quality-pack-resource-caps-unsupported", "index": index})
    for key in supported:
        number = value.get(key)
        if not isinstance(number, (int, float)) or isinstance(number, bool) or number <= 0:
            blockers.append({"code": "quality-pack-resource-cap-invalid", "index": index, "field": key})


def _evaluate_fixture(fixture: dict[str, Any], index: int, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    fixture_blockers: list[dict[str, Any]] = []
    if not isinstance(fixture, dict):
        blockers.append({"code": "behavior-check-fixture-invalid", "index": index})
        return {
            "fixtureId": f"fixture-{index}",
            "expectedOutcome": None,
            "actualOutcome": "FAIL",
            "expectationStatus": "FAIL",
            "blockerCodes": ["behavior-check-fixture-invalid"],
        }
    if fixture.get("schemaVersion") != FIXTURE_SCHEMA:
        fixture_blockers.append({"code": "behavior-check-fixture-schema-invalid"})
    fixture_id = fixture.get("fixtureId")
    if not isinstance(fixture_id, str) or not fixture_id:
        fixture_id = f"fixture-{index}"
        fixture_blockers.append({"code": "behavior-check-fixture-id-missing"})
    expected = fixture.get("expectedOutcome")
    if expected not in {"PASS", "FAIL", "BLOCKED"}:
        fixture_blockers.append({"code": "behavior-check-expected-outcome-invalid"})
        expected = "FAIL"
    signals = fixture.get("signals")
    if not isinstance(signals, dict):
        signals = {}
        fixture_blockers.append({"code": "behavior-check-signals-missing"})
    signal_blockers = _signal_blockers(signals)
    for item in fixture_blockers:
        blockers.append({"fixtureId": fixture_id, **item})
    actual = "FAIL" if signal_blockers or fixture_blockers else "PASS"
    if any(item.get("status") == "BLOCKED" for item in signals.values() if isinstance(item, dict)):
        actual = "BLOCKED"
    expectation_status = "PASS" if actual == expected else "FAIL"
    return {
        "fixtureId": fixture_id,
        "expectedOutcome": expected,
        "actualOutcome": actual,
        "expectationStatus": expectation_status,
        "signalCount": len(signals),
        "blockerCodes": [item["code"] for item in [*fixture_blockers, *signal_blockers]],
    }


def _signal_blockers(signals: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for name in SIGNAL_NAMES:
        signal = signals.get(name)
        if signal is None:
            continue
        if not isinstance(signal, dict):
            blockers.append({"code": "behavior-check-signal-invalid", "signal": name})
            continue
        status = signal.get("status")
        if status in NEGATIVE_STATUSES:
            blockers.append({"code": f"behavior-check-{name}-blocked", "status": status})
    return blockers


def _required_string(value: dict[str, Any], key: str, blockers: list[dict[str, Any]], *, index: int | None = None) -> None:
    if not isinstance(value.get(key), str) or not value.get(key):
        item = {"code": f"quality-pack-{key}-missing"}
        if index is not None:
            item["index"] = index
        blockers.append(item)


def _required_string_list(value: object, key: str, blockers: list[dict[str, Any]], *, index: int | None = None) -> None:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        item = {"code": f"quality-pack-{key}-invalid"}
        if index is not None:
            item["index"] = index
        blockers.append(item)

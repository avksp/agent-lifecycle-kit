"""Adapter capability manifests derived from host descriptors."""

from __future__ import annotations

from typing import Any, cast

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.thread_bridge_schemas import (
    build_thread_bridge_profile,
    build_thread_capability,
    resolve_thread_operation_status,
    validate_thread_bridge_profile,
)
from agent_lifecycle.host_protocol.acp_capability import validate_host_capabilities
from agent_lifecycle.host_protocol.event_capture import (
    EVENT_CAPTURE_OPERATION,
    adapter_declares_event_capture,
    event_capture_declaration,
)
from agent_lifecycle.host_protocol.sandbox_receipts import validate_sandbox_capability
from agent_lifecycle.host_protocol.validation import REQUIRED_OPERATION_NAMES, validate_adapter_descriptor

CAPABILITY_MANIFEST_SCHEMA_VERSION = "agent-adapter-capability-manifest.v1"
CAPABILITY_MANIFEST_VALIDATION_SCHEMA_VERSION = "agent-adapter-capability-manifest-validation.v1"


def build_capability_manifest(descriptor: dict[str, Any]) -> dict[str, Any]:
    """Build a stable capability manifest from an adapter descriptor."""

    raw_model_routing = descriptor.get("modelRouting")
    model_routing: dict[str, Any] = raw_model_routing if isinstance(raw_model_routing, dict) else {}
    raw_operations = descriptor.get("operations")
    operations: list[Any] = raw_operations if isinstance(raw_operations, list) else []
    promotion: dict[str, Any] = {
        "verifiedRequiresLiveTestedHostRange": True,
        "productionPromotionClaimed": False,
    }
    live_range = descriptor.get("liveTestedHostRange")
    if isinstance(live_range, dict):
        promotion["liveTestedHostRange"] = live_range
    manifest = {
        "schemaVersion": CAPABILITY_MANIFEST_SCHEMA_VERSION,
        "adapterId": descriptor.get("adapterId"),
        "host": descriptor.get("host"),
        "maturity": descriptor.get("maturity"),
        "descriptorDigest": canonical_digest(descriptor),
        "unsupportedOperationPolicy": descriptor.get("unsupportedOperationPolicy"),
        "coreSemantics": descriptor.get("coreSemantics"),
        "capabilities": [_capability_from_operation(item, descriptor) for item in operations if isinstance(item, dict)],
        "modelRouting": {
            "profileSupport": model_routing.get("profileSupport"),
            "attemptRoutePolicy": model_routing.get("attemptRoutePolicy"),
            "usageReceiptRequired": model_routing.get("usageReceiptRequired"),
            "unsupportedClassPolicy": model_routing.get("unsupportedClassPolicy"),
            "providerModelNamesInCore": model_routing.get("providerModelNamesInCore"),
            "liveVerified": model_routing.get("liveVerified"),
        },
        "runtimeBoundary": {
            "hostSpecificCode": "adapter-owned",
            "lifecycleSemantics": descriptor.get("coreSemantics"),
            "unsupportedOperations": descriptor.get("unsupportedOperationPolicy"),
            "providerModelNamesInCore": model_routing.get("providerModelNamesInCore"),
        },
        "hostCapabilities": _host_capabilities_from_descriptor(descriptor),
        "sandboxCapabilities": _sandbox_capabilities_from_descriptor(descriptor),
        "eventCapture": _event_capture_from_descriptor(descriptor),
        "promotion": promotion,
    }
    planning_launch = _planning_launch_from_descriptor(descriptor)
    if planning_launch is not None:
        manifest["planningLaunch"] = planning_launch
    thread_bridge = _thread_bridge_from_descriptor(
        descriptor,
        capability_manifest_digest=capability_manifest_identity(manifest),
    )
    if thread_bridge is not None:
        manifest["threadBridge"] = thread_bridge
    return manifest


def validate_capability_manifest(manifest: dict[str, Any], *, descriptor: dict[str, Any]) -> dict[str, Any]:
    """Validate that a capability manifest still matches its descriptor."""

    blockers: list[dict[str, Any]] = []
    descriptor_validation = validate_adapter_descriptor(descriptor)
    if descriptor_validation["status"] == "FAIL":
        blockers.append(
            {
                "code": "adapter-descriptor-invalid",
                "message": "capability manifest cannot pass while descriptor validation fails",
                "descriptorBlockers": descriptor_validation["blockers"],
            }
        )
    if manifest.get("schemaVersion") != CAPABILITY_MANIFEST_SCHEMA_VERSION:
        blockers.append(
            {"code": "invalid-capability-manifest-schema", "message": "unsupported capability manifest schemaVersion"}
        )
    for key in ("adapterId", "host", "maturity", "unsupportedOperationPolicy", "coreSemantics"):
        if manifest.get(key) != descriptor.get(key):
            blockers.append(
                {
                    "code": "capability-manifest-descriptor-mismatch",
                    "field": key,
                    "expected": descriptor.get(key),
                    "actual": manifest.get(key),
                }
            )
    expected_digest = canonical_digest(descriptor)
    if manifest.get("descriptorDigest") != expected_digest:
        blockers.append(
            {
                "code": "capability-manifest-descriptor-digest-mismatch",
                "expected": expected_digest,
                "actual": manifest.get("descriptorDigest"),
            }
        )
    _validate_manifest_capabilities(manifest, descriptor, blockers)
    _validate_runtime_boundary(manifest, descriptor, blockers)
    _validate_host_capability_drift(manifest, descriptor, blockers)
    _validate_sandbox_capability_drift(manifest, descriptor, blockers)
    _validate_event_capture(manifest, descriptor, blockers)
    _validate_planning_launch(manifest, descriptor, blockers)
    _validate_thread_bridge(manifest, descriptor, blockers)
    status = "PASS" if not blockers else "FAIL"
    return {
        "schemaVersion": CAPABILITY_MANIFEST_VALIDATION_SCHEMA_VERSION,
        "status": status,
        "adapterId": descriptor.get("adapterId"),
        "host": descriptor.get("host"),
        "maturity": descriptor.get("maturity"),
        "capabilityCount": len(manifest.get("capabilities", []))
        if isinstance(manifest.get("capabilities"), list)
        else 0,
        "blockers": blockers,
    }


def build_thread_bridge_capability_projection(
    profile: dict[str, Any],
    *,
    qualification_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project adapter metadata into the existing capability contract."""

    profile_validation = validate_thread_bridge_profile(profile)
    if profile_validation["status"] != "PASS":
        raise ValueError("invalid thread bridge profile")
    entries: list[dict[str, Any]] = []
    for operation in profile["operations"]:
        decision = resolve_thread_operation_status(
            profile,
            operation["name"],
            qualification_receipt=qualification_receipt,
        )
        entries.append(
            {
                "name": operation["name"],
                "support": decision["capabilitySupport"],
                "declaredStatus": decision["declaredStatus"],
                "qualificationStatus": decision["qualificationStatus"],
                "effectiveStatus": decision["effectiveStatus"],
                "capabilitySupport": decision["capabilitySupport"],
                "readOnly": operation["readOnly"],
                "approval": operation["approval"],
                "execution": "adapter-owned",
            }
        )
    supports = {item["support"] for item in entries}
    overall = "supported" if "supported" in supports else "unsupported" if supports == {"unsupported"} else "unknown"
    projection = build_thread_capability(
        adapter_id=profile["adapterId"],
        host=profile["host"],
        support=overall,
        operations=entries,
        qualification_receipt_digest=qualification_receipt.get("receiptDigest") if qualification_receipt else None,
    )
    body = {
        **projection,
        "threadBridgeProfileDigest": profile["profileDigest"],
    }
    return {
        **body,
        "capabilityDigest": canonical_digest({key: value for key, value in body.items() if key != "capabilityDigest"}),
    }


def build_thread_bridge_profile_from_descriptor(
    descriptor: dict[str, Any],
    *,
    capability_manifest_digest: str | None = None,
) -> dict[str, Any]:
    """Build a digest-bound thread profile from one adapter descriptor."""

    section = descriptor.get("threadBridge")
    if not isinstance(section, dict):
        raise ValueError("adapter descriptor has no threadBridge profile")
    return build_thread_bridge_profile(
        adapter_id=cast(str, descriptor.get("adapterId")),
        host=cast(str, descriptor.get("host")),
        operations=section.get("operations", []),
        descriptor_digest=canonical_digest(descriptor),
        capability_manifest_digest=capability_manifest_digest,
        host_range=descriptor.get("liveTestedHostRange"),
        policy_version=cast(str, section.get("policyVersion")),
    )


def capability_manifest_identity(manifest: dict[str, Any]) -> str:
    """Return the non-circular digest basis used by thread profiles."""

    return canonical_digest({key: value for key, value in manifest.items() if key != "threadBridge"})


def _capability_from_operation(operation: dict[str, Any], descriptor: dict[str, Any]) -> dict[str, Any]:
    offline_conformance = operation.get("offlineConformance")
    capability = {
        "name": operation.get("name"),
        "mapping": operation.get("mapping"),
        "offlineConformance": offline_conformance,
        "support": "declared",
        "unsupportedOperationPolicy": descriptor.get("unsupportedOperationPolicy"),
        "lifecycleSemantics": descriptor.get("coreSemantics"),
        "liveEvidenceRequiredForVerified": offline_conformance != "deterministic",
    }
    # Keep generated manifests aligned with operation-level lifecycle-control
    # declarations while preserving compatibility with older descriptors.
    for field in ("declaredLevel", "supportedLevel", "qualifiedLevel", "qualificationStatus"):
        if field in operation:
            capability[field] = operation[field]
    return capability


def _event_capture_from_descriptor(descriptor: dict[str, Any]) -> dict[str, Any]:
    if adapter_declares_event_capture(descriptor=descriptor):
        return event_capture_declaration()
    return {
        "status": "NOT_DECLARED",
        "portableEventSchema": "agent-adapter-event.v1",
        "categories": [],
        "producerBoundary": None,
        "promotionRequired": False,
    }


def _host_capabilities_from_descriptor(descriptor: dict[str, Any]) -> list[dict[str, Any]]:
    capabilities = descriptor.get("hostCapabilities")
    if not isinstance(capabilities, list):
        return []
    return [dict(item) for item in capabilities if isinstance(item, dict)]


def _sandbox_capabilities_from_descriptor(descriptor: dict[str, Any]) -> dict[str, Any] | None:
    capabilities = descriptor.get("sandboxCapabilities")
    if not isinstance(capabilities, dict):
        return None
    return dict(capabilities)


def _planning_launch_from_descriptor(descriptor: dict[str, Any]) -> dict[str, Any] | None:
    qualified_launch = descriptor.get("qualifiedLaunch")
    if not isinstance(qualified_launch, dict):
        return None
    return {
        "profileStatus": qualified_launch.get("planningProfileStatus"),
        "planningSupportStatus": qualified_launch.get("planningSupportStatus"),
        "expectedHostVersion": qualified_launch.get("expectedHostVersion"),
        "qualificationRequired": qualified_launch.get("planningQualificationRequired"),
        "hostLaunchStarted": False,
    }


def _thread_bridge_from_descriptor(
    descriptor: dict[str, Any],
    *,
    capability_manifest_digest: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(descriptor.get("threadBridge"), dict):
        return None
    profile = build_thread_bridge_profile_from_descriptor(
        descriptor,
        capability_manifest_digest=capability_manifest_digest,
    )
    return profile


def _validate_manifest_capabilities(
    manifest: dict[str, Any],
    descriptor: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> None:
    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, list):
        blockers.append({"code": "invalid-capability-manifest", "message": "capabilities must be an array"})
        return
    descriptor_operations = descriptor.get("operations")
    if not isinstance(descriptor_operations, list):
        return
    descriptor_names: set[str] = {
        name
        for item in descriptor_operations
        if isinstance(item, dict)
        for name in [item.get("name")]
        if isinstance(name, str)
    }
    manifest_names: set[str] = {
        name for item in capabilities if isinstance(item, dict) for name in [item.get("name")] if isinstance(name, str)
    }
    missing_required = sorted(REQUIRED_OPERATION_NAMES.difference(manifest_names))
    extra = sorted(manifest_names.difference(descriptor_names))
    missing_descriptor = sorted(descriptor_names.difference(manifest_names))
    if missing_required:
        blockers.append({"code": "capability-required-operation-missing", "operations": missing_required})
    if missing_descriptor or extra:
        blockers.append(
            {
                "code": "capability-manifest-operation-drift",
                "missingFromManifest": missing_descriptor,
                "extraInManifest": extra,
            }
        )
    for item in capabilities:
        if not isinstance(item, dict):
            blockers.append({"code": "invalid-capability-entry", "message": "capability entries must be objects"})
            continue
        if item.get("unsupportedOperationPolicy") != "fail-closed":
            blockers.append({"code": "capability-unsupported-operation-policy", "capability": item.get("name")})
        if item.get("lifecycleSemantics") != "delegated-to-agent-lifecycle-core":
            blockers.append({"code": "capability-core-semantics-overclaim", "capability": item.get("name")})


def _validate_runtime_boundary(
    manifest: dict[str, Any],
    descriptor: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> None:
    boundary = manifest.get("runtimeBoundary")
    if not isinstance(boundary, dict):
        blockers.append({"code": "capability-runtime-boundary-missing", "message": "runtimeBoundary must be an object"})
        return
    if boundary.get("lifecycleSemantics") != descriptor.get("coreSemantics"):
        blockers.append({"code": "capability-runtime-boundary-drift", "field": "lifecycleSemantics"})
    if boundary.get("unsupportedOperations") != "fail-closed":
        blockers.append({"code": "capability-runtime-boundary-policy", "field": "unsupportedOperations"})
    if boundary.get("providerModelNamesInCore") is not False:
        blockers.append(
            {
                "code": "capability-provider-model-boundary",
                "message": "provider model names must stay out of core contracts",
            }
        )


def _validate_host_capability_drift(
    manifest: dict[str, Any],
    descriptor: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> None:
    descriptor_capabilities = descriptor.get("hostCapabilities")
    manifest_capabilities = manifest.get("hostCapabilities")
    if descriptor_capabilities is None and manifest_capabilities is None:
        return
    if not isinstance(descriptor_capabilities, list):
        descriptor_capabilities = []
    if manifest_capabilities != descriptor_capabilities:
        blockers.append({"code": "capability-manifest-host-capability-drift"})
        return
    validation = validate_host_capabilities(
        manifest_capabilities,
        adapter_id=descriptor.get("adapterId") if isinstance(descriptor.get("adapterId"), str) else None,
        host=descriptor.get("host") if isinstance(descriptor.get("host"), str) else None,
    )
    if validation["status"] == "FAIL":
        blockers.append({"code": "capability-manifest-host-capability-invalid", "blockers": validation["blockers"]})


def _validate_sandbox_capability_drift(
    manifest: dict[str, Any],
    descriptor: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> None:
    descriptor_capability = descriptor.get("sandboxCapabilities")
    manifest_capability = manifest.get("sandboxCapabilities")
    if descriptor_capability is None and manifest_capability is None:
        return
    if manifest_capability != descriptor_capability:
        blockers.append({"code": "capability-manifest-sandbox-capability-drift"})
        return
    if not isinstance(manifest_capability, dict):
        blockers.append({"code": "capability-manifest-sandbox-capability-invalid"})
        return
    validation = validate_sandbox_capability(manifest_capability)
    if validation["status"] == "FAIL":
        blockers.append({"code": "capability-manifest-sandbox-capability-invalid", "blockers": validation["blockers"]})


def _validate_event_capture(
    manifest: dict[str, Any],
    descriptor: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> None:
    capture = manifest.get("eventCapture")
    if not isinstance(capture, dict):
        blockers.append({"code": "capability-event-capture-missing", "message": "eventCapture must be an object"})
        return
    expected_declared = adapter_declares_event_capture(descriptor=descriptor)
    actual_declared = capture.get("status") == "DECLARED"
    if actual_declared != expected_declared:
        blockers.append(
            {
                "code": "capability-event-capture-drift",
                "expectedDeclared": expected_declared,
                "actualStatus": capture.get("status"),
            }
        )
    if actual_declared:
        operations = descriptor.get("operations", [])
        if not any(isinstance(item, dict) and item.get("name") == EVENT_CAPTURE_OPERATION for item in operations):
            blockers.append(
                {"code": "capability-event-capture-operation-missing", "operation": EVENT_CAPTURE_OPERATION}
            )
        if capture.get("portableEventSchema") != "agent-adapter-event.v1":
            blockers.append(
                {"code": "capability-event-capture-schema", "message": "event capture must use agent-adapter-event.v1"}
            )
        if capture.get("producerBoundary") != "adapter-owned":
            blockers.append(
                {
                    "code": "capability-event-capture-boundary",
                    "message": "event producer boundary must be adapter-owned",
                }
            )
    if capture.get("promotionRequired") is not False:
        blockers.append(
            {
                "code": "capability-event-capture-promotion-overclaim",
                "message": "event capture declaration must not imply promotion",
            }
        )


def _validate_planning_launch(
    manifest: dict[str, Any],
    descriptor: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> None:
    expected = _planning_launch_from_descriptor(descriptor)
    actual = manifest.get("planningLaunch")
    if expected is None:
        if actual is not None:
            blockers.append({"code": "capability-planning-launch-unexpected"})
        return
    if actual != expected:
        blockers.append(
            {
                "code": "capability-planning-launch-drift",
                "expected": expected,
                "actual": actual,
            }
        )


def _validate_thread_bridge(
    manifest: dict[str, Any],
    descriptor: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> None:
    descriptor_profile = descriptor.get("threadBridge")
    manifest_profile = manifest.get("threadBridge")
    if descriptor_profile is None and manifest_profile is None:
        return
    if not isinstance(descriptor_profile, dict) or not isinstance(manifest_profile, dict):
        blockers.append({"code": "capability-thread-bridge-profile-missing"})
        return
    expected = build_thread_bridge_profile_from_descriptor(
        descriptor,
        capability_manifest_digest=capability_manifest_identity(manifest),
    )
    validation = validate_thread_bridge_profile(manifest_profile)
    if validation["status"] != "PASS":
        blockers.append({"code": "capability-thread-bridge-profile-invalid", "blockers": validation["blockers"]})
    if manifest_profile != expected:
        blockers.append({"code": "capability-thread-bridge-profile-drift"})

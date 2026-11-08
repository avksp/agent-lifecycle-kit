"""Pure diagnostic availability observations, separate from task authority."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import canonical_digest


def _model_response_observed(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("status") == "PASS"
        and value.get("backendIdentityAttested") is False
        and all(
            isinstance(value.get(key), str)
            and len(value[key]) == 64
            and all(character in "0123456789abcdef" for character in value[key])
            for key in ("responseDigest", "terminalDigest")
        )
    )


def project_availability(
    *,
    configured: bool,
    executable: dict[str, Any],
    binding_digest: str,
    configuration_digest: str,
    auth_revision_digest: str,
    observation: dict[str, Any] | None,
    now: int,
) -> dict[str, Any]:
    """A fresh observation describes its exact configuration and executable only."""
    observed = observation or {}
    fresh = _observation_is_fresh(observed, executable, binding_digest, configuration_digest, auth_revision_digest, now)
    return {
        "schemaVersion": "agent-binding-availability.v1",
        "status": "PASS" if configured and fresh and executable.get("status") == "PASS" else "UNAVAILABLE",
        "configured": configured,
        "executableDiscovered": executable.get("status") == "PASS",
        "authObservation": "PASS" if fresh else "UNAVAILABLE",
        "probeObservation": "PASS" if fresh else "UNAVAILABLE",
        "qualityQualification": "UNAVAILABLE",
        "observationAgeSeconds": now - observed["observedAt"] if fresh else None,
        "reasonCodes": [] if fresh else ["FRESH_BINDING_OBSERVATION_REQUIRED"],
        "bindingDigest": binding_digest,
        "configurationDigest": configuration_digest,
        "executableDigest": executable.get("executableContentSha256"),
        "modelCallsStarted": False,
        "authorityClaimed": False,
        "quotaAssured": False,
        "actualTokens": None,
        "actualUSD": None,
    }


def _observation_is_fresh(
    observed: dict[str, Any],
    executable: dict[str, Any],
    binding_digest: str,
    configuration_digest: str,
    auth_revision_digest: str,
    now: int,
) -> bool:
    body = {key: value for key, value in observed.items() if key != "observationDigest"}
    return (
        observed.get("schemaVersion") == "agent-local-binding-observation.v1"
        and observed.get("observationDigest") == canonical_digest(body)
        and observed.get("bindingDigest") == binding_digest
        and observed.get("configurationDigest") == configuration_digest
        and observed.get("authRevisionDigest") == auth_revision_digest
        and observed.get("executableDigest") == executable.get("executableContentSha256")
        and type(observed.get("observedAt")) is int
        and type(observed.get("expiresAt")) is int
        and observed["observedAt"] <= now < observed["expiresAt"]
        and 0 < observed["expiresAt"] - observed["observedAt"] <= 3600
        and observed.get("processStarted") is True
        and observed.get("status") == "PASS"
        and _model_response_observed(observed.get("modelResponse"))
        and isinstance(observed.get("launchReceiptDigest"), str)
    )


def build_probe_observation(
    *,
    availability: dict[str, Any],
    auth_revision_digest: str,
    launch: dict[str, Any],
    now: int,
    lineage: dict[str, Any],
    model_response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = {
        "schemaVersion": "agent-local-binding-observation.v1",
        "status": launch.get("status", "BLOCKED") if _model_response_observed(model_response) else "UNAVAILABLE",
        "bindingDigest": availability["bindingDigest"],
        "configurationDigest": availability["configurationDigest"],
        "executableDigest": availability["executableDigest"],
        "authRevisionDigest": auth_revision_digest,
        "observedAt": now,
        "expiresAt": now + 3600,
        "processStarted": launch.get("hostLaunchStarted", False),
        "launchReceiptDigest": launch.get("receiptDigest"),
        "modelResponse": model_response or {"status": "UNAVAILABLE"},
        "lineage": lineage,
        "qualityPromotionClaimed": False,
        "taskAccepted": False,
        "actualTokens": None,
        "actualUSD": None,
    }
    return {**body, "observationDigest": canonical_digest(body)}

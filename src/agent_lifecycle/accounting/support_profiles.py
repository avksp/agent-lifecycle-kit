"""Closed, evidence-neutral matching for H04 adapter capability profiles.

Structural matching is not qualification, model admission, or dispatch authority.
The runtime resolver must independently verify the frozen expectation, referenced
source bytes, qualification, reviewer provenance, and current host binding.
"""

from __future__ import annotations

import re
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.paths import normalize_repo_path

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_MODES = frozenset(
    {"LIFECYCLE_ONLY", "OBSERVATION", "ALK_INVOCATION_ADMISSION", "HOST_PARTIAL_CONTROL", "FULL_FINANCIAL"}
)
_ROLES = frozenset({"coordinator", "worker", "check", "auditor", "retry", "compaction", "closeout"})
_DIMENSIONS = {
    "ACCOUNTING": frozenset({"RECEIPT_IMPORT", "PARTIAL_TOTAL", "FULL_TOTAL"}),
    "CONTROL": frozenset({"ALK_PRE_LAUNCH", "HOST_SCOPED_LIMIT", "ATOMIC_TASK_RUN"}),
    "COVERAGE": frozenset({"NAMED_ROUTES", "ALL_ROUTES"}),
}
_LIMITS = frozenset({"NONE", "ADMISSION_ONLY", "OUTPUT", "STEP", "SESSION_FINANCIAL", "TASK_RUN_FINANCIAL"})
_FAILURE = frozenset({"FAIL_CLOSED", "FAIL_OPEN", "OBSERVE_ONLY"})
_ROUTE_STATES = frozenset({"COVERED", "EXCLUDED", "UNQUALIFIED"})
_ADAPTERS = frozenset(
    {
        "codex",
        "claude",
        "opencode",
        "grok-build",
        "gemini-cli",
        "pi",
        "hermes",
        "qwen-code",
        "kimi-code",
        "cursor",
        "goose",
        "openinterpreter",
    }
)
_SOURCE_KINDS = frozenset(
    {"OFFICIAL_DOCUMENTATION", "OFFICIAL_SOURCE", "RUNTIME_OBSERVATION", "ALK_TEST", "INDEPENDENT_REVIEW"}
)
_CASE_DISPOSITIONS = frozenset(
    {"NATIVE_PASS", "QUALIFIED_LIMITATION", "NOT_APPLICABLE_TO_SELECTED_GUARANTEE", "UNQUALIFIED"}
)
_BINDING_KEYS = frozenset(
    {
        "adapterId",
        "hostVersion",
        "executableSha256",
        "launchMode",
        "providerId",
        "transportId",
        "configurationSha256",
        "evidenceMode",
    }
)
_CLAIM_KEYS = frozenset(
    {
        "claimId",
        "dimension",
        "guarantee",
        "unitId",
        "routeIds",
        "limitKind",
        "boundMethodId",
        "failurePolicy",
        "sourceIds",
    }
)
_REQUEST_CLAIM_KEYS = frozenset(_CLAIM_KEYS - {"claimId", "failurePolicy", "sourceIds"}) | {"requireFailClosed"}
_PROFILE_KEYS = frozenset(
    {
        "profileId",
        "revision",
        "expectationId",
        "binding",
        "modes",
        "claims",
        "routes",
        "sources",
        "sourceCaseDispositions",
        "completeFinancialRun",
    }
)
_REQUEST_KEYS = frozenset(
    {
        "schemaVersion",
        "requestId",
        "expectationDigest",
        "profileDigest",
        "planDigest",
        "alkCandidateDigest",
        "binding",
        "operationId",
        "requestedModes",
        "requiredClaims",
        "routeIds",
        "requestedUpperBound",
    }
)


def _object(value: Any, keys: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise LifecycleError("invalid-accounting-profile", f"{label} has missing or unknown keys")
    return value


def _id(value: Any, label: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise LifecycleError("invalid-accounting-profile", f"{label} is invalid")
    return value


def _hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or _HEX.fullmatch(value) is None:
        raise LifecycleError("invalid-accounting-profile", f"{label} is not SHA-256")
    return value


def _ids(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty) or len(value) > 64:
        raise LifecycleError("invalid-accounting-profile", f"{label} must be a bounded list")
    result = [_id(item, label) for item in value]
    if len(result) != len(set(result)):
        raise LifecycleError("invalid-accounting-profile", f"{label} contains duplicates")
    return result


def _binding(value: Any) -> dict[str, Any]:
    binding = _object(value, _BINDING_KEYS, "host binding")
    for key in ("adapterId", "launchMode", "providerId", "transportId"):
        _id(binding[key], key)
    if binding["adapterId"] not in _ADAPTERS:
        raise LifecycleError("invalid-accounting-profile", "unknown adapterId")
    if not isinstance(binding["hostVersion"], str) or not binding["hostVersion"] or len(binding["hostVersion"]) > 2048:
        raise LifecycleError("invalid-accounting-profile", "hostVersion is invalid")
    mode = binding["evidenceMode"]
    if mode == "RUNTIME_OBSERVED":
        _hex(binding["executableSha256"], "executableSha256")
        _hex(binding["configurationSha256"], "configurationSha256")
    elif mode == "SOURCE_BOUND_LIMITATION":
        if (
            binding["executableSha256"],
            binding["configurationSha256"],
            binding["providerId"],
            binding["transportId"],
        ) != (None, None, "NOT_CLAIMED", "NOT_CLAIMED"):
            raise LifecycleError("invalid-accounting-profile", "source-only binding claims runtime identity")
    else:
        raise LifecycleError("invalid-accounting-profile", "unsupported host evidence mode")
    return binding


def _artifact_ref(value: Any) -> dict[str, Any]:
    ref = _object(value, frozenset({"path", "sha256", "bytes"}), "artifact ref")
    if not isinstance(ref["path"], str) or not ref["path"] or len(ref["path"]) > 2048:
        raise LifecycleError("invalid-accounting-profile", "artifact path is invalid")
    if normalize_repo_path(ref["path"], label="artifact ref") != ref["path"]:
        raise LifecycleError("invalid-accounting-profile", "artifact path is not normalized")
    _hex(ref["sha256"], "artifact sha256")
    if type(ref["bytes"]) is not int or not 0 <= ref["bytes"] <= 9_007_199_254_740_991:
        raise LifecycleError("invalid-accounting-profile", "artifact byte length is invalid")
    return ref


def _validate_sources_and_cases(
    value: dict[str, Any],
    routes: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    claim_ids: set[str],
    route_map: dict[str, dict[str, Any]],
    binding: dict[str, Any],
    modes: list[str],
) -> None:
    if not isinstance(value["sources"], list) or not value["sources"] or len(value["sources"]) > 64:
        raise LifecycleError("invalid-accounting-profile", "sources are missing")
    source_ids: set[str] = set()
    for source in value["sources"]:
        row = _object(source, frozenset({"sourceId", "kind", "origin", "artifact", "versionApplicability"}), "source")
        sid = _id(row["sourceId"], "sourceId")
        if sid in source_ids or not isinstance(row["kind"], str) or row["kind"] not in _SOURCE_KINDS:
            raise LifecycleError("invalid-accounting-profile", "source ID or kind is invalid")
        source_ids.add(sid)
        for key in ("origin", "versionApplicability"):
            if not isinstance(row[key], str) or not row[key] or len(row[key]) > 2048:
                raise LifecycleError("invalid-accounting-profile", f"source {key} is invalid")
        _artifact_ref(row["artifact"])
    if any(set(route["sourceIds"]) - source_ids for route in routes):
        raise LifecycleError("invalid-accounting-profile", "route references absent source")
    if any(set(claim["sourceIds"]) - source_ids for claim in claims):
        raise LifecycleError("invalid-accounting-profile", "claim references absent source")
    dispositions = value["sourceCaseDispositions"]
    if not isinstance(dispositions, list) or len(dispositions) != 13:
        raise LifecycleError("invalid-accounting-profile", "thirteen original case dispositions are required")
    case_ids: set[str] = set()
    for item in dispositions:
        row = _object(
            item,
            frozenset(
                {"sourceCaseId", "sourceCaseSha256", "claimIds", "routeIds", "disposition", "reason", "evidenceRefs"}
            ),
            "case disposition",
        )
        cid = row["sourceCaseId"]
        if not isinstance(cid, str) or not re.fullmatch(r"AC(0[1-9]|1[0-3])", cid) or cid in case_ids:
            raise LifecycleError("invalid-accounting-profile", "source case ID is missing or duplicated")
        case_ids.add(cid)
        _hex(row["sourceCaseSha256"], "sourceCaseSha256")
        if set(_ids(row["claimIds"], "case claimIds", allow_empty=True)) - claim_ids:
            raise LifecycleError("invalid-accounting-profile", "case references absent claim")
        if set(_ids(row["routeIds"], "case routeIds")) - set(route_map):
            raise LifecycleError("invalid-accounting-profile", "case references absent route")
        if not isinstance(row["disposition"], str) or row["disposition"] not in _CASE_DISPOSITIONS:
            raise LifecycleError("invalid-accounting-profile", "case disposition is invalid")
        if binding["evidenceMode"] == "SOURCE_BOUND_LIMITATION" and row["disposition"] == "NATIVE_PASS":
            raise LifecycleError("invalid-accounting-profile", "source-only profile claims native case PASS")
        if not isinstance(row["reason"], str) or not row["reason"] or len(row["reason"]) > 2048:
            raise LifecycleError("invalid-accounting-profile", "case reason is invalid")
        refs = row["evidenceRefs"]
        if not isinstance(refs, list) or not 1 <= len(refs) <= 64:
            raise LifecycleError("invalid-accounting-profile", "case evidence refs are missing")
        for ref in refs:
            _artifact_ref(ref)
    if "FULL_FINANCIAL" in modes:
        guarantees = {(claim["dimension"], claim["guarantee"]) for claim in claims}
        if (
            any(route["state"] != "COVERED" for route in routes)
            or not {("ACCOUNTING", "FULL_TOTAL"), ("CONTROL", "ATOMIC_TASK_RUN"), ("COVERAGE", "ALL_ROUTES")}
            <= guarantees
            or any(row["disposition"] != "NATIVE_PASS" for row in dispositions)
        ):
            raise LifecycleError("invalid-accounting-profile", "full financial prerequisites are incomplete")


def validate_profile_payload(payload: Any) -> dict[str, Any]:
    """Validate a profile's closed shape without treating it as accepted evidence."""

    value = _object(payload, _PROFILE_KEYS, "profile payload")
    _id(value["profileId"], "profileId")
    _id(value["expectationId"], "expectationId")
    if type(value["revision"]) is not int or not 1 <= value["revision"] <= 9_007_199_254_740_991:
        raise LifecycleError("invalid-accounting-profile", "revision is invalid")
    binding = _binding(value["binding"])
    modes = value["modes"]
    if (
        not isinstance(modes, list)
        or not modes
        or any(not isinstance(mode, str) for mode in modes)
        or len(modes) != len(set(modes))
        or not set(modes) <= _MODES
    ):
        raise LifecycleError("invalid-accounting-profile", "profile modes are invalid")
    if "LIFECYCLE_ONLY" in modes and len(modes) != 1:
        raise LifecycleError("invalid-accounting-profile", "lifecycle-only mode cannot be combined")
    if type(value["completeFinancialRun"]) is not bool:
        raise LifecycleError("invalid-accounting-profile", "completeFinancialRun must be boolean")
    if "FULL_FINANCIAL" in modes and not value["completeFinancialRun"]:
        raise LifecycleError("invalid-accounting-profile", "full mode requires complete financial run")
    if binding["evidenceMode"] == "SOURCE_BOUND_LIMITATION" and set(modes) & {
        "OBSERVATION",
        "HOST_PARTIAL_CONTROL",
        "FULL_FINANCIAL",
    }:
        raise LifecycleError("invalid-accounting-profile", "source-only profile claims native-positive mode")

    routes = value["routes"]
    if not isinstance(routes, list) or not 7 <= len(routes) <= 64:
        raise LifecycleError("invalid-accounting-profile", "route inventory is incomplete")
    route_map: dict[str, dict[str, Any]] = {}
    roles: set[str] = set()
    for route in routes:
        row = _object(route, frozenset({"role", "routeId", "state", "claimIds", "reason", "sourceIds"}), "route")
        if not isinstance(row["role"], str) or not isinstance(row["state"], str):
            raise LifecycleError("invalid-accounting-profile", "route role or state is invalid")
        if row["role"] not in _ROLES or row["state"] not in _ROUTE_STATES:
            raise LifecycleError("invalid-accounting-profile", "route role or state is invalid")
        rid = _id(row["routeId"], "routeId")
        if rid in route_map:
            raise LifecycleError("invalid-accounting-profile", "routeId is duplicated")
        if not isinstance(row["reason"], str) or not row["reason"]:
            raise LifecycleError("invalid-accounting-profile", "route reason is required")
        _ids(row["claimIds"], "route claimIds", allow_empty=True)
        _ids(row["sourceIds"], "route sourceIds")
        if row["state"] != "COVERED" and row["claimIds"]:
            raise LifecycleError("invalid-accounting-profile", "uncovered route has positive claims")
        route_map[rid] = row
        roles.add(row["role"])
    if roles != _ROLES:
        raise LifecycleError("invalid-accounting-profile", "all seven roles require inventory")

    claims = value["claims"]
    if not isinstance(claims, list) or len(claims) > 64:
        raise LifecycleError("invalid-accounting-profile", "claims are invalid")
    claim_ids: set[str] = set()
    for claim in claims:
        row = _object(claim, _CLAIM_KEYS, "claim")
        cid = _id(row["claimId"], "claimId")
        if cid in claim_ids:
            raise LifecycleError("invalid-accounting-profile", "claimId is duplicated")
        claim_ids.add(cid)
        if not isinstance(row["dimension"], str) or not isinstance(row["guarantee"], str):
            raise LifecycleError("invalid-accounting-profile", "dimension and guarantee disagree")
        if row["dimension"] not in _DIMENSIONS or row["guarantee"] not in _DIMENSIONS[row["dimension"]]:
            raise LifecycleError("invalid-accounting-profile", "dimension and guarantee disagree")
        _id(row["unitId"], "unitId")
        if not isinstance(row["limitKind"], str) or not isinstance(row["failurePolicy"], str):
            raise LifecycleError("invalid-accounting-profile", "claim limit or failure policy is invalid")
        if row["limitKind"] not in _LIMITS or row["failurePolicy"] not in _FAILURE:
            raise LifecycleError("invalid-accounting-profile", "claim limit or failure policy is invalid")
        if row["boundMethodId"] is not None:
            _id(row["boundMethodId"], "boundMethodId")
        for rid in _ids(row["routeIds"], "claim routeIds"):
            if rid not in route_map or route_map[rid]["state"] != "COVERED" or cid not in route_map[rid]["claimIds"]:
                raise LifecycleError("invalid-accounting-profile", "claim includes an uncovered route")
        _ids(row["sourceIds"], "claim sourceIds")
        if binding["evidenceMode"] == "SOURCE_BOUND_LIMITATION" and (
            row["dimension"],
            row["guarantee"],
            row["unitId"],
            row["limitKind"],
            row["boundMethodId"],
            row["failurePolicy"],
        ) != ("CONTROL", "ALK_PRE_LAUNCH", "alk-owned-invocations", "ADMISSION_ONLY", None, "FAIL_CLOSED"):
            raise LifecycleError("invalid-accounting-profile", "source-only profile claims native capability")
    if any(set(route["claimIds"]) - claim_ids for route in routes):
        raise LifecycleError("invalid-accounting-profile", "route references absent claim")
    if modes == ["LIFECYCLE_ONLY"] and claims:
        raise LifecycleError("invalid-accounting-profile", "lifecycle-only profile has positive claims")
    if modes == ["OBSERVATION"] and any(claim["dimension"] == "CONTROL" for claim in claims):
        raise LifecycleError("invalid-accounting-profile", "observation alone cannot control calls")
    if value["completeFinancialRun"] and "FULL_FINANCIAL" not in modes:
        raise LifecycleError("invalid-accounting-profile", "complete financial claim lacks full mode")
    _validate_sources_and_cases(value, routes, claims, claim_ids, route_map, binding, modes)
    return {
        "status": "STRUCTURE_VALID_ONLY",
        "profileDigest": canonical_digest(value),
        "routeCount": len(route_map),
        "claimCount": len(claims),
        "dispatchEntitlement": False,
    }


def match_requested_claims(
    payload: dict[str, Any],
    request: dict[str, Any],
    *,
    expectation_digest: str,
    plan_digest: str,
    candidate_digest: str,
) -> dict[str, Any]:
    """Pure exact match. A MATCH never grants capability or dispatch."""

    profile = validate_profile_payload(payload)
    _hex(expectation_digest, "expectationDigest")
    _hex(plan_digest, "planDigest")
    _hex(candidate_digest, "alkCandidateDigest")

    def result(status: str, detail: str, matched: list[str] | None = None) -> dict[str, Any]:
        return {
            "schemaVersion": "alk-accounting-structural-match.v1",
            "status": status,
            "detail": detail,
            "matchedClaimIds": matched or [],
            "dispatchEntitlement": False,
            "evidenceQualified": False,
        }

    try:
        req = _object(request, _REQUEST_KEYS, "resolver request")
        if req["schemaVersion"] != "alk-accounting-capability-request.v1":
            return result("MISMATCH", "INVALID_INPUT")
        _id(req["requestId"], "requestId")
        _id(req["operationId"], "operationId")
        for key in ("expectationDigest", "profileDigest", "planDigest", "alkCandidateDigest"):
            _hex(req[key], key)
        _binding(req["binding"])
        requested_modes = req["requestedModes"]
        if (
            not isinstance(requested_modes, list)
            or not requested_modes
            or any(not isinstance(mode, str) for mode in requested_modes)
            or len(requested_modes) != len(set(requested_modes))
        ):
            return result("MISMATCH", "INVALID_INPUT")
        if not set(requested_modes) <= _MODES:
            return result("MISMATCH", "INVALID_INPUT")
        route_ids = _ids(req["routeIds"], "request routeIds")
        requested_claims = req["requiredClaims"]
        if not isinstance(requested_claims, list) or len(requested_claims) > 64:
            return result("MISMATCH", "INVALID_INPUT")
        bound = req["requestedUpperBound"]
        if bound is not None and (type(bound) is not int or not 0 <= bound <= 9_007_199_254_740_991):
            return result("MISMATCH", "INVALID_INPUT")
    except LifecycleError:
        return result("MISMATCH", "INVALID_INPUT")
    if (req["expectationDigest"], req["profileDigest"], req["planDigest"], req["alkCandidateDigest"]) != (
        expectation_digest,
        profile["profileDigest"],
        plan_digest,
        candidate_digest,
    ) or req["binding"] != payload["binding"]:
        return result("MISMATCH", "BINDING_MISMATCH")
    if not set(requested_modes) <= set(payload["modes"]):
        return result("MISMATCH", "UNSUPPORTED_GUARANTEE")
    routes = {row["routeId"]: row for row in payload["routes"]}
    if any(rid not in routes for rid in route_ids):
        return result("MISMATCH", "UNCOVERED_ROUTE")
    claims = payload["claims"]
    matched: list[str] = []
    for needed in requested_claims:
        try:
            _object(needed, _REQUEST_CLAIM_KEYS, "requested claim")
            if not isinstance(needed["dimension"], str) or not isinstance(needed["guarantee"], str):
                return result("MISMATCH", "INVALID_INPUT")
            if needed["dimension"] not in _DIMENSIONS or needed["guarantee"] not in _DIMENSIONS[needed["dimension"]]:
                return result("MISMATCH", "INVALID_INPUT")
            _id(needed["unitId"], "unitId")
            wanted_routes = _ids(needed["routeIds"], "requested claim routeIds")
            if (
                not isinstance(needed["limitKind"], str)
                or needed["limitKind"] not in _LIMITS
                or type(needed["requireFailClosed"]) is not bool
            ):
                return result("MISMATCH", "INVALID_INPUT")
            if needed["boundMethodId"] is not None:
                _id(needed["boundMethodId"], "boundMethodId")
        except LifecycleError:
            return result("MISMATCH", "INVALID_INPUT")
        if not set(wanted_routes) <= set(route_ids) or any(routes[rid]["state"] != "COVERED" for rid in wanted_routes):
            return result("MISMATCH", "UNCOVERED_ROUTE")
        found = next(
            (
                claim
                for claim in claims
                if all(
                    claim[key] == needed[key]
                    for key in ("dimension", "guarantee", "unitId", "limitKind", "boundMethodId")
                )
                and set(wanted_routes) <= set(claim["routeIds"])
                and (not needed["requireFailClosed"] or claim["failurePolicy"] == "FAIL_CLOSED")
            ),
            None,
        )
        if found is None:
            return result("MISMATCH", "UNSUPPORTED_GUARANTEE")
        matched.append(found["claimId"])
    if (
        any(
            needed["dimension"] in {"ACCOUNTING", "CONTROL"}
            and needed["limitKind"] in {"SESSION_FINANCIAL", "TASK_RUN_FINANCIAL"}
            for needed in requested_claims
        )
        and bound is None
    ):
        return result("MISMATCH", "BOUND_UNAVAILABLE")
    if "FULL_FINANCIAL" in requested_modes and (not payload["completeFinancialRun"] or bound is None):
        return result("MISMATCH", "BOUND_UNAVAILABLE")
    return result("MATCH_PENDING_EVIDENCE", "MATCH", matched)


__all__ = ["match_requested_claims", "validate_profile_payload"]

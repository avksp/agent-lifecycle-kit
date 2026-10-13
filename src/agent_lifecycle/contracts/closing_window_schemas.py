"""Closed closing-request data schemas; no native authority or filesystem I/O."""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest, load_json_object
from agent_lifecycle.contracts.deadline_schemas import utc_microseconds
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.workflow_authority import verify_signed_window_grant
from agent_lifecycle.contracts.workflow_authority_schemas import (
    RUN_OUTPUT_ANCHOR_V1, validate_permission_scope,
    validate_run_output_anchor as _validate_output_anchor_shape,
)

WINDOW_REQUEST_V1 = "agent-closing-window-request.v1"
ALLOWED_WRITES_V1 = "agent-closing-allowed-writes.v1"
_MAX_INTEGER = (1 << 53) - 1
_MAX_BYTES = 1_048_576
_WRITE_CLASSES = {"CANONICAL_STATE_REPLACE", "EVENT_LOG_APPEND", "FINAL_PROOF_CREATE_ONCE",
                  "PROOF_BODY_CREATE_ONCE"}

CLOSING_WINDOW_SCHEMAS = {'agent-closing-allowed-writes.v1': {'$id': 'agent-closing-allowed-writes.v1',
                                     '$schema': 'https://json-schema.org/draft/2020-12/schema',
                                     'additionalProperties': False,
                                     'properties': {'bindingId': {'maxLength': 256,
                                                                  'minLength': 1,
                                                                  'type': 'string'},
                                                    'closingWindowId': {'maxLength': 256,
                                                                        'minLength': 1,
                                                                        'type': 'string'},
                                                    'entries': {'items': {'enum': ['CANONICAL_STATE_REPLACE',
                                                                                   'EVENT_LOG_APPEND',
                                                                                   'FINAL_PROOF_CREATE_ONCE',
                                                                                   'PROOF_BODY_CREATE_ONCE']},
                                                                'maxItems': 4,
                                                                'minItems': 1,
                                                                'type': 'array',
                                                                'uniqueItems': True},
                                                    'outputAnchorDigest': {'pattern': '^[0-9a-f]{64}$',
                                                                           'type': 'string'},
                                                    'runId': {'maxLength': 256, 'minLength': 1, 'type': 'string'},
                                                    'schemaVersion': {'const': 'agent-closing-allowed-writes.v1'}},
                                     'required': ['schemaVersion',
                                                  'bindingId',
                                                  'runId',
                                                  'closingWindowId',
                                                  'outputAnchorDigest',
                                                  'entries'],
                                     'type': 'object'},
 'agent-closing-window-request.v1': {'$defs': {'ArtifactRef': {'additionalProperties': False,
                                                               'properties': {'bytes': {'maximum': 1048576,
                                                                                        'minimum': 1,
                                                                                        'type': 'integer'},
                                                                              'path': {'maxLength': 4096,
                                                                                       'minLength': 1,
                                                                                       'type': 'string'},
                                                                              'sha256': {'pattern': '^[0-9a-f]{64}$',
                                                                                         'type': 'string'}},
                                                               'required': ['path', 'sha256', 'bytes'],
                                                               'type': 'object'},
                                               'PermissionScope': {'additionalProperties': False,
                                                                   'properties': {'bindingId': {'maxLength': 256,
                                                                                                'minLength': 1,
                                                                                                'type': 'string'},
                                                                                  'budgetScopeId': {'maxLength': 256,
                                                                                                    'minLength': 1,
                                                                                                    'type': 'string'},
                                                                                  'effectivePlanDigest': {'pattern': '^[0-9a-f]{64}$',
                                                                                                          'type': 'string'},
                                                                                  'evidenceSubjectDigest': {'pattern': '^[0-9a-f]{64}$',
                                                                                                            'type': 'string'},
                                                                                  'journalIdentity': {'maxLength': 256,
                                                                                                      'minLength': 1,
                                                                                                      'type': 'string'},
                                                                                  'originalPlanDigest': {'pattern': '^[0-9a-f]{64}$',
                                                                                                         'type': 'string'},
                                                                                  'packageId': {'maxLength': 256,
                                                                                                'minLength': 1,
                                                                                                'type': 'string'},
                                                                                  'runId': {'maxLength': 256,
                                                                                            'minLength': 1,
                                                                                            'type': 'string'},
                                                                                  'sourceRevision': {'maxLength': 256,
                                                                                                     'minLength': 1,
                                                                                                     'type': 'string'}},
                                                                   'required': ['runId',
                                                                                'packageId',
                                                                                'budgetScopeId',
                                                                                'journalIdentity',
                                                                                'bindingId',
                                                                                'originalPlanDigest',
                                                                                'effectivePlanDigest',
                                                                                'sourceRevision',
                                                                                'evidenceSubjectDigest'],
                                                                   'type': 'object'}},
                                     '$id': 'agent-closing-window-request.v1',
                                     '$schema': 'https://json-schema.org/draft/2020-12/schema',
                                     'additionalProperties': False,
                                     'properties': {'allowedActions': {'items': {'enum': ['read-evidence',
                                                                                          'assess-evidence',
                                                                                          'report',
                                                                                          'final-audit',
                                                                                          'final-check',
                                                                                          'apply-final-outcome',
                                                                                          'finalize',
                                                                                          'accounting-closeout']},
                                                                       'maxItems': 8,
                                                                       'minItems': 1,
                                                                       'type': 'array',
                                                                       'uniqueItems': True},
                                                    'allowedWritesDigest': {'pattern': '^[0-9a-f]{64}$',
                                                                            'type': 'string'},
                                                    'allowedWritesRef': {'$ref': '#/$defs/ArtifactRef'},
                                                    'closingWindowId': {'maxLength': 256,
                                                                        'minLength': 1,
                                                                        'type': 'string'},
                                                    'deadlineConsumerIds': {'items': {'maxLength': 256,
                                                                                      'minLength': 1,
                                                                                      'type': 'string'},
                                                                            'maxItems': 256,
                                                                            'type': 'array',
                                                                            'uniqueItems': True},
                                                    'deadlineInventoryDigest': {'pattern': '^[0-9a-f]{64}$',
                                                                                'type': 'string'},
                                                    'expectedAccountingRevision': {'maximum': 9007199254740991,
                                                                                   'minimum': 0,
                                                                                   'type': 'integer'},
                                                    'expectedWorkflowRevision': {'maximum': 9007199254740991,
                                                                                 'minimum': 0,
                                                                                 'type': 'integer'},
                                                    'expiresAt': {'pattern': '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{6}Z$',
                                                                  'type': 'string'},
                                                    'nonce': {'pattern': '^[0-9a-f]{64}$', 'type': 'string'},
                                                    'originalAuthorizationDigest': {'pattern': '^[0-9a-f]{64}$',
                                                                                    'type': 'string'},
                                                    'originalBlockerDigest': {'pattern': '^[0-9a-f]{64}$',
                                                                              'type': 'string'},
                                                    'originalDeadlineDigest': {'pattern': '^[0-9a-f]{64}$',
                                                                               'type': 'string'},
                                                    'ownerPermissionRef': {'pattern': '^sha256:[0-9a-f]{64}$',
                                                                           'type': 'string'},
                                                    'permission': {'const': 'closing.activate'},
                                                    'policyEffectCandidateDigest': {'pattern': '^[0-9a-f]{64}$',
                                                                                    'type': 'string'},
                                                    'predecessorWindowId': {'anyOf': [{'maxLength': 256,
                                                                                       'minLength': 1,
                                                                                       'type': 'string'},
                                                                                      {'type': 'null'}]},
                                                    'qualifiedPolicyEffectRef': {'$ref': '#/$defs/ArtifactRef'},
                                                    'resourceApprovalDigest': {'pattern': '^[0-9a-f]{64}$',
                                                                               'type': 'string'},
                                                    'resourceApprovalRef': {'$ref': '#/$defs/ArtifactRef'},
                                                    'schemaVersion': {'const': 'agent-closing-window-request.v1'},
                                                    'scope': {'$ref': '#/$defs/PermissionScope'},
                                                    'validFrom': {'pattern': '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{6}Z$',
                                                                  'type': 'string'}},
                                     'required': ['schemaVersion',
                                                  'scope',
                                                  'permission',
                                                  'closingWindowId',
                                                  'predecessorWindowId',
                                                  'nonce',
                                                  'expectedWorkflowRevision',
                                                  'expectedAccountingRevision',
                                                  'validFrom',
                                                  'expiresAt',
                                                  'allowedActions',
                                                  'allowedWritesRef',
                                                  'allowedWritesDigest',
                                                  'resourceApprovalRef',
                                                  'resourceApprovalDigest',
                                                  'qualifiedPolicyEffectRef',
                                                  'policyEffectCandidateDigest',
                                                  'deadlineInventoryDigest',
                                                  'deadlineConsumerIds',
                                                  'originalAuthorizationDigest',
                                                  'originalDeadlineDigest',
                                                  'originalBlockerDigest',
                                                  'ownerPermissionRef'],
                                     'type': 'object'}}


_INTENT_SCHEMA = deepcopy(CLOSING_WINDOW_SCHEMAS[WINDOW_REQUEST_V1])
_INTENT_SCHEMA["required"].remove("ownerPermissionRef")
del _INTENT_SCHEMA["properties"]["ownerPermissionRef"]


def _invalid(detail: str) -> None:
    raise LifecycleError("closing-window-contract-invalid", detail)


def _closed(value: Any, schema: dict) -> dict:
    if type(value) is not dict or set(value) != set(schema["required"]):
        _invalid("Record has missing or unknown fields")
    if len(canonical_bytes(value)) > _MAX_BYTES:
        _invalid("Record exceeds the byte bound")
    return value


def _text(value: Any, label: str, maximum: int = 256) -> str:
    if type(value) is not str or not 1 <= len(value) <= maximum or any(ord(c) < 32 for c in value):
        _invalid(f"{label} is not bounded text")
    return value


def _digest(value: Any, label: str) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        _invalid(f"{label} is not a digest")
    return value


def _uint(value: Any, label: str, maximum: int = _MAX_INTEGER) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        _invalid(f"{label} is not a bounded integer")
    return value


def _relative(value: Any, label: str, *, root_allowed: bool = False) -> str:
    path = _text(value, label, 4096)
    if root_allowed and path == ".":
        return path
    parts = path.split("/")
    if "\\" in path or ":" in path or any(p in {"", ".", ".."} for p in parts):
        _invalid(f"{label} is not a normalized relative path")
    return path


def _artifact_ref(value: Any) -> None:
    if type(value) is not dict or set(value) != {"path", "sha256", "bytes"}:
        _invalid("Artifact ref is not closed")
    _relative(value["path"], "artifact path")
    _digest(value["sha256"], "artifact digest")
    if not 1 <= _uint(value["bytes"], "artifact bytes", _MAX_BYTES):
        _invalid("Artifact bytes are empty")


def _unique_strings(value: Any, label: str, maximum: int, allowed: set[str] | None = None) -> list:
    if type(value) is not list or len(value) > maximum:
        _invalid(f"{label} is not a bounded list")
    for item in value:
        _text(item, label)
    if len(value) != len(set(value)) or allowed is not None and not set(value) <= allowed:
        _invalid(f"{label} has duplicate or unknown members")
    return value


def validate_window_intent(value: Any) -> dict:
    record = _closed(value, _INTENT_SCHEMA)
    if record["schemaVersion"] != WINDOW_REQUEST_V1 or record["permission"] != "closing.activate":
        _invalid("Request version or permission differs")
    validate_permission_scope(record["scope"])
    _text(record["closingWindowId"], "window ID")
    if record["predecessorWindowId"] is not None:
        _text(record["predecessorWindowId"], "predecessor window ID")
    for field in ("nonce", "allowedWritesDigest", "resourceApprovalDigest", "policyEffectCandidateDigest",
                  "deadlineInventoryDigest", "originalAuthorizationDigest", "originalDeadlineDigest",
                  "originalBlockerDigest"):
        _digest(record[field], field)
    for field in ("expectedWorkflowRevision", "expectedAccountingRevision"):
        _uint(record[field], field)
    if utc_microseconds(record["validFrom"]) >= utc_microseconds(record["expiresAt"]):
        _invalid("Request interval must be nonempty")
    actions = _unique_strings(record["allowedActions"], "actions", 8,
                             set(_INTENT_SCHEMA["properties"]["allowedActions"]["items"]["enum"]))
    if not actions:
        _invalid("Request actions are empty")
    _unique_strings(record["deadlineConsumerIds"], "deadline consumers", 256)
    for field in ("allowedWritesRef", "resourceApprovalRef", "qualifiedPolicyEffectRef"):
        _artifact_ref(record[field])
    return record


def validate_window_request(value: Any) -> dict:
    record = _closed(value, CLOSING_WINDOW_SCHEMAS[WINDOW_REQUEST_V1])
    if type(record["ownerPermissionRef"]) is not str or re.fullmatch(
            r"sha256:[0-9a-f]{64}", record["ownerPermissionRef"]) is None:
        _invalid("Owner permission is not a canonical grant reference")
    validate_window_intent({k: v for k, v in record.items() if k != "ownerPermissionRef"})
    return record


def window_intent(value: Any) -> dict:
    """Project the existing22 wire fields; do not refresh or sign any value."""
    record = validate_window_request(value)
    return deepcopy({k: v for k, v in record.items() if k != "ownerPermissionRef"})


def load_window_request(raw: bytes) -> dict:
    """Reject duplicate raw JSON members before any normalization or digest."""
    if type(raw) is not bytes:
        _invalid("Request must be bounded raw bytes")
    return validate_window_request(load_json_object(raw, label="closing request"))


def validate_allowed_writes(value: Any) -> dict:
    record = _closed(value, CLOSING_WINDOW_SCHEMAS[ALLOWED_WRITES_V1])
    if record["schemaVersion"] != ALLOWED_WRITES_V1:
        _invalid("AllowedWrites version differs")
    for field in ("bindingId", "runId", "closingWindowId"):
        _text(record[field], field)
    _digest(record["outputAnchorDigest"], "output anchor digest")
    entries = _unique_strings(record["entries"], "write classes", 4, _WRITE_CLASSES)
    if not entries or entries != sorted(entries):
        _invalid("Write classes must be nonempty and sorted")
    return record


def validate_run_output_anchor(value: Any) -> dict:
    """Check lexical data only; held identity, symlinks and custody remain unproved."""
    record = _validate_output_anchor_shape(value)
    if record["schemaVersion"] != RUN_OUTPUT_ANCHOR_V1 or record["storageProtocolVersion"] != "6":
        _invalid("Output anchor version differs")
    for field in ("bindingDigest", "adoptedStateDigest"):
        _digest(record[field], field)
    for field in ("runId", "journalIdentity"):
        _text(record[field], field)
    identity = record["artifactAuthorityRootIdentity"]
    if type(identity) is not dict or set(identity) != {"platform", "volumeId", "fileId"}:
        _invalid("Root identity is not closed")
    if type(identity["platform"]) is not str or identity["platform"] not in {"POSIX", "WINDOWS"}:
        _invalid("Root platform is unsupported")
    for field in ("volumeId", "fileId"):
        _text(identity[field], field)
    for field in ("artifactAuthorityRootPath", "canonicalStatePath", "packageRoot"):
        _text(record[field], field, 4096)
    path_type = PurePosixPath if identity["platform"] == "POSIX" else PureWindowsPath
    root, state = path_type(record["artifactAuthorityRootPath"]), path_type(record["canonicalStatePath"])
    if not root.is_absolute() or not state.is_absolute() or ".." in root.parts or ".." in state.parts:
        _invalid("Root/state data is not absolute and normalized")
    separator = "/" if identity["platform"] == "POSIX" else "\\"
    for field, path in (("artifactAuthorityRootPath", root), ("canonicalStatePath", state)):
        selected_path = record[field].replace("/", "\\") if separator == "\\" else record[field]
        if selected_path != str(path):
            _invalid("Root/state data has noncanonical path components")
    try:
        relative_state = state.relative_to(root)
    except ValueError:
        _invalid("State data is outside the selected root")
    if not relative_state.parts or "." in record["canonicalStatePath"].replace("\\", "/").split("/"):
        _invalid("Canonical state path is invalid")
    package = _relative(record["resolvedPackageRootRelativePath"], "resolved package", root_allowed=True)
    _relative(record["eventLog"], "event log")
    output = _relative(record["runOutputRootRelativePath"], "run output root")
    run_key = hashlib.sha256(record["runId"].encode("utf-8")).hexdigest()
    expected = ("" if package == "." else package + "/") + ".alk-closing/" + run_key
    if output != expected:
        _invalid("Output root is not derived from the adopted package/run data")
    return record


def _selected_request_join(request: dict, selected: Any) -> None:
    fields = {"scope", "expectedWorkflowRevision", "expectedAccountingRevision",
              "originalAuthorizationDigest", "originalDeadlineDigest", "originalBlockerDigest",
              "outputAnchorDigest"}
    if type(selected) is not dict or set(selected) != fields:
        _invalid("Independent selected request data is incomplete")
    validate_permission_scope(selected["scope"])
    for field in fields - {"scope", "expectedWorkflowRevision", "expectedAccountingRevision"}:
        _digest(selected[field], field)
    for field in ("expectedWorkflowRevision", "expectedAccountingRevision"):
        _uint(selected[field], field)
    if any(request[field] != selected[field] for field in fields - {"outputAnchorDigest"}):
        _invalid("Request differs from selected original scope/revision/authority data")


def _grant_request_join(request: dict, grant: dict) -> None:
    if request["ownerPermissionRef"] != "sha256:" + canonical_digest(grant):
        _invalid("Request does not reference the exact full signed grant")
    if grant["windowIntentDigest"] != canonical_digest(window_intent(request)):
        _invalid("Grant does not bind the original22-field intent")
    fields = ("scope", "permission", "closingWindowId", "nonce", "expectedWorkflowRevision",
              "validFrom", "expiresAt", "allowedActions", "allowedWritesDigest",
              "resourceApprovalDigest", "originalAuthorizationDigest", "originalDeadlineDigest",
              "originalBlockerDigest")
    if any(request[field] != grant[field] for field in fields):
        _invalid("Request differs from the signed grant")


def _writes_anchor_join(request: dict, raw: Any, anchor: dict, selected: dict) -> None:
    if type(raw) is not bytes:
        _invalid("AllowedWrites must be bounded raw bytes")
    ref = request["allowedWritesRef"]
    if len(raw) != ref["bytes"] or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        _invalid("AllowedWrites raw identity differs")
    writes = validate_allowed_writes(load_json_object(raw, label="closing AllowedWrites"))
    if canonical_digest(writes) != request["allowedWritesDigest"]:
        _invalid("AllowedWrites canonical digest differs")
    if set(writes["entries"]) != _WRITE_CLASSES:
        _invalid("Complete positive closing data needs all four write classes")
    scope = request["scope"]
    if (writes["bindingId"] != scope["bindingId"] or writes["runId"] != scope["runId"]
            or writes["closingWindowId"] != request["closingWindowId"]):
        _invalid("AllowedWrites scope/window differs")
    if (canonical_digest(anchor) != selected["outputAnchorDigest"]
            or writes["outputAnchorDigest"] != selected["outputAnchorDigest"]):
        _invalid("Output anchor is not the independently selected data")
    if anchor["runId"] != scope["runId"] or anchor["journalIdentity"] != scope["journalIdentity"]:
        _invalid("Output anchor run/journal differs")


def evaluate_window_request_data(
    request: Any, *, grant_raw: bytes, pin: dict, issuance: dict, current: dict,
    selected: dict, allowed_writes_raw: bytes, output_anchor: dict, observed_at: str,
) -> dict:
    """Join signed and selected data; caller selection is not native trust."""
    record = load_window_request(request) if type(request) is bytes else validate_window_request(request)
    _selected_request_join(record, selected)
    grant = load_json_object(grant_raw, label="closing grant")
    crypto = verify_signed_window_grant(pin, issuance, current, grant,
                                       expected_scope=selected["scope"], observed_at=observed_at)
    _grant_request_join(record, grant)
    anchor = validate_run_output_anchor(output_anchor)
    _writes_anchor_join(record, allowed_writes_raw, anchor, selected)
    return {"schemaVersion": "agent-closing-window-request-data-check.v1", "status": "DATA_CANDIDATE",
            "requestDigest": canonical_digest(record), "intentDigest": canonical_digest(window_intent(record)),
            "grantDigest": crypto["grantDigest"], "outputAnchorDigest": canonical_digest(anchor),
            "signatureVerified": True, "bootstrapQualified": False, "historyVerified": False,
            "selectedAuthorityVerified": False, "heldRootIdentityVerified": False, "clockQualified": False,
            "resourcePolicyVerified": False, "deadlineInputVerified": False,
            "nonceConsumed": False, "nativePermissionGranted": False, "financialAdmissionGranted": False,
            "providerDispatchGranted": False}


__all__ = ["ALLOWED_WRITES_V1", "RUN_OUTPUT_ANCHOR_V1", "WINDOW_REQUEST_V1", "CLOSING_WINDOW_SCHEMAS",
           "validate_window_intent", "validate_window_request", "window_intent", "load_window_request",
           "validate_allowed_writes", "validate_run_output_anchor", "evaluate_window_request_data"]

"""Closed release evidence records; shape is not native acceptance authority."""

from __future__ import annotations

import re
from typing import Any, NoReturn

from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest, load_json_object
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.paths import normalize_repo_path

EXPECTED_V1 = "agent-expected-evidence.v1"
EXPECTED_V2 = "agent-expected-evidence.v2"
RECEIPT_V1 = "agent-evidence-receipt.v1"
COMMAND_V1 = "agent-command-observation.v1"
COMPOSITE_V1 = "agent-composite-applicability.v1"
ASYNC_V1 = "agent-async-observation.v1"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_MAX_INT = 9_007_199_254_740_991
_MAX_REF = 8_388_608
_KINDS = {"command-observation": COMMAND_V1, "composite-applicability": COMPOSITE_V1, "async-observation": ASYNC_V1}
_STATUS = {"PASS", "FAIL", "SKIPPED"}


def _schema(schema_id: str, required: list[str], properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "type": "object",
        "required": required,
        "additionalProperties": False,
        "properties": properties,
    }


_ID_SCHEMA = {"type": "string", "minLength": 1, "maxLength": 128}
_HEX_SCHEMA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_REF_SCHEMA = _schema(
    "agent-release-artifact-ref.v1",
    ["path", "sha256", "bytes"],
    {
        "path": {"type": "string", "minLength": 1, "maxLength": 1024},
        "sha256": _HEX_SCHEMA,
        "bytes": {"type": "integer", "minimum": 0, "maximum": _MAX_REF},
    },
)
_PATH_SCHEMA = {"type": "string", "minLength": 1, "maxLength": 1024}
_UINT_SCHEMA = {"type": "integer", "minimum": 0, "maximum": _MAX_INT}
_EXPECTED_COMPONENT_SCHEMA = _schema(
    "agent-expected-evidence-component.v1",
    [
        "id",
        "repositoryPath",
        "configurationPaths",
        "oraclePaths",
        "buildArtifactPath",
    ],
    {
        "id": _ID_SCHEMA,
        "repositoryPath": _PATH_SCHEMA,
        "configurationPaths": {"type": "array", "maxItems": 64, "uniqueItems": True, "items": _PATH_SCHEMA},
        "oraclePaths": {"type": "array", "maxItems": 64, "uniqueItems": True, "items": _PATH_SCHEMA},
        "buildArtifactPath": {"anyOf": [_PATH_SCHEMA, {"type": "null"}]},
    },
)
_SUBJECT_COMPONENT_SCHEMA = _schema(
    "agent-evidence-subject-component.v1",
    [
        "id",
        "commitOid",
        "contentDigest",
        "buildDigest",
        "configurationDigest",
        "oracleDigest",
    ],
    {
        "id": _ID_SCHEMA,
        "commitOid": {"anyOf": [{"type": "string", "pattern": "^(?:[0-9a-f]{40}|[0-9a-f]{64})$"}, {"type": "null"}]},
        **{key: _HEX_SCHEMA for key in ("contentDigest", "buildDigest", "configurationDigest", "oracleDigest")},
    },
)
_TASK_BINDING_SCHEMA = _schema(
    "agent-evidence-task-binding.v1",
    ["taskId", "attempt", "resultDigest", "snapshotHash"],
    {
        "taskId": _ID_SCHEMA,
        "attempt": {"type": "integer", "minimum": 1, "maximum": _MAX_INT},
        "resultDigest": _HEX_SCHEMA,
        "snapshotHash": _HEX_SCHEMA,
    },
)
_SUBJECT_SCHEMA = _schema(
    "agent-evidence-subject.v1",
    [
        "packageId",
        "runId",
        "planRevision",
        "planDigest",
        "sourceRevision",
        "scope",
        "taskBindings",
        "components",
    ],
    {
        "packageId": _ID_SCHEMA,
        "runId": _ID_SCHEMA,
        "planRevision": {"type": "integer", "minimum": 1, "maximum": _MAX_INT},
        "planDigest": _HEX_SCHEMA,
        "sourceRevision": _ID_SCHEMA,
        "scope": {"enum": ["TASK", "FINAL"]},
        "taskBindings": {"type": "array", "minItems": 1, "maxItems": 1024, "items": _TASK_BINDING_SCHEMA},
        "components": {"type": "array", "minItems": 1, "maxItems": 64, "items": _SUBJECT_COMPONENT_SCHEMA},
    },
)
_PRODUCER_SCHEMA = _schema(
    "agent-evidence-producer.v1",
    ["actorId", "sessionId", "guarantee", "attestation"],
    {
        "actorId": _ID_SCHEMA,
        "sessionId": _ID_SCHEMA,
        "guarantee": {"enum": ["DECLARED", "ATTESTED"]},
        "attestation": {"anyOf": [_REF_SCHEMA, {"type": "null"}]},
    },
)
_CASE_SCHEMA = _schema(
    "agent-command-case.v1",
    ["id", "status", "evidence"],
    {
        "id": _ID_SCHEMA,
        "status": {"enum": sorted(_STATUS)},
        "evidence": {"anyOf": [_REF_SCHEMA, {"type": "null"}]},
    },
)
_COMMAND_SCHEMA = _schema(
    "agent-command-entry.v1",
    ["commandDigest", "status", "exitCode", "stdout", "stderr", "cases"],
    {
        "commandDigest": _HEX_SCHEMA,
        "status": {"enum": sorted(_STATUS)},
        "exitCode": {
            "anyOf": [{"type": "integer", "minimum": -2_147_483_648, "maximum": 4_294_967_295}, {"type": "null"}]
        },
        "stdout": _REF_SCHEMA,
        "stderr": _REF_SCHEMA,
        "cases": {"type": "array", "maxItems": 1024, "items": _CASE_SCHEMA},
    },
)
_BOUNDARY_SCHEMA = {
    "oneOf": [
        _schema(
            "agent-async-duration-boundary.v1", ["kind", "atMs"], {"kind": {"const": "duration"}, "atMs": _UINT_SCHEMA}
        ),
        _schema(
            "agent-async-event-boundary.v1",
            ["kind", "eventId", "atMs"],
            {
                "kind": {"const": "event"},
                "eventId": _ID_SCHEMA,
                "atMs": _UINT_SCHEMA,
            },
        ),
    ]
}
EVIDENCE_RECEIPT_SCHEMAS = {
    EXPECTED_V1: _schema(
        EXPECTED_V1,
        ["schemaVersion", "kind", "scope", "components", "producerRequirement", "requirements"],
        {
            "schemaVersion": {"const": EXPECTED_V1},
            "kind": {"enum": sorted(_KINDS)},
            "scope": {"enum": ["TASK", "FINAL"]},
            "components": {"type": "array", "minItems": 1, "maxItems": 64, "items": _EXPECTED_COMPONENT_SCHEMA},
            "producerRequirement": {"enum": ["DECLARED", "ATTESTED"]},
            "requirements": {
                "oneOf": [
                    _schema(
                        "agent-evidence-command-requirements.v1",
                        ["commandDigests", "caseIds"],
                        {
                            "commandDigests": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 64,
                                "uniqueItems": True,
                                "items": _HEX_SCHEMA,
                            },
                            "caseIds": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 1024,
                                "uniqueItems": True,
                                "items": _ID_SCHEMA,
                            },
                        },
                    ),
                    _schema(
                        "agent-evidence-composite-requirements.v1",
                        ["allowHistoryOnlyChange"],
                        {
                            "allowHistoryOnlyChange": {"const": True},
                        },
                    ),
                    _schema(
                        "agent-evidence-async-requirements.v1",
                        ["surfaceId", "readinessId", "boundary"],
                        {
                            "surfaceId": _ID_SCHEMA,
                            "readinessId": _ID_SCHEMA,
                            "boundary": {
                                "oneOf": [
                                    _schema(
                                        "agent-evidence-duration-requirement.v1",
                                        ["kind", "minimumMilliseconds"],
                                        {
                                            "kind": {"const": "duration"},
                                            "minimumMilliseconds": {
                                                "type": "integer",
                                                "minimum": 1,
                                                "maximum": _MAX_INT,
                                            },
                                        },
                                    ),
                                    _schema(
                                        "agent-evidence-event-requirement.v1",
                                        ["kind", "eventId"],
                                        {
                                            "kind": {"const": "event"},
                                            "eventId": _ID_SCHEMA,
                                        },
                                    ),
                                ]
                            },
                        },
                    ),
                ]
            },
        },
    ),
    RECEIPT_V1: _schema(
        RECEIPT_V1,
        ["schemaVersion", "evidenceId", "subject", "producer", "payload", "payloadDigest", "receiptDigest"],
        {
            "schemaVersion": {"const": RECEIPT_V1},
            "evidenceId": _ID_SCHEMA,
            "subject": _SUBJECT_SCHEMA,
            "producer": _PRODUCER_SCHEMA,
            "payload": {"type": "object"},
            "payloadDigest": _HEX_SCHEMA,
            "receiptDigest": _HEX_SCHEMA,
        },
    ),
    COMMAND_V1: _schema(
        COMMAND_V1,
        ["schemaVersion", "platform", "commands"],
        {
            "schemaVersion": {"const": COMMAND_V1},
            "platform": _schema(
                "agent-command-platform.v1",
                ["os", "architecture", "pythonVersion"],
                {
                    "os": {"enum": ["linux", "macos", "windows"]},
                    "architecture": _ID_SCHEMA,
                    "pythonVersion": _ID_SCHEMA,
                },
            ),
            "commands": {"type": "array", "minItems": 1, "maxItems": 64, "items": _COMMAND_SCHEMA},
        },
    ),
    COMPOSITE_V1: _schema(
        COMPOSITE_V1,
        ["schemaVersion", "previousReceipt", "previousSubjectDigest", "currentSubjectDigest", "componentIds"],
        {
            "schemaVersion": {"const": COMPOSITE_V1},
            "previousReceipt": _REF_SCHEMA,
            "previousSubjectDigest": _HEX_SCHEMA,
            "currentSubjectDigest": _HEX_SCHEMA,
            "componentIds": {"type": "array", "minItems": 1, "maxItems": 64, "items": _ID_SCHEMA},
        },
    ),
    ASYNC_V1: _schema(
        ASYNC_V1,
        [
            "schemaVersion",
            "surfaceId",
            "readinessId",
            "clockId",
            "readyAtMs",
            "coverageStartMs",
            "coverageEndMs",
            "boundary",
            "violationCount",
            "observationArtifact",
        ],
        {
            "schemaVersion": {"const": ASYNC_V1},
            **{key: _ID_SCHEMA for key in ("surfaceId", "readinessId", "clockId")},
            **{key: _UINT_SCHEMA for key in ("readyAtMs", "coverageStartMs", "coverageEndMs", "violationCount")},
            "boundary": _BOUNDARY_SCHEMA,
            "observationArtifact": _REF_SCHEMA,
        },
    ),
}
_REQUIREMENT_VARIANTS = EVIDENCE_RECEIPT_SCHEMAS[EXPECTED_V1]["properties"]["requirements"]["oneOf"]
EVIDENCE_RECEIPT_SCHEMAS[EXPECTED_V2] = _schema(
    EXPECTED_V2,
    [
        "schemaVersion",
        "kind",
        "scope",
        "components",
        "producerRequirement",
        "requirements",
        "originValidation",
    ],
    {
        **EVIDENCE_RECEIPT_SCHEMAS[EXPECTED_V1]["properties"],
        "schemaVersion": {"const": EXPECTED_V2},
        "kind": {"const": "composite-applicability"},
        "requirements": _REQUIREMENT_VARIANTS[1],
        "originValidation": {
            "allOf": [
                EVIDENCE_RECEIPT_SCHEMAS[EXPECTED_V1],
                {
                    "properties": {"kind": {"enum": ["command-observation", "async-observation"]}},
                },
            ]
        },
    },
)
EVIDENCE_RECEIPT_SCHEMAS[EXPECTED_V1]["allOf"] = [
    {
        "if": {"properties": {"kind": {"const": kind}}},
        "then": {"properties": {"requirements": _REQUIREMENT_VARIANTS[index]}},
    }
    for index, kind in enumerate(("command-observation", "composite-applicability", "async-observation"))
]
_PRODUCER_SCHEMA["allOf"] = [
    {
        "if": {"properties": {"guarantee": {"const": "DECLARED"}}},
        "then": {"properties": {"attestation": {"type": "null"}}},
    },
    {"if": {"properties": {"guarantee": {"const": "ATTESTED"}}}, "then": {"properties": {"attestation": _REF_SCHEMA}}},
]
_COMMAND_SCHEMA["allOf"] = [
    {"if": {"properties": {"status": {"const": "PASS"}}}, "then": {"properties": {"exitCode": {"const": 0}}}}
]
_SUBJECT_SCHEMA["allOf"] = [
    {"if": {"properties": {"scope": {"const": "TASK"}}}, "then": {"properties": {"taskBindings": {"maxItems": 1}}}}
]


def _invalid(field: str) -> NoReturn:
    raise LifecycleError("evidence-receipt-invalid", f"Invalid {field}")


def _object(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        _invalid(label)
    return value


def _id(value: Any, label: str) -> str:
    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= 128:
        _invalid(label)
    return value


def _hex(value: Any, label: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        _invalid(label)
    return value


def _int(value: Any, label: str, *, minimum: int = 0, maximum: int = _MAX_INT) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid(label)
    return value


def _path(value: Any, label: str, *, root: bool = False) -> str:
    if root and value == ".":
        return value
    if type(value) is not str or not value or len(value.encode("utf-8")) > 1024:
        _invalid(label)
    try:
        return normalize_repo_path(value, label=label)
    except LifecycleError:
        _invalid(label)


def _tree(value: Any, depth: int = 0) -> None:
    if depth > 16:
        _invalid("object depth")
    if type(value) is dict:
        if len(value) > 1024:
            _invalid("object member count")
        for key, item in value.items():
            if type(key) is not str or len(key.encode("utf-8")) > 8192:
                _invalid("object key")
            _tree(item, depth + 1)
    elif type(value) is list:
        if len(value) > 1024:
            _invalid("list item count")
        for item in value:
            _tree(item, depth + 1)
    elif type(value) is str and len(value.encode("utf-8")) > 8192:
        _invalid("string byte count")
    elif type(value) not in {str, int, bool, type(None)}:
        _invalid("JSON value type")


def validate_artifact_ref(value: Any) -> dict[str, Any]:
    item = _object(value, {"path", "sha256", "bytes"}, "artifact ref")
    _path(item["path"], "artifact path")
    _hex(item["sha256"], "artifact digest")
    _int(item["bytes"], "artifact bytes", maximum=_MAX_REF)
    return item


def _id_list(value: Any, label: str, *, maximum: int = 1024, sorted_required: bool = False) -> list[str]:
    if type(value) is not list or not 1 <= len(value) <= maximum:
        _invalid(label)
    items = [_id(item, label) for item in value]
    if len(set(items)) != len(items) or (sorted_required and items != sorted(items)):
        _invalid(label)
    return items


def validate_expected_evidence(value: Any) -> dict[str, Any]:
    fields = {"schemaVersion", "kind", "scope", "components", "producerRequirement", "requirements"}
    if type(value) is dict and value.get("schemaVersion") == EXPECTED_V2:
        record = _object(value, fields | {"originValidation"}, "expected V2 evidence")
        _tree(record)
        if len(canonical_bytes(record)) > 65_536 or record["kind"] != "composite-applicability":
            _invalid("expected V2 bytes or kind")
        requirement = _object(record["requirements"], {"allowHistoryOnlyChange"}, "V2 composite requirements")
        if requirement["allowHistoryOnlyChange"] is not True:
            _invalid("V2 history permission")
        common = {key: item for key, item in record.items() if key != "originValidation"}
        common["schemaVersion"] = EXPECTED_V1
        validate_expected_evidence(common)
        origin = _object(record["originValidation"], fields, "V1 origin")
        if (
            origin["schemaVersion"] != EXPECTED_V1
            or type(origin["kind"]) is not str
            or origin["kind"] not in {"command-observation", "async-observation"}
        ):
            _invalid("noncomposite V1 origin")
        validate_expected_evidence(origin)
        if any(record[key] != origin[key] for key in ("scope", "components", "producerRequirement")):
            _invalid("independently expected origin bindings")
        return record
    record = _object(value, fields, "expected evidence")
    _tree(record)
    if record["schemaVersion"] != EXPECTED_V1 or type(record["kind"]) is not str or record["kind"] not in _KINDS:
        _invalid("expected evidence version or kind")
    if (
        type(record["scope"]) is not str
        or record["scope"] not in {"TASK", "FINAL"}
        or (
            type(record["producerRequirement"]) is not str
            or record["producerRequirement"] not in {"DECLARED", "ATTESTED"}
        )
    ):
        _invalid("expected scope or producer requirement")
    components = record["components"]
    if type(components) is not list or not 1 <= len(components) <= 64:
        _invalid("expected components")
    ids: set[str] = set()
    for component in components:
        item = _object(
            component,
            {"id", "repositoryPath", "configurationPaths", "oraclePaths", "buildArtifactPath"},
            "expected component",
        )
        component_id = _id(item["id"], "component id")
        if component_id in ids:
            _invalid("duplicate component")
        ids.add(component_id)
        _path(item["repositoryPath"], "component root", root=True)
        for name in ("configurationPaths", "oraclePaths"):
            paths = item[name]
            if type(paths) is not list or len(paths) > 64:
                _invalid(name)
            for path in paths:
                _path(path, name)
            if len(set(paths)) != len(paths) or paths != sorted(paths):
                _invalid(name)
        if item["buildArtifactPath"] is not None:
            _path(item["buildArtifactPath"], "build artifact")
    req = record["requirements"]
    kind = record["kind"]
    if kind == "command-observation":
        _object(req, {"commandDigests", "caseIds"}, "command requirements")
        digests = req["commandDigests"]
        if type(digests) is not list or not 1 <= len(digests) <= 64:
            _invalid("command digests")
        for item in digests:
            _hex(item, "command digest")
        if len(set(digests)) != len(digests):
            _invalid("command digests")
        _id_list(req["caseIds"], "required cases")
    elif kind == "composite-applicability":
        if req != {"allowHistoryOnlyChange": True}:
            _invalid("composite requirements")
    else:
        _object(req, {"surfaceId", "readinessId", "boundary"}, "async requirements")
        _id(req["surfaceId"], "surface id")
        _id(req["readinessId"], "readiness id")
        boundary = req["boundary"]
        if type(boundary) is not dict:
            _invalid("async boundary")
        if boundary.get("kind") == "duration":
            _object(boundary, {"kind", "minimumMilliseconds"}, "duration boundary")
            _int(boundary["minimumMilliseconds"], "minimum duration", minimum=1)
        elif boundary.get("kind") == "event":
            _object(boundary, {"kind", "eventId"}, "event boundary")
            _id(boundary["eventId"], "event id")
        else:
            _invalid("async boundary kind")
    if len(canonical_bytes(record)) > 65_536:
        _invalid("expected evidence bytes")
    return record


def _subject(value: Any) -> dict[str, Any]:
    fields = {
        "packageId",
        "runId",
        "planRevision",
        "planDigest",
        "sourceRevision",
        "scope",
        "taskBindings",
        "components",
    }
    subject = _object(value, fields, "evidence subject")
    for name in ("packageId", "runId", "sourceRevision"):
        _id(subject[name], name)
    _int(subject["planRevision"], "planRevision", minimum=1)
    _hex(subject["planDigest"], "planDigest")
    if type(subject["scope"]) is not str or subject["scope"] not in {"TASK", "FINAL"}:
        _invalid("subject scope")
    bindings = subject["taskBindings"]
    if type(bindings) is not list or not bindings or len(bindings) > 1024:
        _invalid("task bindings")
    ids = []
    for binding in bindings:
        item = _object(binding, {"taskId", "attempt", "resultDigest", "snapshotHash"}, "task binding")
        ids.append(_id(item["taskId"], "task id"))
        _int(item["attempt"], "attempt", minimum=1)
        _hex(item["resultDigest"], "result digest")
        _hex(item["snapshotHash"], "snapshot hash")
    if ids != sorted(set(ids)) or (subject["scope"] == "TASK" and len(ids) != 1):
        _invalid("task binding order or scope")
    components = subject["components"]
    if type(components) is not list or not 1 <= len(components) <= 64:
        _invalid("subject components")
    component_ids = []
    for component in components:
        item = _object(
            component,
            {"id", "commitOid", "contentDigest", "buildDigest", "configurationDigest", "oracleDigest"},
            "subject component",
        )
        component_ids.append(_id(item["id"], "component id"))
        if item["commitOid"] is not None and (
            type(item["commitOid"]) is not str or _COMMIT.fullmatch(item["commitOid"]) is None
        ):
            _invalid("component commit")
        for name in ("contentDigest", "buildDigest", "configurationDigest", "oracleDigest"):
            _hex(item[name], name)
    if component_ids != sorted(set(component_ids)):
        _invalid("subject component order")
    return subject


def _command_payload(payload: dict[str, Any]) -> None:
    _object(payload, {"schemaVersion", "platform", "commands"}, "command payload")
    platform = _object(payload["platform"], {"os", "architecture", "pythonVersion"}, "platform")
    if type(platform["os"]) is not str or platform["os"] not in {"linux", "macos", "windows"}:
        _invalid("platform os")
    for name in ("architecture", "pythonVersion"):
        _id(platform[name], name)
    commands = payload["commands"]
    if type(commands) is not list or not 1 <= len(commands) <= 64:
        _invalid("commands")
    seen: set[str] = set()
    total_cases = 0
    for command in commands:
        item = _object(command, {"commandDigest", "status", "exitCode", "stdout", "stderr", "cases"}, "command")
        digest = _hex(item["commandDigest"], "command digest")
        if digest in seen or type(item["status"]) is not str or item["status"] not in _STATUS:
            _invalid("duplicate command or status")
        seen.add(digest)
        if item["exitCode"] is not None:
            _int(item["exitCode"], "exit code", minimum=-2_147_483_648, maximum=4_294_967_295)
        if item["status"] == "PASS" and item["exitCode"] != 0:
            _invalid("PASS exit code")
        validate_artifact_ref(item["stdout"])
        validate_artifact_ref(item["stderr"])
        cases = item["cases"]
        if type(cases) is not list or len(cases) > 1024:
            _invalid("cases")
        total_cases += len(cases)
        if total_cases > 1024:
            _invalid("receipt case count")
        case_ids: set[str] = set()
        for case in cases:
            observation = _object(case, {"id", "status", "evidence"}, "case")
            case_id = _id(observation["id"], "case id")
            if case_id in case_ids or type(observation["status"]) is not str or observation["status"] not in _STATUS:
                _invalid("duplicate case or status")
            case_ids.add(case_id)
            if observation["evidence"] is not None:
                validate_artifact_ref(observation["evidence"])


def _async_payload(payload: dict[str, Any]) -> None:
    fields = {
        "schemaVersion",
        "surfaceId",
        "readinessId",
        "clockId",
        "readyAtMs",
        "coverageStartMs",
        "coverageEndMs",
        "boundary",
        "violationCount",
        "observationArtifact",
    }
    _object(payload, fields, "async payload")
    for name in ("surfaceId", "readinessId", "clockId"):
        _id(payload[name], name)
    for name in ("readyAtMs", "coverageStartMs", "coverageEndMs", "violationCount"):
        _int(payload[name], name)
    boundary = payload["boundary"]
    if (
        type(boundary) is not dict
        or type(boundary.get("kind")) is not str
        or boundary["kind"] not in {"duration", "event"}
    ):
        _invalid("async boundary")
    fields = {"kind", "atMs"} if boundary["kind"] == "duration" else {"kind", "eventId", "atMs"}
    _object(boundary, fields, "async boundary")
    _int(boundary["atMs"], "boundary atMs")
    if boundary["kind"] == "event":
        _id(boundary["eventId"], "event id")
    validate_artifact_ref(payload["observationArtifact"])
    if not payload["coverageStartMs"] <= payload["readyAtMs"] <= boundary["atMs"] <= payload["coverageEndMs"]:
        _invalid("async coverage interval")


def validate_evidence_receipt_shape(value: Any) -> dict[str, Any]:
    fields = {"schemaVersion", "evidenceId", "subject", "producer", "payload", "payloadDigest", "receiptDigest"}
    receipt = _object(value, fields, "evidence receipt")
    _tree(receipt)
    if len(canonical_bytes(receipt)) > 262_144 or receipt["schemaVersion"] != RECEIPT_V1:
        _invalid("receipt bytes or version")
    _id(receipt["evidenceId"], "evidence id")
    _subject(receipt["subject"])
    producer = _object(receipt["producer"], {"actorId", "sessionId", "guarantee", "attestation"}, "producer")
    _id(producer["actorId"], "producer actor")
    _id(producer["sessionId"], "producer session")
    if type(producer["guarantee"]) is not str or producer["guarantee"] not in {"DECLARED", "ATTESTED"}:
        _invalid("producer guarantee")
    if producer["guarantee"] == "DECLARED":
        if producer["attestation"] is not None:
            _invalid("DECLARED attestation")
    else:
        validate_artifact_ref(producer["attestation"])
    payload = receipt["payload"]
    if type(payload) is not dict or len(canonical_bytes(payload)) > 131_072:
        _invalid("payload bytes")
    version = payload.get("schemaVersion")
    if version == COMMAND_V1:
        _command_payload(payload)
    elif version == COMPOSITE_V1:
        _object(
            payload,
            {"schemaVersion", "previousReceipt", "previousSubjectDigest", "currentSubjectDigest", "componentIds"},
            "composite payload",
        )
        validate_artifact_ref(payload["previousReceipt"])
        _hex(payload["previousSubjectDigest"], "previous subject")
        _hex(payload["currentSubjectDigest"], "current subject")
        _id_list(payload["componentIds"], "component ids", maximum=64, sorted_required=True)
    elif version == ASYNC_V1:
        _async_payload(payload)
    else:
        _invalid("payload version")
    _hex(receipt["payloadDigest"], "payload digest")
    _hex(receipt["receiptDigest"], "receipt digest")
    if receipt["payloadDigest"] != canonical_digest(payload):
        _invalid("payload digest binding")
    if receipt["receiptDigest"] != canonical_digest(
        {key: item for key, item in receipt.items() if key != "receiptDigest"}
    ):
        _invalid("receipt digest binding")
    return receipt


def load_evidence_receipt_bytes(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or len(raw) > 262_144:
        _invalid("receipt raw bytes")
    return validate_evidence_receipt_shape(load_json_object(raw, label="evidence receipt"))


def classify_evidence_candidate(
    receipt: Any, *, descriptor: Any, evidence_id: str, expected_subject: Any
) -> dict[str, Any]:
    """Check frozen expectations; referenced bytes and current source remain unverified."""
    expected = validate_expected_evidence(descriptor)
    value = validate_evidence_receipt_shape(receipt)
    _id(evidence_id, "expected evidence id")
    subject = _subject(expected_subject)
    if (
        value["evidenceId"] != evidence_id
        or value["subject"] != subject
        or value["subject"]["scope"] != expected["scope"]
    ):
        _invalid("independently expected evidence subject")
    if value["payload"]["schemaVersion"] != _KINDS[expected["kind"]]:
        _invalid("expected payload kind")
    if [item["id"] for item in subject["components"]] != sorted(item["id"] for item in expected["components"]):
        _invalid("expected components")
    if expected["producerRequirement"] == "ATTESTED" or value["producer"]["guarantee"] == "ATTESTED":
        return {"status": "UNSUPPORTED", "reason": "producer-attestation-unqualified", "acceptanceAuthority": False}
    payload = value["payload"]
    if expected["kind"] == "command-observation":
        requirements = expected["requirements"]
        commands = payload["commands"]
        if set(item["commandDigest"] for item in commands) != set(requirements["commandDigests"]):
            _invalid("expected command set")
        cases = [case for command in commands for case in command["cases"]]
        if set(case["id"] for case in cases) != set(requirements["caseIds"]) or len(cases) != len(
            requirements["caseIds"]
        ):
            _invalid("expected case set")
        if any(item["status"] != "PASS" or item["exitCode"] != 0 for item in commands):
            _invalid("required command outcome")
        if any(item["status"] != "PASS" or item["evidence"] is None for item in cases):
            _invalid("required case outcome")
    elif expected["kind"] == "composite-applicability":
        if expected["schemaVersion"] != EXPECTED_V2:
            return {"status": "UNSUPPORTED", "reason": "predecessor-expectations-unbound", "acceptanceAuthority": False}
        if payload["currentSubjectDigest"] != canonical_digest(subject):
            _invalid("current composite subject")
        if payload["componentIds"] != [item["id"] for item in subject["components"]]:
            _invalid("composite component set")
    else:
        requirements = expected["requirements"]
        if payload["surfaceId"] != requirements["surfaceId"] or payload["readinessId"] != requirements["readinessId"]:
            _invalid("expected async surface or readiness")
        boundary = payload["boundary"]
        wanted = requirements["boundary"]
        if boundary["kind"] != wanted["kind"] or payload["violationCount"] != 0:
            _invalid("async boundary or observed violation")
        if boundary["kind"] == "duration" and boundary["atMs"] - payload["readyAtMs"] < wanted["minimumMilliseconds"]:
            _invalid("async minimum duration")
        if boundary["kind"] == "event" and boundary["eventId"] != wanted["eventId"]:
            _invalid("async expected event")
    return {
        "status": "DATA_CANDIDATE",
        "reason": "references-and-current-source-unverified",
        "acceptanceAuthority": False,
    }


__all__ = [
    "EVIDENCE_RECEIPT_SCHEMAS",
    "classify_evidence_candidate",
    "load_evidence_receipt_bytes",
    "validate_artifact_ref",
    "validate_evidence_receipt_shape",
    "validate_expected_evidence",
]

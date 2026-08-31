from __future__ import annotations

import unittest
from unittest.mock import patch

from agent_lifecycle.compiler.phase_packets import (
    FORBIDDEN_PAYLOAD_KEYS,
    build_phase_packet,
    validate_phase_packet,
)
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.redaction import redact_text

_DIGEST = "a" * 64


def _criterion() -> dict[str, object]:
    return {"id": "AC-1", "requirementIds": ["R-1"], "evidenceIds": ["EV-1"]}


def _evidence() -> dict[str, object]:
    return {"id": "EV-1", "description": "focused evidence", "required": True}


def _implementation_payload() -> dict[str, object]:
    return {
        "schemaVersion": "agent-phase-implementation-payload.v1",
        "taskId": "WS-1",
        "attempt": 1,
        "taskPacketDigest": _DIGEST,
        "writes": ["src/b.py", "src/a.py", "src/a.py"],
        "readOnly": ["docs"],
        "forbiddenWrites": [".git"],
        "acceptanceCriteria": [_criterion()],
        "evidenceRequirements": [_evidence()],
        "activeBlockerIds": [],
    }


def _planning_payload() -> dict[str, object]:
    return {
        "schemaVersion": "agent-phase-planning-handoff-payload.v1",
        "workstreams": [
            {
                "id": "WS-1",
                "dependsOn": [],
                "writes": ["src/a.py"],
                "readOnly": ["docs"],
                "forbiddenWrites": [".git"],
                "acceptanceCriteria": [_criterion()],
                "evidenceRequirements": [_evidence()],
                "activeBlockerIds": [],
            }
        ],
        "dependencyEdges": [{"from": "WS-0", "to": "WS-1"}],
    }


def _audit_payload() -> dict[str, object]:
    return {
        "schemaVersion": "agent-phase-task-audit-payload.v1",
        "taskId": "WS-1",
        "attempt": 1,
        "resultDigest": _DIGEST,
        "changeSetDigest": "b" * 64,
        "changedPaths": ["src/a.py"],
        "writes": ["src/a.py"],
        "readOnly": ["docs"],
        "forbiddenWrites": [".git"],
        "reviewRequirements": {
            "independentRequired": True,
            "minimumVerdict": "ACCEPTED",
            "requiredReviewerIds": ["reviewer-1"],
        },
        "acceptanceCriteria": [_criterion()],
        "evidenceReferences": ["work/evidence.json"],
        "activeBlockerIds": [],
    }


def _remediation_payload() -> dict[str, object]:
    return {
        "schemaVersion": "agent-phase-remediation-payload.v1",
        "taskId": "WS-1",
        "attempt": 2,
        "priorResultDigest": _DIGEST,
        "priorReviewDigest": "b" * 64,
        "changedPaths": ["src/a.py"],
        "openFindingIds": ["F-1"],
        "remainingAttempts": 1,
        "writes": ["src/a.py"],
        "readOnly": ["docs"],
        "forbiddenWrites": [".git"],
        "acceptanceCriteria": [_criterion()],
        "evidenceRequirements": [_evidence()],
        "activeBlockerIds": [],
    }


def _build(purpose: str, payload: dict[str, object], *, limit: int = 65536) -> dict[str, object]:
    return build_phase_packet(
        purpose=purpose,
        payload=payload,
        plan_digest=_DIGEST,
        plan_lock_digest="b" * 64,
        state_revision=None if purpose == "PLANNING_HANDOFF" else 2,
        source_revision="deadbeef",
        write_scope_digest="c" * 64,
        acceptance_digest="d" * 64,
        evidence_digest="e" * 64,
        active_blocker_ids=list(payload.get("activeBlockerIds", [])),
        max_context_bytes=limit,
    )


class PhasePacketTests(unittest.TestCase):
    def test_builds_and_validates_each_purpose(self) -> None:
        for purpose, payload in (
            ("PLANNING_HANDOFF", _planning_payload()),
            ("IMPLEMENTATION", _implementation_payload()),
            ("TASK_AUDIT", _audit_payload()),
            ("REMEDIATION", _remediation_payload()),
        ):
            with self.subTest(purpose=purpose):
                packet = _build(purpose, payload)
                self.assertEqual(validate_phase_packet(packet), packet)
                body = {key: value for key, value in packet.items() if key != "packetDigest"}
                self.assertEqual(packet["packetDigest"], canonical_digest(body))

    def test_normalizes_string_lists_and_redacts_values(self) -> None:
        payload = _implementation_payload()
        local_path = "/" + "Users/private/source.py"
        payload["acceptanceCriteria"] = [{"id": "AC-1", "description": f"error at {local_path}"}]

        packet = _build("IMPLEMENTATION", payload)

        self.assertEqual(packet["payload"]["writes"], ["src/a.py", "src/b.py"])
        self.assertEqual(
            packet["payload"]["acceptanceCriteria"][0]["description"],
            "error at <redacted>",
        )

    def test_rejects_every_forbidden_key_at_any_depth(self) -> None:
        self.assertEqual(len(FORBIDDEN_PAYLOAD_KEYS), 29)
        for key in sorted(FORBIDDEN_PAYLOAD_KEYS):
            for location in ("root", "nested", "deeply-nested"):
                payload = _implementation_payload()
                if location == "root":
                    payload[key] = "x"
                elif location == "nested":
                    payload["acceptanceCriteria"] = [{"id": "AC-1", "source": {key: "x"}}]
                else:
                    payload["acceptanceCriteria"] = [{"id": "AC-1", "source": {"nested": {key: "x"}}}]
                with self.subTest(key=key, location=location), self.assertRaises(LifecycleError) as raised:
                    _build("IMPLEMENTATION", payload)
                self.assertEqual(raised.exception.code, "phase-packet-forbidden-content")

    def test_rejects_every_required_payload_fact(self) -> None:
        fixtures = {
            "PLANNING_HANDOFF": _planning_payload,
            "IMPLEMENTATION": _implementation_payload,
            "TASK_AUDIT": _audit_payload,
            "REMEDIATION": _remediation_payload,
        }
        for purpose, factory in fixtures.items():
            reference = factory()
            for field in tuple(reference):
                payload = factory()
                payload.pop(field)
                with self.subTest(purpose=purpose, field=field), self.assertRaises(LifecycleError) as raised:
                    _build(purpose, payload)
                self.assertEqual(raised.exception.code, "phase-packet-required-fact-missing")

        for field in tuple(_planning_payload()["workstreams"][0]):
            payload = _planning_payload()
            payload["workstreams"][0].pop(field)
            with self.subTest(record="workstream", field=field), self.assertRaises(LifecycleError) as raised:
                _build("PLANNING_HANDOFF", payload)
            self.assertEqual(raised.exception.code, "phase-packet-required-fact-missing")

        for field in ("from", "to"):
            payload = _planning_payload()
            payload["dependencyEdges"][0].pop(field)
            with self.subTest(record="dependencyEdge", field=field), self.assertRaises(LifecycleError) as raised:
                _build("PLANNING_HANDOFF", payload)
            self.assertEqual(raised.exception.code, "phase-packet-required-fact-missing")

        for purpose, factory in fixtures.items():
            payload = factory()
            criteria = (
                payload["workstreams"][0]["acceptanceCriteria"]
                if purpose == "PLANNING_HANDOFF"
                else payload["acceptanceCriteria"]
            )
            criteria[0].pop("id")
            with self.subTest(purpose=purpose, record="criterion"), self.assertRaises(LifecycleError) as raised:
                _build(purpose, payload)
            self.assertEqual(raised.exception.code, "phase-packet-required-fact-missing")

        for purpose, factory in fixtures.items():
            if purpose == "TASK_AUDIT":
                continue
            payload = factory()
            evidence = (
                payload["workstreams"][0]["evidenceRequirements"]
                if purpose == "PLANNING_HANDOFF"
                else payload["evidenceRequirements"]
            )
            evidence[0].pop("id")
            with self.subTest(purpose=purpose, record="evidence"), self.assertRaises(LifecycleError) as raised:
                _build(purpose, payload)
            self.assertEqual(raised.exception.code, "phase-packet-required-fact-missing")

        for field in tuple(_audit_payload()["reviewRequirements"]):
            payload = _audit_payload()
            payload["reviewRequirements"].pop(field)
            with self.subTest(record="review", field=field), self.assertRaises(LifecycleError) as raised:
                _build("TASK_AUDIT", payload)
            self.assertEqual(raised.exception.code, "phase-packet-required-fact-missing")

    def test_rejects_missing_extra_and_wrong_authority(self) -> None:
        missing = _implementation_payload()
        missing.pop("taskId")
        with self.assertRaises(LifecycleError) as raised:
            _build("IMPLEMENTATION", missing)
        self.assertEqual(raised.exception.code, "phase-packet-required-fact-missing")

        for field, invalid in (
            ("implementationAuthorized", True),
            ("proofAuthority", "claimed"),
            ("productionPromotionClaimed", True),
        ):
            packet = _build("IMPLEMENTATION", _implementation_payload())
            packet[field] = invalid
            body = {key: value for key, value in packet.items() if key != "packetDigest"}
            packet["packetDigest"] = canonical_digest(body)
            with self.subTest(field=field), self.assertRaises(LifecycleError) as raised:
                validate_phase_packet(packet)
            self.assertEqual(raised.exception.code, "phase-packet-forbidden-content")

    def test_retains_complete_nested_records(self) -> None:
        payload = _audit_payload()
        payload["acceptanceCriteria"] = [
            {
                "id": "AC-1",
                "requirementIds": ["R-2", "R-1"],
                "evidenceIds": ["EV-2", "EV-1"],
                "independentEvidenceIds": ["EV-3"],
                "independence": {"required": True},
                "statement": "acceptance statement",
                "description": "acceptance description",
                "source": {"kind": "manifest"},
                "priority": 1,
            }
        ]
        packet = _build("TASK_AUDIT", payload)

        criterion = packet["payload"]["acceptanceCriteria"][0]
        self.assertEqual(set(criterion), set(payload["acceptanceCriteria"][0]))
        self.assertEqual(criterion["requirementIds"], ["R-1", "R-2"])
        self.assertEqual(criterion["evidenceIds"], ["EV-1", "EV-2"])

    def test_runtime_types_match_the_published_nested_schemas(self) -> None:
        cases = (
            ("acceptanceCriteria", "statement", 1),
            ("acceptanceCriteria", "description", 1),
            ("evidenceRequirements", "description", 1),
            ("evidenceRequirements", "artifactPath", 1),
            ("evidenceRequirements", "required", "yes"),
        )
        for collection, field, invalid in cases:
            payload = _implementation_payload()
            payload[collection] = [{"id": "record-1", field: invalid}]
            with self.subTest(collection=collection, field=field), self.assertRaises(LifecycleError) as raised:
                _build("IMPLEMENTATION", payload)
            self.assertEqual(raised.exception.code, "phase-packet-required-fact-missing")

    def test_bounds_raw_context_before_redaction(self) -> None:
        oversized = _implementation_payload()
        oversized["acceptanceCriteria"] = [{"id": "AC-1", "description": "x" * 70000}]
        with (
            patch(
                "agent_lifecycle.compiler.phase_packets.redact_value",
                side_effect=AssertionError("redaction must not run"),
            ),
            self.assertRaises(LifecycleError) as raised,
        ):
            _build("IMPLEMENTATION", oversized)
        self.assertEqual(raised.exception.code, "phase-packet-context-limit-exceeded")

    def test_phase_strings_preserve_shared_redaction_semantics(self) -> None:
        samples = (
            "deploy --password=hunter2 staged",
            "_secret=abc123",
            "1password=x9y8z7",
            "..token=abc",
            '"password": "hunter2"',
            "Bearer abc.def",
        )
        for sample in samples:
            payload = _implementation_payload()
            payload["acceptanceCriteria"] = [{"id": "AC-1", "description": sample}]
            packet = _build("IMPLEMENTATION", payload)
            expected, _changed = redact_text(sample)
            with self.subTest(sample=sample):
                self.assertEqual(packet["payload"]["acceptanceCriteria"][0]["description"], expected)

    def test_rejects_stored_unredacted_values_and_digest_drift(self) -> None:
        packet = _build("IMPLEMENTATION", _implementation_payload())
        packet["payload"]["acceptanceCriteria"][0]["description"] = "/tmp/private.py"
        body = {key: value for key, value in packet.items() if key != "packetDigest"}
        packet["packetDigest"] = canonical_digest(body)
        with self.assertRaises(LifecycleError) as raised:
            validate_phase_packet(packet)
        self.assertEqual(raised.exception.code, "phase-packet-forbidden-content")

        packet = _build("IMPLEMENTATION", _implementation_payload())
        packet["sourceRevision"] = "changed"
        with self.assertRaises(LifecycleError) as raised:
            validate_phase_packet(packet)
        self.assertEqual(raised.exception.code, "phase-packet-required-fact-missing")

    def test_rejects_context_overflow_without_truncation(self) -> None:
        payload = _implementation_payload()
        payload["acceptanceCriteria"] = [{"id": "AC-1", "description": "x" * 2000}]
        with self.assertRaises(LifecycleError) as raised:
            _build("IMPLEMENTATION", payload, limit=1024)
        self.assertEqual(raised.exception.code, "phase-packet-context-limit-exceeded")

        with self.assertRaises(LifecycleError) as raised:
            _build("IMPLEMENTATION", _implementation_payload(), limit=65537)
        self.assertEqual(raised.exception.code, "phase-packet-context-limit-exceeded")


if __name__ == "__main__":
    unittest.main()

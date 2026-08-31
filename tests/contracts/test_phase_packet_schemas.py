from __future__ import annotations

import unittest

from agent_lifecycle.contracts.phase_packet_schemas import PHASE_PACKET_SCHEMAS


class PhasePacketSchemaTests(unittest.TestCase):
    def test_all_five_schemas_are_closed(self) -> None:
        self.assertEqual(len(PHASE_PACKET_SCHEMAS), 5)
        for schema in PHASE_PACKET_SCHEMAS.values():
            self.assertFalse(schema["additionalProperties"])

    def test_payload_records_are_closed(self) -> None:
        planning = PHASE_PACKET_SCHEMAS["agent-phase-planning-handoff-payload.v1"]
        workstream = planning["properties"]["workstreams"]["items"]
        edge = planning["properties"]["dependencyEdges"]["items"]
        implementation = PHASE_PACKET_SCHEMAS["agent-phase-implementation-payload.v1"]
        task_audit = PHASE_PACKET_SCHEMAS["agent-phase-task-audit-payload.v1"]
        remediation = PHASE_PACKET_SCHEMAS["agent-phase-remediation-payload.v1"]
        review = task_audit["properties"]["reviewRequirements"]

        self.assertFalse(workstream["additionalProperties"])
        self.assertFalse(edge["additionalProperties"])
        self.assertFalse(review["additionalProperties"])
        for payload, field in (
            (planning, "workstreams"),
            (implementation, "acceptanceCriteria"),
            (task_audit, "acceptanceCriteria"),
            (remediation, "acceptanceCriteria"),
        ):
            owner = payload["properties"][field]
            criterion = (
                owner["items"]["properties"]["acceptanceCriteria"]["items"]
                if field == "workstreams"
                else owner["items"]
            )
            self.assertFalse(criterion["additionalProperties"])
        for payload, field in (
            (planning, "workstreams"),
            (implementation, "evidenceRequirements"),
            (remediation, "evidenceRequirements"),
        ):
            owner = payload["properties"][field]
            evidence = (
                owner["items"]["properties"]["evidenceRequirements"]["items"]
                if field == "workstreams"
                else owner["items"]
            )
            self.assertFalse(evidence["additionalProperties"])

    def test_envelope_authority_and_purpose_are_exact(self) -> None:
        schema = PHASE_PACKET_SCHEMAS["agent-phase-packet.v1"]
        properties = schema["properties"]

        self.assertEqual(properties["implementationAuthorized"], {"const": False})
        self.assertEqual(properties["proofAuthority"], {"const": "none"})
        self.assertEqual(properties["productionPromotionClaimed"], {"const": False})
        self.assertEqual(
            properties["purpose"]["enum"],
            ["PLANNING_HANDOFF", "IMPLEMENTATION", "TASK_AUDIT", "REMEDIATION"],
        )


if __name__ == "__main__":
    unittest.main()

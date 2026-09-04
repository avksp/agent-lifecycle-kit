from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema


class ReleaseAccountingSchemaTests(unittest.TestCase):
    def test_release_accounting_schemas_are_registered_and_bounded(self) -> None:
        source = get_schema("agent-release-accounting-source.v1")
        accounting = get_schema("agent-release-accounting.v1")
        validation = get_schema("agent-release-accounting-validation.v1")
        generation = get_schema("agent-release-accounting-generation.v1")

        self.assertEqual(source["properties"]["entries"]["maxItems"], 1024)
        self.assertEqual(accounting["properties"]["sourceArtifacts"]["maxItems"], 64)
        self.assertEqual(source["properties"]["workflowEconomics"], {"type": "object"})
        self.assertEqual(accounting["properties"]["workflowEconomics"], {"type": "object"})
        self.assertEqual(accounting["properties"]["productionPromotionClaimed"], {"const": False})
        self.assertEqual(validation["properties"]["productionPromotionClaimed"], {"const": False})
        self.assertEqual(generation["properties"]["liveCallsStarted"], {"const": False})

    def test_phase_cli_schemas_are_registered(self) -> None:
        phase_input = get_schema("agent-phase-resource-input.v1")
        phase_generation = get_schema("agent-phase-resource-generation.v1")
        self.assertEqual(phase_input["properties"]["phases"]["maxItems"], 256)
        self.assertEqual(phase_generation["properties"]["liveCallsStarted"], {"const": False})


if __name__ == "__main__":
    unittest.main()

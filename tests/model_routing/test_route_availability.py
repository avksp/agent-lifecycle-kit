from __future__ import annotations

import unittest

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.model_routing.availability import build_probe_observation, project_availability


class RouteAvailabilityTests(unittest.TestCase):
    def test_version_or_config_alone_never_confers_availability(self) -> None:
        value = self.project(None)
        self.assertEqual(value["status"], "UNAVAILABLE")
        self.assertFalse(value["authorityClaimed"])
        self.assertIsNone(value["actualUSD"])

    def test_successful_process_without_model_response_is_unavailable(self) -> None:
        for response in (None, {}, {"status": "PASS"}, {"status": "UNAVAILABLE"}):
            observation = build_probe_observation(
                availability=self.project(None),
                auth_revision_digest="a" * 64,
                launch={"status": "PASS", "hostLaunchStarted": True, "receiptDigest": "f" * 64},
                now=100,
                lineage={"test": "UNIT_ONLY"},
                model_response=response,
            )
            self.assertEqual(observation["status"], "UNAVAILABLE")
            self.assertEqual(self.project(observation)["status"], "UNAVAILABLE")

    @staticmethod
    def project(observation: dict | None, **kwargs: object) -> dict:
        arguments = {
            "configured": True,
            "executable": {"status": "PASS", "executableContentSha256": "e" * 64},
            "binding_digest": "b" * 64,
            "configuration_digest": "c" * 64,
            "auth_revision_digest": "a" * 64,
            "observation": observation,
            "now": 101,
        }
        return project_availability(**{**arguments, **kwargs})

    def test_probe_is_diagnostic_and_every_identity_or_expiry_invalidates(self) -> None:
        availability = self.project(None)
        observation = build_probe_observation(
            availability=availability,
            auth_revision_digest="a" * 64,
            launch={"status": "PASS", "hostLaunchStarted": True, "receiptDigest": "f" * 64},
            model_response={
                "status": "PASS",
                "responseDigest": "d" * 64,
                "terminalDigest": "e" * 64,
                "backendIdentityAttested": False,
            },
            now=100,
            lineage={"operationId": "op"},
        )
        self.assertEqual(self.project(observation)["status"], "PASS")
        self.assertFalse(observation["taskAccepted"])
        self.assertEqual(self.project(observation)["qualityQualification"], "UNAVAILABLE")
        for field in ("bindingDigest", "configurationDigest", "authRevisionDigest", "executableDigest"):
            changed = {**observation, field: "0" * 64}
            changed["observationDigest"] = canonical_digest(
                {key: value for key, value in changed.items() if key != "observationDigest"}
            )
            self.assertEqual(self.project(changed)["status"], "UNAVAILABLE")
        self.assertEqual(self.project(observation, now=3700)["status"], "UNAVAILABLE")
        self.assertEqual(self.project({**observation, "processStarted": False})["status"], "UNAVAILABLE")

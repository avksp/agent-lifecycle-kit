"""Generic source rejects promotion, lossy carry, foreign selectors and unsafe paths."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.declared_source_schemas import validate_owner_bindings, validate_project_carry
from agent_lifecycle.contracts.scoped_usage_schemas import validate_source_usage_policy_shape
from tests.accounting.test_generic_source_usage import GenericFixture, carry_data


class DeclaredSourceSchemaTests(unittest.TestCase):
    def test_carry_unknown_service_units_and_known_partials_are_not_measurements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            carry = carry_data(Path(tmp))
            self.assertIs(validate_project_carry(carry), carry)
            mutations = []
            for key, value in (("unknownIntervals", []), ("financialAssurance", "ATTESTED")):
                changed = copy.deepcopy(carry)
                changed[key] = value
                mutations.append(changed)
            for key, value in (("quantity", 0), ("quantity", True), ("quantity", 1.5), ("originRefDigest", "0" * 64)):
                changed = copy.deepcopy(carry)
                changed["declaredUnitRecords"][0][key] = value
                mutations.append(changed)
            changed = copy.deepcopy(carry)
            changed["declaredUnitRecords"].append(changed["declaredUnitRecords"][0])
            mutations.append(changed)
            changed = copy.deepcopy(carry)
            changed["sourceRefs"][0]["path"] = "../foreign.raw"
            mutations.append(changed)
            changed = copy.deepcopy(carry)
            changed["sourceRefs"][0]["bytes"] = 1_048_577
            mutations.append(changed)
            for data in mutations:
                with self.subTest(data=data["financialAssurance"]), self.assertRaises(LifecycleError):
                    validate_project_carry(data)

    def test_policy_versions_routes_and_mutable_immutable_separation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = GenericFixture(Path(tmp))
            validate_source_usage_policy_shape(fixture.policy)
            for key, value in (
                ("schemaVersion", "alk-source-usage-completion-policy.v1"),
                ("accountingKind", "EXISTING_DECLARED_COORDINATOR_LEDGER"),
                ("financialClosureAllowed", True),
            ):
                changed = copy.deepcopy(fixture.policy)
                changed[key] = value
                with self.subTest(key=key), self.assertRaises(LifecycleError):
                    validate_source_usage_policy_shape(changed)
            changed = copy.deepcopy(fixture.policy)
            changed["financialSource"]["headPath"] = "outside/HEAD.json"
            with self.assertRaises(LifecycleError):
                validate_source_usage_policy_shape(changed)

    def test_owner_attribution_cannot_be_guessed_or_duplicated(self) -> None:
        owners = {
            "schemaVersion": "agent-project-source-owner-bindings.v1",
            "requiredRoles": ["coordinator", "worker", "check", "auditor", "retry", "compaction", "closeout"],
            "ownerBindings": [{"actorId": "owner", "role": "worker", "taskIds": ["Q"]}],
        }
        validate_owner_bindings(owners)
        owners["ownerBindings"].append({"actorId": "another", "role": "coordinator", "taskIds": ["Q"]})
        with self.assertRaises(LifecycleError):
            validate_owner_bindings(owners)

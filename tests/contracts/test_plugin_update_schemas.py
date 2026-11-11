from __future__ import annotations

import copy
import unittest

from jsonschema import Draft202012Validator

from agent_lifecycle.contracts import LifecycleError, canonical_bytes
from agent_lifecycle.contracts.plugin_update_schemas import (
    PLUGIN_UPDATE_SCHEMAS,
    UPDATE_CACHE_SCHEMA,
    UPDATE_IMPACT_SCHEMA,
    UPDATE_INVENTORY_SCHEMA,
    UPDATE_REQUEST_SCHEMA,
    UPDATE_SOURCE,
)
from agent_lifecycle.contracts.plugin_update_validation import (
    update_json,
    update_report,
    validate_plan_inventory,
    validate_release_impact,
    validate_update_cache,
    validate_update_request,
)


def make_request(**values):
    return {"schemaVersion": UPDATE_REQUEST_SCHEMA, **values}


def make_descriptor():
    return {
        "schemaVersion": UPDATE_IMPACT_SCHEMA,
        "version": "2.48.0",
        "sourceCommit": "a" * 40,
        "origin": UPDATE_SOURCE,
        "baseVersions": ["2.47.0"],
        "domains": {},
        "changes": [],
        "exclusions": [],
    }


class PluginUpdateSchemasTests(unittest.TestCase):
    def test_negative_cache_nullable_pair_requires_bounded_failed_attempt(self):
        value = {
            "schemaVersion": UPDATE_CACHE_SCHEMA,
            "policyDigest": "a" * 64,
            "observedAt": None,
            "candidate": None,
            "lastAttemptAt": 10000,
            "lastFailureReason": "plugin-update-network-unavailable",
        }
        validator = Draft202012Validator(PLUGIN_UPDATE_SCHEMAS[UPDATE_CACHE_SCHEMA])
        validator.validate(value)
        self.assertEqual(validate_update_cache(value), value)
        malformed = [
            {**value, "candidate": {}},
            {**value, "observedAt": 10000},
            {**value, "lastAttemptAt": True},
            {**value, "lastAttemptAt": -1},
            {**value, "lastAttemptAt": 4102444801},
            {**value, "lastFailureReason": "private exception text"},
            {key: item for key, item in value.items() if key != "lastFailureReason"},
            {key: item for key, item in value.items() if key != "lastAttemptAt"},
        ]
        for item in malformed:
            with self.subTest(item=item), self.assertRaises(LifecycleError):
                validate_update_cache(item)

    def test_public_definitions_are_closed_and_valid_json_schemas(self):
        self.assertEqual(len(PLUGIN_UPDATE_SCHEMAS), 5)
        for name, schema in PLUGIN_UPDATE_SCHEMAS.items():
            with self.subTest(name=name):
                Draft202012Validator.check_schema(schema)
                self.assertEqual(schema["$id"], name)
                self.assertIs(schema["additionalProperties"], False)

    def test_minimal_request_has_manual_policy_without_implied_observations(self):
        request = make_request()
        self.assertEqual(validate_update_request(request), request)
        self.assertNotIn("observations", request)

    def test_unknown_request_fields_and_foreign_source_refuse(self):
        for value in (
            make_request(argv=["rm", "-rf"]),
            make_request(source="https://example.org"),
            make_request(mode="auto"),
            make_request(triggerQualified=1),
            make_request(targetVersion="2.48.0; touch marker"),
            make_request(pin="v2.47.0", targetVersion="2.48.0"),
        ):
            with self.subTest(value=value), self.assertRaises(LifecycleError):
                validate_update_request(value)

    def test_caller_cannot_promote_host_observation(self):
        request = make_request(observations={"loadedInstructions": {"version": "2.47.0", "provenance": "ATTESTED"}})
        with self.assertRaises(LifecycleError):
            validate_update_request(request)

    def test_exact_version_rejects_empty_and_leading_zero_prerelease_identifiers(self):
        for version in ("01.0.0", "1.0.0-01", "1.0.0-alpha..one", "1.0.0-alpha."):
            with self.subTest(version=version), self.assertRaises(LifecycleError):
                validate_update_request(make_request(targetVersion=version))

    def test_duplicate_nonfinite_depth_and_byte_inputs_refuse(self):
        samples = [
            b'{"a":1,"a":2}',
            b'{"a":NaN}',
            b'{"a":Infinity}',
            canonical_bytes({"a": "x" * 262145}),
            canonical_bytes({"a": "x" * 4097}),
        ]
        nested = {}
        for _ in range(18):
            nested = {"x": nested}
        samples.append(canonical_bytes(nested))
        for raw in samples:
            with self.subTest(length=len(raw)), self.assertRaises(LifecycleError):
                update_json(raw)

    def test_descriptor_missing_coverage_is_valid_but_never_complete_by_default(self):
        descriptor = make_descriptor()
        self.assertEqual(validate_release_impact(descriptor)["domains"], {})

    def test_invalid_domain_review_and_duplicate_changes_refuse(self):
        descriptor = make_descriptor()
        descriptor["domains"] = {
            "quality": {"identifiers": [], "coverage": "COMPLETE", "semanticReview": "REVIEWED", "evidenceRefs": []}
        }
        with self.assertRaises(LifecycleError):
            validate_release_impact(descriptor)
        descriptor = make_descriptor()
        change = {"domain": "quality", "identifier": "validation.commands", "impact": "UNCHANGED", "reason": "review"}
        descriptor["changes"] = [change, copy.deepcopy(change)]
        with self.assertRaises(LifecycleError):
            validate_release_impact(descriptor)

    def test_plan_inventory_is_explicit_unique_and_bounded(self):
        base = {"schemaVersion": UPDATE_INVENTORY_SCHEMA, "plans": [{"manifest": "plans/a.json"}]}
        self.assertEqual(validate_plan_inventory(base), base)
        for paths in (
            [{"manifest": "../outside.json"}],
            [{"manifest": "/outside.json"}],
            [{"manifest": "a.json"}, {"manifest": "a.json"}],
            [{"manifest": f"plan/{i}.json"} for i in range(33)],
        ):
            with self.subTest(paths=paths), self.assertRaises(LifecycleError):
                validate_plan_inventory({**base, "plans": paths})

    def test_unapplied_edit_can_only_contain_literals_and_portable_path(self):
        descriptor = make_descriptor()
        change = {
            "domain": "path",
            "identifier": "plan.json",
            "impact": "ADAPTATION_REQUIRED",
            "reason": "rename",
            "proposedEdit": {"path": "plan.json", "pointer": "/title", "expectedValue": "old", "proposedValue": "new"},
        }
        descriptor["changes"] = [change]
        self.assertEqual(validate_release_impact(descriptor), descriptor)
        for value in (["script"], {"execute": "script"}):
            change["proposedEdit"]["proposedValue"] = value
            with self.assertRaises(LifecycleError):
                validate_release_impact(descriptor)

    def test_every_report_preserves_zero_dispatch_and_no_authority(self):
        report = update_report("check", "OFF", make_request(), {"reason": "manual only"})
        Draft202012Validator(PLUGIN_UPDATE_SCHEMAS[report["schemaVersion"]]).validate(report)
        self.assertIs(report["authorityClaimed"], False)
        self.assertEqual((report["modelCallsStarted"], report["nativeProcessesStarted"]), (0, 0))

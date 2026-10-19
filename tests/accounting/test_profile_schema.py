"""Differential H04 contract checks; synthetic profiles do not qualify a host."""
from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

import jsonschema

from agent_lifecycle.accounting.host_bridge import _profile_schema
from agent_lifecycle.accounting.profile_schema import matches_profile_schema
from agent_lifecycle.contracts import LifecycleError
from tests.accounting import test_host_bridge as fixtures

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SHA256 = "e54a9847e441b1d9253a8d1192d8f209a886f36bf953045dea99217ee9a9fd98"


def leaf_paths(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from leaf_paths(child, path + (key,))
    elif isinstance(value, list) and value:
        for index, child in enumerate(value[:2]):
            yield from leaf_paths(child, path + (index,))
    else:
        yield path


class ProfileSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = (ROOT / "tasks/release-2-16/h04-artifact-contracts.json").read_bytes()
        if len(raw) != 43190 or hashlib.sha256(raw).hexdigest() != SCHEMA_SHA256:
            raise AssertionError("Changed independently reviewed H04 schema")
        cls.definitions = json.loads(raw)["$defs"]
        case = fixtures.SourceQualificationConsumerTests()
        case.setUp()
        cls.addClassCleanup(case.doCleanups)
        case.make_final()
        cls.positive = {name: json.loads((case.profiles / "codex" / filename).read_bytes())
                        for name, filename in [("qualification", "qualification.json"),
                                               ("profile", "profile.json"),
                                               ("resolverEvidence", "resolver-evidence.json")]}

    def compare(self, value, definitions, name="root"):
        oracle = jsonschema.Draft202012Validator({"$defs": definitions, "$ref": "#/$defs/" + name})
        expected = oracle.is_valid(value)
        self.assertEqual(matches_profile_schema(value, definitions, name), expected)
        return expected

    def test_real_pinned_roots_accept_the_same_source_only_fixture(self):
        for name, value in self.positive.items():
            with self.subTest(root=name):
                self.assertTrue(self.compare(value, self.definitions, name))
                self.assertIsNone(_profile_schema(value, self.definitions, name))

    def test_required_and_unknown_properties_match_the_oracle(self):
        for name, original in self.positive.items():
            for field in self.definitions[name]["required"]:
                value = copy.deepcopy(original)
                del value[field]
                with self.subTest(root=name, missing=field):
                    self.assertFalse(self.compare(value, self.definitions, name))
            with self.subTest(root=name, extra=True):
                self.assertFalse(self.compare({**original, "unexpected": 0}, self.definitions, name))

    def test_independent_nested_mutations_match_the_oracle(self):
        for name, original in self.positive.items():
            for path in list(leaf_paths(original))[:48]:
                for replacement in (None, True, 0, "", {}, []):
                    value = copy.deepcopy(original)
                    parent = value
                    for key in path[:-1]:
                        parent = parent[key]
                    parent[path[-1]] = replacement
                    with self.subTest(root=name, path=path, replacement=replacement):
                        self.compare(value, self.definitions, name)

    def test_array_uniqueness_uses_json_equality(self):
        definitions = {"root": {"type": "array", "uniqueItems": True}}
        cases = [[True, 1], [False, 0], [1, 1], [None, None], [[1], [1]],
                 [{"a": 1, "b": 2}, {"b": 2, "a": 1}], [0, True, False]]
        for value in cases:
            with self.subTest(value=value):
                self.compare(value, definitions)

    def test_host_binding_conditionals_match_real_definitions(self):
        original = self.positive["qualification"]
        for mode in ("SOURCE_BOUND_LIMITATION", "RUNTIME_OBSERVED"):
            for executable, configuration in [(None, None), ("a" * 64, "b" * 64),
                                               (True, "b" * 64), ("bad", "b" * 64)]:
                value = copy.deepcopy(original)
                value["binding"].update(evidenceMode=mode, executableSha256=executable,
                                        configurationSha256=configuration)
                with self.subTest(mode=mode, executable=executable, configuration=configuration):
                    self.compare(value, self.definitions, "qualification")

    def test_patterns_lengths_and_integer_bounds_match(self):
        definitions = {"root": {"anyOf": [
            {"type": "string", "pattern": "a+", "minLength": 2, "maxLength": 4},
            {"type": "integer", "minimum": 1, "maximum": 3},
        ]}}
        for value in ["", "a", "ba", "aaaa", "aaaaa", "bb", True, False, 0, 1, 3, 4, None]:
            with self.subTest(value=value):
                self.compare(value, definitions)
        definitions = {"root": {"type": "array", "minItems": 1, "maxItems": 2,
                                 "items": {"enum": [True, 1, None]}}}
        for value in [[], [True], [1], [False], [None], [1, None], [1, 1, 1]]:
            with self.subTest(array=value):
                self.compare(value, definitions)

    def test_optional_condition_property_is_not_implicitly_required(self):
        definitions = {"root": {"type": "object",
            "properties": {"flag": {"type": "boolean"}, "amount": {"type": "integer"}},
            "if": {"properties": {"flag": {"const": True}}}, "then": {"required": ["amount"]}}}
        for value in [{}, {"flag": False}, {"flag": True}, {"amount": 0},
                      {"flag": True, "amount": True}, {"flag": True, "amount": 1}]:
            with self.subTest(value=value):
                self.compare(value, definitions)

    def test_local_reference_siblings_and_all_applicators_apply(self):
        definitions = {"root": {"$ref": "#/$defs/base", "minimum": 3,
                                 "allOf": [{"maximum": 7}], "anyOf": [{"const": 4}, {"const": 6}]},
                       "base": {"type": "integer"}}
        for value in [True, None, 1, 3, 4, 6, 7, 8]:
            with self.subTest(value=value):
                self.compare(value, definitions)

    def test_unknown_malformed_and_remote_schemas_refuse(self):
        cases = [{"not": {}}, {"type": True}, {"type": []}, {"type": ["integer", "integer"]},
                 {"pattern": "["}, {"pattern": 1}, {"required": "x"}, {"required": [1]},
                 {"required": ["x", "x"]}, {"enum": []}, {"enum": [True, True]},
                 {"properties": []}, {"additionalProperties": {}}, {"minLength": True},
                 {"minimum": False}, {"uniqueItems": 1}, {"anyOf": []}, {"allOf": "bad"},
                 {"items": []}, {"$ref": "https://invalid.example/schema"},
                 {"$ref": "#/$defs/missing"}, {"const": float("nan")}]
        for schema in cases:
            with self.subTest(schema=schema):
                self.assertFalse(matches_profile_schema(0, {"root": schema}, "root"))

    def test_invalid_schema_refuses_even_in_an_unselected_branch(self):
        for bad in [{"$ref": "#/$defs/root"}, {"unknownKeyword": True}]:
            with self.subTest(bad=bad):
                self.assertFalse(matches_profile_schema(0, {"root": {"anyOf": [{}, bad]}}, "root"))
        self.assertFalse(matches_profile_schema(0, {"root": {}, "unused": {"not": {}}}, "root"))

    def test_reference_and_value_depth_boundaries(self):
        for count in (64, 65):
            definitions = {"r" + str(i): {"$ref": "#/$defs/r" + str(i + 1)} for i in range(count)}
            definitions["r" + str(count)] = {"type": "integer"}
            with self.subTest(referenceDepth=count):
                self.assertEqual(matches_profile_schema(0, definitions, "r0"), count == 64)
            value = 0
            for _ in range(count):
                value = [value]
            with self.subTest(valueDepth=count):
                self.assertEqual(matches_profile_schema(value, {"root": {}}, "root"), count == 64)

    def test_alternatives_cannot_reset_the_global_work_budget(self):
        schema = {"anyOf": [{"type": "array", "items": {"type": "integer"}} for _ in range(20)] + [{}]}
        definitions = {"root": schema}
        self.assertTrue(self.compare([1, "x"], definitions))
        value = [1] * 3999 + ["x"]
        self.assertTrue(jsonschema.Draft202012Validator(schema).is_valid(value))
        self.assertFalse(matches_profile_schema(value, definitions, "root"))

    def test_noncanonical_or_cyclic_values_refuse(self):
        values = [0.0, float("inf"), float("nan"), (1,), {1: "x"}, "\ud800"]
        cyclic = []
        cyclic.append(cyclic)
        values.append(cyclic)
        for index, value in enumerate(values):
            with self.subTest(case=index):
                self.assertFalse(matches_profile_schema(value, {"root": {}}, "root"))

    def test_wrapper_retains_the_qualification_refusal_code(self):
        with self.assertRaises(LifecycleError) as caught:
            _profile_schema({}, self.definitions, "qualification")
        self.assertEqual(caught.exception.code, "accounting-qualification-schema-invalid")

from __future__ import annotations

import copy
import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.model_routing.stage_bindings import (
    ordered_stage_refs,
    portable_selection,
    select_stage,
    validate_stage_registry,
)


def registry_fixture() -> dict:
    ref = {"path": ".alk/host-launch/example.json", "sha256": "a" * 64}
    entry = {
        "adapterId": "codex",
        "hostModelProfile": {**ref, "modelClass": "strong-reasoning"},
        "launchProfile": dict(ref),
        "hostParameters": {"reasoningEffort": "high"},
        "parameterSupport": {"allowedEfforts": ["none", "high"], "evidence": dict(ref)},
        "qualificationEvidence": dict(ref),
    }
    return {"schemaVersion": "agent-local-stage-bindings.v1", "bindings": {"primary": entry}}


class StageBindingsTests(unittest.TestCase):
    def test_closed_registry_and_parameter_support(self) -> None:
        registry = registry_fixture()
        self.assertEqual(validate_stage_registry(registry)["bindingCount"], 1)
        for mutation in (
            lambda r: r.update(extra=True),
            lambda r: r["bindings"]["primary"].update(fallbacks=["primary"]),
            lambda r: r["bindings"]["primary"]["hostParameters"].update(reasoningEffort="low"),
            lambda r: r["bindings"]["primary"]["launchProfile"].update(path=".alk/host-launch/../bad.json"),
        ):
            changed = copy.deepcopy(registry)
            mutation(changed)
            with self.assertRaises(LifecycleError):
                validate_stage_registry(changed)

    def test_three_total_unique_refs_and_explicit_membership(self) -> None:
        for refs in ([], ["a", "a"], ["a", "b", "c", "d"], ["../../bad"]):
            with self.subTest(refs=refs), self.assertRaises(LifecycleError):
                ordered_stage_refs({"stages": {"implementation": {"executionBindingRefs": refs}}}, "implementation")
        profile = {"stages": {"implementation": {"executionBindingRefs": ["a", "b", "c"]}}}
        self.assertEqual(ordered_stage_refs(profile, "implementation", "b"), ["b"])
        with self.assertRaises(LifecycleError):
            ordered_stage_refs(profile, "implementation", "unapproved")

    def test_stage_mode_and_portable_allowlist(self) -> None:
        self.assertEqual(select_stage("implement"), "implementation")
        self.assertEqual(select_stage("review", "audit"), "audit")
        with self.assertRaises(LifecycleError):
            select_stage("implement", "audit")
        local = {
            "stage": "audit",
            "modelClass": "strong-reasoning",
            "bindingId": "private-id",
            "model": "private-model",
            "reasoningEffort": "high",
            "pins": {"private-path": "a" * 64},
        }
        self.assertEqual(portable_selection(local), {"stage": "audit", "modelClass": "strong-reasoning"})

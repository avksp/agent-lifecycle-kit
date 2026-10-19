"""Closed negative A5 contracts; these tests make no host-protection claim."""

from __future__ import annotations

import copy
import unittest

from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.immutable_input_schemas import (
    parse_a5_record,
    validate_a5_adoption_binding,
    validate_a5_boundary_registry,
    validate_a5_decision,
    validate_a5_decision_binding,
    validate_a5_invocation_context,
    validate_a5_invocation_request,
    validate_a5_plan_policy,
    validate_a5_policy,
    validate_a5_request,
)

HASH = "a" * 64


def sealed(value: dict, field: str) -> dict:
    value[field] = canonical_digest({key: item for key, item in value.items() if key != field})
    return value


def subject() -> dict:
    return {
        "runId": "run",
        "packageId": "package",
        "taskId": "task",
        "targetAttempt": 1,
        "operationId": "op",
        "stateRevision": 5,
        "planDigest": HASH,
        "sourceRevision": "source",
    }


def policy() -> dict:
    return sealed(
        {
            "schemaVersion": "agent-a5-limited-policy.v1",
            "mode": "A5_LIMITED",
            "adapterId": "codex",
            "expectationId": "a5:codex",
            "targetVersion": "0.155.1",
            "entrySurface": "ALK_TASK_START",
            "frozenTaskRequirement": "NONE",
            "boundaryRecordDigest": HASH,
            "strongAdmissionSupported": False,
        },
        "policyDigest",
    )


def request() -> dict:
    return {
        "schemaVersion": "agent-a5-limited-request.v1",
        "subject": subject(),
        "requestedProtection": "NONE",
        "expectedPolicyDigest": policy()["policyDigest"],
        "expectedBoundaryRecordDigest": HASH,
    }


def decision(protection="NONE") -> dict:
    disposition = "DENY_STRONG" if protection == "STRONG_A5" else "ORDINARY_NO_A5"
    reason = "STRONG_UNPROVEN" if protection == "STRONG_A5" else "NO_STRONG_REQUIREMENT"
    return sealed(
        {
            "schemaVersion": "agent-a5-limited-decision.v1",
            "subject": subject(),
            "policyDigest": policy()["policyDigest"],
            "boundaryRecordDigest": HASH,
            "requestDigest": canonical_digest(request()),
            "effectiveRequirement": protection,
            "disposition": disposition,
            "reason": reason,
            "strongProtectionGranted": False,
            "scope": "ALK_ADMISSION_CLASSIFICATION_ONLY",
        },
        "decisionDigest",
    )


class A5ClosedSchemaTests(unittest.TestCase):
    def test_policy_request_and_negative_decisions(self) -> None:
        self.assertEqual(validate_a5_policy(policy())["strongAdmissionSupported"], False)
        self.assertEqual(validate_a5_request(request())["requestedProtection"], "NONE")
        self.assertEqual(validate_a5_decision(decision())["disposition"], "ORDINARY_NO_A5")
        self.assertEqual(validate_a5_decision(decision("STRONG_A5"))["disposition"], "DENY_STRONG")
        self.assertEqual(
            validate_a5_plan_policy(
                {
                    "schemaVersion": "agent-a5-plan-policy.v1",
                    "mode": "A5_LIMITED",
                    "defaultRequirement": "STRONG_A5",
                    "contractDigest": HASH,
                }
            )["defaultRequirement"],
            "STRONG_A5",
        )
        self.assertEqual(
            validate_a5_invocation_request(
                {"schemaVersion": "agent-a5-invocation-request.v1", "requestedProtection": "NONE"}
            )["requestedProtection"],
            "NONE",
        )

    def test_unknown_fields_false_as_integer_and_wrong_digest_reject(self) -> None:
        altered = policy()
        altered["allowHostProtection"] = True
        with self.assertRaises(LifecycleError):
            validate_a5_policy(altered)
        altered = request()
        altered["subject"]["targetAttempt"] = True
        with self.assertRaises(LifecycleError):
            validate_a5_request(altered)
        altered = policy()
        altered["targetVersion"] = "changed"
        with self.assertRaises(LifecycleError):
            validate_a5_policy(altered)

    def test_positive_flag_and_inconsistent_decision_reject(self) -> None:
        altered = decision()
        altered["strongProtectionGranted"] = True
        sealed(altered, "decisionDigest")
        with self.assertRaises(LifecycleError):
            validate_a5_decision(altered)
        altered = decision()
        altered["disposition"] = "DENY_STRONG"
        sealed(altered, "decisionDigest")
        with self.assertRaises(LifecycleError):
            validate_a5_decision(altered)

    def test_decision_container_discriminators_reject_as_contract_errors(self) -> None:
        for field in ("disposition", "reason"):
            for value in ([], {}):
                with self.subTest(field=field, value=value):
                    altered = decision()
                    altered[field] = value
                    sealed(altered, "decisionDigest")
                    with self.assertRaises(LifecycleError):
                        parse_a5_record(canonical_bytes(altered), "decision")

    def test_duplicate_raw_members_reject_before_interpretation(self) -> None:
        raw = b'{"schemaVersion":"agent-a5-invocation-request.v1","requestedProtection":"NONE","requestedProtection":"STRONG_A5"}'
        with self.assertRaises(LifecycleError):
            parse_a5_record(raw, "invocationRequest")

    def test_decision_binding_rejects_replay_and_downgrade(self) -> None:
        self.assertEqual(validate_a5_decision_binding(decision(), policy(), request())["disposition"], "ORDINARY_NO_A5")
        strong_request = request()
        strong_request["requestedProtection"] = "STRONG_A5"
        strong_decision = decision("STRONG_A5")
        strong_decision["requestDigest"] = canonical_digest(strong_request)
        sealed(strong_decision, "decisionDigest")
        self.assertEqual(
            validate_a5_decision_binding(strong_decision, policy(), strong_request)["disposition"], "DENY_STRONG"
        )
        with self.assertRaises(LifecycleError):
            validate_a5_decision_binding(decision(), policy(), strong_request)
        changed_policy = policy()
        changed_policy["targetVersion"] = "v2"
        sealed(changed_policy, "policyDigest")
        with self.assertRaises(LifecycleError):
            validate_a5_decision_binding(decision(), changed_policy, request())

    def test_managed_context_cannot_be_standalone(self) -> None:
        context = {
            "schemaVersion": "agent-a5-invocation-context.v1",
            "invocationId": "call",
            "operation": "MANAGED_TASK",
            "origin": "FROZEN_WORKFLOW_TASK",
            "workflowSubject": subject(),
            "frozenAuthorityRefs": [{"path": name, "sha256": HASH} for name in ("manifest", "lock", "state")],
            "adapterId": "codex",
            "sessionId": None,
            "requestedProtection": "NONE",
            "expectedProtection": "NONE",
            "policyDigest": policy()["policyDigest"],
            "boundaryRecordDigest": HASH,
            "normalizedRequestDigest": HASH,
            "taskInputDigest": HASH,
            "profileDigest": None,
            "strongProtectionGranted": False,
        }
        sealed(context, "contextDigest")
        self.assertEqual(validate_a5_invocation_context(context)["operation"], "MANAGED_TASK")
        altered = copy.deepcopy(context)
        altered["operation"] = "VERSION_PREFLIGHT"
        altered["origin"] = "VERSION_ONLY_PREFLIGHT"
        sealed(altered, "contextDigest")
        with self.assertRaises(LifecycleError):
            validate_a5_invocation_context(altered)
        altered = copy.deepcopy(context)
        altered["frozenAuthorityRefs"] = []
        sealed(altered, "contextDigest")
        with self.assertRaises(LifecycleError):
            validate_a5_invocation_context(altered)

    def test_adoption_preserves_ordinary_classification(self) -> None:
        binding = sealed(
            {
                "schemaVersion": "agent-a5-adoption-binding.v1",
                "runId": "run",
                "taskId": "task",
                "actualAttempt": 1,
                "originalPlanDigest": HASH,
                "currentPlanDigest": "b" * 64,
                "originalPolicyDigest": None,
                "currentPolicyDigest": HASH,
                "originalDecisionDigest": None,
                "compatibilityReceiptDigest": HASH,
                "classification": "PRESERVED_LEGACY_NO_A5",
                "strongProtectionGranted": False,
            },
            "bindingDigest",
        )
        self.assertEqual(validate_a5_adoption_binding(binding)["strongProtectionGranted"], False)
        binding["strongProtectionGranted"] = True
        sealed(binding, "bindingDigest")
        with self.assertRaises(LifecycleError):
            validate_a5_adoption_binding(binding)

    def test_boundary_registry_is_closed_and_unique(self) -> None:
        records = []
        for index, adapter in enumerate(
            (
                "codex",
                "claude",
                "opencode",
                "grok-build",
                "gemini-cli",
                "pi",
                "hermes",
                "qwen-code",
                "kimi-code",
                "cursor",
                "goose",
                "openinterpreter",
            )
        ):
            records.append(
                sealed(
                    {
                        "adapterId": adapter,
                        "expectationId": f"expectation-{index}",
                        "targetVersion": "v1",
                        "mode": "A5_LIMITED",
                        "strongAdmissionSupported": False,
                        "strongCapability": "UNPROVEN",
                        "sourceDigest": HASH,
                    },
                    "boundaryRecordDigest",
                )
            )
        registry = sealed({"schemaVersion": "agent-a5-boundary-registry.v1", "records": records}, "registryDigest")
        self.assertEqual(len(validate_a5_boundary_registry(registry)["records"]), 12)
        registry["records"][1] = copy.deepcopy(registry["records"][0])
        sealed(registry, "registryDigest")
        with self.assertRaises(LifecycleError):
            validate_a5_boundary_registry(registry)


if __name__ == "__main__":
    unittest.main()

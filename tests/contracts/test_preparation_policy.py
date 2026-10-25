"""Finite policy fixtures are controller mechanics, not host attestation."""

import copy
import unittest

from agent_lifecycle.contracts.preparation_policy import (
    POLICY_SCHEMA,
    evaluate_preparation_policy,
)


def context_fixture(prefix_digest="f" * 64):
    grant = {"qualified": True, "digest": "a" * 64, "expiresAt": 1000}
    return {
        "schemaVersion": POLICY_SCHEMA,
        "goalDigest": "b" * 64,
        "phaseDigest": "c" * 64,
        "sourceDigest": "d" * 64,
        "authorization": grant,
        "nativeDeadlineAt": 1000,
        "quantity": "RESERVATION_TOKENS",
        "executionChain": False,
        "inputDigest": "b" * 64,
        "unitDefinitionId": "reportedTokens:fixture:v1",
        "routeQualificationDigest": "a" * 64,
        "issuerDigest": "a" * 64,
        "validityDigest": "a" * 64,
        "chain": {
            "required": ["area", "integration", "final"],
            "slots": [
                {
                    "stage": stage,
                    "qualified": True,
                    "authorizationDigest": grant["digest"],
                    "expiresAt": 1000,
                    "remaining": 1,
                }
                for stage in ("area", "integration", "final")
            ],
        },
        "readiness": {"qualified": True, "sourceDigest": "d" * 64, "checks": {"provider": "PASS", "input": "PASS"}},
        "progress": {
            "qualified": True,
            "status": "UNAVAILABLE",
            "goalDigest": "b" * 64,
            "phaseDigest": "c" * 64,
            "sourceDigest": "d" * 64,
            "journalPrefixDigest": prefix_digest,
            "completedRounds": 0,
            "nonproductiveRounds": 0,
            "verifiedInitial": True,
        },
        "repeat": {"required": False},
        "limits": {
            "tokens": 1000,
            "chargedMilliseconds": 1000,
            "requests": 8,
            "semanticRounds": 8,
            "closeoutTokens": 200,
        },
        "request": {"tokens": 100, "chargedMilliseconds": 100, "requests": 1, "semanticRound": 1},
    }


def usage_fixture(prefix_digest="f" * 64):
    return {
        "qualified": True,
        "prefixDigest": prefix_digest,
        "quantity": "RESERVATION_TOKENS",
        "tokens": 0,
        "chargedMilliseconds": 0,
        "requests": 0,
        "semanticRound": 0,
    }


class PreparationPolicyTests(unittest.TestCase):
    def evaluate(self, context=None, usage=None):
        return evaluate_preparation_policy(
            context or context_fixture(),
            usage or usage_fixture(),
            now=100,
        )

    def test_verified_initial_and_audit_progress(self):
        self.assertEqual(self.evaluate()["reason"], "READY")
        context = context_fixture()
        context["progress"].update(
            status="ADVANCING",
            completedRounds=1,
            verifiedInitial=False,
        )
        self.assertEqual(self.evaluate(context)["status"], "PASS")
        self.assertFalse(self.evaluate(context)["authorityClaimed"])

    def test_default_stall_wait_and_missing_history(self):
        context = context_fixture()
        context["progress"].update(
            status="STALLED",
            completedRounds=2,
            nonproductiveRounds=2,
            verifiedInitial=False,
        )
        self.assertEqual(self.evaluate(context)["reason"], "PROCESS_PROGRESS_STALLED")
        context["window"] = "another budget after compact"
        self.assertEqual(self.evaluate(context)["reason"], "PROCESS_PROGRESS_STALLED")
        context["progress"].update(status="EXPECTED_WAIT", waitUntil=120)
        self.assertEqual(self.evaluate(context)["reason"], "PROCESS_EXPECTED_WAIT")
        context["progress"]["waitUntil"] = 99
        self.assertEqual(self.evaluate(context)["reason"], "PREPARATION_HISTORY_UNAVAILABLE")
        context["progress"].update(status="UNAVAILABLE", verifiedInitial=False)
        self.assertEqual(self.evaluate(context)["reason"], "PREPARATION_HISTORY_UNAVAILABLE")

    def test_only_bound_finite_approved_stall_override(self):
        context = context_fixture()
        context["progress"].update(
            status="STALLED",
            completedRounds=2,
            nonproductiveRounds=2,
        )
        context["nonproductiveRoundLimit"] = 3
        self.assertNotEqual(self.evaluate(context)["status"], "PASS")
        context["stallOverrideAuthorization"] = context["authorization"]
        self.assertEqual(self.evaluate(context)["status"], "PASS")
        for limit in (True, 0, -1, 2**63, "3"):
            context["nonproductiveRoundLimit"] = limit
            self.assertNotEqual(self.evaluate(context)["status"], "PASS")

    def test_caps_include_protected_closeout_and_expensive_requests(self):
        for name, used in (("tokens", 701), ("chargedMilliseconds", 901), ("requests", 8), ("semanticRound", 9)):
            with self.subTest(name=name):
                context, usage = context_fixture(), usage_fixture()
                context["progress"]["status"] = "ADVANCING"
                usage[name] = used
                self.assertEqual(self.evaluate(context, usage)["reason"], "PREPARATION_BUDGET_EXHAUSTED")

    def test_missing_chain_readiness_authority_and_stronger_quantity(self):
        mutations = [
            (lambda c: c["chain"]["slots"].pop(), "REVIEW_CHAIN_NOT_READY"),
            (lambda c: c["chain"]["required"].remove("final"), "REVIEW_CHAIN_NOT_READY"),
            (lambda c: c["readiness"]["checks"].update(auth="UNAVAILABLE"), "PREPARATION_READINESS_UNAVAILABLE"),
            (lambda c: c["authorization"].update(expiresAt=100), "PREPARATION_AUTHORITY_UNAVAILABLE"),
            (lambda c: c.update(nativeDeadlineAt=99), "PREPARATION_NATIVE_DEADLINE_EXPIRED"),
            (lambda c: c.update(quantity="WHOLE_HOST_TOKENS"), "PREPARATION_QUANTITY_UNSUPPORTED"),
        ]
        for mutate, expected in mutations:
            context = context_fixture()
            mutate(context)
            self.assertEqual(self.evaluate(context)["reason"], expected)

    def test_repeat_requires_named_invalidated_input_and_benefit(self):
        context = context_fixture()
        context["repeat"] = {
            "required": True,
            "qualified": True,
            "disposition": "INVALIDATED",
            "inputDigests": ["e" * 64],
            "benefitDigest": "f" * 64,
        }
        self.assertEqual(self.evaluate(context)["status"], "PASS")
        for key in ("qualified", "disposition", "inputDigests", "benefitDigest"):
            bad = copy.deepcopy(context)
            del bad["repeat"][key]
            self.assertNotEqual(self.evaluate(bad)["status"], "PASS")

    def test_portable_closed_output_ignores_secret_debug_fields(self):
        context = context_fixture()
        context["debug"] = {"api_key": "secret", "path": "/private/source"}
        result = self.evaluate(context)
        self.assertEqual(result["status"], "PASS")
        self.assertNotIn("secret", str(result))
        self.assertNotIn("/private", str(result))
        context["debug"] = "x" * 65537
        self.assertNotEqual(self.evaluate(context)["status"], "PASS")

    def test_first_refusal_order_survives_multiple_invalid_inputs(self):
        cases = [
            ([("authorization", "qualified", False), ("chain", "slots", [])], "PREPARATION_AUTHORITY_UNAVAILABLE"),
            (
                [(None, "nativeDeadlineAt", 99), (None, "quantity", "WHOLE_HOST_TOKENS")],
                "PREPARATION_NATIVE_DEADLINE_EXPIRED",
            ),
            ([(None, "quantity", "WHOLE_HOST_TOKENS"), ("chain", "slots", [])], "PREPARATION_QUANTITY_UNSUPPORTED"),
            ([("chain", "slots", []), ("readiness", "qualified", False)], "REVIEW_CHAIN_NOT_READY"),
            (
                [("readiness", "qualified", False), ("progress", "qualified", False)],
                "PREPARATION_READINESS_UNAVAILABLE",
            ),
            ([("progress", "qualified", False), ("repeat", "required", "invalid")], "PREPARATION_HISTORY_UNAVAILABLE"),
            (
                [
                    ("progress", "status", "EXPECTED_WAIT"),
                    ("progress", "waitUntil", 120),
                    ("repeat", "required", "invalid"),
                ],
                "PROCESS_EXPECTED_WAIT",
            ),
            (
                [
                    ("progress", "status", "STALLED"),
                    ("progress", "completedRounds", 2),
                    ("progress", "nonproductiveRounds", 2),
                    ("repeat", "required", "invalid"),
                ],
                "PROCESS_PROGRESS_STALLED",
            ),
        ]
        for patches, reason in cases:
            context = context_fixture()
            for group, key, value in patches:
                (context if group is None else context[group])[key] = value
            with self.subTest(reason=reason):
                result = self.evaluate(context)
                self.assertEqual(result["reason"], reason)
                self.assertFalse(result["authorityClaimed"])
                self.assertFalse(result["productionPromotionClaimed"])

    def test_malformed_finite_values_and_budget_refusal_order(self):
        for group, key in (
            ("progress", "completedRounds"),
            ("progress", "nonproductiveRounds"),
            ("limits", "tokens"),
            ("request", "tokens"),
        ):
            for value in (True, -1, "1", 2**63):
                context = context_fixture()
                context[group][key] = value
                with self.subTest(group=group, key=key, value=value):
                    self.assertEqual(self.evaluate(context)["reason"], "PREPARATION_INPUT_UNAVAILABLE")
        context, usage = context_fixture(), usage_fixture()
        context["request"]["requests"] = 2
        usage["tokens"] = 1000
        self.assertEqual(self.evaluate(context, usage)["reason"], "PREPARATION_BUDGET_EXHAUSTED")
        self.assertEqual(self.evaluate(context)["reason"], "PREPARATION_INPUT_UNAVAILABLE")

from __future__ import annotations

import copy
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

BINDINGS = ("source", "harness", "oracle", "fixture", "environment", "contract")
MAX_RESOURCE = (1 << 63) - 1
from agent_lifecycle.workflow.closing_window import assess_retained_evidence, evaluate_closing_resources  # noqa: E402

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)


def scope(**changes) -> dict:
    return {
        "capInventoryComplete": True,
        "effectiveCaps": [
            {
                "capId": "original",
                "disposition": "SUPERSEDED_BY_WINDOW",
                "limit": 100,
                "policyRef": "qualified-prospective-policy",
            }
        ],
        "scopeId": "run",
        "scopeKind": "RUN",
        "unit": "reportedTokens",
        "operationUnit": "reportedTokens",
        "unitDefinition": "tokens-v1",
        "operationUnitDefinition": "tokens-v1",
        "sourceQualificationRef": "source-proof",
        "openingRef": "opening",
        "pendingRef": "pending",
        "protectionRef": "protected",
        "reservationRef": "reservations",
        "oldCap": 100,
        "spentAtActivation": 90,
        "approvedAdditional": 20,
        "cumulativeSpent": 90,
        "windowSpent": 0,
        "activeReservations": 0,
        "windowReservations": 0,
        "protectedCloseout": 5,
        "windowProtectedCloseout": 5,
        "operationUpperBound": 15,
        **changes,
    }


def check(name: str, dependencies: tuple[str, ...] = ()) -> dict:
    bindings = {key: f"{key}-v1" for key in BINDINGS}
    return {
        "checkId": name,
        "subject": "attempt-1",
        "bindings": bindings,
        "executionState": "TERMINAL",
        "dependencies": list(dependencies),
        "plannedUpperBound": 20,
        "receipt": {
            "receiptId": f"receipt-{name}",
            "digest": "a" * 64,
            "producer": "independent-auditor",
            "attemptId": "attempt-1",
            "operationId": f"operation-{name}",
            "subject": "attempt-1",
            "bindings": copy.deepcopy(bindings),
            "outcome": "PASS",
            "completed": True,
            "authenticity": "QUALIFIED",
            "validUntil": "2026-09-22T00:00:00Z",
        },
    }


def evidence() -> dict:
    return {
        "schemaVersion": "agent-retained-evidence-assessment.v1",
        "inventoryComplete": True,
        "requiredCheckIds": ["Q", "D", "E", "P"],
        "checks": [check("Q"), check("D", ("Q",)), check("E", ("D",)), check("P")],
        "originalAttempt": {
            "status": "REWORK",
            "resourceStatus": "FAIL",
            "spent": 120,
            "oldCap": 100,
            "executionDeadline": "2026-09-20T00:00:00Z",
            "absoluteDeadlineStatus": "FAIL",
        },
    }


def assess(value: dict) -> dict:
    return assess_retained_evidence(value, now=NOW, observer_qualification="independently-established-observer")


class ClosingResourceTests(unittest.TestCase):
    def test_binding_task_and_run_caps_are_checked_in_addition_to_window(self) -> None:
        for capped_scope in ("RUN", "TASK"):
            with self.subTest(capped_scope=capped_scope):
                run = scope(approvedAdditional=200)
                task = scope(scopeId="task", scopeKind="TASK")
                capped = run if capped_scope == "RUN" else task
                capped["effectiveCaps"].append(
                    {"capId": "still-binding", "disposition": "BINDING", "limit": 100, "policyRef": "unchanged-policy"}
                )
                result = evaluate_closing_resources([run, task], inventory_complete=True)
                self.assertEqual(result["status"], "DENY")
                row = next(r for r in result["scopes"] if r["scopeKind"] == capped_scope)
                self.assertEqual(row["cumulativeRequired"], 110)
                self.assertEqual(row["violatedEffectiveCaps"], ["still-binding"])
                self.assertFalse(row["fits"])
                capped["effectiveCaps"][-1]["limit"] = 110
                self.assertEqual(
                    evaluate_closing_resources([run, task], inventory_complete=True)["status"], "VALIDATED_DATA"
                )

    def test_unknown_required_cap_disposition_never_infers_new_authority(self) -> None:
        for variant in ("missing", "incomplete", "empty", "unknown", "limit", "policy", "superseded-policy"):
            with self.subTest(variant=variant):
                value = scope()
                if variant == "missing":
                    del value["effectiveCaps"]
                elif variant == "incomplete":
                    value["capInventoryComplete"] = False
                elif variant == "empty":
                    value["effectiveCaps"] = []
                else:
                    cap = value["effectiveCaps"][0]
                    if variant == "unknown":
                        cap["disposition"] = "UNKNOWN"
                    elif variant == "limit":
                        cap["limit"] = None
                    else:
                        cap["policyRef"] = None
                        if variant == "policy":
                            cap["disposition"] = "BINDING"
                result = evaluate_closing_resources([value], inventory_complete=True)
                self.assertEqual(result["status"], "UNAVAILABLE")
                self.assertNotIn("fits", result["scopes"][0])
                self.assertEqual(result["authority"], "NOT_EVALUATED")

    def test_original_overrun_preserved_and_unused_old_allowance_not_added(self) -> None:
        for spent, ceiling, excess in [(90, 110, 0), (120, 140, 20)]:
            with self.subTest(spent=spent):
                value = [scope(spentAtActivation=spent, cumulativeSpent=spent)]
                original = copy.deepcopy(value)
                result = evaluate_closing_resources(value, inventory_complete=True)
                self.assertEqual(result["status"], "VALIDATED_DATA")
                row = result["scopes"][0]
                self.assertEqual(
                    (row["proposedCumulativeCeiling"], row["windowAllowance"], row["oldExcess"]), (ceiling, 20, excess)
                )
                self.assertEqual((row["cumulativeRequired"], row["windowRequired"]), (ceiling, 20))
                self.assertEqual(value, original)
                self.assertEqual(result["authority"], "NOT_EVALUATED")

    def test_run_fit_does_not_bypass_task_limit_and_one_charge_updates_two_views(self) -> None:
        run = scope(
            cumulativeSpent=94, windowSpent=4, activeReservations=2, windowReservations=2, operationUpperBound=9
        )
        result = evaluate_closing_resources([run], inventory_complete=True)
        self.assertEqual(result["scopes"][0]["cumulativeRequired"], 110)
        self.assertEqual(result["scopes"][0]["windowRequired"], 20)
        task = scope(scopeId="task", scopeKind="TASK", approvedAdditional=5, operationUpperBound=5)
        result = evaluate_closing_resources([scope(operationUpperBound=5), task], inventory_complete=True)
        self.assertEqual([r["status"] for r in result["scopes"]], ["VALIDATED_DATA", "DENY"])
        self.assertEqual(result["status"], "DENY")

    def test_unknowns_units_malformed_and_overflows_cannot_fit(self) -> None:
        variants = [
            ({"spentAtActivation": None}, "UNAVAILABLE"),
            ({"operationUpperBound": None}, "UNAVAILABLE"),
            ({"pendingRef": None}, "UNAVAILABLE"),
            ({"unit": None}, "UNAVAILABLE"),
            ({"operationUnit": "billableTokens"}, "UNAVAILABLE"),
            ({"operationUnitDefinition": "different"}, "UNAVAILABLE"),
            ({"operationUpperBound": True}, "DENY"),
            ({"approvedAdditional": "20"}, "DENY"),
            ({"spentAtActivation": MAX_RESOURCE, "cumulativeSpent": MAX_RESOURCE}, "DENY"),
            ({"activeReservations": MAX_RESOURCE}, "DENY"),
            ({"operationUpperBound": 16}, "DENY"),
            ({"cumulativeSpent": 89}, "DENY"),
            ({"windowReservations": 1}, "DENY"),
        ]
        for changes, expected in variants:
            with self.subTest(changes=changes):
                result = evaluate_closing_resources([scope(**changes)], inventory_complete=True)
                self.assertEqual(result["status"], expected)
        self.assertEqual(evaluate_closing_resources([scope()], inventory_complete=False)["status"], "UNAVAILABLE")
        self.assertEqual(
            evaluate_closing_resources([scope(scopeKind="TASK")], inventory_complete=True)["status"], "UNAVAILABLE"
        )
        self.assertEqual(evaluate_closing_resources([scope(), scope()], inventory_complete=True)["status"], "DENY")


class RetainedEvidenceTests(unittest.TestCase):
    def test_expired_permission_resource_failure_and_unaccepted_attempt_do_not_erase_evidence(self) -> None:
        value = evidence()
        before = copy.deepcopy(value)
        result = assess(value)
        self.assertEqual(result["status"], "REUSE")
        self.assertEqual(result["retainedInput"]["originalAttempt"], before["originalAttempt"])
        self.assertEqual(result["authority"], "NOT_EVALUATED")
        self.assertEqual(result["acceptance"], "NOT_EVALUATED")
        self.assertFalse(result["dispatch"])
        self.assertTrue(result["futureAdmissionRequired"])
        self.assertEqual(value, before)
        result["retainedInput"]["originalAttempt"]["spent"] = 0
        self.assertEqual(value["originalAttempt"]["spent"], 120)

    def test_completed_negative_stays_negative_even_when_reusable(self) -> None:
        value = evidence()
        value["checks"][0]["receipt"]["outcome"] = "FAIL"
        result = assess(value)
        self.assertEqual(result["status"], "REUSE")
        self.assertFalse(result["evidenceGateSatisfied"])
        self.assertEqual(next(r for r in result["checks"] if r["checkId"] == "Q")["originalOutcome"], "FAIL")

    def test_changed_binding_and_known_missing_results_only_invalidate_dependents(self) -> None:
        for variant in ("binding", "never-started", "terminal-missing", "semantic-ttl"):
            with self.subTest(variant=variant):
                value = evidence()
                q = value["checks"][0]
                if variant == "binding":
                    q["bindings"]["oracle"] = "oracle-v2"
                elif variant == "semantic-ttl":
                    q["receipt"]["validUntil"] = NOW.isoformat()
                else:
                    q["receipt"] = None
                    q["executionState"] = "NEVER_STARTED" if variant == "never-started" else "TERMINAL"
                result = assess(value)
                self.assertEqual(
                    {r["checkId"]: r["status"] for r in result["checks"]},
                    {"Q": "RERUN_REQUIRED", "D": "RERUN_REQUIRED", "E": "RERUN_REQUIRED", "P": "REUSE"},
                )
                self.assertTrue(all(r["admissionStatus"] == "NOT_ADMITTED" for r in result["checks"]))
                self.assertFalse(result["dispatch"])

    def test_unknown_inventory_definition_dependencies_and_binding_fail_closed(self) -> None:
        for variant in (
            "inventory",
            "definition",
            "unknown-edge",
            "unknown-dependencies",
            "cycle",
            "binding",
            "provenance",
        ):
            with self.subTest(variant=variant):
                value = evidence()
                q = value["checks"][0]
                if variant == "inventory":
                    value["inventoryComplete"] = False
                elif variant == "definition":
                    value["checks"].pop()
                elif variant == "unknown-edge":
                    q["dependencies"] = ["unknown"]
                elif variant == "unknown-dependencies":
                    q["dependencies"] = None
                elif variant == "cycle":
                    q["dependencies"] = ["E"]
                elif variant == "binding":
                    del q["receipt"]["bindings"]["source"]
                else:
                    del q["receipt"]["operationId"]
                self.assertEqual(assess(value)["status"], "UNAVAILABLE")
        self.assertEqual(
            assess_retained_evidence(evidence(), now=NOW, observer_qualification=None)["status"], "UNAVAILABLE"
        )

    def test_running_unknown_and_unfinished_receipt_block_duplicate_work_and_dependents(self) -> None:
        for state, receipt in [
            ("RUNNING", None),
            ("UNKNOWN", None),
            ("TERMINAL", {**check("Q")["receipt"], "completed": False}),
        ]:
            with self.subTest(state=state):
                value = evidence()
                value["checks"][0].update(executionState=state, receipt=receipt)
                result = assess(value)
                self.assertEqual(
                    {r["checkId"]: r["status"] for r in result["checks"]},
                    {"Q": "UNAVAILABLE", "D": "UNAVAILABLE", "E": "UNAVAILABLE", "P": "REUSE"},
                )
                self.assertEqual(result["retainedInput"], value)

    def test_malformed_metadata_is_denied_without_input_mutation(self) -> None:
        for field, bad in [("plannedUpperBound", True), ("dependencies", "Q"), ("executionState", "ACCEPTED")]:
            with self.subTest(field=field):
                value = evidence()
                value["checks"][0][field] = bad
                before = copy.deepcopy(value)
                self.assertEqual(assess(value)["status"], "DENY")
                self.assertEqual(value, before)


if __name__ == "__main__":
    unittest.main()

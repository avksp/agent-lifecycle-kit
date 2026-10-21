"""Progress tests use independent exact observation/qualification joins."""

from __future__ import annotations

import unittest
from copy import deepcopy

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.metrics.goal_progress import build_goal_progress


def progress_inputs(count: int = 2) -> tuple[dict, list, dict]:
    context = {"goalDigest": "a" * 64, "phaseDigest": "b" * 64,
               "subjectDigest": "c" * 64, "sourceRevision": "d" * 40,
               "criteriaDigests": ["e" * 64], "evidenceDigests": ["e" * 64],
               "outcomeDigests": ["e" * 64],
               "stateRevision": count, "verifiedInitial": False}
    observations = [{
        **{key: context[key] for key in ("goalDigest", "phaseDigest", "subjectDigest", "sourceRevision")},
        "stateRevision": index + 1, "operationDigest": canonical_digest(["operation", index]),
        "qualificationDigest": canonical_digest(["qualification", index]),
        "acceptedCriteria": [], "qualifiedEvidence": [], "verifiedOutcomes": [],
        "kind": "WORK", "semanticRoundCompleted": index > 0,
        "observedAt": index + 1,
        "waitingUntil": None, "waitAuthorizationDigest": None,
    } for index in range(count)]
    return qualify(context, observations)


def qualify(context: dict, observations: list) -> tuple[dict, list, dict]:
    context["historyDigest"] = canonical_digest(observations)
    receipts = {item["qualificationDigest"]: {
        **{key: context[key] for key in ("goalDigest", "phaseDigest", "subjectDigest", "sourceRevision")},
        "status": "PASS", "provenanceValidated": True,
        "operationDigest": item["operationDigest"], "observationDigest": canonical_digest(item),
    } for item in observations}
    receipts[context["historyDigest"]] = {
        **{key: context[key] for key in ("goalDigest", "phaseDigest", "subjectDigest", "sourceRevision")},
        "status": "PASS", "provenanceValidated": True, "completePrefix": True,
        "historyDigest": context["historyDigest"], "stateRevision": context["stateRevision"],
        "obligationsDigest": canonical_digest({key: context[key] for key in (
            "criteriaDigests", "evidenceDigests", "outcomeDigests",
        )}),
    }
    return context, observations, receipts


class GoalProgressTests(unittest.TestCase):
    def test_expired_historical_wait_does_not_hide_later_audit_or_stalled_work(self) -> None:
        for advancing in (True, False):
            context, observations, _ = progress_inputs(3)
            observations[1].update(kind="WAIT", semanticRoundCompleted=False,
                                   waitingUntil=50, waitAuthorizationDigest="e" * 64)
            observations[2]["kind"] = "AUDIT" if advancing else "WORK"
            if advancing:
                observations[2]["qualifiedEvidence"] = ["e" * 64]
            result = self.project(qualify(context, observations))
            self.assertEqual(result["state"], "ADVANCING" if advancing else "STALLED")
            self.assertEqual(result["nonproductiveRounds"], 0 if advancing else 1)

    def test_current_expired_or_historically_unbounded_wait_remains_unavailable(self) -> None:
        for observed, until in ((2, 50), (2, 90000), (-1, 200), (101, 200)):
            context, observations, _ = progress_inputs()
            observations[1].update(kind="WAIT", semanticRoundCompleted=False,
                                   observedAt=observed, waitingUntil=until, waitAuthorizationDigest="e" * 64)
            self.assertEqual(self.project(qualify(context, observations))["state"], "UNAVAILABLE")

    def test_artifact_and_proof_churn_for_same_evidence_obligation_is_not_progress(self) -> None:
        context, observations, _ = progress_inputs()
        for observation in observations:
            observation["qualifiedEvidence"] = ["e" * 64]
        result = self.project(qualify(context, observations))
        self.assertEqual(result["state"], "STALLED")
        observations[1]["qualifiedEvidence"].append("f" * 64)
        self.assertEqual(self.project(qualify(context, observations))["state"], "UNAVAILABLE")

    def project(self, inputs: tuple) -> dict:
        context, observations, receipts = inputs
        return build_goal_progress(context, observations, qualified_receipts=receipts, now=100)

    def test_verified_initial_is_separate_from_missing_history(self) -> None:
        context, observations, receipts = progress_inputs(0)
        self.assertEqual(self.project((context, observations, receipts))["state"], "UNAVAILABLE")
        context["verifiedInitial"] = True
        result = self.project((context, observations, receipts))
        self.assertTrue(result["initialContext"])
        self.assertEqual(result["nonproductiveRounds"], 0)

    def test_artifact_churn_does_not_advance_two_completed_rounds(self) -> None:
        result = self.project(progress_inputs(3))
        self.assertEqual(result["state"], "STALLED")
        self.assertEqual(result["nonproductiveRounds"], 2)
        self.assertFalse(result["authorityClaimed"])

    def test_real_new_criteria_and_read_only_audit_or_diagnosis_advance(self) -> None:
        for field in ("acceptedCriteria", "qualifiedEvidence", "verifiedOutcomes"):
            for kind in ("WORK", "AUDIT", "DIAGNOSIS"):
                with self.subTest(field=field, kind=kind):
                    context, observations, _ = progress_inputs()
                    observations[-1][field] = ["e" * 64]
                    observations[-1]["kind"] = kind
                    result = self.project(qualify(context, observations))
                    self.assertEqual(result["state"], "ADVANCING")

    def test_wait_is_bounded_and_not_a_semantic_round(self) -> None:
        context, observations, _ = progress_inputs(3)
        observations[-1].update(kind="WAIT", semanticRoundCompleted=False,
                                waitingUntil=200, waitAuthorizationDigest="e" * 64)
        result = self.project(qualify(context, observations))
        self.assertEqual(result["state"], "EXPECTED_WAIT")
        self.assertEqual(result["nonproductiveRounds"], 1)
        observations[-1]["waitingUntil"] = 99
        self.assertEqual(self.project(qualify(context, observations))["state"], "UNAVAILABLE")

    def test_missing_stale_duplicate_regressed_and_wrong_subject_refuse(self) -> None:
        for change in ("missing-proof", "stale", "duplicate", "regression", "wrong-subject"):
            context, observations, receipts = deepcopy(progress_inputs())
            if change == "missing-proof":
                receipts.clear()
            elif change == "stale":
                context["stateRevision"] += 1
            elif change == "duplicate":
                observations[1]["operationDigest"] = observations[0]["operationDigest"]
            elif change == "regression":
                observations[0]["acceptedCriteria"] = ["e" * 64]
            else:
                observations[1]["sourceRevision"] = "f" * 40
            if change != "missing-proof":
                context, observations, receipts = qualify(context, observations)
            self.assertEqual(self.project((context, observations, receipts))["state"], "UNAVAILABLE", change)

    def test_overflow_history_refuses_instead_of_slicing(self) -> None:
        with self.assertRaises(LifecycleError):
            self.project(progress_inputs(65))

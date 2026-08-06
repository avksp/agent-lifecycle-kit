from __future__ import annotations

import unittest

from agent_lifecycle.quality import build_bug_forensics_advisory, bug_forensics_recommended


class BugForensicsAdvisorTests(unittest.TestCase):
    def test_recommends_bug_forensics_for_defect_regression_flaky_incident_and_security_inputs(self) -> None:
        examples = [
            ("Find and fix the checkout bug", "defect-signal-bug"),
            ("Repair the regression in the billing plan", "defect-signal-regression"),
            ("Investigate the flaky test that passes on retry", "defect-signal-flaky"),
            ("Triage the production incident and hotfix safely", "defect-signal-incident"),
            ("Fix the security bug that leaks a token", "defect-signal-security-bug"),
        ]
        for text, reason in examples:
            with self.subTest(text=text):
                advisory = build_bug_forensics_advisory(text)

                self.assertTrue(bug_forensics_recommended(advisory))
                self.assertEqual(advisory["recommendation"], "SUGGEST")
                self.assertIn("bug-forensics", advisory["recommendedQualityProfiles"])
                self.assertIn(reason, advisory["reasonCodes"])
                self.assertTrue(advisory["gateBoundary"]["advisoryOnly"])
                self.assertFalse(advisory["gateBoundary"]["activeWorkflowGateClaimed"])
                self.assertTrue(advisory["gateBoundary"]["blockingRequiresReviewedPlanOptIn"])
                self.assertFalse(advisory["modelCallsStarted"])
                self.assertFalse(advisory["hostLaunchStarted"])
                self.assertFalse(advisory["rawTaskTextStored"])

    def test_feature_input_stays_not_applicable(self) -> None:
        advisory = build_bug_forensics_advisory("Add the settings page copy")

        self.assertFalse(bug_forensics_recommended(advisory))
        self.assertEqual(advisory["recommendation"], "NOT_APPLICABLE")
        self.assertEqual(advisory["recommendedQualityProfiles"], [])
        self.assertEqual(advisory["evidenceExpectations"], [])
        self.assertEqual(advisory["reasonCodes"], ["no-defect-signal"])


if __name__ == "__main__":
    unittest.main()

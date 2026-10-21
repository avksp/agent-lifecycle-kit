"""Independent verbose authoring and strict, honestly scoped paired measurements."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, canonical_bytes
from agent_lifecycle.metrics.plan_package_comparison import compare_plan_packages

_FIXTURES = Path(__file__).resolve().parents[1] / "planning/fixtures"
SOURCE = "tasks/compact-example/compact-input.json"
MANIFEST = "tasks/compact-example/plan.manifest.json"
_VERBOSE_SOURCE = "tasks/compact-example/verbose-input.json"


def paired_inputs(tier: str = "S0") -> tuple[bytes, bytes]:
    """Author the verbose control explicitly; never derive it from translator output."""
    compact = (_FIXTURES / ("compact-" + tier.lower() + "-plan.json")).read_bytes()
    source = json.loads(compact)
    requirements, criteria, evidence, tasks, commands = [], [], [], [], []
    for index, change in enumerate(source["changes"]):
        identity = change["id"]
        ac, ev = "AC-" + identity, "EV-" + identity
        requirements.append(
            {
                "id": "R-" + identity,
                "description": change["requirement"],
                "owner": source["owner"],
                "acceptanceIds": [ac],
                "evidenceIds": [ev],
            }
        )
        criteria.append(
            {"id": ac, "requirementIds": ["R-" + identity], "evidenceIds": [ev], "statement": change["acceptance"]}
        )
        evidence.append(
            {"id": ev, "description": change["evidenceDescription"], "artifactPath": change["evidencePath"]}
        )
        tasks.append(
            {
                "id": "WS-" + identity,
                "title": change["title"],
                "owner": source["owner"],
                "dependsOn": ["WS-" + source["changes"][index - 1]["id"]] if index else [],
                "writes": change["writes"],
                "acceptanceIds": [ac],
                "evidenceIds": [ev],
                "plannedItems": [
                    {
                        "id": ac,
                        "title": change["title"],
                        "acceptanceIds": [ac],
                        "evidenceIds": [ev],
                        "validationCommands": change["validationCommands"],
                    }
                ],
            }
        )
        for command in change["validationCommands"]:
            if command not in commands:
                commands.append(command)
    runtime = source["package"]["artifactRoot"]
    plan = source["package"]["planArtifactRoot"]
    review = plan + "/independent-plan-review.json"
    verbose = {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "DRAFT",
        "planRevision": 1,
        "package": {**source["package"], "root": ".", "workspaceRoot": "."},
        "planFiles": sorted([_VERBOSE_SOURCE, MANIFEST, review]),
        "packageIntegrity": {
            "required": True,
            "lockSchemaVersion": "agent-plan-lock.v2",
            "inventorySource": "planFiles",
            "undeclaredTopLevelFiles": "reject",
            "allowedUnlistedFiles": ["plan.lock.json"],
        },
        "author": source["author"],
        "baseRevision": source["baseRevision"],
        "specification": {
            "tier": tier,
            "intent": "to-be",
            "status": "DRAFT",
            "source": _VERBOSE_SOURCE,
            "requirements": requirements,
            "tierResolutionRequest": {
                "taskCount": len(source["changes"]),
                "executableOwners": [source["owner"]],
                "capabilityHints": ["bounded-mechanical"] if source["mechanical"] else [],
                "riskFlags": {
                    name: False
                    for name in ("architecture", "security", "performance", "browser", "externalEnvironment")
                },
                "externalSpecification": False,
                "requirementsBytes": sum(len(change["requirement"].encode("utf-8")) for change in source["changes"]),
            },
        },
        "workstreams": tasks,
        "acceptance": {"criteria": criteria, "evidence": evidence},
        "validation": {"commands": commands, "extraEvidence": [item["id"] for item in evidence]},
        "readOnly": source["readOnly"],
        "forbiddenWrites": source["forbiddenWrites"],
        "leadOwned": [
            {"path": plan, "reason": "explicit plan authority"},
            {"path": runtime, "reason": "explicit runtime evidence authority"},
        ],
        "releaseImpact": source["releaseImpact"],
        "securityGates": source["securityGates"],
        "contextLimits": source["contextLimits"],
        "orchestration": {
            **source["orchestration"],
            "stateFile": runtime + "/run.state.json",
            "eventLog": runtime + "/workflow-events.jsonl",
        },
        "planReview": {"required": True, "report": review, "reviewedRevision": 1, "verdict": "READY_TO_FREEZE"},
        "implementationAudit": {"required": True, "finalRequired": True},
        "budgetPolicy": {
            "liveHostCallsAllowedByDefault": False,
            "modelTokenBudgetForPlanValidation": 0,
            "moneyFieldsCanonical": False,
            "budgetUnits": "reported-tokens",
        },
        "finalAuditGates": ["[AC-" + c["id"] + "|EV-" + c["id"] + "] " + c["acceptance"] for c in source["changes"]],
    }
    return (json.dumps(verbose, ensure_ascii=False, indent=2) + "\n").encode(), compact


def _compare(*, tier: str = "S0", legacy: bytes | None = None, compact: bytes | None = None, **kwargs) -> dict:
    control, candidate = paired_inputs(tier)
    return compare_plan_packages(
        case_id="CONTROLLED-" + tier,
        legacy_input=legacy if legacy is not None else control,
        compact_input=compact if compact is not None else candidate,
        compact_source_path=SOURCE,
        manifest_path=MANIFEST,
        source_revision="a" * 40,
        source_lineage_digest="b" * 64,
        **kwargs,
    )


class PlanPackageComparisonTests(unittest.TestCase):
    def test_both_independent_verbose_controls_preserve_all_canonical_facts(self) -> None:
        for tier in ("S0", "S1"):
            with self.subTest(tier=tier):
                legacy, compact = paired_inputs(tier)
                value = _compare(tier=tier)
                self.assertEqual(value["status"], "PASS")
                self.assertTrue(value["canonicalFactsEqual"])
                self.assertEqual(value["inputs"]["legacy"]["bytes"], len(legacy))
                self.assertEqual(value["inputs"]["compact"]["bytes"], len(compact))
                self.assertEqual(value["authoringInputByteDelta"], len(compact) - len(legacy))
                self.assertEqual(value["sourceDocumentLocationDifferences"]["legacy"], _VERBOSE_SOURCE)
                self.assertFalse(value["tokenOrMoneySavingsClaimed"])
                self.assertFalse(value["downstreamAuthorityProofClaimed"])
                for metric in value["realWorkflowMetrics"].values():
                    self.assertIsNone(metric["value"])
                    self.assertEqual(metric["status"], "UNAVAILABLE")
                self.assertEqual(value["localElapsedSeconds"]["status"], "UNAVAILABLE")
                self.assertEqual(value["reviewInputBytes"]["status"], "UNAVAILABLE")

    def test_author_ids_commands_requirements_and_budgets_cannot_be_normalized_away(self) -> None:
        original, _ = paired_inputs()
        for field in ("author", "requirements", "commands", "budget"):
            legacy = json.loads(original)
            if field == "author":
                legacy["author"] = "different-real-author"
            elif field == "requirements":
                legacy["specification"]["requirements"][0]["description"] = "Different intended behaviour"
            elif field == "commands":
                legacy["validation"]["commands"] = ["different actual check"]
            elif field == "budget":
                legacy["orchestration"]["maxReportedTokensPerRun"] += 1
            with self.subTest(field=field):
                try:
                    value = _compare(legacy=canonical_bytes(legacy))
                except LifecycleError:
                    continue
                self.assertEqual(value["status"], "FAIL")
                self.assertFalse(value["canonicalFactsEqual"])
                self.assertTrue(value["semanticMismatchFields"])

    def test_only_source_inventory_location_can_differ(self) -> None:
        legacy, _ = paired_inputs()
        value = json.loads(legacy)
        value["planFiles"].append("tasks/compact-example/another-obligation.md")
        actual = _compare(legacy=canonical_bytes(value))
        self.assertEqual(actual["status"], "FAIL")
        self.assertIn("planFiles", actual["semanticMismatchFields"])

    def test_invalid_legacy_and_risky_compact_inputs_never_get_positive_comparison(self) -> None:
        legacy, compact = paired_inputs()
        broken = json.loads(legacy)
        broken["status"] = "INVALID"
        with self.assertRaises(LifecycleError):
            _compare(legacy=canonical_bytes(broken))
        for risk in ("architecture", "security", "performance", "externalEnvironment", "release", "data"):
            source = json.loads(compact)
            source["riskFlags"][risk] = True
            with self.subTest(risk=risk), self.assertRaises(LifecycleError):
                _compare(compact=canonical_bytes(source))

    def test_local_samples_and_review_bytes_are_separate_explicit_measurements(self) -> None:
        samples = {"legacy": [0.01, 0.02, 0.03], "compact": [0.03, 0.04, 0.05]}
        before = deepcopy(samples)
        value = _compare(local_elapsed_seconds=samples, review_input_bytes={"legacy": 111, "compact": 222})
        self.assertEqual(value["localElapsedSeconds"]["status"], "MEASURED_LOCAL_ONLY")
        self.assertEqual(value["localElapsedSeconds"]["compact"], samples["compact"])
        self.assertEqual(value["reviewInputBytes"]["compact"], 222)
        self.assertEqual(samples, before)
        self.assertFalse(value["tokenOrMoneySavingsClaimed"])

    def test_unpaired_nonfinite_boolean_or_excessive_timing_samples_refuse(self) -> None:
        for invalid in (
            {"legacy": [], "compact": []},
            {"legacy": [True], "compact": [0.1]},
            {"legacy": [float("nan")], "compact": [0.1]},
            {"legacy": [float("inf")], "compact": [0.1]},
            {"legacy": [-1], "compact": [0.1]},
            {"legacy": [61], "compact": [0.1]},
            {"legacy": [0.1] * 4, "compact": [0.1] * 4},
            {"legacy": [0.1], "compact": [0.1, 0.2]},
            {"compact": [0.1]},
        ):
            with self.subTest(samples=invalid), self.assertRaises(LifecycleError):
                _compare(local_elapsed_seconds=invalid)
        for counts in ({"legacy": True, "compact": 1}, {"legacy": 1}, {"legacy": 0, "compact": 1}):
            with self.subTest(counts=counts), self.assertRaises(LifecycleError):
                _compare(review_input_bytes=counts)

    def test_duplicate_json_and_oversized_verbose_input_refuse(self) -> None:
        legacy, _ = paired_inputs()
        for raw in (b" " * 262145, b'{"status":"DRAFT",' + legacy.lstrip()[1:]):
            with self.assertRaises(LifecycleError):
                _compare(legacy=raw)

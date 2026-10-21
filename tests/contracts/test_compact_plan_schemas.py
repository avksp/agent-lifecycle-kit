"""Closed compact-source parsing at hostile and incomplete input boundaries."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, canonical_bytes
from agent_lifecycle.contracts.compact_plan_schemas import (
    COMPACT_RISKS,
    MAX_COMPACT_INPUT_BYTES,
    ORCHESTRATION_FIELDS,
    load_compact_plan_input,
    require_compact_plan_input,
)

_FIXTURES = Path(__file__).resolve().parents[1] / "planning/fixtures"


def _source() -> dict:
    return json.loads((_FIXTURES / "compact-s0-plan.json").read_bytes())


class CompactInputContractTests(unittest.TestCase):
    def test_valid_sources_round_trip_without_mutation(self) -> None:
        for name in ("compact-s0-plan.json", "compact-s1-plan.json"):
            with self.subTest(name=name):
                raw = (_FIXTURES / name).read_bytes()
                source = load_compact_plan_input(raw)
                original = deepcopy(source)
                self.assertEqual(require_compact_plan_input(source), original)
                self.assertEqual(load_compact_plan_input(canonical_bytes(source)), original)

    def test_every_root_fact_is_required_and_unknown_facts_refused(self) -> None:
        original = _source()
        for field in original:
            with self.subTest(missing=field):
                source = deepcopy(original)
                del source[field]
                with self.assertRaises(LifecycleError):
                    require_compact_plan_input(source)
        for field in ("modelRoute", "planReview", "authorized", "reviewer", "extensions"):
            with self.subTest(unknown=field):
                source = _source()
                source[field] = {"independent": True}
                with self.assertRaises(LifecycleError):
                    require_compact_plan_input(source)

    def test_duplicate_keys_are_refused_at_every_json_level(self) -> None:
        for raw in (b'{"tier":"S0","tier":"S1"}', b'{"package":{"id":"a","id":"b"}}'):
            with self.subTest(raw=raw), self.assertRaises(LifecycleError) as raised:
                load_compact_plan_input(raw)
            self.assertEqual(raised.exception.code, "compact-plan-json-duplicate-key")

    def test_malformed_nonfinite_deep_and_oversized_json_is_refused(self) -> None:
        samples = [
            b"\xff",
            b"{",
            b"null",
            b"[]",
            b'{"x":NaN}',
            b'{"x":Infinity}',
            b"[" * 1500 + b"0" + b"]" * 1500,
            b" " * (MAX_COMPACT_INPUT_BYTES + 1),
        ]
        for raw in samples:
            with self.subTest(size=len(raw)), self.assertRaises(LifecycleError):
                load_compact_plan_input(raw)

    def test_risk_cannot_be_missing_malformed_or_hidden(self) -> None:
        for field in COMPACT_RISKS:
            for value in (True, "false", 0, None, []):
                with self.subTest(field=field, value=value):
                    source = _source()
                    source["riskFlags"][field] = value
                    with self.assertRaises(LifecycleError):
                        require_compact_plan_input(source)
        for transform in (lambda flags: flags.pop("data"), lambda flags: flags.update(unknown=False)):
            source = _source()
            transform(source["riskFlags"])
            with self.assertRaises(LifecycleError):
                require_compact_plan_input(source)

    def test_caps_are_explicit_positive_integers_and_serial(self) -> None:
        numeric = ORCHESTRATION_FIELDS - {"startMode", "remediationMode"}
        for field in numeric:
            for value in (True, 0, -1, 1.5, "3", None):
                with self.subTest(field=field, value=value):
                    source = _source()
                    source["orchestration"][field] = value
                    with self.assertRaises(LifecycleError):
                        require_compact_plan_input(source)
        for field, value in (
            ("maxParallelTasks", 2),
            ("maxTaskAttempts", 4),
            ("maxPlanReviewRounds", 5),
            ("startMode", "auto-after-freeze"),
            ("remediationMode", "unbounded"),
        ):
            source = _source()
            source["orchestration"][field] = value
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                require_compact_plan_input(source)

    def test_task_caps_must_fit_run_caps(self) -> None:
        for field in ("maxToolCallsPerRun", "maxReportedTokensPerRun", "maxRunWallSeconds", "maxEvidenceBytesPerRun"):
            source = _source()
            source["orchestration"][field] = 1
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                require_compact_plan_input(source)

    def test_changes_require_all_facts_and_unique_ids(self) -> None:
        for field in _source()["changes"][0]:
            source = _source()
            del source["changes"][0][field]
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                require_compact_plan_input(source)
        for identity in ("Import", "import", "../escape", "", "A" * 41):
            source = _source()
            source["tier"] = "S1"
            second = deepcopy(source["changes"][0])
            second["id"] = identity
            source["changes"].append(second)
            with self.subTest(identity=identity), self.assertRaises(LifecycleError):
                require_compact_plan_input(source)

    def test_empty_or_oversized_lists_and_text_refuse(self) -> None:
        for field, value in (
            ("changes", []),
            ("changes", [{}] * 13),
            ("securityGates", []),
            ("author", ""),
            ("releaseImpact", "x" * 4097),
        ):
            source = _source()
            source[field] = value
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                require_compact_plan_input(source)
        for field, value in (
            ("writes", []),
            ("validationCommands", []),
            ("requirement", "x" * 4097),
            ("validationCommands", ["true"] * 33),
            ("writes", ["x"] * 129),
        ):
            source = _source()
            source["changes"][0][field] = value
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                require_compact_plan_input(source)

    def test_paths_cannot_traverse_expand_or_alias(self) -> None:
        for path in ("../escape", "/tmp/escape", "src/**", "src//x", "src/./x", "src/../x", "src/\x00x"):
            source = _source()
            source["changes"][0]["writes"] = [path]
            with self.subTest(path=path), self.assertRaises(LifecycleError):
                require_compact_plan_input(source)
        source = _source()
        source["changes"][0]["writes"] = ["src/One.py", "src/one.py"]
        with self.assertRaises(LifecycleError):
            require_compact_plan_input(source)

    def test_context_and_base_identity_refuse_ambiguous_values(self) -> None:
        for field, value in (
            ("targetReviewerPacketTokens", True),
            ("maxReviewerPacketTokens", 1),
            ("smallContextProfilesRequired", False),
        ):
            source = _source()
            source["contextLimits"][field] = value
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                require_compact_plan_input(source)
        for sha in ("1" * 39, "A" * 40, None):
            source = _source()
            source["baseRevision"]["sha"] = sha
            with self.subTest(sha=sha), self.assertRaises(LifecycleError):
                require_compact_plan_input(source)

    def test_in_memory_entry_also_enforces_utf8_input_size(self) -> None:
        source = json.loads((_FIXTURES / "compact-s1-plan.json").read_bytes())
        for index in range(4):
            item = deepcopy(source["changes"][0])
            item["id"] = "Long" + str(index)
            for name in ("requirement", "acceptance", "evidenceDescription"):
                item[name] = "\u044f" * 4096
            source["changes"].append(item)
        with self.assertRaises(LifecycleError) as raised:
            require_compact_plan_input(source)
        self.assertEqual(raised.exception.code, "compact-plan-input-too-large")


if __name__ == "__main__":
    unittest.main()

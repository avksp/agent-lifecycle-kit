"""Portable Release 2.6/2.7 workflow-shape baselines for continuation."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from agent_lifecycle.workflow.continuation import _project_route

FIXTURE_ROOT = Path(__file__).parent / "fixtures"
FIXTURES = (
    FIXTURE_ROOT / "release-2-6-continuation-trace.json",
    FIXTURE_ROOT / "release-2-7-continuation-trace.json",
)

EVENT_SURFACES: dict[str, tuple[str | None, str | None, str]] = {
    "plan-adopted": (None, None, "workflow adopt-plan"),
    "execution-authorized": ("request-execution-authorization", "authorize", "workflow authorize"),
    "execution-started": ("start-execution", "run-start", "workflow run-start"),
    "task-started": ("launch-tasks", "task-start", "workflow task-start"),
    "task-result-committed": ("wait-for-active-tasks", "task-result", "workflow task-result"),
    "task-rework-requested": ("accept-task", "task-review-apply", "workflow task-review-apply"),
    "task-accepted": ("accept-task", "task-review-apply", "workflow task-review-apply"),
    "final-audit-outcome-applied": (
        "final-audit-outcome",
        "final-audit-outcome",
        "workflow final-audit-outcome",
    ),
    "run-finalized": ("finalize-run", "finalize", "workflow finalize"),
}


class WorkflowContinuationBaselineTests(unittest.TestCase):
    def test_fixture_inventory_matches_observed_release_shapes(self) -> None:
        expected = {"2.6": (23, 9, 24), "2.7": (28, 9, 30)}
        for path in FIXTURES:
            with self.subTest(path=path.name):
                fixture = _load(path)
                event_count, event_type_count, final_revision = expected[fixture["source"]["release"]]
                events = fixture["eventTrace"]

                self.assertEqual(len(events), event_count)
                self.assertEqual(len({event["eventType"] for event in events}), event_type_count)
                self.assertEqual(fixture["source"]["eventCount"], event_count)
                self.assertEqual(fixture["source"]["eventTypeCount"], event_type_count)
                self.assertEqual(fixture["finalState"]["stateRevision"], final_revision)
                self.assertEqual(fixture["finalState"]["phase"], "COMPLETE")

    def test_direct_and_continuation_surfaces_normalize_to_same_trace(self) -> None:
        for path in FIXTURES:
            with self.subTest(path=path.name):
                fixture = _load(path)

                direct = _replay_direct(fixture)
                continuation = _replay_continuation(fixture)

                self.assertEqual(continuation, direct)
                self.assertEqual(continuation["eventTypes"], [item["eventType"] for item in fixture["eventTrace"]])
                self.assertEqual(continuation["attemptHistory"], fixture["finalState"]["tasks"])
                self.assertEqual(continuation["finalPhase"], "COMPLETE")

    def test_revision_gaps_and_unavailable_telemetry_remain_explicit(self) -> None:
        for path in FIXTURES:
            with self.subTest(path=path.name):
                fixture = _load(path)
                revisions = {event["stateRevision"] for event in fixture["eventTrace"]}
                gaps = fixture["eventLogGaps"]
                unavailable_revisions = {gap["stateRevision"] for gap in gaps}
                expected = set(range(2, fixture["finalState"]["stateRevision"] + 1))

                self.assertEqual(expected.difference(revisions), unavailable_revisions)
                self.assertTrue(all(gap["status"] == "UNAVAILABLE" for gap in gaps))
                self.assertTrue(all(value == "UNAVAILABLE" for value in fixture["telemetry"].values()))
                self.assertNotIn("reductionPercent", fixture)
                self.assertEqual(fixture["interface"]["maxTransitionsPerApply"], 1)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _replay_direct(fixture: dict[str, Any]) -> dict[str, Any]:
    event_types: list[str] = []
    for event in fixture["eventTrace"]:
        event_type = event["eventType"]
        _action_type, _route_name, command = EVENT_SURFACES[event_type]
        self_describing_event = _event_for_direct_command(command, event_type)
        event_types.append(self_describing_event)
    return _normalized_result(fixture, event_types)


def _event_for_direct_command(command: str, event_type: str) -> str:
    known_commands = {entry[2] for entry in EVENT_SURFACES.values()}
    if command not in known_commands:
        raise AssertionError(f"unsupported direct workflow command: {command}")
    return event_type


def _replay_continuation(fixture: dict[str, Any]) -> dict[str, Any]:
    event_types: list[str] = []
    for event in fixture["eventTrace"]:
        event_type = event["eventType"]
        action_type, expected_route, _command = EVENT_SURFACES[event_type]
        if action_type is None:
            event_types.append(event_type)
            continue
        task_id = event.get("taskId")
        task_ids = [task_id] if isinstance(task_id, str) else []
        route = _project_route(
            Path("run.state.json"),
            {"phase": "RUNNING"},
            {"type": action_type, "taskIds": task_ids},
            {"taskId": task_id} if isinstance(task_id, str) else {},
        )
        if route["name"] != expected_route or route["transition"] is None:
            raise AssertionError(f"continuation route mismatch for {event_type}")
        event_types.append(event_type)
    return _normalized_result(fixture, event_types)


def _normalized_result(fixture: dict[str, Any], event_types: list[str]) -> dict[str, Any]:
    return {
        "eventTypes": event_types,
        "attemptHistory": fixture["finalState"]["tasks"],
        "finalPhase": fixture["finalState"]["phase"],
    }


if __name__ == "__main__":
    unittest.main()

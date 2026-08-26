from __future__ import annotations

import unittest

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.external_job_schemas import build_external_job_request, build_external_job_status
from agent_lifecycle.host_protocol.external_jobs import validate_external_job_transition


class ExternalJobTransitionTests(unittest.TestCase):
    def test_queued_to_running_and_exact_replay_are_valid(self) -> None:
        request = self._request()
        queued = self._status(request, "QUEUED", 0)
        running = self._status(request, "RUNNING", 1)

        self.assertEqual(validate_external_job_transition(queued, running, request=request)["status"], "PASS")
        replay = validate_external_job_transition(running, dict(running), request=request)
        self.assertEqual(replay["status"], "PASS")
        self.assertTrue(replay["idempotent"])

    def test_stale_sequence_and_terminal_mutation_fail_closed(self) -> None:
        request = self._request()
        running = self._status(request, "RUNNING", 2)
        stale = self._status(request, "RUNNING", 1)
        self.assertIn("external-job-transition-sequence-stale", self._codes(
            validate_external_job_transition(running, stale, request=request)
        ))

        terminal = self._status(request, "SUCCEEDED", 3)
        mutated = {**terminal, "observedAt": "2026-08-26T03:31:00Z"}
        self._redigest(mutated)
        self.assertIn("external-job-terminal-status-immutable", self._codes(
            validate_external_job_transition(terminal, mutated, request=request)
        ))

    def test_terminal_parent_requires_every_child_terminal_and_clean(self) -> None:
        parent_request = self._request(job_id="parent")
        child_request = self._request(job_id="child", parent=("parent", 1))
        child_ref = {
            "jobId": child_request["jobId"],
            "attempt": child_request["attempt"],
            "requestDigest": child_request["requestDigest"],
        }
        running_parent = self._status(parent_request, "RUNNING", 1, children=[child_ref])
        terminal_parent = self._status(parent_request, "SUCCEEDED", 2, children=[child_ref])

        missing = validate_external_job_transition(running_parent, terminal_parent, request=parent_request)
        self.assertIn("external-job-terminal-child-status-missing", self._codes(missing))

        live_child = self._status(child_request, "RUNNING", 1)
        live = validate_external_job_transition(
            running_parent, terminal_parent, request=parent_request, child_statuses=[live_child]
        )
        self.assertIn("external-job-terminal-child-live", self._codes(live))

        failed_cleanup = self._status(child_request, "CANCELLED", 2, cleanup="FAIL")
        failed = validate_external_job_transition(
            running_parent, terminal_parent, request=parent_request, child_statuses=[failed_cleanup]
        )
        self.assertIn("external-job-terminal-child-cleanup-failed", self._codes(failed))

        clean_child = self._status(child_request, "CANCELLED", 2, cleanup="PASS")
        accepted = validate_external_job_transition(
            running_parent, terminal_parent, request=parent_request, child_statuses=[clean_child]
        )
        self.assertEqual(accepted["status"], "PASS")

    def test_child_references_cannot_be_removed_or_substituted(self) -> None:
        request = self._request(job_id="parent")
        child_request = self._request(job_id="child", parent=("parent", 1))
        child_ref = {"jobId": "child", "attempt": 1, "requestDigest": child_request["requestDigest"]}
        previous = self._status(request, "RUNNING", 1, children=[child_ref])
        current = self._status(request, "RUNNING", 2)

        validation = validate_external_job_transition(previous, current, request=request)

        self.assertIn("external-job-child-lineage-removed", self._codes(validation))

    def test_terminal_parent_rejects_post_terminal_writes_and_unknown_children(self) -> None:
        request = self._request(job_id="parent")
        running = self._status(request, "RUNNING", 1)
        terminal = self._status(request, "CANCELLED", 2, post_write=True)
        post_write = validate_external_job_transition(running, terminal, request=request)
        self.assertIn("external-job-terminal-post-write", self._codes(post_write))

        other_request = self._request(job_id="other")
        other = self._status(other_request, "SUCCEEDED", 1)
        unknown = validate_external_job_transition(running, self._status(request, "SUCCEEDED", 2), request=request,
                                                   child_statuses=[other])
        self.assertIn("external-job-terminal-child-unexpected", self._codes(unknown))

    @staticmethod
    def _request(*, job_id: str = "job-1", parent: tuple[str, int] | None = None) -> dict:
        return build_external_job_request(
            job_id=job_id,
            attempt=1,
            parent_job_id=parent[0] if parent else None,
            parent_attempt=parent[1] if parent else None,
            adapter_id="synthetic",
            operation="review",
            execution_kind="PROCESS",
            descriptor_digest="1" * 64,
            plan_digest="2" * 64,
            plan_lock_digest="3" * 64,
            source_revision="0123456789abcdef",
            source_snapshot_digest="4" * 64,
            limits={
                "maxWallSeconds": 60,
                "maxOutputBytes": 1024,
                "maxArtifactBytes": 1024,
                "maxArtifacts": 4,
                "maxCostMicros": 1_000_000,
                "maxReportedTokens": 10_000,
                "cancelGraceSeconds": 2,
            },
        )

    @staticmethod
    def _status(
        request: dict,
        state: str,
        sequence: int,
        *,
        children: list[dict] | None = None,
        cleanup: str = "PASS",
        post_write: bool = False,
    ) -> dict:
        started = None if state == "QUEUED" else "2026-08-26T03:30:00Z"
        ended = "2026-08-26T03:30:02Z" if state in {"SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"} else None
        return build_external_job_status(
            request=request,
            state=state,
            sequence=sequence,
            observed_at="2026-08-26T03:30:02Z",
            started_at=started,
            ended_at=ended,
            children=children,
            process_cleanup_status=cleanup if state != "RUNNING" else "NOT_REQUIRED",
            post_terminal_write_detected=post_write,
        )

    @staticmethod
    def _redigest(value: dict) -> None:
        value["statusDigest"] = canonical_digest({key: item for key, item in value.items() if key != "statusDigest"})

    @staticmethod
    def _codes(validation: dict) -> set[str]:
        return {item["code"] for item in validation["blockers"]}


if __name__ == "__main__":
    unittest.main()

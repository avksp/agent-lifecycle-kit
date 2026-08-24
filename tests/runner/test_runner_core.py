from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.runner.core import (
    build_runner_snapshot,
    initialize_runner_state,
    load_runner_policy,
    load_runner_state,
    request_runner_stop,
    resume_runner,
    transition_runner,
    validate_runner_state,
    write_runner_state,
    write_runner_state_create,
)


class RemovedRunnerAuthorityTests(unittest.TestCase):
    def test_every_legacy_operation_fails_without_state_access_or_mutation(self) -> None:
        operations = (
            load_runner_policy,
            initialize_runner_state,
            load_runner_state,
            validate_runner_state,
            transition_runner,
            request_runner_stop,
            resume_runner,
            build_runner_snapshot,
            write_runner_state,
            write_runner_state_create,
        )
        for operation in operations:
            with self.subTest(operation=operation.__name__):
                with self.assertRaises(LifecycleError) as raised:
                    operation()
                self.assertEqual(raised.exception.code, "runner-authority-removed")


if __name__ == "__main__":
    unittest.main()

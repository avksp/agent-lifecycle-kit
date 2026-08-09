from __future__ import annotations

import argparse
import unittest
from unittest.mock import patch

from agent_lifecycle.cli.dispatch import dispatch
from agent_lifecycle.contracts import LifecycleError


class DispatchRoutingTests(unittest.TestCase):
    def test_root_dispatch_routes_each_domain_group_to_its_delegate(self) -> None:
        cases = {
            "diagnose": "dispatch_adapters",
            "adapter": "dispatch_adapters",
            "version": "dispatch_contracts",
            "review-mesh": "dispatch_contracts",
            "workflow": "dispatch_lifecycle",
            "runner": "dispatch_lifecycle",
            "report": "dispatch_observability",
            "metrics": "dispatch_observability",
            "plan": "dispatch_planning",
            "task": "dispatch_planning",
        }
        for command, delegate in cases.items():
            with self.subTest(command=command), patch(
                f"agent_lifecycle.cli.dispatch.{delegate}",
                return_value={"delegate": delegate},
            ) as handler:
                payload = dispatch(argparse.Namespace(command=command), [])

            self.assertEqual(payload, {"delegate": delegate})
            handler.assert_called_once()

    def test_unknown_group_keeps_stable_error(self) -> None:
        with self.assertRaisesRegex(LifecycleError, "reserved but not implemented") as caught:
            dispatch(argparse.Namespace(command="future"), [])

        self.assertEqual(caught.exception.code, "command-not-implemented")

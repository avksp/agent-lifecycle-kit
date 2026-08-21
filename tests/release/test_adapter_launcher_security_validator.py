from __future__ import annotations

import unittest
from pathlib import Path

from tools.release.validate_adapter_launcher_security import _identity_and_redaction_blockers


ROOT = Path(__file__).resolve().parents[2]


class AdapterLauncherSecurityMarkerTests(unittest.TestCase):
    def test_named_security_sources_expose_identity_and_shared_redaction_markers(self) -> None:
        args = type(
            "Args",
            (),
            {
                "launcher": "src/agent_lifecycle/adapter_sessions/launcher.py",
                "profile": "src/agent_lifecycle/adapter_sessions/local_launch_profile.py",
                "qualification": "src/agent_lifecycle/adapter_sessions/qualification.py",
                "redaction": "src/agent_lifecycle/contracts/redaction.py",
            },
        )()
        expectations = {
            "launcher": ("launcher", ROOT / args.launcher),
            "profile": ("profile", ROOT / args.profile),
            "qualification": ("qualification", ROOT / args.qualification),
            "redaction": ("redaction", ROOT / args.redaction),
        }
        for _name, (category, path) in expectations.items():
            with self.subTest(category=category):
                self.assertEqual(
                    _identity_and_redaction_blockers(path, path.read_text(encoding="utf-8"), args),
                    [],
                )


if __name__ == "__main__":
    unittest.main()

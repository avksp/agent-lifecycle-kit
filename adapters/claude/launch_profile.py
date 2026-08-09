"""Qualified local profile for Claude Code 2.1.226."""

PROFILE = {
    "schemaVersion": "agent-local-host-launch-profile.v1",
    "status": "LOCAL_OPT_IN",
    "adapterId": "claude",
    "executable": "claude",
    "argvTemplate": ["-p", "--output-format", "stream-json", "--verbose", "Continue the frozen ALK task in this repository. Preserve review, audit, and finalization gates."],
    "versionProbeArgs": ["--version"],
    "env": {"allow": ["HOME", "PATH"], "allowPatterns": [], "projectPolicyAllowed": False},
    "timeoutSeconds": 300,
    "shell": False,
    "writesNativeConfig": False,
    "promptInjectionDefault": False,
    "publicSupportClaimed": False,
    "productionPromotionClaimed": False,
    "qualification": {
        "schemaVersion": "agent-host-launch-qualification-policy.v1",
        "expectedVersion": "2.1.226",
        "receiptFile": "claude-2.1.226.qualification.json",
        "requiredForManagedTask": True,
        "maxPreflightProcesses": 1,
        "modelCallsForPreflight": 0,
    },
}

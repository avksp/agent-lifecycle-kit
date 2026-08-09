"""Qualified local profile for OpenCode 1.18.15."""

PROFILE = {
    "schemaVersion": "agent-local-host-launch-profile.v1",
    "status": "LOCAL_OPT_IN",
    "adapterId": "opencode",
    "executable": "opencode",
    "argvTemplate": ["run", "--format", "json", "Continue the frozen ALK task in this repository. Preserve review, audit, and finalization gates."],
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
        "expectedVersion": "1.18.15",
        "receiptFile": "opencode-1.18.15.qualification.json",
        "requiredForManagedTask": True,
        "maxPreflightProcesses": 1,
        "modelCallsForPreflight": 0,
    },
}

# Claude lifecycle-control candidate

This directory contains a copy-preview candidate for the optional ALK
lifecycle-control bridge. It describes the host event boundary; it does not
install hooks or edit Claude Code settings.

The candidate supports the portable `pre-action`, `post-action` and `stop`
event shapes. The host-owned producer must send bounded, redacted envelopes to
ALK. ALK checks the frozen plan, lock, state revision, action digest and
ownership before accepting the evidence.

The current candidate publishes `GUIDANCE_ONLY` and
`NO_RECOMMENDATION` for every operation. A fixture or a successful version
probe does not qualify enforcement. Promotion requires an exact Claude Code
version and independently reproduced positive and negative evidence showing
that a denied file edit or command did not happen.

## Copy preview

Review `lifecycle-control.template.json` and adapt it to the host integration
owned by the operator. Copying this file does not modify `.claude/`, Claude
Code settings or provider configuration. Keep any host-side authority outside
model-writable project paths.

## Offline check

From the repository root:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 tools/live_hosts/claude_lifecycle_control_harness.py --mode fixture-check --receipt work/claude-lifecycle-control-fixture.json --report work/claude-lifecycle-control-fixture-report.json
```

The result is deliberately `NO_RECOMMENDATION`. It confirms the template and
receipt boundaries but does not claim that Claude blocked a host action.

## Live qualification

Live qualification is an explicit operator action. It requires a clean
dedicated worktree, `--allow-live`, a ten-second host-version probe timeout and an externally produced
matrix containing exact-version event evidence. Without that matrix the
harness performs only a version preflight and returns `NO_RECOMMENDATION`.
The harness never edits operator settings and never stores prompts,
transcripts, environment values or secrets.

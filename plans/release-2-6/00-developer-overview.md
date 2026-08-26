# Developer overview

Release 2.6 closes operator API/CLI gaps and standardizes the accounting patterns independently invented by three projects.

The canonical reviewed package lives under `plans/release-2-6`; generated task packets, workflow state, validation output, audit evidence and accounting live under the distinct lead-owned `work/release-2-6` artifact root. Runtime execution must not create a `workflow/` subtree inside the tracked plan package.

`plan lock-create` is a packaging operation, not plan approval. It requires an already `FROZEN` manifest plus an independent `agent-plan-review.v1` with verdict `READY_TO_FREEZE`, no open Medium-or-higher finding, and exact package, revision and manifest-digest binding. The finalized manifest pre-declares `planReview.report` and its `planFiles` entry before independent review; the auditor hashes those exact bytes and writes the report into that path, so no self-reference normalization is needed. The binding helper lives in `freeze/package_integrity.py`, composes the existing independent-review validator, and is invoked through a dedicated `cli/plan_lock_commands.py` helper so `_dispatch_plan` remains under the hard function-size gate; `review/validation.py` stays read-only. The command writes only `<planArtifactRoot>/plan.lock.json` with no-replace semantics and immediately verifies both lock and package inventory. A status string by itself cannot create a lock.

`metrics phase-resources` reads one bounded JSON document of explicit phase records, calls the existing builder, writes the requested artifact and returns its validator result. Shared canonical JSON input limits apply, the phase builder enforces `MAX_PHASE_RESOURCE_ENTRIES = 256` in both build and validation paths, and the command never reads host transcripts implicitly.

`metrics release-accounting` composes explicit source artifacts into one validated accounting artifact. It keeps lifecycle elapsed wall time separate from parallel reviewer compute, marks non-additive scopes, preserves `UNAVAILABLE`, and exposes ALK-process, implementation, audit and post-audit-remediation views without replacing the existing cost categories. It does not infer missing usage from file size.

Version provenance names controller/core, host plugin and skill package separately so a direct CLI cannot silently stand in for a stale plugin cache. Version disagreement is evidence, not an automatic confidence upgrade.

The phase-session recipe reuses task packets, `workflow task-snapshot`, `context checkpoint/restore`, `plan handoff` and `goal summarize`. Its bounded no-model regression extends `tests/planning/test_continuity.py`; no new session state or transcript store is introduced.

Release 2.6 establishes comparable accounting semantics and a real baseline. Later workflow optimizations must derive acceptance targets from post-2.6 measurements; they must not invent arbitrary ratios or lower architecture, security, quality or audit gates.

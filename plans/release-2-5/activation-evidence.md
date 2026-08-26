# Activation evidence

Status: `ACTIVATED_FOR_PLANNING / NOT_IMPLEMENTATION_EVIDENCE`.

## Case A - surviving reviewer processes and mixed output

Source artifact:

- project: AI Solution Advisor;
- artifact: `alk/external-audit.md` under the local review package;
- bytes: 14 160;
- SHA-256: `25269548749fe7fcb7c07664c5f638b5b7c35ffd1d1f1fe1ffdafe11912075e2`;
- bounded fact: wrapper processes were stopped, child OpenCode processes continued writing to the same files, a second generation overlapped them, logs mixed and no verdict was usable.

Required lifecycle capability:

- process-group ownership survives wrapper cancellation;
- a cancelled attempt has a terminal immutable state;
- output paths are unique per job and attempt;
- writes observed after cancellation invalidate the result;
- a later attempt cannot append to or replace earlier artifacts.

## Case B - bounded wait without a consolidated verdict

Source artifacts:

- project: DotSpace Board R04;
- no-verdict envelope bytes: 1 152;
- no-verdict SHA-256: `631ecf7ff5e19864bd9cb47fb8f65a5521cf0a87adb92c0ce03aedbee5166558`;
- accounting bytes: 6 769;
- accounting SHA-256: `c9e14f44d40dab9562a3d8aaa25e624424651bb203958d8d78122ea307a4b753`;
- bounded fact: an external reviewer launched child frontend/backend audits, the children did not return a final consolidated result within the bounded wait, and the process was interrupted;
- measured use: 1 215 037 tokens and 770.811 seconds;
- acceptance effect: none; terminal verdict `NO_FINAL_VERDICT`.

Required lifecycle capability:

- parent/child job lineage and bounded wait are explicit;
- partial child output remains diagnostic only;
- timeout/interruption without a final result becomes FAILED, CANCELLED or EXPIRED, never SUCCEEDED;
- consumed resources remain reportable even when acceptance effect is false.

## Why Release 1.88 is insufficient

The synchronous external-check contract starts one bounded local process and emits its result in the same invocation. It does not represent queued/running state, separately addressable cancellation, parent/child jobs, terminal no-verdict or immutable per-attempt artifact namespaces. Extending that one-shot receipt with hidden background behavior would weaken its current determinism.

Process resumption is deliberately not authorized by these incidents. After interruption the old attempt remains terminal and immutable; recovery creates a new attempt with a new namespace. This prevents a later process from inheriting ambiguous ownership of children or partially written output.

## Privacy and authority

This activation record stores no raw prompts, logs, credentials, provider responses or local absolute paths. Source artifacts remain local and are bound only by byte count and digest. Activation grants no workflow authority, provider support claim or production promotion.

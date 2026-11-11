# Host update boundaries

[Русская версия](../ru/adapters/plugin-updates.md)

ALK supplies update advice. The host owns installation, cache replacement,
permissions and session loading. An assessment, recipe, JSON receipt or matching
version label is not permission to change native files.

| Mode or operation | Current behavior |
| --- | --- |
| off | No automatic work or native dispatch. |
| manual | Explicit metadata and plan checks. |
| notify | Unsupported without a qualified trigger; a caller flag cannot supply it. |
| ask | Show an inert manual recipe and its gaps when explicit plan inputs remain current. |
| safe-auto | Unsupported; no qualified safe boundary, exhaustive affected scope or recovery. |
| install | Refuse before native dispatch. |
| reconcile | Observe this Python runtime and separate declared installed/loaded labels. |

These limits apply to the update operation. They do not change an adapter's
other ALK integration level. There is no model or provider default in this API.
No new installer, native executor, scheduler or host fork is added.

Use the same request policy throughout a check, assessment and offer. A policy,
target, commit or selected-file change requires a fresh assessment. Offer checks
the explicit file hashes again under the same 32-plan, 64-file, 256-KiB-per-file
and eight-MiB aggregate input bounds. Active, paused, unknown or frozen-without-
state boundaries defer activation. Completed history remains intact.

```sh
agent-lifecycle plugin-update offer --request request.json --assessment impact.json --out offer.json
agent-lifecycle plugin-update install --request request.json --offer offer.json --out refusal.json
agent-lifecycle plugin-update reconcile --request observations.json --out identities.json
```

For a declared Codex host, ALK can display documented marketplace remove,
exact-ref add, plugin add and plugin list command shapes. The current route is
an **inert operator recipe**. It is not a qualified transaction or installation
recommendation. Other unmapped hosts receive an explicit unsupported result;
there is no silent fallback to another adapter.

Before any separate manual update, inspect the actual host help/version,
resolve the exact upstream tag/commit again and obtain permission for its real
scope. Marketplace removal and reinstall can affect the user's other projects.
An explicit local plan list cannot establish that global scope. ALK does not
scan foreign projects or sessions to make it appear complete.

Keep the original plan, lock, state, expenses, attempts and clocks. Do not
rewrite frozen authority because a newer plugin exists. Retain a verified old
runtime or use a reviewed amendment through the existing lifecycle. A previous
cache or backup is not proof of usable rollback.

After an external update, restart or reload only through the host's supported
procedure. Inspect installed files and the resolved runtime separately. Loaded
instruction labels supplied by the caller stay `DECLARED`; equal labels do not
attest activation. Missing evidence stays `UNKNOWN`, and disagreements show
`DRIFT`. Reconciliation changes no lifecycle state and grants no permission.

A failed or timed-out native update may have an unknown partial effect.
Preserve its receipt and inspect actual state before another action. Do not
blindly retry or promise cache retention. ALK cannot veto a host's independent
background updater. See [plan impact](../reference/plugin-updates.md).

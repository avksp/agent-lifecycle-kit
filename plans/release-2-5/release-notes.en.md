# Release 2.5.0

## Summary

Represent optional asynchronous external-tool work as bounded jobs and hashed artifact results without adding provider clients to ALK core.

## Highlights

- Every state transition is idempotent, source-bound and separate from ALK workflow authority.
- The core validates receipts and never performs provider or network calls.
- Large or sensitive payloads remain outside portable lifecycle evidence.
- A descriptor or successful happy path alone cannot claim support.

## Activation

The plan is activated by two bounded incidents: child reviewer processes survived wrapper cancellation and mixed output, and nested child audits ended without a consolidated verdict after a bounded wait.

## Compatibility

The capability is optional and inactive unless a frozen plan or project profile enables it. Ordinary workflows retain their behavior and cost.
